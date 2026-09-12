#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build the catalog's metadata JSON from a real ROM library.

Three sources, in order of how much they can be trusted:

  The ROM's own 64-byte header -- byte order, country, game code, CRC pair.
  These need no database and cannot be wrong about the file in front of them.

  data/coverdb.csv -- genre, publisher, year, players and the canonical name,
  keyed on that same header CRC pair, with the product code as the fallback
  for a dump it has never seen (tools/identify.py). Reviewed once and
  committed, so every card gets the same answer and a wrong one can be fixed
  for everybody.

  The metadata collection, when one is on the card: publisher, year and
  player count for games the database has never catalogued, and the
  description the browser shows on the details screen, all looked up by the
  game code the header carries (tools/metadata_repo.py).

Anything none of the three knows is left unset rather than guessed. A catalog
entry with year 0 or no genre is a game the browser simply cannot filter on --
the honest outcome for a hack, a homebrew build, or a translation that no
database has ever catalogued.

Output feeds tools/build_catalog.py unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import coverdb, genre_map, headers, identify, library, rom_header
from tools.metadata_repo import MetadataRepo, RepoError

DEFAULT_COVERDB = Path(__file__).resolve().parent.parent / "data" / "coverdb.csv"
DEFAULT_GENRES = genre_map.DEFAULT_PATH
OVERRIDABLE = ("title", "genre", "publisher", "year", "players", "regions", "cover",
               "favorite", "description")


def read_header(path: Path):
    """Through the run-wide cache: see tools/headers.py."""
    return headers.read(path)


def load_overrides(path: Path | None) -> dict[str, dict]:
    """Per-game corrections, keyed by ROM path relative to the scan root.

    Genre labels are real data but not always right -- libretro files Mario
    Kart 64 under Sports -- and this is where a card owner disagrees without
    editing a database."""
    if path is None:
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise SystemExit("overrides file needs schema_version: 1")
    games = document.get("games")
    if not isinstance(games, dict):
        raise SystemExit("overrides file needs a games object")
    return {str(k).replace("\\", "/").casefold(): v for k, v in games.items()}


def load_cover_map(path: Path | None) -> dict[str, str]:
    """ROM path -> sprite name, as tools/pack_covers.py planned it."""
    if path is None:
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    covers = document.get("covers") if isinstance(document, dict) else None
    if document.get("schema_version") != 1 or not isinstance(covers, dict):
        raise SystemExit("cover map needs schema_version: 1 and a covers object")
    return {str(k).replace("\\", "/").casefold(): v for k, v in covers.items()}


def relative_root(roms: Path, sd_root: Path | None) -> Path:
    """Which directory catalog paths are recorded against.

    This is not cosmetic. The browser resolves a catalog path as sd:/ROMS/<p>
    and then as sd:/<p>; a path recorded against a ROM folder that is neither
    the card root nor ROMS/ matches neither, and every launch fails with
    nothing on screen to explain it. Passing --sd-root records paths against
    the card, which always resolves."""
    if sd_root is None:
        return roms
    roms_resolved, sd_resolved = roms.resolve(), sd_root.resolve()
    try:
        roms_resolved.relative_to(sd_resolved)
    except ValueError as exc:
        raise SystemExit(f"--sd-root {sd_root} does not contain {roms}") from exc
    return sd_resolved


def publisher_of(author: str) -> str:
    """The collection writes "Developer | Publisher"; the catalog wants the
    publisher, which is what the box says and what the filter offers."""
    return author.rsplit("|", 1)[-1].strip()


