# SPDX-License-Identifier: AGPL-3.0-only
"""Minimal but real N64 headers, so tests exercise the code that reads them."""

from pathlib import Path

Z64_MAGIC = b"\x80\x37\x12\x40"


def header_bytes(crc1: int, crc2: int, title: str = "TEST", country: str = "E",
                 version: int = 0, game_code: str = "NT") -> bytes:
    header = bytearray(0x40)
    header[0:4] = Z64_MAGIC
    header[0x10:0x14] = crc1.to_bytes(4, "big")
    header[0x14:0x18] = crc2.to_bytes(4, "big")
    header[0x20:0x34] = title.encode("ascii")[:20].ljust(20, b"\0")
    header[0x3B] = ord("N")
    header[0x3C:0x3E] = game_code.encode("ascii")[:2].ljust(2, b"\0")
    header[0x3E] = ord(country)
    header[0x3F] = version
    return bytes(header)


def write_rom(path: Path, crc1: int, crc2: int, **kwargs) -> str:
    """Create a ROM file and return its header CRC pair, the database key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Padded past the header so the file is plausibly a ROM, not just a header.
    path.write_bytes(header_bytes(crc1, crc2, **kwargs) + b"\0" * 0x40)
    # The header cache is keyed on size and mtime, but a test that rewrites the
    # same path twice inside one clock tick would otherwise read the old one.
    from tools import headers
    headers.clear()
    return f"{crc1:08X}{crc2:08X}"


# The two byte orders that are not the native one. Written out here rather than
# reusing tools/rom_header.deswap, so a test that compares the two is comparing
# two opinions and not one opinion with itself.
V64_MAGIC = b"\x37\x80\x40\x12"   # byteswapped pairs
N64_MAGIC = b"\x40\x12\x37\x80"   # word swapped


def to_v64(image: bytes) -> bytes:
    """The same cartridge dumped with every pair of bytes reversed."""
    return b"".join(image[i:i + 2][::-1] for i in range(0, len(image), 2))


def to_n64(image: bytes) -> bytes:
    """The same cartridge dumped with every 32-bit word reversed."""
    return b"".join(image[i:i + 4][::-1] for i in range(0, len(image), 4))


# Keyed by the form tools/rom_header.py names, so a test can loop over all three
# orderings of one cartridge without spelling the conversion out each time.
SWAP = {"z64": lambda image: image, "v64": to_v64, "n64": to_n64}


def rom_image(crc1: int, crc2: int, body: bytes = b"", **kwargs) -> bytes:
    """A whole plausible big-endian ROM: a real header with something behind
    it, because a CRC32 of nothing but a header proves nothing."""
    return header_bytes(crc1, crc2, **kwargs) + (body or bytes(range(256)) * 4)


def write_rom_in(path: Path, form: str, image: bytes) -> bytes:
    """Write one big-endian image out as a .z64, .v64 or .n64 dump of the same
    cartridge. Returns the bytes that actually landed on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = SWAP[form](image)
    path.write_bytes(data)
    from tools import headers
    headers.clear()
    return data
