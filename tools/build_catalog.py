#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build a deterministic SleekMenu catalog using only Python's stdlib.

Format 2 adds a description string to every record. Text that reaches the
console is reduced to the 95 printable ASCII characters its font has: the
descriptions come from box backs and carry curly quotes, dashes, trademark
signs and the occasional accent, and the browser's 5x8 atlas has 128 glyphs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import unicodedata
import zlib
from pathlib import Path, PurePosixPath

MAGIC = b"EBC1"
VERSION = 2
HEADER = struct.Struct("<4sHHIIIIII")
# title, path, cover, publisher, genre, description offsets; year; players,
# regions, flags; padding to 32 bytes. src/catalog.c reads exactly this.
RECORD = struct.Struct("<IIIIIIHBBB3x")
REGIONS = {"USA": 1, "JAPAN": 2, "EUROPE": 4}
# Cartridge dumps and 64DD disk images; src/catalog.c lists the same set.
ROM_SUFFIXES = {".z64", ".v64", ".n64", ".ndd"}
MAX_DESCRIPTION = 2000
# Record flags. src/catalog.h names the same bits.
FLAG_FAVORITE = 1
# A ROM-shaped file the tool set aside (no N64 header). Carried so the
# browser knows the file and never lists it, rather than finding it in the
# folder and taking it for a game the catalog missed.
FLAG_SET_ASIDE = 2

# Characters the font lacks that have an obvious ASCII spelling. Everything
# else non-ASCII is decomposed and stripped of its accents; what is left
# with no base letter is dropped.
_SPELLINGS = {
    "‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "―": "-", "−": "-", "­": "",
    "…": "...", "™": "", "®": "", "©": "", " ": " ",
    "×": "x", "·": "-", "•": "-", "æ": "ae", "Æ": "AE",
    "œ": "oe", "Œ": "OE", "ß": "ss", "ø": "o", "Ø": "O",
}


class CatalogError(ValueError):
    pass


def _text(value: object, field: str, *, required: bool = True) -> str:
    # An optional field accepts both spellings of "nobody knows": absent, and
    # present but empty. The builder that writes these emits "" rather than
    # omitting the key, so refusing one and not the other would be arbitrary.
    if not required and (value is None or (isinstance(value, str) and not value.strip())):
        return ""
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{field} must be a non-empty string")
    if "\x00" in value:
        raise CatalogError(f"{field} may not contain NUL")
    return value.strip()


def console_text(value: str) -> str:
    """The same words, in the characters the console can draw."""
    text = "".join(_SPELLINGS.get(c, c) for c in value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if 32 <= ord(c) < 127)
    return re.sub(r"\s+", " ", text).strip()


def _description(value: object, field: str) -> str:
    text = _text(value, field, required=False)
    text = console_text(text)
    if len(text) > MAX_DESCRIPTION:
        raise CatalogError(f"{field} is longer than {MAX_DESCRIPTION} characters")
    return text


