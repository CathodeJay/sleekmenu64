# SPDX-License-Identifier: AGPL-3.0-only
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class GridRenderingTests(unittest.TestCase):
    def test_tile_copy_uses_aligned_pixel_stores(self):
        """Native pixel tests cannot catch MIPS memcpy store selection."""
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
            # Keep the production helper available separately, even when it
            # also inlines into ui_draw; inspect only its framebuffer copy.
            assembly = subprocess.check_output(
                [str(objdump), "-dr", "--section=.text.draw_tile", str(obj)],
                cwd=ROOT, text=True,
            )
        self.assertRegex(assembly, r"\bsh\b", "tile pixels must use halfword stores")
        self.assertNotRegex(assembly, r"\b(?:sdl|sdr)\b", "unaligned stores cause bands on Analogue 3D")
        self.assertNotIn("memcpy", assembly, "do not delegate framebuffer stores to memcpy")


if __name__ == "__main__":
    unittest.main()
