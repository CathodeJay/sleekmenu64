#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Fold libretro's genres into a list the tab strip can show.

libretro-database files N64 games under twenty-four genres, several of which
hold under a dozen games -- "Various", "Sports with Animals", one Lightgun
Shooter. A tab strip 168 pixels wide cannot show twenty-four of anything, and
a filter you have to cycle past Gambling to reach is not a filter.

The mapping is data, not code, because it is a judgement call and yours is as
good as mine: edit data/genres.csv and rebuild. Nothing here decides what
belongs where.

A genre the file does not mention passes through unchanged and is reported, so
a library with genres this one has never seen grows a visible tab rather than
being silently swallowed.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

SCHEMA_VERSION = 1
SCHEMA_LINE = f"# sleekmenu-genres {SCHEMA_VERSION}"
FIELDS = ("source", "genre")
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "genres.csv"


class GenreMapError(ValueError):
    pass


def loads(text: str) -> dict[str, str]:
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    if not lines:
        return {}
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    if reader.fieldnames is None or tuple(reader.fieldnames) != FIELDS:
        raise GenreMapError(f"header must be exactly {','.join(FIELDS)}, got {reader.fieldnames}")
    mapping: dict[str, str] = {}
    for number, row in enumerate(reader, start=2):
        source = str(row.get("source", "") or "").strip()
        genre = str(row.get("genre", "") or "").strip()
        if not source or not genre:
            raise GenreMapError(f"line {number}: both columns are required")
        if source.casefold() in mapping:
            raise GenreMapError(f"line {number}: duplicate source genre {source!r}")
        mapping[source.casefold()] = genre
    return mapping


def load(path: Path | None = None) -> dict[str, str]:
    path = path or DEFAULT_PATH
    if not path.is_file():
        return {}
    try:
        return loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GenreMapError(f"cannot read genre map: {exc}") from exc


def apply(mapping: dict[str, str], genre: str) -> str:
    """The display genre. An unmapped one is its own answer."""
    if not genre:
        return ""
    return mapping.get(genre.casefold(), genre)


def unmapped(mapping: dict[str, str], genres) -> list[str]:
    """Genres in a library that the file says nothing about."""
    return sorted({genre for genre in genres
                   if genre and genre.casefold() not in mapping})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show what a genre map does to a metadata file.")
    parser.add_argument("metadata", type=Path, help="output of tools/build_metadata.py")
    parser.add_argument("--genres", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args(argv)
    import collections
    import json
    try:
        mapping = load(args.genres)
        games = json.loads(args.metadata.read_text(encoding="utf-8"))["games"]
    except (GenreMapError, OSError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    before = collections.Counter(g["genre"] for g in games if g["genre"])
    after = collections.Counter(apply(mapping, g["genre"]) for g in games if g["genre"])
    print(f"{len(before)} genres -> {len(after)}")
    for name, count in after.most_common():
        print(f"  {count:5}  {name}")
    missing = unmapped(mapping, before)
    if missing:
        print(f"\nnot in {args.genres}, passed through unchanged:")
        for name in missing:
            print(f"  {before[name]:5}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
