# SPDX-License-Identifier: AGPL-3.0-only
"""The boot code's checksum, on the computer and on the console.

The algorithm was checked against real cartridges of every retail boot code
(6101, 6102, 6103, 6105, 6106, byteswapped dumps included) on a card of
3,400 games; those files cannot ship here. What can: the two
implementations agree with each other over synthetic images, the fix
rewrites exactly the two words and nothing else, and the tool refuses what
it should.
"""

import contextlib
import io
import pathlib
import subprocess
import tempfile
import unittest
import zlib

from tools import n64_checksum
from tools.n64_checksum import (BOOT_CODE_LENGTH, BOOT_CODE_OFFSET, CIC_BY_BOOT_CRC, NEEDED,
                                Verdict, cic_of, compute, fix, verify)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def synthetic(seed: int = 12345, size: int = NEEDED) -> bytearray:
    """The same linear congruential bytes tests/rom_checksum_test.c makes."""
    state = seed
    out = bytearray(size)
    for i in range(size):
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        out[i] = (state >> 16) & 0xFF
    return out


def with_boot_code(image: bytearray, cic: int) -> bytearray:
    """Make the image's boot code identify as `cic` by the CRC the browser
    and the tool both use: brute force is cheap when the CRC-32 of a
    0xFC0-byte block is being forced through four free bytes."""
    target = next(crc for crc, c in CIC_BY_BOOT_CRC.items() if c == cic)
    image[:4] = b"\x80\x37\x12\x40"
    boot = image[BOOT_CODE_OFFSET:BOOT_CODE_OFFSET + BOOT_CODE_LENGTH]
    # CRC-32 is linear: the last four bytes can be chosen to hit any value.
    prefix_crc = zlib.crc32(bytes(boot[:-4]))
    patch = _crc32_tail(prefix_crc, target)
    boot[-4:] = patch
    image[BOOT_CODE_OFFSET:BOOT_CODE_OFFSET + BOOT_CODE_LENGTH] = boot
    assert cic_of(bytes(image)) == cic
    return image


def _crc32_tail(prefix_crc: int, target: int) -> bytes:
    """Four bytes that take a running CRC-32 from prefix_crc to target."""
    # Reverse the four byte steps of the table-driven CRC.
    table = [0] * 256
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        table[i] = c
    inverse = {v >> 24: i for i, v in enumerate(table)}
    want = target ^ 0xFFFFFFFF
    state = prefix_crc ^ 0xFFFFFFFF
    # Walk the wanted register back four steps to find the bytes.
    steps = []
    for _ in range(4):
        index = inverse[want >> 24]
        want = ((want ^ table[index]) << 8) & 0xFFFFFFFF
        steps.append(index)
    # want now holds the state before the four bytes, up to its low byte
    # positions; solve forwards for each byte.
    out = bytearray()
    current = state
    for index in reversed(steps):
        byte = (current ^ index) & 0xFF
        out.append(byte)
        current = (current >> 8) ^ table[(current ^ byte) & 0xFF]
    return bytes(out)


class AlgorithmTests(unittest.TestCase):
    def test_the_console_and_the_tool_agree(self):
        """Same bytes, two implementations, five boot codes."""
        image = bytes(synthetic())
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / "rom-checksum-test"
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Isrc",
                            "src/rom_checksum.c", "tests/rom_checksum_test.c", "-o", str(binary)],
                           cwd=ROOT, check=True)
            printed = subprocess.run([str(binary), "12345"], check=True, capture_output=True,
                                     text=True).stdout.split()
        got = {int(printed[i]): (int(printed[i + 1], 16), int(printed[i + 2], 16))
               for i in range(0, len(printed), 3)}
        self.assertEqual(sorted(got), [6101, 6102, 6103, 6105, 6106])
        for cic, words in got.items():
            self.assertEqual(compute(image, cic), words, f"CIC {cic}")

    def test_each_boot_code_sums_differently(self):
        image = bytes(synthetic())
        sums = {cic: compute(image, cic) for cic in (6102, 6103, 6105, 6106)}
        self.assertEqual(len(set(sums.values())), 4)
        self.assertEqual(compute(image, 6101), compute(image, 6102), "6101 shares the 6102 rules")

    def test_a_short_image_and_an_unknown_boot_code_are_refused(self):
        with self.assertRaises(n64_checksum.ChecksumError):
            compute(bytes(synthetic(size=NEEDED - 1)), 6102)
        with self.assertRaises(n64_checksum.ChecksumError):
            compute(bytes(synthetic()), 6104)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = pathlib.Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name: str, image: bytes) -> pathlib.Path:
        path = self.directory / name
        path.write_bytes(image)
        return path

    def test_verify_reads_the_header_words_and_the_boot_code(self):
        image = with_boot_code(synthetic(), 6102)
        expected = compute(bytes(image), 6102)
        image[0x10:0x18] = expected[0].to_bytes(4, "big") + expected[1].to_bytes(4, "big")
        verdict = verify(self.write("good.z64", bytes(image)))
        self.assertEqual(verdict, Verdict(6102, expected, expected))
        self.assertTrue(verdict.matches)

    def test_fix_rewrites_the_two_words_and_nothing_else(self):
        image = with_boot_code(synthetic(), 6103)
        image[0x10:0x18] = bytes(8)
        path = self.write("hack.z64", bytes(image) + b"tail")
        before = verify(path)
        self.assertFalse(before.matches)
        fix(path)
        after = path.read_bytes()
        self.assertEqual(after[:0x10], bytes(image[:0x10]))
        self.assertEqual(after[0x18:], bytes(image[0x18:]) + b"tail")
        self.assertTrue(verify(path).matches)
        # A second fix writes nothing: the words already match.
        stamp = path.stat().st_mtime_ns
        fix(path)
        self.assertEqual(path.stat().st_mtime_ns, stamp)

    def test_a_byteswapped_dump_is_summed_native_and_fixed_in_its_own_order(self):
        image = with_boot_code(synthetic(), 6106)
        image[0x10:0x18] = bytes(8)
        swapped = bytearray(image)
        swapped[0::2], swapped[1::2] = image[1::2], image[0::2]
        path = self.write("hack.v64", bytes(swapped))
        verdict = fix(path)
        self.assertEqual(verdict.cic, 6106)
        fixed = path.read_bytes()
        self.assertEqual(fixed[:4], b"\x37\x80\x40\x12", "still byteswapped")
        native = bytearray(fixed)
        native[0::2], native[1::2] = fixed[1::2], fixed[0::2]
        words = compute(bytes(native), 6106)
        self.assertEqual(native[0x10:0x18], words[0].to_bytes(4, "big") + words[1].to_bytes(4, "big"))

    def test_an_unknown_boot_code_is_left_alone(self):
        image = synthetic()
        image[:4] = b"\x80\x37\x12\x40"
        path = self.write("homebrew.z64", bytes(image))
        verdict = fix(path)
        self.assertFalse(verdict.known)
        self.assertEqual(path.read_bytes(), bytes(image))

    def test_the_command_line_reports_and_fixes(self):
        image = with_boot_code(synthetic(), 6105)
        image[0x10:0x18] = bytes(8)
        path = self.write("hack.z64", bytes(image))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(n64_checksum.main([str(path)]), 1)
            self.assertEqual(n64_checksum.main(["--fix", str(path)]), 0)
            self.assertEqual(n64_checksum.main([str(path)]), 0)
        self.assertIn("MISMATCH", out.getvalue())
        self.assertIn("fixed", out.getvalue())


if __name__ == "__main__":
    unittest.main()
