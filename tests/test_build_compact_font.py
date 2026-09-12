# SPDX-License-Identifier: AGPL-3.0-only
import re
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from tools.build_compact_font import (ATLAS_SIZE, DEFAULT_SOURCE, GLYPH_SIZE, build,
                                      build_atlas, parse_bdf)

ROOT = Path(__file__).resolve().parents[1]

# A three-glyph font in the vendored font's box: a full cell, a dot in the
# lower right (the descender row), and a two-pixel-wide glyph placed one
# pixel in from the left.
SAMPLE_BDF = """STARTFONT 2.1
FONT -misc-sample-medium-r-normal--8-80-72-72-C-50-ISO10646-1
SIZE 8 72 72
FONTBOUNDINGBOX 5 8 0 -1
STARTPROPERTIES 1
FONT_ASCENT 7
ENDPROPERTIES
CHARS 3
STARTCHAR full
ENCODING 65
SWIDTH 625 0
DWIDTH 5 0
BBX 5 8 0 -1
BITMAP
F8
F8
F8
F8
F8
F8
F8
F8
ENDCHAR
STARTCHAR dot
ENCODING 66
SWIDTH 625 0
DWIDTH 5 0
BBX 1 1 4 -1
BITMAP
80
ENDCHAR
STARTCHAR bar
ENCODING 67
SWIDTH 625 0
DWIDTH 5 0
BBX 2 3 1 0
BITMAP
C0
C0
C0
ENDCHAR
ENDFONT
"""


class CompactFontTests(unittest.TestCase):
    def test_atlas_has_16_by_8_five_by_eight_glyphs(self):
        self.assertEqual(GLYPH_SIZE, (5, 8))
        self.assertEqual(ATLAS_SIZE, (80, 64))
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "font.bdf", Path(directory) / "font.png"
            source.write_text(SAMPLE_BDF, encoding="utf-8")
            build_atlas(source, output)
            with Image.open(output) as atlas:
                self.assertEqual(atlas.size, ATLAS_SIZE)
                on, off = (255, 255, 255, 255), (0, 0, 0, 0)
                # 'A' is at column 1 of row 4: cell (5, 32), every pixel set
                self.assertEqual(atlas.getpixel((5, 32)), on)
                self.assertEqual(atlas.getpixel((9, 39)), on)
                self.assertEqual(atlas.getpixel((4, 32)), off)
                self.assertEqual(atlas.getpixel((10, 32)), off)
                # 'B': one pixel, bottom right of its cell (10..14, 32..39)
                self.assertEqual(atlas.getpixel((14, 39)), on)
                self.assertEqual(atlas.getpixel((13, 39)), off)
                self.assertEqual(atlas.getpixel((14, 38)), off)
                # 'C': two wide, three tall, sitting on the baseline (row 6),
                # one pixel in from the left
                self.assertEqual(atlas.getpixel((16, 36)), on)
                self.assertEqual(atlas.getpixel((17, 38)), on)
                self.assertEqual(atlas.getpixel((15, 36)), off)
                self.assertEqual(atlas.getpixel((18, 36)), off)
                self.assertEqual(atlas.getpixel((16, 35)), off)
                self.assertEqual(atlas.getpixel((16, 39)), off)
                # nothing else
                self.assertEqual(atlas.getpixel((0, 0)), off)

    def test_the_vendored_font_has_every_printable_ascii_glyph(self):
        box, glyphs = parse_bdf(DEFAULT_SOURCE.read_text(encoding="utf-8"))
        self.assertEqual(box, (5, 8, 0, -1))
        for code in range(33, 127):
            self.assertIn(code, glyphs, chr(code))
            self.assertTrue(any(glyphs[code]), f"{chr(code)} is blank")
        # a letter is what it says it is: 'A' is the peaked shape
        self.assertEqual(glyphs[ord("A")], [0x00, 0x0C, 0x12, 0x12, 0x1E, 0x12, 0x12, 0x00])
        # and a space is blank
        self.assertFalse(any(glyphs[ord(" ")]))

    def test_the_sprite_claims_glyph_sized_tiles(self):
        """A font sprite that claims libdragon's default 16-pixel tiles draws
        the wrong letter for every character on screen."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sprite = build(DEFAULT_SOURCE, root / "filesystem", root / "work")
            payload = sprite.read_bytes()
            self.assertEqual((payload[0] << 8) | payload[1], ATLAS_SIZE[0])
            self.assertEqual((payload[2] << 8) | payload[3], ATLAS_SIZE[1])
            self.assertEqual(payload[6], ATLAS_SIZE[0] // GLYPH_SIZE[0])   # hslices
            self.assertEqual(payload[7], ATLAS_SIZE[1] // GLYPH_SIZE[1])   # vslices

    def test_building_the_font_needs_no_toolchain(self):
        """It used to shell out to mksprite, so a machine without a MIPS
        cross-compiler could not build the release ROM -- and failed with a
        traceback rather than saying so."""
        source = ROOT / "tools" / "build_compact_font.py"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("subprocess", text)
        self.assertNotIn("mksprite", text.split('"""')[2])

    def test_wrong_source_geometry_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "font.bdf"
            source.write_text(SAMPLE_BDF.replace("FONTBOUNDINGBOX 5 8 0 -1", "FONTBOUNDINGBOX 8 16 0 -2"),
                              encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "5x8"):
                build_atlas(source, Path(directory) / "font.png")
            source.write_text("not a font\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "FONTBOUNDINGBOX"):
                build_atlas(source, Path(directory) / "font.png")

    def test_the_browser_agrees_with_the_atlas(self):
        """display.h's glyph size is what every column of text is laid out
        by, and display.c refuses a sprite of any other geometry; both have
        to say what the tool builds."""
        header = (ROOT / "src/display.h").read_text(encoding="utf-8")
        self.assertIn(f"SM_FONT_WIDTH = {GLYPH_SIZE[0]},", header)
        self.assertIn(f"SM_FONT_HEIGHT = {GLYPH_SIZE[1]}", header)
        display = (ROOT / "src/display.c").read_text(encoding="utf-8")
        self.assertIn("font->width == 16 * SM_FONT_WIDTH && font->height == 8 * SM_FONT_HEIGHT", display)
        self.assertIn("font->hslices == 16 && font->vslices == 8", display)
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("FONT_SOURCE := third_party/spleen/spleen-5x8.bdf", makefile)

    def test_the_vi_filter_stays_on_at_320_wide(self):
        """FILTERS_DISABLED looked like the way to a crisp font, and at 16 bpp
        and 320 across libdragon asserts on it at startup (a hardware bug on
        NTSC consoles, its issue #66). The ROM shipped that way once and
        stopped at the assert on the console. Resample stays until the
        framebuffer is 32-bit or 640 wide."""
        display = (ROOT / "src/display.c").read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/", "", display, flags=re.S)   # the comment names the option; the code must not
        self.assertIn("display_init(resolution, DEPTH_16_BPP, 2, GAMMA_NONE, FILTERS_RESAMPLE);", code)
        self.assertNotIn("FILTERS_DISABLED", code)
        self.assertNotIn("FILTERS_DEDITHER", code)


if __name__ == "__main__":
    unittest.main()
