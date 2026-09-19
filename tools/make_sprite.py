#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Write libdragon sprites without the libdragon toolchain.

The only other way to produce a .sprite is libdragon's own mksprite, which
means a MIPS cross-compiler -- an absurd price for "bring your own box
art", so this module writes the container directly.

The format is libdragon's, not ours, and it is reproduced from
tools/mksprite/mksprite.c (spritemaker_write) rather than guessed at:

    offset 0   uint16  width
    offset 2   uint16  height
    offset 4   uint8   0                     (deprecated bitdepth field)
    offset 5   uint8   texture format | 0x80 (SPRITE_FLAGS_EXT)
    offset 6   uint8   hslices
    offset 7   uint8   vslices
    offset 8   pixels, big-endian, then padded to an 8-byte boundary
    then       128-byte sprite_ext_t

Only uncompressed RGBA16 is written. mksprite defaults to compression level 1,
which is a libdragon-specific codec that would have to be reimplemented here;
uncompressed costs about 3 KB per 96x72 cover and saves the console the
decompression, which is the right trade for a card with 50 GB free.

tests/test_make_sprite.py checks the output byte-for-byte against sprites
produced by the real mksprite, so a libdragon change that breaks this will be
caught rather than shipped.
"""

from __future__ import annotations

import argparse
import io
import struct
import sys
from pathlib import Path

CANVAS_SIZE = (96, 72)
# The colour behind art that does not fill the frame. Matching the detail
# panel's background makes a portrait cover look matted rather than pasted.
MATTE_RGBA = (28, 32, 40, 255)

FMT_RGBA16 = 2
SPRITE_FLAGS_EXT = 0x80
SPRITE_EXT_SIZE = 124
SPRITE_EXT_VERSION = 4
TMEM_BYTES = 4096
MAX_LODS = 7


class SpriteError(ValueError):
    pass


def rgba16(red: int, green: int, blue: int, alpha: int) -> int:
    """RGBA8888 -> RGBA5551, exactly as mksprite's conv_rgb5551 does it."""
    return ((red >> 3) << 11) | ((green >> 3) << 6) | ((blue >> 3) << 1) | (1 if alpha >= 128 else 0)


