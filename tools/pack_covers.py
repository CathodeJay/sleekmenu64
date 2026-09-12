#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Turn the box art a library needs into cover sprites, one per box.

The metadata collection files art by game code, and so does this: every ROM
whose header says NSME gets the sprite NSME.sprite, and a library that keeps
Super Mario 64 in a genre folder, two best-of folders and a hacks folder puts
one picture on the card, not four. On a 3,400-game library that is seven
hundred sprites instead of three thousand.

Conversion is done in this process by tools/make_sprite.py, straight from the
bytes of the collection -- a zip is never unpacked onto the card.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import headers, library, make_sprite
from tools.metadata_repo import Found, MetadataRepo, RepoError


class CoverPackError(ValueError):
    pass


@dataclass(frozen=True)
class Plan:
    covers: dict[str, str]        # ROM path -> sprite name
    sources: dict[str, Found]     # sprite name -> where its picture is
    without: list[str]            # ROM paths the collection has no box for


def sprite_name(key: str) -> str:
    """"N/S/M/E" -> "NSME.sprite"; the neutral "N/S/M" -> "NSM.sprite"."""
    return key.replace("/", "") + ".sprite"


def plan(roms_root: Path, rom_paths: list[str], repo: MetadataRepo) -> Plan:
    """Which sprite each ROM gets, and which picture each sprite comes from."""
    covers: dict[str, str] = {}
    sources: dict[str, Found] = {}
    without: list[str] = []
    for rom_path in rom_paths:
        header = headers.read(roms_root / rom_path)
        found = repo.art(header.product_code) if header is not None else None
        if found is None:
            without.append(rom_path)
            continue
        name = sprite_name(found.key)
        covers[rom_path] = name
        sources.setdefault(name, found)
    return Plan(covers, sources, without)


def pack(planned: Plan, repo: MetadataRepo, destination: Path, dry_run: bool = False,
         progress=None) -> int:
    """Write every sprite the plan names. Returns how many were written.
    `progress` is anything with a step(detail) method -- see tools/progress.py
    -- or None; converting several hundred pictures takes long enough to
    look stuck."""
    destination.mkdir(parents=True, exist_ok=True)
    written = 0
    for name in sorted(planned.sources):
        if not dry_run:
            found = planned.sources[name]
            make_sprite.convert_bytes(repo.read(found), destination / name, found.path,
                                      width_scale=repo.width_scale)
        written += 1
        if progress is not None:
            progress.step(name)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roms", type=Path, help="the ROM folder to plan for")
    parser.add_argument("--metadata", type=Path, required=True,
                        help="the metadata collection: its zip, or a folder")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        with MetadataRepo.open(args.metadata) as repo:
            planned = plan(args.roms, library.walk(args.roms), repo)
            written = pack(planned, repo, args.destination, args.dry_run)
    except (CoverPackError, RepoError, make_sprite.SpriteError, library.LibraryError,
            OSError) as exc:
        parser.error(str(exc))
    for rom_path, name in planned.covers.items():
        print(f"{rom_path} -> {name}")
    print(f"{written} sprites, {len(planned.without)} ROMs without a box")
    return 0


if __name__ == "__main__":
    sys.exit(main())
