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

import hashlib

from tools import (build_catalog, build_metadata, card_catalog, cover_pack, coverdb, custom_art,
                   headers, library, make_sprite, pack_covers)
from tools.metadata_repo import MetadataRepo, RepoError
from tools.progress import Progress
from tools.card_layout import (  # noqa: F401  (re-exported for callers)
    CARD_FOLDER, COVERS_FOLDER, COVERS_LARGE_FOLDER, COVER_PACK_NAME, COVER_PACK_LARGE_NAME,
    CATALOG_NAME, CATALOG_JSON_NAME)


class PrepareError(ValueError):
    pass


def _check_directory(path: Path, what: str) -> Path:
    if not path.is_dir():
        raise PrepareError(f"{what} is not a directory: {path}")
    return path


def previous_catalog(card: Path) -> dict | None:
    """What the last run wrote, for what it already did: the headers it
    read and the sprites it made. None for a first run or a broken file --
    a run never depends on it."""
    try:
        return card_catalog.load(card)
    except card_catalog.CatalogJsonError:
        return None


def remember_headers(card: Path, previous: dict | None) -> int:
    """Seed the header cache from the last catalog: every game and every
    set-aside it carries `file` and `header` for. Returns how many."""
    if previous is None:
        return 0
    records = {}
    for entry in list(previous.get("games", [])) + list(previous.get("set_aside", [])):
        path, file = entry.get("path"), entry.get("file")
        if isinstance(path, str) and isinstance(file, dict) and "header" in file:
            records[path] = file
    return headers.remember(card, records)


def reusable_sprites(card: Path, previous: dict | None, planned, repo,
                     large_covers: bool) -> dict[str, tuple[bytes, bytes | None]]:
    """The sprites the last run made from pictures that have not changed,
    read out of the packs on the card: a picture with the same identity
    as before gives the same sprite, so the bytes are kept rather than
    made again. Empty when the card has no packs, or the identities are
    not recorded, or the packs will not read."""
    if previous is None:
        return {}
    known = previous.get("sprites")
    if not isinstance(known, dict):
        return {}
    folder = card / CARD_FOLDER
    try:
        small = (folder / COVER_PACK_NAME).read_bytes()
        large = (folder / COVER_PACK_LARGE_NAME).read_bytes() if large_covers else None
    except OSError:
        return {}
    try:
        small_index = {entry.hash: entry for entry in cover_pack.read_index(small)}
        large_index = ({entry.hash: entry for entry in cover_pack.read_index(large)}
                       if large is not None else {})
    except cover_pack.CoverPackError:
        return {}
    out: dict[str, tuple[bytes, bytes | None]] = {}
    for name, source in planned.sources.items():
        identity = pack_covers.source_identity(source, repo)
        if not identity or known.get(name) != identity:
            continue
        if cover_pack.cover_hash(name) not in small_index:
            continue
        if large is not None and cover_pack.cover_hash(name) not in large_index:
            continue
        entry = small_index[cover_pack.cover_hash(name)]
        bytes_small = small[entry.offset:entry.offset + entry.length]
        bytes_large = None
        if large is not None:
            entry = large_index[cover_pack.cover_hash(name)]
            bytes_large = large[entry.offset:entry.offset + entry.length]
        out[name] = (bytes_small, bytes_large)
    return out


def _pack_unchanged(previous: dict | None, name: str, data: bytes, on_card: Path) -> bool:
    """Whether the pack on the card is byte for byte what was just built,
    by the digest the last run recorded and the file's size: then the
    write -- 80 MB over USB for the large pack -- is skipped."""
    if previous is None:
        return False
    packs = previous.get("packs")
    if not isinstance(packs, dict) or not isinstance(packs.get(name), dict):
        return False
    recorded = packs[name]
    try:
        size = on_card.stat().st_size
    except OSError:
        return False
    return (size == len(data) and recorded.get("size") == len(data)
            and recorded.get("sha256") == hashlib.sha256(data).hexdigest())


