#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""The half an N64 ROM cannot answer: genre, publisher, year, players.

None of those four are anywhere in a cartridge image, so they come from
libretro-database -- a checkout the caller points at, never vendored here. Its
metadat/ files are clrmamepro DATs keyed on the No-Intro name, which is the
same name convention the library and the box art already use.

The DATs are Creative Commons Attribution-ShareAlike 4.0. Nothing from them is
copied into this repository; a catalog built with this module carries the
attribution the licence asks for, and building one is the user's own act on
their own library.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DAT_NAME = "Nintendo - Nintendo 64.dat"

# folder under metadat/ -> (key inside the game block, field on GameMeta)
SOURCES = {
    "genre": ("genre", "genre"),
    "publisher": ("publisher", "publisher"),
    "releaseyear": ("releaseyear", "year"),
    "maxusers": ("users", "players"),
}

GAME_BLOCK = re.compile(r"game \(\s*(.*?)\s*\n\)", re.S)
COMMENT = re.compile(r'comment "([^"]*)"')
# Every block also carries the No-Intro CRC32 of the ROM file itself. That is a
# far better key than the name -- it is what the dump IS, not what someone
# called it -- and it is how tools/seed_coverdb.py builds the shipped database.
# The CRC may sit anywhere inside the rom ( ... ) block: libretro writes
# `rom ( crc XXXXXXXX )`, but the wider clrmamepro convention is
# `rom ( name "..." size N crc XXXXXXXX )`. Anchoring on `crc` as the
# first token made the second shape parse to nothing, silently, which
# would drop the whole exact-CRC path with no counter to show it.
ROM_CRC = re.compile(r'rom\s*\((?:"[^"]*"|[^)"])*?\bcrc\s+([0-9A-Fa-f]{1,8})')
# metadat/serial carries the NUS number printed on the cartridge label. The
# middle group is header bytes 0x3B..0x3E, so a ROM answers it for free -- and
# it is shared by every revision and language variant of a release, which is
# what makes it the right fallback when the exact dump is unknown.
SERIAL = re.compile(r'serial "([^"]*)"')
SERIAL_FOLDER = "serial"

# No-Intro renamed lettered revisions to numbers; the library holds both
# spellings, sometimes as two copies of the same bytes.
REVISIONS = {f" (Rev {chr(ord('A') + i)})": f" (Rev {i + 1})" for i in range(8)}
# GoodN64-style short region tags, still common on cards assembled years ago.
SHORT_REGIONS = {" (U)": " (USA)", " (E)": " (Europe)", " (J)": " (Japan)"}
TRAILING_TAG = re.compile(r"\s*\([^()]*\)\s*$")


@dataclass
class GameMeta:
    genre: str = ""
    publisher: str = ""
    year: int = 0
    players: int = 0

    def __bool__(self) -> bool:
        return bool(self.genre or self.publisher or self.year or self.players)


