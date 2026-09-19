#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Prepare a card, from the card.

    python3 sleekmenu-prep.pyz

That is the whole thing, when this file sits on the card: where it is
running from is where the card is, so there is nothing to point it at. It
finds your games wherever they are on the card -- a ROMS folder, a folder of
your own, loose at the root -- reads every ROM header, finds each game's box
and description in the metadata collection by the game code the header
carries, converts the boxes, packs them, and writes the catalog. Run it
again after adding games and it does the whole card again in a few seconds
-- nothing is downloaded, so there is nothing to save.

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
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from tools import (build_catalog, card_layout, cover_pack, coverdb, headers, library,
                   make_sprite, metadata_repo, n64_checksum, pack_covers, prepare_card)
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
                        "to the card root, or pass --card.")
    return archive.parent


@dataclass(frozen=True)
class Library:
    root: Path              # what the ROM paths are relative to: the card, or --roms
    rom_paths: list[str]    # every ROM under it, as library.walk lists them
    created: Path | None    # the ROMS/ folder made for a card with no games yet


def find_library(card: Path, explicit: Path | None, create: bool = True) -> Library:
    """Where the games are. Nothing is assumed about the folder: the whole
    card is walked, minus the folders that are known not to hold games, so
    `ROMS`, `roms`, `Games`, two folders or loose files at the root all
    work, and the catalog spells each folder the way the card does. A card
    with no games at all gets a ROMS/ folder and a message saying where the
    games go, which is more use than an error naming a folder the person
    has not heard of. An explicit --roms that does not exist is still an
    error: that one was typed."""
    if explicit is not None:
        root = library.spelled_on_disk(card, explicit)
        if not root.is_dir():
            raise PrepError(f"--roms {explicit} is not a folder")
        return Library(root, library.walk(root), None)
    rom_paths = library.walk(card)
    if rom_paths:
        return Library(card, rom_paths, None)
    roms = card / "ROMS"
    if roms.is_dir() or not create:
        return Library(card, [], None)
    roms.mkdir(parents=True)
    return Library(card, [], roms)


def describe_library(found: Library) -> str:
    """One line for the report: `3412 in ROMS/, 3 at the card root`."""
    where: Counter[str] = Counter()
    for path in found.rom_paths:
        where["in " + path.split("/", 1)[0] + "/" if "/" in path else "at the card root"] += 1
    if not where:
        return "no ROMs"
    return ", ".join(f"{count} {name}"
                     for name, count in sorted(where.items(), key=lambda item: (-item[1], item[0])))


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


@dataclass(frozen=True)
class ChecksumReport:
    checked: int              # dumps the database does not know, summed
    mismatched: list[str]     # of those, the ones whose header does not match
    fixed: list[str]          # rewritten, when asked to
    unknown_boot: int         # a boot code with no checksum rules (homebrew)


def check_checksums(roms: Path, rom_paths: list[str], database: dict, fix: bool,
                    progress=None) -> ChecksumReport:
    """The boot code's checksum, for every dump the database does not know.
    A retail dump the database knows is by definition intact; hacks,
    translations and homebrew are where a header goes stale, and they are
    a few hundred files rather than a few thousand, each read a megabyte
    deep. With `fix`, a header that does not match is rewritten in place,
    which is why it is a switch and not the default."""
    checked = unknown_boot = 0
    mismatched: list[str] = []
    fixed: list[str] = []
    for rom_path in rom_paths:
        header = headers.read(roms / rom_path)
        if header is None or header.crc_pair in database:
            continue
        try:
            verdict = n64_checksum.fix(roms / rom_path) if fix else n64_checksum.verify(roms / rom_path)
        except (n64_checksum.ChecksumError, OSError):
            continue
        if progress is not None:
            progress.step(Path(rom_path).name)
        if not verdict.known:
            unknown_boot += 1
            continue
        checked += 1
        if not verdict.matches:
            mismatched.append(rom_path)
            if fix:
                fixed.append(rom_path)
                headers.clear()
    return ChecksumReport(checked, mismatched, fixed, unknown_boot)


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


def report_checksums(roms: Path, rom_paths: list[str], database: dict, fix: bool) -> None:
    """The checksum pass and what it says. A mismatch is the one thing on
    a card that makes a game black-screen on the console and work in an
    emulator, so it is named file by file, with the way out."""
    candidates = sum(1 for p in rom_paths
                     if (h := headers.read(roms / p)) is not None and h.crc_pair not in database)
    if not candidates:
        return
    progress = Progress(candidates, "checksums")
    report = check_checksums(roms, rom_paths, database, fix, progress)
    progress.done(f"checksum: {report.checked} hacks, translations and homebrew checked, "
                  f"{len(report.mismatched)} with a header that does not match"
                  + (f", {report.unknown_boot} with a boot code of their own" if report.unknown_boot else ""))
    for rom_path in report.mismatched:
        print(f"          {'fixed  ' if rom_path in report.fixed else 'BAD    '} {rom_path}")
    if report.mismatched and not fix:
        print("          The browser rewrites these at launch where the cartridge lets it; "
              "to fix the files themselves, run again with --fix-checksums.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sleekmenu-prep",
        description="Prepare an SD card for SleekMenu 64: scan ROMs, find their box art and "
                    "descriptions in the metadata collection, write the catalog and cover pack.")
    parser.add_argument("--card", type=Path, default=None,
                        help="card root (default: the folder this file is in)")
    parser.add_argument("--roms", type=Path, default=None,
                        help="one folder to catalog (default: every game on the card)")
    parser.add_argument("--metadata", type=Path, default=None,
                        help="the n64-flashcart-menu-metadata release zip or folder "
                             "(default: whichever is on the card)")
    parser.add_argument("--dry-run", action="store_true",
                        help="do everything except write to the card")
    parser.add_argument("--fix-checksums", action="store_true",
                        help="rewrite the header checksum of a hack that would not boot on a console")
    parser.add_argument("--no-checksums", action="store_true",
                        help="skip the checksum pass over hacks and homebrew")
    args = parser.parse_args(argv)

    try:
        card = find_card(args.card)
        found = find_library(card, args.roms, create=not args.dry_run)
        source = find_metadata(card, args.metadata)
    except (PrepError, library.LibraryError) as error:
        print(f"sleekmenu-prep: {error}", file=sys.stderr)
        return 2

    roms, rom_paths = found.root, found.rom_paths
    print(f"card:     {card}")
    print(f"roms:     {describe_library(found)}" + (f" under {roms}" if roms != card else ""))
    if not args.dry_run:
        for folder in lay_out(card):
            print(f"created   {folder.relative_to(card)}/")
    if found.created is not None:
        print(f"created   {found.created.relative_to(card)}/")
        print()
        print("There were no games yet, so the folders are in place and nothing "
              "else was done. Copy your ROMs onto the card -- into ROMS/, or any "
              "folders you like -- and run this again.")
        return 0
    if not rom_paths:
        print("\nNo .z64, .v64 or .n64 files anywhere on the card. Copy your games "
              "onto it, in any folders you like, and run this again.")
        return 0

    # One pass over the card, with progress, before anything else asks. Every
    # later step reads headers through the cache and touches the card no more.
    scan = Progress(len(rom_paths), "scanning")
    found_roms = headers.scan(roms, rom_paths, scan)
    scan.done(f"scanned   {len(rom_paths)} files, {found_roms} are N64 ROMs")

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
        if not args.no_checksums:
            report_checksums(roms, rom_paths, coverdb.load(database_path),
                             fix=args.fix_checksums and not args.dry_run)
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
