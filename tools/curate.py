#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Fix what the database got wrong, once, for everybody.

A genre that is simply wrong turns up constantly and is not a bug in the
matching: libretro files Ocarina of Time under Role-playing, Mario Kart 64
under Sports and Blast Corps under Puzzle. That is real data, honestly
parsed, and still wrong.

The fix belongs in data/coverdb.csv, keyed on the ROM header CRC, because
that file is reviewed and committed: a correction made here is a correction
for every card built afterwards, and coverdb.merge protects it from being
overwritten the next time the database is reseeded.

    curate.py show Ocarina
    curate.py set-genre Ocarina "Action-Adventure"
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import replace
from pathlib import Path

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import coverdb

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "coverdb.csv"


class CurateError(ValueError):
    pass


def matching(database: dict[str, coverdb.Entry], pattern: str) -> list[coverdb.Entry]:
    """Rows whose name matches. A plain string is a case-insensitive substring;
    prefix it with `re:` for a regular expression."""
    if pattern.startswith("re:"):
        try:
            expression = re.compile(pattern[3:], re.IGNORECASE)
        except re.error as exc:
            raise CurateError(f"bad regular expression: {exc}") from exc
        test = lambda name: expression.search(name) is not None
    else:
        needle = pattern.casefold()
        test = lambda name: needle in name.casefold()
    return sorted((entry for entry in database.values() if test(entry.name)),
                  key=lambda entry: (entry.name.casefold(), entry.crc))


def _report(rows: list[coverdb.Entry], field: str, value: str, dry_run: bool, log) -> int:
    for entry in rows:
        before = getattr(entry, field) or "(none)"
        mark = " " if before == value else "*"
        log(f"  {mark} {entry.crc}  {before:22} -> {value:22}  {entry.name}")
    log(f"{len(rows)} rows {'would change' if dry_run else 'changed'}")
    return len(rows)


def set_field(database: dict[str, coverdb.Entry], pattern: str, field: str,
              value: str, dry_run: bool, log=print) -> dict[str, coverdb.Entry]:
    rows = matching(database, pattern)
    if not rows:
        raise CurateError(f"nothing matches {pattern!r}")
    _report(rows, field, value, dry_run, log)
    if dry_run:
        return database
    for entry in rows:
        database[entry.crc] = replace(entry, **{field: value})
    return database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="list rows matching a name")
    show.add_argument("pattern")

    genre = sub.add_parser("set-genre", help="correct the genre on matching rows")
    genre.add_argument("pattern")
    genre.add_argument("genre")

    args = parser.parse_args(argv)
    try:
        database = coverdb.load(args.db)
        if args.command == "show":
            for entry in matching(database, args.pattern):
                print(f"  {entry.crc}  {entry.serial or '----':4}  "
                      f"{entry.genre or '(none)':20}  {entry.name}")
            return 0
        if args.command == "set-genre":
            database = set_field(database, args.pattern, "genre", args.genre, args.dry_run)
        if not args.dry_run:
            coverdb.save(args.db, database)
    except (CurateError, coverdb.CoverDBError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
