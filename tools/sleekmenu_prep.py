#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Prepare a card, from the card.

    python3 sleekmenu-prep.pyz

That is the whole thing, when this file sits on the card next to your ROMS
folder: where it is running from is where the card is, so there is nothing
to point it at. It reads every ROM header, finds each game's box and
description in the metadata collection by the game code the header carries,
converts the boxes, packs them, and writes the catalog. Run it again after
adding games and it does the whole card again in a few seconds -- nothing is
downloaded, so there is nothing to save.

What it puts beside itself:

    sleekmenu/catalog.ebc      titles, genre, publisher, year, descriptions
    sleekmenu/covers.pak       every cover in one file

The collection is n64-flashcart-menu-metadata, the public-domain set the
N64FlashcartMenu and the EverDrive-64 Pro both use. This tool never touches
the network: download release-metadata.zip from

    https://github.com/n64-tools/n64-flashcart-menu-metadata/releases

once, drop it on the card next to this file (or in sleekmenu/), and it is
read in place -- the zip is never unpacked onto the card. A card that already
holds the collection unpacked for another menu (menu/metadata) is read as it
is. Without a collection the card gets a catalog and no covers, which is a
working card, not an error.

This is the same pipeline as tools/prepare_card.py with the card found for
you; it exists so that the release can be one ROM and one file, with no
metadata and no art in it.
"""

from __future__ import annotations

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
import sys
import tempfile
from pathlib import Path

from tools import (build_catalog, card_layout, cover_pack, coverdb, headers, library,
                   make_sprite, metadata_repo, pack_covers, prepare_card)
from tools.metadata_repo import MetadataRepo, RepoError
from tools.progress import Progress

BUNDLED_PACKAGE = "sleekmenu_data"     # exists only inside the built archive


class PrepError(Exception):
    pass


def archive_path() -> Path | None:
    """The .pyz this is running from, or None when running from a checkout."""
    candidate = Path(sys.argv[0]).resolve()
    if candidate.suffix == ".pyz" and candidate.is_file():
        return candidate
    return None


def find_card(explicit: Path | None) -> Path:
    """Where the card is. Given `--card`, that. Otherwise the folder this
    archive is sitting in -- which is the point of putting it on the card."""
    if explicit is not None:
        card = explicit.resolve()
        if not card.is_dir():
            raise PrepError(f"{card} is not a folder")
        return card
    archive = archive_path()
    if archive is None:
        raise PrepError("Not running from the card. Either copy sleekmenu-prep.pyz "
                        "to the card root next to your ROMS folder, or pass --card.")
    return archive.parent


def find_roms(card: Path, explicit: Path | None, create: bool = True) -> tuple[Path, bool]:
    """The ROM folder, and whether it had to be created. A fresh card has no
    ROMS/ yet; making it and saying where to put games is more use than an
    error naming a folder the person has not heard of. An explicit --roms that
    does not exist is still an error: that one was typed."""
    if explicit is not None:
        roms = explicit.resolve()
        if not roms.is_dir():
            raise PrepError(f"--roms {roms} is not a folder")
        return roms, False
    roms = card / "ROMS"
    if roms.is_dir():
        return roms, False
    if not create:
        raise PrepError(f"No ROM folder at {roms}.")
    roms.mkdir(parents=True)
    return roms, True


def lay_out(card: Path) -> list[Path]:
    """Every folder the browser or this tool expects, made if missing. Returns
    the ones that were created, for the report."""
    made = []
    folder = card / card_layout.CARD_FOLDER
    if not folder.is_dir():
        folder.mkdir(parents=True)
        made.append(folder)
    return made


def find_metadata(card: Path, explicit: Path | None) -> Path | None:
    """The collection to read: what was pointed at, else what is on the card."""
    if explicit is not None:
        if not (explicit.is_file() or explicit.is_dir()):
            raise PrepError(f"--metadata {explicit} does not exist")
        return explicit
    return metadata_repo.find_on_card(card)


def bundled_data(name: str, work: Path) -> Path | None:
    """A data file carried inside the archive, extracted to `work` so the rest
    of the pipeline -- which reads paths -- can open it. None from a checkout,
    where the caller falls back to the repository's data/ folder."""
    try:
        from importlib import resources
        source = resources.files(BUNDLED_PACKAGE).joinpath(name)
        text = source.read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, TypeError, AttributeError):
        return None
    target = work / name
    target.write_text(text, encoding="utf-8")
    return target


