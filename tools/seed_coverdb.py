#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build the shipped cover database from a real ROM library.

This is a maintainer's tool, not something a card owner runs. It does the
guessing once -- here, where the result can be read, corrected and committed --
so that nobody's build has to guess again.

Two ways to identify a game, and the difference matters:

  --file-crc  reads every ROM in full, deswapping byteswapped dumps as it goes,
              and matches the No-Intro CRC32 recorded in libretro-database.
              This is exact. A file renamed to anything at all still matches,
              and so does a .v64 of a game the database only knows as .z64.
              It costs one full read of the library, which is minutes, not
              seconds -- pass --crc-cache so a second run does not repeat it.

  by name     reads only each ROM's 64-byte header and matches libretro on the
              filename. Instant, and wrong often enough to be worth replacing,
              which is exactly why the result belongs in a reviewed file rather
              than in everybody's build.

Either way the row is keyed on the header CRC pair, because that is what the
console and the browser can both compute cheaply from the first 64 bytes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import zlib
from collections import Counter
from dataclasses import replace
from pathlib import Path, PurePosixPath

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import coverdb, rom_header
from tools.libretro_meta import LibretroMeta

ROM_SUFFIXES = {".z64", ".v64", ".n64"}
CHUNK = 1 << 20


def rom_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in ROM_SUFFIXES)


def read_header(path: Path):
    try:
        with path.open("rb") as handle:
            return rom_header.parse(handle.read(rom_header.HEADER_SIZE))
    except OSError:
        return None


def file_crc32(path: Path, form: str) -> str:
    """The CRC32 No-Intro would have recorded, which is always of the big-endian
    image. A byteswapped dump is deswapped on the way past so it matches the
    same database row as its .z64 twin instead of matching nothing."""
    digest = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            if form != "z64":
                if len(chunk) % 4:
                    chunk = chunk[:len(chunk) - len(chunk) % 4]
                chunk = rom_header.deswap(chunk, form)
            digest = zlib.crc32(chunk, digest)
    return f"{digest & 0xFFFFFFFF:08X}"


def load_cache(path: Path | None) -> dict[str, str]:
    """path -> crc32, keyed with size and mtime so an edited file is re-read."""
    if path is None or not path.is_file():
        return {}
    cache: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            cache[f"{row['path']}|{row['size']}|{row['mtime']}"] = row["crc32"]
        except (json.JSONDecodeError, KeyError):
            continue
    return cache


def cache_key(path: Path) -> str:
    stat = path.stat()
    return f"{path}|{stat.st_size}|{int(stat.st_mtime)}"