def _slices(width: int, height: int, tiles: tuple[int, int] | None = None) -> tuple[int, int]:
    """Sub-tile counts. mksprite derives them from a 16-pixel grid unless it is
    told the tile size, which the font needs: its glyphs are 5x8, and a sprite
    that claims 16-pixel tiles draws the wrong letters."""
    if tiles:
        tile_width, tile_height = tiles
        if tile_width <= 0 or tile_height <= 0:
            raise SpriteError(f"tile size must be positive, got {tiles}")
        if width % tile_width or height % tile_height:
            raise SpriteError(f"{width}x{height} does not divide into {tile_width}x{tile_height} tiles")
        return max(1, width // tile_width), max(1, height // tile_height)
    return max(1, width // 16), max(1, height // 16)


def _fits_tmem(width: int, height: int) -> bool:
    """Whether the texture fits TMEM in one upload, which the console needs to
    know and cannot work out from width and height alone: rows are padded to
    eight bytes before they are counted."""
    pitch = (width * 2 + 7) & ~7
    return pitch * height <= TMEM_BYTES


def _extended_block(width: int, height: int) -> bytes:
    """sprite_ext_t: no palette, no mipmaps, no detail texture, default sampling."""
    parts = [
        struct.pack(">HHI", SPRITE_EXT_SIZE, SPRITE_EXT_VERSION, 0),
        b"\0" * (8 * MAX_LODS),
        struct.pack(">HH", 0x20 if _fits_tmem(width, height) else 0, 0),
        # texparms for S and T: no translation, one repeat, no mirroring.
        struct.pack(">ffHBB", 0.0, 1.0, 0, 0, 0) * 2,
        # detail texture is absent; mksprite still writes its defaults.
        struct.pack(">ffHBB", 0.0, 2048.0, 0xFFFF, 0, 0) * 2,
        struct.pack(">fBBBB", 0.0, 0, 0, 0, 0),
        b"\0" * 4,  # walign(out, 8)
    ]
    block = b"".join(parts)
    assert len(block) == 128, len(block)
    return block


def encode(image, tiles: tuple[int, int] | None = None) -> bytes:
    """Encode an already-sized RGBA image as an uncompressed RGBA16 sprite."""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    width, height = image.size
    if not (0 < width <= 0xFFFF and 0 < height <= 0xFFFF):
        raise SpriteError(f"unsupported sprite size: {width}x{height}")
    hslices, vslices = _slices(width, height, tiles)
    pixels = image.load()
    body = bytearray()
    for y in range(height):
        for x in range(width):
            body += struct.pack(">H", rgba16(*pixels[x, y]))
    header = struct.pack(">HHBBBB", width, height, 0,
                         FMT_RGBA16 | SPRITE_FLAGS_EXT, hslices, vslices)
    padding = -(len(header) + len(body)) % 8
    return header + bytes(body) + b"\0" * padding + _extended_block(width, height)


def decode(payload: bytes) -> tuple[int, int, bytes]:
    """The inverse of encode(), for looking at a sprite the console will
    draw: width, height, and the pixels as packed RGB bytes, row by row.
    Only the uncompressed RGBA16 this module writes is read; the alpha bit
    is dropped, since a cover is opaque."""
    if len(payload) < 8:
        raise SpriteError("not a sprite: shorter than its header")
    width, height, _depth, fmt, _h, _v = struct.unpack_from(">HHBBBB", payload, 0)
    if fmt & ~SPRITE_FLAGS_EXT != FMT_RGBA16:
        raise SpriteError(f"not an RGBA16 sprite: format {fmt & ~SPRITE_FLAGS_EXT}")
    count = width * height
    if len(payload) < 8 + count * 2:
        raise SpriteError("sprite is shorter than its pixels")
    pixels = struct.unpack_from(f">{count}H", payload, 8)
    rgb = bytearray(count * 3)
    for i, value in enumerate(pixels):
        rgb[i * 3] = (value >> 11) << 3
        rgb[i * 3 + 1] = ((value >> 6) & 0x1F) << 3
        rgb[i * 3 + 2] = ((value >> 1) & 0x1F) << 3
    return width, height, bytes(rgb)


def to_ppm(width: int, height: int, rgb: bytes) -> bytes:
    """Decoded pixels as a binary PPM, which Tk draws without Pillow."""
    return f"P6 {width} {height} 255\n".encode("ascii") + rgb


def fit_image(image, canvas: tuple[int, int] = CANVAS_SIZE,
              matte: tuple[int, int, int, int] = MATTE_RGBA, width_scale: float = 1.0):
    """Fit an image inside the sprite canvas without changing its aspect
    ratio -- after undoing a stretch the source carries, when `width_scale`
    says it does: the Pro menu's metadata is pre-stretched to double width
    for a 640-pixel mode, and fitting that as-is gives a letterboxed
    ribbon of a box."""
    from PIL import Image

    source = image.convert("RGBA")
    if width_scale != 1.0:
        source = source.resize((max(1, round(source.width * width_scale)), source.height),
                               Image.Resampling.LANCZOS)
    source.thumbnail(canvas, Image.Resampling.LANCZOS)
    fitted = Image.new("RGBA", canvas, matte)
    fitted.alpha_composite(source, ((canvas[0] - source.width) // 2,
                                    (canvas[1] - source.height) // 2))
    return fitted


def convert_image(image, destination: Path, canvas: tuple[int, int] | None = CANVAS_SIZE,
                  matte: tuple[int, int, int, int] = MATTE_RGBA,
                  tiles: tuple[int, int] | None = None, width_scale: float = 1.0) -> int:
    """Convert an open Pillow image to a sprite file. Returns the bytes written.

    `canvas` of None keeps the image at its own size, which is what a font
    atlas wants: it is already exactly the right shape and fitting it onto a
    cover-sized matte would destroy it."""
    payload = encode(fit_image(image, canvas, matte, width_scale) if canvas else image, tiles)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return len(payload)


def convert_bytes(data: bytes, destination: Path, what: str = "image",
                  canvas: tuple[int, int] | None = CANVAS_SIZE, width_scale: float = 1.0) -> int:
    """Convert an image held in memory -- one read straight out of a zip."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SpriteError("Pillow is required to convert images: pip install pillow") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            return convert_image(image, destination, canvas, width_scale=width_scale)
    except OSError as exc:
        raise SpriteError(f"cannot read {what}: {exc}") from exc


def convert(source: Path, destination: Path, canvas: tuple[int, int] | None = CANVAS_SIZE,
            matte: tuple[int, int, int, int] = MATTE_RGBA,
            tiles: tuple[int, int] | None = None) -> int:
    """Convert one image file to a sprite. Returns the bytes written."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SpriteError("Pillow is required to convert images: pip install pillow") from exc
    try:
        with Image.open(source) as image:
            return convert_image(image, destination, canvas, matte, tiles)
    except OSError as exc:
        raise SpriteError(f"cannot read image {source}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert an image to a libdragon sprite.")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--width", type=int, default=CANVAS_SIZE[0])
    parser.add_argument("--height", type=int, default=CANVAS_SIZE[1])
    args = parser.parse_args(argv)
    try:
        written = convert(args.source, args.destination, (args.width, args.height))
    except SpriteError as exc:
        parser.error(str(exc))
    print(f"{args.destination}: {written} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
