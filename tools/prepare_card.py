#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Prepare an EverDrive-64 SD card: one command, no toolchain.

One tool rather than a chain of them, and nothing beyond Python and Pillow:
a card manager the way the Dreamcast scene settled on one. It does these
things in order, in this process:

  1. find each ROM's box in the metadata collection, by its game code
  2. convert those boxes to sprites the console can read, one per box
  3. read every ROM header and build the metadata
  4. encode the catalog and write sleekmenu/ onto the card

Nothing here needs libdragon, a compiler, or a network. Pillow is the only
dependency, and only if there is art to convert.

    python3 tools/prepare_card.py --roms /Volumes/CARD/ROMS --card /Volumes/CARD \\
        --metadata ~/Downloads/release-metadata.zip --rom build/release/SleekMenu64.z64

Pass --dry-run to see exactly what would be written and to where.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import (build_catalog, build_metadata, card_catalog, cover_pack, coverdb, custom_art,
                   library, make_sprite, pack_covers)
from tools.metadata_repo import MetadataRepo, RepoError
from tools.progress import Progress
from tools.card_layout import (  # noqa: F401  (re-exported for callers)
    CARD_FOLDER, COVERS_FOLDER, COVER_PACK_NAME, CATALOG_NAME, CATALOG_JSON_NAME)


class PrepareError(ValueError):
    pass


def _check_directory(path: Path, what: str) -> Path:
    if not path.is_dir():
        raise PrepareError(f"{what} is not a directory: {path}")
    return path


