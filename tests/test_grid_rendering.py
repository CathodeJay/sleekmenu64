# SPDX-License-Identifier: AGPL-3.0-only
import os
import pathlib
import re
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Functions that write rows of pixels onto the screen, through put_pixels,
#: which is always inlined into them.
SCREEN_WRITERS = ("draw_tile", "draw_description")


class GridRenderingTests(unittest.TestCase):
    def test_screen_rows_are_written_without_partial_stores(self):
        """The screen is uncached and the grid and the details' description
        start at odd pixels. The Analogue 3D draws bands where a row is
        written with partial stores (swl/swr, sdl/sdr), which memcpy uses
        for an unaligned destination. Native pixel tests cannot see which
        stores the MIPS compiler picks, so this compiles ui.c for the
        console and reads them."""
        toolchain = pathlib.Path(os.environ.get("N64_INST") or ROOT / ".toolchain")
        compiler = toolchain / "bin/mips64-elf-gcc"
        objdump = toolchain / "bin/mips64-elf-objdump"
        if not compiler.is_file() or not objdump.is_file():
            self.skipTest("N64 toolchain not installed")
        with tempfile.TemporaryDirectory() as directory:
            obj = pathlib.Path(directory) / "ui.o"
            subprocess.run(
                [str(compiler), "-std=gnu17", "-O2", "-march=vr4300", "-mtune=vr4300",
                 "-mabi=o64", "-ffunction-sections", "-fkeep-static-functions",
                 "-Isrc", "-c", "src/ui.c", "-o", str(obj)],
                cwd=ROOT, check=True,
            )
            for function in SCREEN_WRITERS:
                assembly = subprocess.check_output(
                    [str(objdump), "-dr", f"--section=.text.{function}", str(obj)],
                    cwd=ROOT, text=True,
                )
                self.assertRegex(assembly, r"\bsh\b", f"{function}: the ends of a row go two bytes at a time")
                self.assertNotRegex(assembly, r"\b(?:sdl|sdr|swl|swr)\b",
                                    f"{function}: partial stores draw bands on the Analogue 3D")
                self.assertNotIn("memcpy", assembly, f"{function}: memcpy picks its own stores")
                self.assertRegex(assembly, r"\bsd\b", f"{function}: the middle of a row goes eight bytes at a time")

    def test_nothing_is_copied_onto_the_screen_with_memcpy(self):
        """Every row that reaches the screen goes through put_pixels."""
        source = (ROOT / "src/ui.c").read_text(encoding="utf-8")
        for call in re.findall(r"memcpy\(([^;]*)\);", source):
            self.assertNotRegex(call, r"\b(?:s|dst)->buffer\b|^dst\b", call)


if __name__ == "__main__":
    unittest.main()
