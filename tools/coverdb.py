#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""The CRC-keyed record of what a ROM is.

Every user used to re-derive the same facts from scratch, heuristically, on
their own machine: walk the ROMs, compare filenames against a database, hope.
That put a fuzzy string match in the path of every card, and a library named
even slightly differently got half its metadata and no explanation for the
rest.

The Dreamcast scene stopped doing this years ago. openMenu keys its metadata
on the disc's own product number and ships a curated catalogue alongside, so
the guessing happens once, in public, where someone can correct it -- and
never on the console or in a user's build.

This is that file. The key is the ROM header's CRC pair, which the cartridge
computes over its own contents: it is identical for every copy of a dump
whatever the file is called, and it survives byteswapping because the header
is deswapped before it is read. Two different games cannot collide on it; two
copies of one game cannot fail to agree on it. Box art is not in here at all:
it is found by the game code the header carries, in the metadata collection
tools/metadata_repo.py reads.

    crc       16 hex digits: header CRC1 then CRC2, uppercase
    serial    the NUS product code from the header -- NUS-*NSME*-USA -- which
              is shared by every revision and language variant of a release,
              and is therefore the fallback that finds the row for a dump this
              file has never seen. It is not an identity: romhacks inherit it
              from what they were built on.
    name      the canonical (No-Intro) name
    genre     from libretro-database, CC BY-SA 4.0
    publisher likewise
    year      likewise, 0 when unknown
    players   likewise, 0 when unknown
    regions   USA / JAPAN / EUROPE, pipe-separated, from the ROM's country byte

CSV because it is the format a stranger can fix in a pull request without
tooling. Lines starting with '#' are comments.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

SCHEMA_VERSION = 3
SCHEMA_LINE = f"# sleekmenu-coverdb {SCHEMA_VERSION}"
FIELDS = ("crc", "serial", "name", "genre", "publisher", "year", "players", "regions")
# The file is meant to be edited by hand and shared, so it has to tolerate
# its own history. Version 2 carried an `art` column naming the picture in a
# name-keyed art pack; covers are found by game code now and the column is
# read and dropped. Version 1 had no serial column either.
FIELDS_V2 = ("crc", "serial", "name", "art", "genre", "publisher", "year", "players", "regions")
FIELDS_V1 = tuple(field for field in FIELDS_V2 if field != "serial")
KNOWN_FIELDS = (FIELDS, FIELDS_V2, FIELDS_V1)
REGIONS = ("USA", "JAPAN", "EUROPE")
ZERO_CRC = "0" * 16
_CRC = re.compile(r"^[0-9A-F]{16}$")


class CoverDBError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    crc: str
    name: str
    serial: str = ""
    genre: str = ""
    publisher: str = ""
    year: int = 0
    players: int = 0
    regions: tuple[str, ...] = ()

    def __post_init__(self):
        """Canonicalise on construction, so an Entry built in code and one read
        from the file are the same object -- otherwise dumps(loads(x)) != x for
        anything a caller assembled by hand."""
        object.__setattr__(self, "crc", normalise_crc(self.crc))
        object.__setattr__(self, "regions", _regions("|".join(self.regions)))


def normalise_crc(value: str) -> str:
    crc = str(value).strip().upper()
    if not _CRC.match(crc):
        raise CoverDBError(f"crc must be 16 hex digits, got {value!r}")
    if crc == ZERO_CRC:
        # Some homebrew and a few bad dumps leave the CRC pair blank. It is not
        # a key -- every one of them would collide with every other.
        raise CoverDBError("crc is all zeroes, which identifies nothing")
    return crc


def _number(value: str, field: str, maximum: int) -> int:
    text = str(value).strip()
    if not text:
        return 0
    try:
        number = int(text)
    except ValueError as exc:
        raise CoverDBError(f"{field} must be a whole number, got {value!r}") from exc
    if not 0 <= number <= maximum:
        raise CoverDBError(f"{field} must be between 0 and {maximum}, got {number}")
    return number


