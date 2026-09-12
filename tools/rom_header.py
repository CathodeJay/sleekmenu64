#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""What an N64 ROM says about itself.

The first 64 bytes of a cartridge image carry a handful of facts that need no
database: the byte order the dump is in, the country the cartridge was sold in,
the game's own id, and the CRC pair the console checks at boot. Everything else
a library wants -- genre, publisher, year, how many people can play -- is not in
the ROM at any offset, and has to come from somewhere else.

This module is the "somewhere else is not needed" half. It is pure: hand it 64
bytes, get a record back.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADER_SIZE = 0x40

# The three byte orders N64 dumps come in. The extension lies often enough --
# the library this was written for holds 86 byteswapped images named .z64 --
# that the magic is the only thing worth trusting.
MAGIC = {
    b"\x80\x37\x12\x40": "z64",  # big endian, native
    b"\x37\x80\x40\x12": "v64",  # byteswapped pairs
    b"\x40\x12\x37\x80": "n64",  # word swapped
}

OFFSET_CRC = 0x10
OFFSET_TITLE = 0x20
TITLE_LENGTH = 20
OFFSET_ID = 0x3B      # 0x3B media, 0x3C..0x3D game code, 0x3E country, 0x3F version
OFFSET_COUNTRY = 0x3E
OFFSET_VERSION = 0x3F

# Country codes, from krikzz's rom_config_database and the widely-agreed
# community table. Mapped onto the three buckets the catalog stores. A cartridge
# can honestly belong to two: 'A' shipped for both NTSC markets.
COUNTRY = {
    "A": ("USA", "JAPAN"), "E": ("USA",), "N": ("USA",), "J": ("JAPAN",),
    "P": ("EUROPE",), "D": ("EUROPE",), "F": ("EUROPE",), "I": ("EUROPE",),
    "S": ("EUROPE",), "H": ("EUROPE",), "X": ("EUROPE",), "Y": ("EUROPE",),
    "U": ("EUROPE",), "W": ("EUROPE",), "L": ("EUROPE",),
    # NTSC markets the catalog has no bucket for; recorded, never guessed at.
    "B": (), "C": (), "K": (), "7": (),
}

# The same information as the filename says it, for dumps whose header country
# byte is blank -- homebrew and hacks usually leave it zero.
FILENAME_REGIONS = (
    (re.compile(r"\((?:USA|U)\)|\(USA[,)]", re.I), "USA"),
    (re.compile(r"\((?:Japan|J|JP)\)|\(Japan[,)]", re.I), "JAPAN"),
    (re.compile(r"\((?:Europe|E|EUR|PAL)\)|\(Europe[,)]", re.I), "EUROPE"),
    (re.compile(r"\((?:Australia|Germany|France|Italy|Spain|Netherlands|Sweden)\)", re.I), "EUROPE"),
)


def deswap(data: bytes, form: str) -> bytes:
    """Return the header as big-endian bytes, whatever order it arrived in."""
    if form == "v64":
        pairs = bytearray(data)
        pairs[0::2], pairs[1::2] = data[1::2], data[0::2]
        return bytes(pairs)
    if form == "n64":
        out = bytearray(len(data))
        for i in range(0, len(data) - 3, 4):
            out[i:i + 4] = data[i:i + 4][::-1]
        return bytes(out)
    return data


@dataclass
class RomHeader:
    form: str                       # "z64" | "v64" | "n64"
    internal_title: str             # the name the cartridge calls itself
    rom_id: str                     # six symbols, the form registry.dat stores
    game_code: str                  # header 0x3C..0x3D
    country: str                    # the raw country byte, as a character
    version: int
    crc1: int
    crc2: int
    regions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def crc_pair(self) -> str:
        return f"{self.crc1:08X}{self.crc2:08X}"

    @property
    def product_code(self) -> str:
        """The middle group of the NUS number on the cartridge label: media
        letter, two-character game code, region letter -- NUS-*NSME*-USA.

        It is the closest thing the N64 has to the Dreamcast product number
        openMenu keys on, and it is worth exactly one thing here: it is the
        same for every revision and language variant of a release, so it finds
        art when the exact dump is unknown. It is not an identity. Romhacks
        inherit it untouched from whatever they were built on, and two
        characters of game code was never much room for thirteen hundred
        releases."""
        code = self.rom_id[:4]
        return code if len(code) == 4 and "?" not in code else ""


def parse(data: bytes) -> RomHeader | None:
    """None when the bytes are not an N64 header at all."""
    if len(data) < HEADER_SIZE:
        return None
    form = MAGIC.get(bytes(data[:4]))
    if form is None:
        return None
    h = deswap(bytes(data[:HEADER_SIZE]), form)

    raw_title = h[OFFSET_TITLE:OFFSET_TITLE + TITLE_LENGTH]
    title = raw_title.decode("latin-1").rstrip("\0 ").strip()
    title = "".join(c if 32 <= ord(c) < 127 else " " for c in title).strip()

    country_byte = h[OFFSET_COUNTRY]
    country = chr(country_byte) if 32 <= country_byte < 127 else ""
    # The stock firmware's six-symbol id: 0x3B..0x3E as characters, then the
    # version byte as two hex digits. Unprintables render '?', as the menu does.
    symbols = "".join(chr(b) if 32 <= b < 127 else "?" for b in h[OFFSET_ID:OFFSET_ID + 4])

    return RomHeader(
        form=form,
        internal_title=title,
        rom_id=f"{symbols}{h[OFFSET_VERSION]:02X}",
        game_code=symbols[1:3],
        country=country,
        version=h[OFFSET_VERSION],
        crc1=int.from_bytes(h[OFFSET_CRC:OFFSET_CRC + 4], "big"),
        crc2=int.from_bytes(h[OFFSET_CRC + 4:OFFSET_CRC + 8], "big"),
        regions=COUNTRY.get(country, ()),
    )


def regions_for(header: RomHeader | None, filename: str) -> list[str]:
    """The header is the cartridge's own answer and wins. Homebrew and hacks
    usually leave the country byte blank, so the filename is asked second --
    never to override a header that spoke."""
    if header is not None and header.regions:
        return list(header.regions)
    if header is not None and header.country in COUNTRY:
        return []  # it answered, and the answer was a market we have no bucket for
    found = [name for pattern, name in FILENAME_REGIONS if pattern.search(filename)]
    return sorted(set(found), key=found.index)