def prepare(roms: Path, card: Path, database_path: Path, repo: MetadataRepo | None = None,
            rom_image: Path | None = None, overrides: Path | None = None,
            work: Path | None = None, dry_run: bool = False,
            loose_covers: bool = False, genres: Path | None = None,
            log=print, progress_stream=None, rom_paths: list[str] | None = None,
            progress_factory=None, roms_folder: str = "", large_covers: bool = True,
            rebuild: bool = False, checksums: dict[str, dict] | None = None) -> dict:
    """`rebuild` makes the run start from nothing: every header read, every
    picture converted, every pack written, as if the card had no catalog.
    `checksums` is the checksum pass's verdict per ROM path, kept in the
    catalog so the next run need not read those files again."""
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
    covers_large_out = work / CARD_FOLDER / COVERS_LARGE_FOLDER if large_covers else None
    if rom_paths is None:
        rom_paths = library.walk(roms)
    summary: dict[str, object] = {"database_entries": len(coverdb.load(database_path))
                                  if database_path.is_file() else 0}

    # The last run's catalog is what makes this one short: headers it read
    # are not read again for files that have not changed, sprites it made
    # from pictures that have not changed are kept, and a pack that comes
    # out the same is not written again.
    previous = None if rebuild else previous_catalog(card)
    summary["remembered_headers"] = remember_headers(card, previous)

    covers: dict[str, str] = {}
    # The card owner's own art is looked up whether or not there is a
    # collection: a card of homebrew with a picture beside each game is a
    # card with covers.
    art_folder = custom_art.art_dir(card)
    planned = pack_covers.plan(roms, rom_paths, repo, art_folder)
    identities = {name: pack_covers.source_identity(source, repo)
                  for name, source in planned.sources.items()}
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
        reuse = reusable_sprites(card, previous, planned, repo, covers_large_out is not None)
        converted = pack_covers.pack(planned, repo, covers_out, dry_run=dry_run,
                                     progress=progress, large_destination=covers_large_out,
                                     reuse=reuse)
        summary["sprites"] = len(planned.sources)
        summary["sprites_converted"] = converted
        kept = len(planned.sources) - converted
        line = (f"sprites:  {len(planned.sources)}"
                + (" at both sizes" if covers_large_out is not None else "")
                + f", {converted} converted"
                + (f", {kept} kept from the last run" if kept else ""))
        if progress is not None:
            progress.done(line)
        else:
            log(line)
        if summary["sprites"] and not loose_covers and not dry_run:
            # One file instead of hundreds. FatFs has no directory index, so
            # every cover opened by name walks the directory from the start --
            # over 100 KB of it, with names this long -- which is the pause
            # between moving the cursor and the picture appearing.
            count, size = cover_pack.pack_directory(covers_out, work / COVER_PACK_NAME)
            summary["pack_bytes"] = size
            log(f"pack:     {count} covers in one {size // 1024} KB file")
            if covers_large_out is not None:
                # The box view's pack: the same names at 256x180, opened by
                # the browser beside the first and read one sprite at a time.
                count, size = cover_pack.pack_directory(covers_large_out, work / COVER_PACK_LARGE_NAME)
                summary["large_pack_bytes"] = size
                log(f"large:    {count} covers for the box view in one "
                    + (f"{size // 1048576} MB" if size >= 1048576 else f"{size // 1024} KB") + " file")

    metadata_path = work / "metadata.json"
    document, how = build_metadata.build(roms, card, database_path, genres, overrides,
                                         covers, repo, rom_paths, cover_origins=planned.origins)
    summary["games"] = len(document["games"])
    with_meta = sum(1 for game in document["games"]
                    if game["genre"] or game["publisher"] or game["year"] or game["players"])
    with_text = sum(1 for game in document["games"] if game["description"])
    summary["with_metadata"] = with_meta
    summary["with_description"] = with_text
    log(f"metadata: {len(document['games'])} games, {with_meta} with genre/publisher/year/players, "
        f"{with_text} with a description")
    aside = document.get("set_aside", [])
    summary["set_aside"] = len(aside)
    if aside:
        # Named, because a file that looks like a game and is not one is
        # exactly what a person would otherwise go looking for in the list.
        log(f"set aside: {len(aside)} ROM-shaped file{'s' if len(aside) != 1 else ''} with no N64 "
            "header, left out of the list (the browser never shows them):")
        for entry in aside[:20]:
            log(f"          {entry['path']}")
        if len(aside) > 20:
            log(f"          ... and {len(aside) - 20} more")

    # For the next run: which file each header came from, so an unchanged
    # file is not opened again; what each sprite was made from; and what
    # each pack came to, so an unchanged one is not written again.
    prefix = roms_folder.strip("/") + "/" if roms_folder.strip("/") else ""
    for entry in list(document["games"]) + list(document.get("set_aside", [])):
        file = headers.record(card / str(entry["path"]))
        if file is not None:
            entry["file"] = file
        relative = str(entry["path"])[len(prefix):] if str(entry["path"]).startswith(prefix) else None
        if checksums and relative in checksums:
            entry["checksum"] = checksums[relative]
    document["sprites"] = {name: identity for name, identity in identities.items() if identity}
    document["packs"] = {}
    for name in (COVER_PACK_NAME, COVER_PACK_LARGE_NAME):
        built = work / name
        if built.is_file():
            data = built.read_bytes()
            document["packs"][name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    metadata_path.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    catalog = work / CATALOG_NAME
    build_catalog.build(metadata_path, catalog, work / "catalog.manifest.json")
    summary["catalog_bytes"] = catalog.stat().st_size

    destination = card / CARD_FOLDER
    written: list[str] = []
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(catalog, destination / CATALOG_NAME)
        written.append(f"{CARD_FOLDER}/{CATALOG_NAME}")
        card_catalog.write(card, document, roms_folder)
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
                for name in (COVER_PACK_NAME,) + ((COVER_PACK_LARGE_NAME,) if covers_large_out is not None else ()):
                    built = work / name
                    if _pack_unchanged(previous, name, built.read_bytes(), destination / name):
                        log(f"pack:     {name} is what the card has; not written again")
                        summary.setdefault("packs_kept", []).append(name)
                        continue
                    shutil.copy2(built, destination / name)
                    written.append(f"{CARD_FOLDER}/{name} ({summary['sprites']} covers)")
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
    parser.add_argument("--no-large-covers", action="store_true",
                        help="skip covers-large.pak, the box view's 256x180 covers")
    parser.add_argument("--genres", type=Path, default=build_metadata.DEFAULT_GENRES,
                        help="genre consolidation map; pass a missing path to keep libretro's")
    args = parser.parse_args(argv)

    repo = None
    try:
        if args.metadata is not None:
            repo = MetadataRepo.open(args.metadata)
        summary = prepare(args.roms, args.card, args.coverdb, repo, args.rom, args.overrides,
                          args.work, args.dry_run, args.loose_covers, args.genres,
                          large_covers=not args.no_large_covers)
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