def data_file(name: str, work: Path) -> Path:
    bundled = bundled_data(name, work)
    if bundled is not None:
        return bundled
    checkout = Path(__file__).resolve().parent.parent / "data" / name
    if checkout.is_file():
        return checkout
    raise PrepError(f"{name} is neither bundled in this archive nor in a checkout's data/ folder")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sleekmenu-prep",
        description="Prepare an SD card for SleekMenu 64: scan ROMs, find their box art and "
                    "descriptions in the metadata collection, write the catalog and cover pack.")
    parser.add_argument("--card", type=Path, default=None,
                        help="card root (default: the folder this file is in)")
    parser.add_argument("--roms", type=Path, default=None,
                        help="ROM folder (default: ROMS/ on the card)")
    parser.add_argument("--metadata", type=Path, default=None,
                        help="the n64-flashcart-menu-metadata release zip or folder "
                             "(default: whichever is on the card)")
    parser.add_argument("--dry-run", action="store_true",
                        help="do everything except write to the card")
    args = parser.parse_args(argv)

    try:
        card = find_card(args.card)
        roms, roms_created = find_roms(card, args.roms, create=not args.dry_run)
        source = find_metadata(card, args.metadata)
    except PrepError as error:
        print(f"sleekmenu-prep: {error}", file=sys.stderr)
        return 2

    print(f"card:     {card}")
    print(f"roms:     {roms}")
    if not args.dry_run:
        for folder in lay_out(card):
            print(f"created   {folder.relative_to(card)}/")
    if roms_created:
        print(f"created   {roms.relative_to(card)}/")
        print()
        print("There were no games yet, so the folders are in place and nothing "
              "else was done. Copy your ROMs into ROMS/ -- any subfolders you like --"
              " and run this again.")
        return 0

    # One pass over the card, with progress, before anything else asks. Every
    # later step reads headers through the cache and touches the card no more.
    rom_paths = library.walk(roms)
    if not rom_paths:
        print("\nROMS/ has no .z64, .v64 or .n64 files in it. Copy your games there "
              "and run this again.")
        return 0
    scan = Progress(len(rom_paths), "scanning")
    found = headers.scan(roms, rom_paths, scan)
    scan.done(f"scanned   {len(rom_paths)} files, {found} are N64 ROMs")

    work = Path(tempfile.mkdtemp(prefix="sleekmenu-prep-"))
    repo = None
    try:
        database_path = data_file("coverdb.csv", work)
        genres_path = data_file("genres.csv", work)
        if source is None:
            print("metadata: no collection on the card; the card gets a catalog and no covers")
            print(f"          download {metadata_repo.RELEASE_ZIP_NAME} from "
                  f"{metadata_repo.RELEASES_URL}")
            print("          and put it next to this file, then run this again")
        else:
            repo = MetadataRepo.open(source)
            print(f"metadata: {repo.art_count()} boxes in {source}")
        summary = prepare_card.prepare(
            roms=roms, card=card, database_path=database_path, repo=repo,
            work=work / "build", dry_run=args.dry_run, genres=genres_path, log=print,
            progress_stream=None, rom_paths=rom_paths)
    except (PrepError, RepoError, prepare_card.PrepareError, coverdb.CoverDBError,
            pack_covers.CoverPackError, make_sprite.SpriteError, cover_pack.CoverPackError,
            build_catalog.CatalogError, library.LibraryError, OSError) as error:
        print(f"sleekmenu-prep: {error}", file=sys.stderr)
        return 1
    finally:
        if repo is not None:
            repo.close()

    if args.dry_run:
        print("\ndry run: nothing written to the card")
    else:
        for name in summary.get("written", []):
            print(f"wrote     {card / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
