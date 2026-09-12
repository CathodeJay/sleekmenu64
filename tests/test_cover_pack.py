# SPDX-License-Identifier: AGPL-3.0-only
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools import cover_pack, make_sprite

ROOT = Path(__file__).resolve().parents[1]
HOST_CC = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Isrc"]

FIXTURE = {
    "Super Mario 64 (USA).sprite": (96, 72),
    "Wave Race 64 (USA).sprite": (64, 48),
    "Zelda (Japan).sprite": (96, 72),
}


def sprite_bytes(width: int, height: int) -> bytes:
    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = ((x * 3) % 256, (y * 5) % 256, (x + y) % 256, 255)
    return make_sprite.encode(image)


class CoverPackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.covers = {name: sprite_bytes(*size) for name, size in FIXTURE.items()}

    def tearDown(self):
        self.temporary.cleanup()

    def test_round_trip_preserves_every_cover(self):
        blob = cover_pack.build(self.covers)
        entries = cover_pack.read_index(blob)
        self.assertEqual({e.name for e in entries}, set(self.covers))
        for entry in entries:
            self.assertEqual(blob[entry.offset:entry.offset + entry.length],
                             self.covers[entry.name])

    def test_the_index_is_sorted_because_the_console_binary_searches_it(self):
        entries = cover_pack.read_index(cover_pack.build(self.covers))
        self.assertEqual([e.hash for e in entries], sorted(e.hash for e in entries))

    def test_hashing_ignores_case(self):
        self.assertEqual(cover_pack.cover_hash("Mario (USA).sprite"),
                         cover_pack.cover_hash("MARIO (usa).SPRITE"))

    def test_payloads_are_aligned(self):
        entries = cover_pack.read_index(cover_pack.build(self.covers))
        for entry in entries:
            self.assertEqual(entry.offset % cover_pack.ALIGN, 0)

    def test_a_damaged_pack_is_refused_rather_than_half_read(self):
        blob = bytearray(cover_pack.build(self.covers))
        blob[cover_pack.HEADER_SIZE + 4] ^= 0xFF          # corrupt an offset
        with self.assertRaisesRegex(cover_pack.CoverPackError, "checksum"):
            cover_pack.read_index(bytes(blob))

    def test_an_empty_pack_is_refused(self):
        with self.assertRaisesRegex(cover_pack.CoverPackError, "empty"):
            cover_pack.build({})

    def test_packing_a_directory(self):
        source = self.root / "covers"
        source.mkdir()
        for name, data in self.covers.items():
            (source / name).write_bytes(data)
        count, size = cover_pack.pack_directory(source, self.root / "covers.pak")
        self.assertEqual(count, len(self.covers))
        # One file instead of many, and barely larger than the pictures in it.
        self.assertLess(size, sum(len(v) for v in self.covers.values()) + 4096)

    def test_the_console_reader_agrees_with_the_packer(self):
        """The contract that matters: Python writes it, C reads it. A
        disagreement about an offset or a byte order means every cover on the
        card is missing or is somebody else's picture."""
        good = self.root / "covers.pak"
        good.write_bytes(cover_pack.build(self.covers))
        truncated = self.root / "truncated.pak"
        truncated.write_bytes(good.read_bytes()[:cover_pack.HEADER_SIZE + 8])

        binary = self.root / "cover-pack-test"
        subprocess.run(HOST_CC + ["src/cover_pack.c", "tests/cover_pack_test.c",
                                  "-o", str(binary)], cwd=ROOT, check=True)
        subprocess.run([str(binary), str(good), str(truncated)], check=True)


if __name__ == "__main__":
    unittest.main()