def prepare(roms: Path, card: Path, database_path: Path, repo: MetadataRepo | None = None,
            rom_image: Path | None = None, overrides: Path | None = None,
            work: Path | None = None, dry_run: bool = False,
            loose_covers: bool = False, genres: Path | None = None,
            log=print, progress_stream=None, rom_paths: list[str] | None = None,
            progress_factory=None) -> dict:
    _check_directory(roms, "ROM folder")
    _check_directory(card, "card")
    try:
        roms.resolve().relative_to(card.resolve())
    except ValueError as exc:
        raise PrepareError(
            f"the ROM folder must be on the card: {roms} is not inside {card}. "
            "The catalog records where each game lives relative to the card root, "
            "and the browser has no way to reach anything outside it."
        ) from exc

    work = work or Path(tempfile.mkdtemp(prefix="sleekmenu-"))
    work.mkdir(parents=True, exist_ok=True)
    covers_out = work / CARD_FOLDER / COVERS_FOLDER
    if rom_paths is None:
        rom_paths = library.walk(roms)
    summary: dict[str, object] = {"database_entries": len(coverdb.load(database_path))
                                  if database_path.is_file() else 0}

    covers: dict[str, str] = {}
    # The card owner's own art is looked up whether or not there is a
    # collection: a card of homebrew with a picture beside each game is a
    # card with covers.
    art_folder = custom_art.art_dir(card)
    planned = pack_covers.plan(roms, rom_paths, repo, art_folder)
    if repo is not None or planned.sources:
        covers = planned.covers
        (work / "cover-map.json").write_text(
            json.dumps({"schema_version": 1, "covers": covers}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        (work / "cover-unmatched.json").write_text(
            json.dumps({"schema_version": 1, "unmatched": planned.without}, indent=2) + "\n",
            encoding="utf-8")
        summary.update(covers=len(covers), without_art=len(planned.without),
                       custom_art=planned.custom, hires=planned.hires)
        log(f"covers:   {len(covers)} ROMs have a box"
            + (f" ({planned.custom} from your own art)" if planned.custom else "")
            + (f" ({planned.hires} high-resolution)" if planned.hires else "")
            + f", {len(planned.without)} do not")

        # Progress follows the log: a caller that silenced one wants neither.
        # print is the only log that means "a person is watching" -- unless
        # the caller brought its own progress, which a window does.
        progress = None
        if planned.sources and not dry_run:
            if progress_factory is not None:
                progress = progress_factory(len(planned.sources), "sprites")
            elif log is print and progress_stream is not False:
                progress = Progress(len(planned.sources), "sprites",
                                    stream=None if progress_stream is None else progress_stream)
        summary["sprites"] = pack_covers.pack(planned, repo, covers_out, dry_run=dry_run,
                                              progress=progress)
        if progress is not None:
            progress.done(f"sprites:  {summary['sprites']} written")
        else:
            log(f"sprites:  {summary['sprites']} written to {covers_out}")
        if summary["sprites"] and not loose_covers and not dry_run:
            # One file instead of hundreds. FatFs has no directory index, so
            # every cover opened by name walks the directory from the start --
            # over 100 KB of it, with names this long -- which is the pause
            # between moving the cursor and the picture appearing.
            count, size = cover_pack.pack_directory(covers_out, work / COVER_PACK_NAME)
            summary["pack_bytes"] = size
            log(f"pack:     {count} covers in one {size // 1024} KB file")

    metadata_path = work / "metadata.json"
    document, how = build_metadata.build(roms, card, database_path, genres, overrides,
                                         covers, repo, rom_paths, cover_origins=planned.origins)
    metadata_path.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    summary["games"] = len(document["games"])
    with_meta = sum(1 for game in document["games"]
                    if game["genre"] or game["publisher"] or game["year"] or game["players"])
    with_text = sum(1 for game in document["games"] if game["description"])
    summary["with_metadata"] = with_meta
    summary["with_description"] = with_text
    log(f"metadata: {len(document['games'])} games, {with_meta} with genre/publisher/year/players, "
        f"{with_text} with a description")

    catalog = work / CATALOG_NAME
    build_catalog.build(metadata_path, catalog, work / "catalog.manifest.json")
    summary["catalog_bytes"] = catalog.stat().st_size

    destination = card / CARD_FOLDER
    written: list[str] = []
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(catalog, destination / CATALOG_NAME)
        written.append(f"{CARD_FOLDER}/{CATALOG_NAME}")
        card_catalog.write(card, document)
        written.append(f"{CARD_FOLDER}/{CATALOG_JSON_NAME}")
        # summary["sprites"] is 0 when nothing in the library has a box; there
        # is no pack and no loose sprite to copy, and that is not a failure.
        if summary.get("sprites"):
            if loose_covers:
                target = destination / COVERS_FOLDER
                target.mkdir(parents=True, exist_ok=True)
                for sprite in sorted(covers_out.glob("*.sprite")):
                    shutil.copy2(sprite, target / sprite.name)
                written.append(f"{CARD_FOLDER}/{COVERS_FOLDER}/ ({summary['sprites']} sprites)")
            else:
                shutil.copy2(work / COVER_PACK_NAME, destination / COVER_PACK_NAME)
                written.append(f"{CARD_FOLDER}/{COVER_PACK_NAME} ({summary['sprites']} covers)")
        if rom_image is not None:
            if not rom_image.is_file():
                raise PrepareError(f"ROM image not found: {rom_image}")
            shutil.copy2(rom_image, card / rom_image.name)
            written.append(rom_image.name)
    summary["written"] = written
    summary["work"] = str(work)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--roms", type=Path, required=True, help="the ROM folder on the card")
    parser.add_argument("--card", type=Path, required=True, help="the mounted card root")
    parser.add_argument("--metadata", type=Path,
                        help="the n64-flashcart-menu-metadata release zip, or a folder of it")
    parser.add_argument("--rom", type=Path, help="SleekMenu64.z64 to copy to the card root")
    parser.add_argument("--coverdb", type=Path, default=build_metadata.DEFAULT_COVERDB)
    parser.add_argument("--overrides", type=Path, help="per-game corrections")
    parser.add_argument("--work", type=Path, help="keep intermediate files here")
    parser.add_argument("--dry-run", action="store_true", help="build everything, write nothing")
    parser.add_argument("--loose-covers", action="store_true",
                        help="write a covers/ directory instead of covers.pak; slower to browse")
    parser.add_argument("--genres", type=Path, default=build_metadata.DEFAULT_GENRES,
                        help="genre consolidation map; pass a missing path to keep libretro's")
    args = parser.parse_args(argv)

    repo = None
    try:
        if args.metadata is not None:
            repo = MetadataRepo.open(args.metadata)
        summary = prepare(args.roms, args.card, args.coverdb, repo, args.rom, args.overrides,
                          args.work, args.dry_run, args.loose_covers, args.genres)
    except (PrepareError, RepoError, coverdb.CoverDBError, pack_covers.CoverPackError,
            make_sprite.SpriteError, cover_pack.CoverPackError, build_catalog.CatalogError,
            library.LibraryError, OSError) as exc:
        parser.error(str(exc))
    finally:
        if repo is not None:
            repo.close()

    print()
    if args.dry_run:
        print(f"dry run: nothing written. Intermediates are in {summary['work']}")
    else:
        for item in summary["written"]:
            print(f"wrote {args.card}/{item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