def _relative_path(value: object, field: str, suffixes: set[str] | None = None) -> str:
    text = _text(value, field)
    path = PurePosixPath(text.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise CatalogError(f"{field} must be a safe relative path")
    normalized = str(path)
    if normalized in ("", "."):
        raise CatalogError(f"{field} must name a file")
    if suffixes is not None and path.suffix.lower() not in suffixes:
        raise CatalogError(f"{field} must end in one of: {', '.join(sorted(suffixes))}")
    return normalized


def normalize(document: object) -> list[dict[str, object]]:
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise CatalogError("root must contain schema_version: 1")
    games = document.get("games")
    if not isinstance(games, list):
        raise CatalogError("games must be an array")

    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(games):
        prefix = f"games[{index}]"
        if not isinstance(raw, dict):
            raise CatalogError(f"{prefix} must be an object")
        path = _relative_path(raw.get("path"), f"{prefix}.path", ROM_SUFFIXES)
        key = path.casefold()
        if key in seen:
            raise CatalogError(f"duplicate ROM path: {path}")
        seen.add(key)

        region_names = raw.get("regions")
        if region_names is None:
            region_names = []
        # An empty list is a ROM whose header names no market and whose
        # filename carries no region tag -- most hacks and homebrew. It stores
        # as mask 0, which the browser reads as "matches no region filter".
        if not isinstance(region_names, list):
            raise CatalogError(f"{prefix}.regions must be an array")
        region_mask = 0
        for name in region_names:
            if not isinstance(name, str) or name.upper() not in REGIONS:
                raise CatalogError(f"{prefix}.regions contains unsupported region: {name!r}")
            region_mask |= REGIONS[name.upper()]

        year = raw.get("year")
        players = raw.get("players")
        # 0 means nobody knows, and that is a real answer for a hack, a
        # homebrew build or a translation no database has ever catalogued. The
        # browser already reads 0 as "unset" and simply never matches a filter
        # on it, so rejecting the file here would only force a wrong guess.
        if year is None:
            year = 0
        if players is None:
            players = 0
        if not isinstance(year, int) or isinstance(year, bool) or not (year == 0 or 1970 <= year <= 2100):
            raise CatalogError(f"{prefix}.year must be 0, or an integer from 1970 to 2100")
        # The console has four controller ports, but a handful of games seat
        # more people than that by sharing pads -- Micro Machines 64 Turbo
        # takes eight. Storing the real number and filtering on "at least"
        # keeps those games findable; clamping to 4 would throw the fact away.
        if not isinstance(players, int) or isinstance(players, bool) or not 0 <= players <= 8:
            raise CatalogError(f"{prefix}.players must be an integer from 0 to 8")
        favorite = raw.get("favorite", False)
        if not isinstance(favorite, bool):
            raise CatalogError(f"{prefix}.favorite must be boolean")
        cover_value = raw.get("cover")
        cover = "" if cover_value in (None, "") else _relative_path(cover_value, f"{prefix}.cover")

        result.append({
            "title": console_text(_text(raw.get("title"), f"{prefix}.title")) or "?",
            "path": path,
            "cover": cover,
            # Genre and publisher come from a database that does not cover
            # hacks, homebrew or translations. Empty means unknown, and the
            # browser never matches an unknown against a filter.
            "publisher": console_text(_text(raw.get("publisher"), f"{prefix}.publisher", required=False)),
            "genre": console_text(_text(raw.get("genre"), f"{prefix}.genre", required=False)),
            "description": _description(raw.get("description"), f"{prefix}.description"),
            "year": year,
            "players": players,
            "region_mask": region_mask,
            "flags": FLAG_FAVORITE if favorite else 0,
        })
    aside = document.get("set_aside", [])
    if not isinstance(aside, list):
        raise CatalogError("set_aside must be an array")
    for index, raw in enumerate(aside):
        prefix = f"set_aside[{index}]"
        if not isinstance(raw, dict):
            raise CatalogError(f"{prefix} must be an object")
        path = _relative_path(raw.get("path"), f"{prefix}.path", ROM_SUFFIXES)
        key = path.casefold()
        if key in seen:
            raise CatalogError(f"duplicate ROM path: {path}")
        seen.add(key)
        result.append({
            "title": console_text(PurePosixPath(path).stem) or "?",
            "path": path,
            "cover": "",
            "publisher": "",
            "genre": "",
            "description": "",
            "year": 0,
            "players": 0,
            "region_mask": 0,
            "flags": FLAG_SET_ASIDE,
        })
    return sorted(result, key=lambda game: (str(game["path"]).casefold(), str(game["title"]).casefold()))


def encode(games: list[dict[str, object]]) -> bytes:
    strings = bytearray(b"\x00")
    offsets: dict[str, int] = {"": 0}

    def intern(value: object) -> int:
        text = str(value)
        if text not in offsets:
            offsets[text] = len(strings)
            strings.extend(text.encode("utf-8") + b"\x00")
        return offsets[text]

    records = bytearray()
    for game in games:
        records.extend(RECORD.pack(
            intern(game["title"]), intern(game["path"]), intern(game["cover"]),
            intern(game["publisher"]), intern(game["genre"]), intern(game["description"]),
            int(game["year"]), int(game["players"]), int(game["region_mask"]),
            int(game["flags"]),
        ))
    records_offset = HEADER.size
    strings_offset = records_offset + len(records)
    payload = bytes(records + strings)
    header = HEADER.pack(MAGIC, VERSION, HEADER.size, len(games), records_offset,
                         strings_offset, len(strings), zlib.crc32(payload), 0)
    return header + payload


def build(input_path: Path, output_path: Path, manifest_path: Path) -> None:
    try:
        document = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read metadata: {exc}") from exc
    games = normalize(document)
    data = encode(games)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    manifest = {
        "catalog_format": VERSION,
        "catalog_sha256": hashlib.sha256(data).hexdigest(),
        "game_count": sum(1 for game in games if not int(game["flags"]) & FLAG_SET_ASIDE),
        "set_aside_count": sum(1 for game in games if int(game["flags"]) & FLAG_SET_ASIDE),
        "input": input_path.name,
        "output": output_path.name,
        "record_size": RECORD.size,
        "size_bytes": len(data),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        build(args.metadata, args.output, args.manifest)
    except CatalogError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())