def _loose(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _candidates(stem: str):
    """Names to try, best first. Every one is a rename someone actually made,
    not a guess at what a title might have been called."""
    yield stem
    swapped = stem
    for old, new in REVISIONS.items():
        swapped = swapped.replace(old, new)
    for old, new in SHORT_REGIONS.items():
        swapped = swapped.replace(old, new)
    if swapped != stem:
        yield swapped
    # Peel trailing parenthetical tags one at a time: "(USA) (Rev 1) (Beta)"
    # loses the beta first, then the revision. Region is peeled last and only
    # if nothing else matched, since it is the tag most likely to matter.
    trimmed = swapped
    while True:
        match = TRAILING_TAG.search(trimmed)
        if not match:
            break
        trimmed = trimmed[:match.start()]
        if trimmed:
            yield trimmed


class LibretroMeta:
    def __init__(self) -> None:
        self.by_name: dict[str, GameMeta] = {}
        self.by_loose: dict[str, GameMeta] = {}
        self.loose_names: dict[str, str] = {}
        self.crc_names: dict[str, str] = {}
        self.serials: dict[str, str] = {}
        self.loose_serials: dict[str, str] = {}
        self.serials_by_crc: dict[str, str] = {}
        self.name_crcs: dict[str, str] = {}
        self.counts: dict[str, int] = {}

    @classmethod
    def load(cls, root: Path) -> "LibretroMeta":
        metadat = Path(root)
        if metadat.name != "metadat":
            metadat = metadat / "metadat"
        if not metadat.is_dir():
            raise FileNotFoundError(f"no metadat/ directory under {root}")
        self = cls()
        for folder, (key, attribute) in SOURCES.items():
            path = metadat / folder / DAT_NAME
            if not path.is_file():
                self.counts[folder] = 0
                continue
            found = 0
            pattern = re.compile(re.escape(key) + r'\s+"?([^"\n]*)"?')
            for block in GAME_BLOCK.findall(path.read_text(encoding="utf-8", errors="replace")):
                name = COMMENT.search(block)
                value = pattern.search(block)
                if not name:
                    continue
                crc = ROM_CRC.search(block)
                if crc:
                    key = crc.group(1).upper().zfill(8)
                    self.crc_names.setdefault(key, name.group(1))
                    self.name_crcs.setdefault(name.group(1), key)
                if not value:
                    continue
                text = value.group(1).strip()
                if not text:
                    continue
                entry = self.by_name.setdefault(name.group(1), GameMeta())
                if attribute in ("year", "players"):
                    digits = re.match(r"\d+", text)
                    if not digits:
                        continue
                    setattr(entry, attribute, int(digits.group(0)))
                else:
                    setattr(entry, attribute, text)
                found += 1
            self.counts[folder] = found
        serial_path = metadat / SERIAL_FOLDER / DAT_NAME
        if serial_path.is_file():
            for block in GAME_BLOCK.findall(serial_path.read_text(encoding="utf-8", errors="replace")):
                name = COMMENT.search(block)
                serial = SERIAL.search(block)
                if name and serial:
                    self.serials.setdefault(name.group(1), serial.group(1).strip())
                    crc = ROM_CRC.search(block)
                    if crc:
                        self.serials_by_crc.setdefault(crc.group(1).upper().zfill(8),
                                                       serial.group(1).strip())
            # The serial DAT spells titles its own way -- "007 - GoldenEye
            # (Japan)" where the genre DAT says "GoldenEye 007 (Japan)" -- so
            # an exact join loses real games. Index it loosely as well.
            for name, serial in self.serials.items():
                self.loose_serials.setdefault(_loose(name), serial)
            self.counts[SERIAL_FOLDER] = len(self.serials)

        # A loose index for names that differ only in punctuation or case.
        for name, meta in self.by_name.items():
            self.by_loose.setdefault(_loose(name), meta)
            self.loose_names.setdefault(_loose(name), name)
        return self

    def resolve(self, stem: str) -> tuple[str, GameMeta | None, str]:
        """The database's own name for this game, the metadata, and how it was
        found -- so a caller can report the difference between a name that
        matched outright and one that only matched after a tag was peeled off.

        The name matters as much as the metadata: it is the title an art pack
        will have filed the cover under, and it is what goes in the shipped
        cover database so nobody has to guess at it twice."""
        for index, candidate in enumerate(_candidates(stem)):
            hit = self.by_name.get(candidate)
            if hit:
                return candidate, hit, "exact" if index == 0 else "variant"
        loose = _loose(stem)
        hit = self.by_loose.get(loose)
        if hit:
            return self.loose_names.get(loose, stem), hit, "loose"
        return "", None, "none"

    def lookup(self, stem: str) -> tuple[GameMeta | None, str]:
        _, meta, kind = self.resolve(stem)
        return meta, kind

    def serial_for(self, name: str) -> str:
        """The NUS middle group for a game the database knows by name, in the
        four-symbol form a ROM header gives: NUS-*NSME*-USA -> NSME."""
        serial = ""
        for candidate in _candidates(name):
            serial = self.serials.get(candidate, "")
            if serial:
                break
        if not serial:
            serial = self.loose_serials.get(_loose(name), "")
        if not serial:
            # The serial DAT titles some games its own way -- "007 - GoldenEye"
            # where the others say "GoldenEye 007" -- and no amount of string
            # normalising reorders that. Both DATs carry the No-Intro CRC32 of
            # the same file, so join on that instead and stop guessing.
            crc = self.name_crcs.get(name)
            if crc:
                serial = self.serials_by_crc.get(crc, "")
        if not serial:
            return ""
        parts = serial.split("-")
        code = parts[1] if len(parts) == 3 else serial
        return code.strip().upper() if len(code.strip()) == 4 else ""

    def by_crc32(self, crc32: str) -> tuple[str, GameMeta | None] | None:
        """Look a game up by the No-Intro CRC32 of the ROM file. Exact, and
        indifferent to what the file was renamed to."""
        name = self.crc_names.get(str(crc32).upper().zfill(8))
        if name is None:
            return None
        return name, self.by_name.get(name)