def _regions(value: str) -> tuple[str, ...]:
    found = [part.strip().upper() for part in str(value).split("|") if part.strip()]
    for region in found:
        if region not in REGIONS:
            raise CoverDBError(f"unknown region {region!r}; expected one of {', '.join(REGIONS)}")
    # Ordered as REGIONS lists them so the file does not churn on rewrite.
    return tuple(region for region in REGIONS if region in found)


def entry_from_row(row: dict[str, str]) -> Entry:
    missing = [field for field in ("crc", "name") if not str(row.get(field, "")).strip()]
    if missing:
        raise CoverDBError(f"row is missing {', '.join(missing)}: {row}")
    return Entry(
        crc=str(row["crc"]).strip(),
        name=str(row["name"]).strip(),
        serial=str(row.get("serial", "") or "").strip().upper(),
        genre=str(row.get("genre", "") or "").strip(),
        publisher=str(row.get("publisher", "") or "").strip(),
        year=_number(row.get("year", ""), "year", 9999),
        players=_number(row.get("players", ""), "players", 8),
        regions=_regions(str(row.get("regions", "") or "")),
    )


def loads(text: str) -> dict[str, Entry]:
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    if not lines:
        return {}
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    if reader.fieldnames is None or tuple(reader.fieldnames) not in KNOWN_FIELDS:
        raise CoverDBError(f"header must be exactly {','.join(FIELDS)}, got {reader.fieldnames}")
    entries: dict[str, Entry] = {}
    for number, row in enumerate(reader, start=2):
        try:
            entry = entry_from_row(row)
        except CoverDBError as exc:
            raise CoverDBError(f"line {number}: {exc}") from exc
        if entry.crc in entries:
            raise CoverDBError(f"line {number}: duplicate crc {entry.crc}")
        entries[entry.crc] = entry
    return entries


def load(path: Path) -> dict[str, Entry]:
    try:
        return loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CoverDBError(f"cannot read cover database: {exc}") from exc


def dumps(entries) -> str:
    """Deterministic text. Sorted by name so a human can find a row and a diff
    shows what actually changed, not what moved."""
    rows = sorted(entries.values() if isinstance(entries, dict) else entries,
                  key=lambda entry: (entry.name.casefold(), entry.name, entry.crc))
    out = io.StringIO()
    out.write(SCHEMA_LINE + "\n")
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    for entry in rows:
        writer.writerow({
            "crc": entry.crc, "serial": entry.serial,
            "name": entry.name, "genre": entry.genre, "publisher": entry.publisher,
            "year": entry.year or "", "players": entry.players or "",
            "regions": "|".join(entry.regions),
        })
    return out.getvalue()


def save(path: Path, entries) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(entries), encoding="utf-8")
    return len(entries)


def merge(base: dict[str, Entry], incoming) -> dict[str, Entry]:
    """Fill gaps in existing rows and add new ones. Never silently replaces a
    value that is already there -- a curated row outranks a generated one."""
    merged = dict(base)
    for entry in (incoming.values() if isinstance(incoming, dict) else incoming):
        current = merged.get(entry.crc)
        if current is None:
            merged[entry.crc] = entry
            continue
        merged[entry.crc] = replace(
            current,
            serial=current.serial or entry.serial,
            genre=current.genre or entry.genre,
            publisher=current.publisher or entry.publisher,
            year=current.year or entry.year,
            players=current.players or entry.players,
            regions=current.regions or entry.regions,
        )
    return merged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and normalise a cover database.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--rewrite", action="store_true",
                        help="write the file back in canonical order")
    args = parser.parse_args(argv)
    try:
        entries = load(args.path)
        if args.rewrite:
            save(args.path, entries)
    except CoverDBError as exc:
        parser.error(str(exc))
    with_serial = sum(1 for entry in entries.values() if entry.serial)
    with_meta = sum(1 for entry in entries.values() if entry.genre or entry.publisher or entry.year)
    print(f"{len(entries)} entries; {with_serial} carry a product code, {with_meta} carry metadata")
    return 0


if __name__ == "__main__":
    sys.exit(main())