def build(roms: Path, sd_root: Path | None = None, coverdb_path: Path | None = DEFAULT_COVERDB,
          genres: Path | None = DEFAULT_GENRES, overrides: Path | None = None,
          covers: dict[str, str] | None = None, repo: MetadataRepo | None = None,
          rom_paths: list[str] | None = None) -> tuple[dict, Counter]:
    database = coverdb.load(coverdb_path) if coverdb_path and coverdb_path.is_file() else {}
    index = identify.Index(database)
    mapping = genre_map.load(genres)
    patches = load_overrides(overrides)
    covers = {key.casefold(): value for key, value in (covers or {}).items()}
    root = relative_root(roms, sd_root)

    if rom_paths is None:
        rom_paths = library.walk(roms)
    if not rom_paths:
        raise SystemExit(f"no ROMs under {roms}")

    records, how = [], Counter()
    for rom_path in rom_paths:
        path = roms / rom_path
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if library.is_disk(rom_path):
            # A 64DD image has no cartridge header and no game code, so no
            # database and no collection know it: the name is the record.
            how["64dd disk"] += 1
            region = library.disk_region(path)
            record = {
                "title": relative.stem,
                "path": str(relative),
                "regions": [region] if region else rom_header.regions_for(None, relative.name),
                "genre": "",
                "publisher": "",
                "year": 0,
                "players": 0,
                "description": "",
            }
            cover = covers.get(rom_path.casefold()) or covers.get(str(relative).casefold())
            if cover:
                record["cover"] = cover
            records.append(record)
            continue
        header = read_header(path)
        if header is None:
            how["not a rom"] += 1
            continue
        how[f"format {header.form}"] += 1

        entry, matched = index.identify(header)
        if entry is not None:
            how[f"database by {matched}"] += 1
            genre, publisher = entry.genre, entry.publisher
            year, players = entry.year, entry.players
            regions = list(entry.regions) or rom_header.regions_for(header, relative.name)
        else:
            how["database knows nothing"] += 1
            genre = publisher = ""
            year = players = 0
            regions = rom_header.regions_for(header, relative.name)

        description = ""
        if repo is not None:
            info = repo.info(header.product_code)
            if info is not None:
                how["collection has metadata"] += 1
                publisher = publisher or publisher_of(info.author)
                year = year or info.year
                players = players or info.players
            description = repo.description(header.product_code)
            if description:
                how["collection has a description"] += 1

        record = {
            # The header CRC pair and game code, so a correction to
            # data/coverdb.csv or a newer collection can be applied to an
            # existing metadata file without reading the library again. On a
            # card of 3371 ROMs that is the difference between a second and
            # most of an hour. Both are dropped when the catalog is encoded.
            "crc": header.crc_pair,
            "code": header.product_code,
            "title": relative.stem,
            "path": str(relative),
            "regions": regions,
            "genre": genre,
            "publisher": publisher,
            "year": year,
            "players": players,
            "description": description,
        }
        cover = covers.get(rom_path.casefold()) or covers.get(str(relative).casefold())
        if cover:
            record["cover"] = cover
        records.append(record)

    # Consolidation happens last, so overrides are written in whichever
    # vocabulary the person editing them prefers and still land in the right
    # bucket. Twenty-four genres is more than a 168-pixel tab strip can show
    # and more than anyone wants to cycle through.
    if mapping:
        seen_raw = {record["genre"] for record in records if record["genre"]}
        for record in records:
            consolidated = genre_map.apply(mapping, record["genre"])
            if consolidated != record["genre"]:
                how["genre consolidated"] += 1
            record["genre"] = consolidated
        for name in genre_map.unmapped(mapping, seen_raw):
            how[f"genre not in map: {name}"] += 1

    for record in records:
        patch = patches.get(record["path"].casefold())
        if patch:
            record.update({k: v for k, v in patch.items() if k in OVERRIDABLE})
            how["override"] += 1

    attribution = ("read from the ROM headers and data/coverdb.csv"
                   + ("; descriptions and gaps from the n64-flashcart-menu-metadata "
                      "collection (public domain)" if repo is not None else ""))
    return {"schema_version": 1, "attribution": attribution, "games": records}, how


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roms", type=Path, help="the ROM directory to walk")
    parser.add_argument("--sd-root", type=Path,
                        help="record catalog paths against this directory (the card root)")
    parser.add_argument("--coverdb", type=Path, default=DEFAULT_COVERDB,
                        help="the CRC-keyed database (default: the one in this repo)")
    parser.add_argument("--genres", type=Path, default=DEFAULT_GENRES,
                        help="genre consolidation map; pass a missing path to keep libretro's")
    parser.add_argument("--metadata", type=Path,
                        help="the metadata collection (zip or folder), for descriptions")
    parser.add_argument("--overrides", type=Path, help="per-game corrections")
    parser.add_argument("--cover-map", type=Path, help="output of tools/pack_covers.py")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    repo = None
    try:
        if args.metadata is not None:
            repo = MetadataRepo.open(args.metadata)
        document, how = build(args.roms, args.sd_root, args.coverdb, args.genres,
                              args.overrides, load_cover_map(args.cover_map), repo)
    except (RepoError, library.LibraryError, coverdb.CoverDBError) as exc:
        parser.error(str(exc))
    finally:
        if repo is not None:
            repo.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    total = len(document["games"])
    named = sum(1 for game in document["games"]
                if game["genre"] or game["publisher"] or game["year"] or game["players"])
    print(f"{total} ROMs -> {args.output}")
    for key in sorted(how):
        print(f"  {how[key]:5}  {key}")
    print(f"  {named:5}  with metadata ({100 * named // max(total, 1)}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