def seed(roms_root: Path, meta: LibretroMeta, use_file_crc: bool, cache_path: Path | None, deadline: float | None,
         only_unmatched: bool = False, include_unidentified: bool = False,
         log=print) -> tuple[dict[str, coverdb.Entry], Counter, bool]:
    cache = load_cache(cache_path)
    handle = cache_path.open("a", encoding="utf-8") if cache_path else None
    entries: dict[str, coverdb.Entry] = {}
    how: Counter = Counter()
    complete = True
    try:
        for index, path in enumerate(rom_files(roms_root)):
            if deadline is not None and time.monotonic() > deadline:
                log(f"stopping after {index} ROMs; re-run to continue")
                complete = False
                break
            header = read_header(path)
            if header is None:
                how["not a rom"] += 1
                continue
            if header.crc_pair == coverdb.ZERO_CRC:
                # No usable key. Nothing to file it under.
                how["blank header crc"] += 1
                continue

            relative = PurePosixPath(path.relative_to(roms_root).as_posix())
            name, found, kind = "", None, "none"
            # A name match costs nothing; reading a 16 MB ROM off a card at
            # 5 MB/s costs three seconds. With --only-unmatched the cheap
            # answer is tried first and the expensive one only runs where it
            # would actually add something -- hours instead of most of a day
            # on a large library, at the price of trusting a name match that
            # succeeded.
            if only_unmatched:
                name, found, kind = meta.resolve(relative.stem)
            if use_file_crc and found is None:
                key = cache_key(path)
                crc32 = cache.get(key)
                if crc32 is None:
                    crc32 = file_crc32(path, header.form)
                    if handle:
                        handle.write(json.dumps({"path": str(path), "size": path.stat().st_size,
                                                 "mtime": int(path.stat().st_mtime),
                                                 "crc32": crc32}) + "\n")
                        handle.flush()
                hit = meta.by_crc32(crc32)
                if hit:
                    name, found, kind = hit[0], hit[1], "file crc"
            if found is None and not name:
                name, found, kind = meta.resolve(relative.stem)
            how[f"matched by {kind}"] += 1
            if kind == "none" and not include_unidentified:
                # A row whose name is just the filename identifies the dump but
                # not the game, and the pipeline already knows the filename.
                # A placeholder row would only make the database look as if
                # it knew something it does not.
                how["unidentified, not filed"] += 1
                continue

            entry = coverdb.Entry(
                crc=header.crc_pair,
                serial=header.product_code,
                name=name or relative.stem,
                genre=found.genre if found else "",
                publisher=found.publisher if found else "",
                year=found.year if found else 0,
                players=found.players if found else 0,
                regions=tuple(rom_header.regions_for(header, relative.name)),
            )
            # Several files, one dump -- a library that keeps a game in a
            # genre folder and two best-of folders is three files and one row.
            # First writer wins; a later copy only fills in what it left blank.
            if entry.crc in entries:
                entry = coverdb.merge({entry.crc: entries[entry.crc]}, [entry])[entry.crc]
            entries[entry.crc] = entry
    finally:
        if handle:
            handle.close()
    return entries, how, complete


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roms", type=Path, help="the ROM library to read")
    parser.add_argument("--libretro", type=Path, required=True,
                        help="a libretro-database checkout (or its metadat/ directory)")
    parser.add_argument("--file-crc", action="store_true",
                        help="identify games by full-file CRC32 instead of by name")
    parser.add_argument("--only-unmatched", action="store_true",
                        help="with --file-crc, read in full only what the name match missed")
    parser.add_argument("--include-unidentified", action="store_true",
                        help="also file ROMs no database could name (their filename becomes the name)")
    parser.add_argument("--crc-cache", type=Path, help="remember computed CRC32s here")
    parser.add_argument("--time-budget", type=float,
                        help="stop cleanly after this many seconds; re-run to continue")
    parser.add_argument("--merge", action="store_true",
                        help="fill gaps in the existing --output rather than replacing it")
    parser.add_argument("--fill-serials", action="store_true",
                        help="only add missing serials to --output, by name; reads no ROMs")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    meta = LibretroMeta.load(args.libretro)

    if args.fill_serials:
        # No ROM walk: the database already records which game each row is, and
        # libretro records that game's serial. Useful when the library is not
        # to hand, and idempotent when it is.
        existing = coverdb.load(args.output)
        filled = 0
        for key, entry in list(existing.items()):
            if entry.serial:
                continue
            serial = meta.serial_for(entry.name)
            if serial:
                existing[key] = replace(entry, serial=serial)
                filled += 1
        coverdb.save(args.output, existing)
        have = sum(1 for entry in existing.values() if entry.serial)
        print(f"{filled} serials added; {have}/{len(existing)} rows now carry one")
        return 0

    deadline = time.monotonic() + args.time_budget if args.time_budget else None
    entries, how, complete = seed(args.roms, meta, args.file_crc,
                                  args.crc_cache, deadline, args.only_unmatched,
                                  args.include_unidentified)
    if args.merge and args.output.is_file():
        entries = coverdb.merge(coverdb.load(args.output), entries)
    coverdb.save(args.output, entries)

    print(f"{len(entries)} entries -> {args.output}")
    for key in sorted(how):
        print(f"  {how[key]:5}  {key}")
    if not complete:
        print("  INCOMPLETE: ran out of time budget; re-run with the same --crc-cache")
    return 0 if complete else 2


if __name__ == "__main__":
    sys.exit(main())
