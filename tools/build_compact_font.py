#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build SleekMenu's interface font from the vendored Spleen 5x8 BDF.

The browser draws text with libdragon's graphics_draw_text, which takes a
sprite atlas of fixed cells, one per ASCII code: sixteen columns, eight
rows, the cell size being the glyph size. The font used to be libdragon's
example atlas shrunk from 16x16 to 6x8 by nearest-neighbour, which left
every letter a little ragged. Spleen is drawn at 5x8 to begin with, so each
pixel of it is meant to be there.

The BDF is read here rather than converted by any font tool: it is a plain
text format, one hex row per scanline, and reading it keeps the release
build free of anything beyond Python and Pillow. tools/make_sprite.py then
writes libdragon's sprite container; the test suite checks that output
byte-for-byte against the real mksprite, tile counts included.
"""
from __future__ import annotations
import argparse
from pathlib import Path

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import make_sprite

ATLAS_COLUMNS, ATLAS_ROWS = 16, 8
GLYPH_SIZE = (5, 8)
ATLAS_SIZE = (ATLAS_COLUMNS * GLYPH_SIZE[0], ATLAS_ROWS * GLYPH_SIZE[1])
SPRITE_NAME = "sleekmenu-font.sprite"
DEFAULT_SOURCE = Path(__file__).resolve().parent.parent / "third_party" / "spleen" / "spleen-5x8.bdf"
# The atlas holds one cell per code the browser can ask for; the font's
# other glyphs (Latin-1, box drawing) are not reachable through a C char.
FIRST_CODE, LAST_CODE = 0, ATLAS_COLUMNS * ATLAS_ROWS - 1


def parse_bdf(text: str) -> tuple[tuple[int, int, int, int], dict[int, list[int]]]:
    """The font's bounding box (width, height, x offset, y offset) and, per
    code point, the glyph as rows of set pixels, each row an int with bit
    (width - 1 - x) for pixel x, already placed in the font's box."""
    box = None
    glyphs: dict[int, list[int]] = {}
    code = None
    bbx = None
    rows: list[int] | None = None
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        key = parts[0]
        if key == "FONTBOUNDINGBOX":
            box = tuple(int(v) for v in parts[1:5])
        elif key == "STARTCHAR":
            code, bbx, rows = None, None, None
        elif key == "ENCODING":
            code = int(parts[1])
        elif key == "BBX":
            bbx = tuple(int(v) for v in parts[1:5])
        elif key == "BITMAP":
            rows = []
        elif key == "ENDCHAR":
            if code is not None and code >= 0 and bbx is not None and rows is not None and box is not None:
                glyphs[code] = _place(box, bbx, rows)
            code, bbx, rows = None, None, None
        elif rows is not None:
            # A bitmap row: hex, most significant bit leftmost, padded to
            # whole bytes on the right.
            rows.append(int(key, 16) >> (len(key) * 4 - bbx[0]) if bbx and bbx[0] else 0)
    if box is None:
        raise ValueError("not a BDF: no FONTBOUNDINGBOX")
    return box, glyphs


def _place(box, bbx, rows):
    """A glyph's rows in the font's box. Both are given from the baseline:
    the font box's y offset is the descent, the glyph's its own."""
    width, height, x_offset, y_offset = box
    glyph_width, glyph_height, glyph_x, glyph_y = bbx
    placed = [0] * height
    top = (height + y_offset) - (glyph_height + glyph_y)   # rows of box above the glyph
    for i, row in enumerate(rows[:glyph_height]):
        y = top + i
        if 0 <= y < height:
            shifted = row << (width - glyph_width - (glyph_x - x_offset))
            placed[y] |= shifted & ((1 << width) - 1)
    return placed


def build_atlas(source: Path, output: Path) -> None:
    from PIL import Image
    box, glyphs = parse_bdf(source.read_text(encoding="utf-8", errors="replace"))
    if (box[0], box[1]) != GLYPH_SIZE:
        raise ValueError(f"font source must be {GLYPH_SIZE[0]}x{GLYPH_SIZE[1]}, got {box[0]}x{box[1]}")
    atlas = Image.new("RGBA", ATLAS_SIZE, (0, 0, 0, 0))
    pixels = atlas.load()
    for code in range(FIRST_CODE, LAST_CODE + 1):
        rows = glyphs.get(code)
        if not rows:
            continue
        left, top = (code % ATLAS_COLUMNS) * GLYPH_SIZE[0], (code // ATLAS_COLUMNS) * GLYPH_SIZE[1]
        for y, row in enumerate(rows):
            for x in range(GLYPH_SIZE[0]):
                if row & (1 << (GLYPH_SIZE[0] - 1 - x)):
                    pixels[left + x, top + y] = (255, 255, 255, 255)
    output.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(output, format="PNG", optimize=False)


def build(source: Path, filesystem: Path, work: Path) -> Path:
    """BDF -> atlas -> tiled RGBA16 sprite, in this process. The tile size
    is the glyph size: a sprite that claims libdragon's default 16-pixel
    tiles draws the wrong letter for every character."""
    atlas = work / "sleekmenu-font.png"
    build_atlas(source, atlas)
    filesystem.mkdir(parents=True, exist_ok=True)
    sprite = filesystem / SPRITE_NAME
    make_sprite.convert(atlas, sprite, canvas=None, tiles=GLYPH_SIZE)
    return sprite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--filesystem", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args(argv)
    sprite = build(args.source, args.filesystem, args.work)
    print(f"{sprite}: {sprite.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
