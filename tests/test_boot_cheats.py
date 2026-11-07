# SPDX-License-Identifier: AGPL-3.0-only
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class BootCheatsTests(unittest.TestCase):
    def test_boot_code_decoder(self):
        """Run the real decoder without the N64-only installer and I/O."""
        source = (ROOT / "third_party/n64flashcartmenu/boot/cheats.c").read_text(encoding="utf-8")
        definitions_start = source.index("/** @brief Cheat structure */")
        definitions_end = source.index("#define X106_XOR_CONSTANT", definitions_start)
        decoder_start = source.index("static bool cheats_get_next (")
        decoder_end = source.index("\n}\n", decoder_start) + len("\n}\n")
        harness = (ROOT / "tests/boot_cheats_test.c").read_text(encoding="utf-8")
        translation_unit = (
            "#include <stdbool.h>\n#include <stdint.h>\n"
            + source[definitions_start:definitions_end]
            + source[decoder_start:decoder_end]
            + harness
        )
        with tempfile.TemporaryDirectory() as directory:
            test_source = pathlib.Path(directory) / "boot_cheats_test.c"
            binary = pathlib.Path(directory) / "boot-cheats-test"
            test_source.write_text(translation_unit, encoding="utf-8")
            subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(test_source), "-o", str(binary)],
                cwd=ROOT, check=True,
            )
            subprocess.run([str(binary)], cwd=directory, check=True)


if __name__ == "__main__":
    unittest.main()
