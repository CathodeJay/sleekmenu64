# SPDX-License-Identifier: AGPL-3.0-only
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools import make_sprite

FIXTURES = Path(__file__).parent / "fixtures" / "sprites"


def sample_image(width: int, height: int) -> Image.Image:
    """The formula the checked-in reference sprites were generated from.

    It has to stay exactly as it is or the fixtures stop meaning anything."""
    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = ((x * 7 + y) % 256, (y * 11 + x * 3) % 256,
                            (x * y + 17) % 256, (x * 13 + y * 5) % 256)
    return image


class MakeSpriteTests(unittest.TestCase):
    def test_output_is_byte_identical_to_libdragons_mksprite(self):
        """The reference files came out of `mksprite -f RGBA16 -c 0`. If this
        fails, we are no longer writing the format the console reads -- the
        sizes chosen cover an odd width (row padding), a 1x1 (slice counts
        clamping to 1), and one small enough to fit TMEM plus one that is not
        (the flag in the extended header)."""
        for name in ("1x1", "16x16", "17x5", "33x41"):
            with self.subTest(sprite=name):
                width, height = (int(part) for part in name.split("x"))
                expected = (FIXTURES / f"{name}.sprite").read_bytes()
                self.assertEqual(make_sprite.encode(sample_image(width, height)), expected)

    def test_rgba16_matches_the_reference_conversion(self):
        self.assertEqual(make_sprite.rgba16(0, 0, 0, 0), 0x0000)
        self.assertEqual(make_sprite.rgba16(255, 255, 255, 255), 0xFFFF)
        self.assertEqual(make_sprite.rgba16(8, 0, 8, 255), 0x0803)
        self.assertEqual(make_sprite.rgba16(0, 8, 0, 255), 0x0041)
        # The low three bits of each channel are dropped, not rounded.
        self.assertEqual(make_sprite.rgba16(15, 0, 0, 255), make_sprite.rgba16(8, 0, 0, 255))
        # Alpha is one bit, and the cut is at half, not at "any transparency".
        self.assertEqual(make_sprite.rgba16(0, 0, 0, 127) & 1, 0)
        self.assertEqual(make_sprite.rgba16(0, 0, 0, 128) & 1, 1)

    def test_tmem_flag_accounts_for_row_padding(self):
        """A row is padded to eight bytes before it counts against TMEM, so
        width alone does not decide this."""
        self.assertTrue(make_sprite._fits_tmem(32, 64))     # 64 * 64 == 4096
        self.assertFalse(make_sprite._fits_tmem(32, 65))
        self.assertFalse(make_sprite._fits_tmem(33, 64))    # 68 -> padded to 72

    def test_fitting_letterboxes_onto_the_matte_without_distortion(self):
        tall = Image.new("RGBA", (100, 400), (255, 0, 0, 255))
        fitted = make_sprite.fit_image(tall)
        self.assertEqual(fitted.size, make_sprite.CANVAS_SIZE)
        # The corners are matte because a 1:4 image cannot fill a 4:3 frame.
        self.assertEqual(fitted.getpixel((0, 0)), make_sprite.MATTE_RGBA)
        self.assertEqual(fitted.getpixel((48, 36)), (255, 0, 0, 255))

    def test_a_pre_stretched_picture_is_read_at_half_width(self):
        """The Pro menu's metadata is stretched to double width for a
        640-pixel mode: Super Mario 64's box arrives as 240x85. Fitted as-is
        it would be a 96x34 ribbon; at half width it is the 4:3 box again."""
        stretched = Image.new("RGBA", (240, 85), (200, 30, 30, 255))
        fitted = make_sprite.fit_image(stretched, width_scale=0.5)
        # 120x85 fits the 96x72 canvas at 96x68: matte above and below only.
        self.assertEqual(fitted.size, (96, 72))
        self.assertEqual(fitted.getpixel((48, 36))[:3], (200, 30, 30))
        self.assertEqual(fitted.getpixel((0, 36))[:3], (200, 30, 30))
        self.assertNotEqual(fitted.getpixel((48, 0))[:3], (200, 30, 30))
        ribbon = make_sprite.fit_image(stretched)
        self.assertNotEqual(ribbon.getpixel((48, 4))[:3], (200, 30, 30))

    def test_convert_writes_a_cover_sized_sprite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "art.png"
            sample_image(200, 150).save(source)
            written = make_sprite.convert(source, root / "out" / "art.sprite")
            # 8-byte header + 96*72*2 pixels + 128-byte extended block.
            self.assertEqual(written, 8 + 96 * 72 * 2 + 128)
            payload = (root / "out" / "art.sprite").read_bytes()
            self.assertEqual(payload[:4], bytes((0, 96, 0, 72)))

    def test_conversion_is_deterministic(self):
        first = make_sprite.encode(sample_image(40, 30))
        second = make_sprite.encode(sample_image(40, 30))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
