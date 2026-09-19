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
from dataclasses import dataclass, field
from pathlib import Path

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import custom_art, headers, hires, library, make_sprite, provenance
from tools.custom_art import Custom
from tools.metadata_repo import Found, MetadataRepo, RepoError


class CoverPackError(ValueError):
    pass


@dataclass(frozen=True)
class Plan:
    covers: dict[str, str]                 # ROM path -> sprite name
    sources: dict[str, object]             # sprite name -> where its picture is: Found, Custom or Hires
    without: list[str]                     # ROM paths with no box anywhere
    custom: int = 0                        # ROMs whose box is the card owner's own
    origins: dict[str, str] = field(default_factory=dict)   # ROM path -> tools/provenance.py label
    hires: int = 0                         # ROMs whose box is a fetched high-resolution one


def sprite_name(key: str) -> str:
    """"N/S/M/E" -> "NSME.sprite"; the neutral "N/S/M" -> "NSM.sprite"."""
    return key.replace("/", "") + ".sprite"


def collection_origin(found: Found, code: str) -> str:
    """Whether the collection answered with this cartridge's own box (its
    region's, or the region-neutral one) or with another region's."""
    key = found.key.replace("/", "").upper()
    if key == code.upper() or len(key) == 3:
        return provenance.COVER_COLLECTION
    return provenance.COVER_COLLECTION_REGION


def plan(roms_root: Path, rom_paths: list[str], repo: MetadataRepo | None,
         art_folder: Path | None = None) -> Plan:
    """Which sprite each ROM gets, and which picture each sprite comes from:
    the card owner's own picture first (tools/custom_art.py), a fetched
    high-resolution box second (tools/hires.py), the collection last. A
    picture named after a game code -- the owner's or a fetched one --
    takes the collection's sprite name for that code and so replaces the
    collection's box for every ROM that carries it. `origins` says which
    answered, per ROM, in tools/provenance.py's words."""
    covers: dict[str, str] = {}
    sources: dict[str, object] = {}
    without: list[str] = []
    origins: dict[str, str] = {}
    custom = high = 0
    index = custom_art.Index()
    hires_folder = hires.folder(art_folder)
    for rom_path in rom_paths:
        header = headers.read(roms_root / rom_path)
        code = header.product_code if header is not None else ""
        own = custom_art.find_art(index, roms_root, rom_path, art_folder, code)
        if own is not None:
            covers[rom_path] = own.sprite
            sources[own.sprite] = own
            origins[rom_path] = (provenance.yours_code(code) if own.sprite == custom_art.code_sprite(code)
                                 else provenance.COVER_YOURS_ROM)
            custom += 1
            continue
        big = hires.find(index, hires_folder, code)
        if big is not None:
            covers[rom_path] = big.sprite
            if not isinstance(sources.get(big.sprite), Custom):
                sources[big.sprite] = big
            origins[rom_path] = hires.origin(hires_folder, big.path)
            high += 1
            continue
        found = repo.art(code) if repo is not None and header is not None else None
        if found is None:
            without.append(rom_path)
            origins[rom_path] = provenance.NONE
            continue
        name = sprite_name(found.key)
        covers[rom_path] = name
        if not isinstance(sources.get(name), (Custom, hires.Hires)):
            sources.setdefault(name, found)
        origins[rom_path] = collection_origin(found, code)
    return Plan(covers, sources, without, custom, origins, high)


def pack(planned: Plan, repo: MetadataRepo | None, destination: Path, dry_run: bool = False,
         progress=None, large_destination: Path | None = None) -> int:
    """Write every sprite the plan names. Returns how many were written.
    `progress` is anything with a step(detail) method -- see tools/progress.py
    -- or None; converting several hundred pictures takes long enough to
    look stuck. With `large_destination`, the box view's 256x180 sprite is
    written there too, from the same decode of the same picture, under the
    same name: one plan, two sizes, so the two packs cannot disagree."""
    destination.mkdir(parents=True, exist_ok=True)
    if large_destination is not None:
        large_destination.mkdir(parents=True, exist_ok=True)
    written = 0
    for name in sorted(planned.sources):
        if not dry_run:
            found = planned.sources[name]
            also = ([(large_destination / name, make_sprite.LARGE_CANVAS_SIZE)]
                    if large_destination is not None else [])
            if isinstance(found, Found):
                make_sprite.convert_bytes(repo.read(found), destination / name, found.path,
                                          width_scale=repo.width_scale, also=also)
            else:
                make_sprite.convert(found.path, destination / name, also=also)
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
