#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Re-apply every database correction to a card, without re-reading the library.

A correction to data/coverdb.csv -- a genre libretro got wrong -- or a newer
metadata collection normally reaches a card by rebuilding everything, which
means reading every ROM header again. On a 3371-game card at SD speeds that
is most of an hour, and it needs the card to hand.

Everything needed is already in the metadata file the last build produced:
every game, where it lives, its header CRC and its game code. This walks that
instead and re-derives, every run, from the files that are the actual sources
of truth:

    data/coverdb.csv   what each game is, and its genre
    data/genres.csv    how genres are consolidated for the tab strip
    the collection     its box, by game code, and its description

Re-deriving rather than patching is the point. A genre fix applied once to a
build artefact is lost the moment anything rebuilds from an older copy of it.
Sources of truth are files in the repository; everything under build/ is
disposable.

Covers are only ever ADDED -- a game that already has one keeps it. Genres
are REPLACED where a database row was found, because correcting a wrong one
is the whole purpose; a game with no row keeps its own genre, consolidated.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import (build_catalog, build_metadata, cover_pack, coverdb, genre_map, identify,
                   make_sprite, pack_covers)
from tools.metadata_repo import MetadataRepo, RepoError


class RefreshError(ValueError):
    pass


def _as_header(game: dict):
    """What identify needs, from what the metadata file kept."""
    crc = str(game.get("crc") or "")
    code = str(game.get("code") or "")
    if len(crc) != 16 or crc == coverdb.ZERO_CRC:
        crc = ""
    return SimpleNamespace(crc_pair=crc, product_code=code if len(code) == 4 else "")


def refresh_genres(games: list[dict], index: identify.Index,
                   mapping: dict[str, str]) -> dict[str, int]:
    """Re-derive every genre -- and publisher, year and player count -- from
    the database, then consolidate the genre.

    Replaced rather than filled in: a curated row saying Ocarina of Time is an
    action-adventure is worth nothing if a metadata file that says role-playing
    wins. A game the database does not know keeps its own values and is
    consolidated like any other."""
    how = {"from the database": 0, "consolidated only": 0, "unchanged": 0}
    for game in games:
        before = game.get("genre", "")
        entry, _ = index.identify(_as_header(game))
        raw = entry.genre if (entry is not None and entry.genre) else before
        game["genre"] = genre_map.apply(mapping, raw)
        if entry is not None:
            for field in ("publisher", "year", "players"):
                value = getattr(entry, field)
                if value:
                    game[field] = value
        if game["genre"] == before:
            how["unchanged"] += 1
        elif entry is not None and entry.genre:
            how["from the database"] += 1
        else:
            how["consolidated only"] += 1
    return how


def refresh_from_collection(games: list[dict], repo: MetadataRepo,
                            covers: Path | None) -> dict[str, int]:
    """Boxes for games without one, descriptions for every game, and the
    publisher, year and player count for games the database left blank."""
    how = {"covers added": 0, "descriptions": 0, "gaps filled": 0, "still no box": 0}
    wanted: dict[str, object] = {}
    for game in games:
        code = str(game.get("code") or "")
        if not repo.valid_code(code):
            continue
        if not game.get("cover"):
            found = repo.art(code)
            if found is None:
                how["still no box"] += 1
            else:
                game["cover"] = pack_covers.sprite_name(found.key)
                wanted.setdefault(game["cover"], found)
                how["covers added"] += 1
        info = repo.info(code)
        if info is not None:
            filled = False
            if not game.get("publisher") and info.author:
                game["publisher"] = build_metadata.publisher_of(info.author)
                filled = True
            if not game.get("year") and info.year:
                game["year"] = info.year
                filled = True
            if not game.get("players") and info.players:
                game["players"] = info.players
                filled = True
            how["gaps filled"] += filled
        description = repo.description(code)
        if description:
            game["description"] = description
            how["descriptions"] += 1
    if covers is not None:
        covers.mkdir(parents=True, exist_ok=True)
        for name, found in wanted.items():
            target = covers / name
            if not target.is_file():
                make_sprite.convert_bytes(repo.read(found), target, found.path,
                                          width_scale=repo.width_scale)
                how["sprites converted"] = how.get("sprites converted", 0) + 1
    return how


def refresh(metadata_path: Path, database_path: Path, output: Path,
            repo: MetadataRepo | None = None, covers: Path | None = None,
            pack: Path | None = None, catalog: Path | None = None,
            genres: Path | None = None, log=print) -> dict:
    document = json.loads(metadata_path.read_text(encoding="utf-8"))
    games = document.get("games")
    if not isinstance(games, list):
        raise RefreshError(f"{metadata_path} has no games array")
    database = coverdb.load(database_path) if database_path.is_file() else {}
    index = identify.Index(database)

    mapping = genre_map.load(genres)
    genre_how = refresh_genres(games, index, mapping)
    log(f"genres: {len(set(g['genre'] for g in games if g['genre']))} distinct after "
        f"consolidation")
    for key, count in genre_how.items():
        if count:
            log(f"    {count:5}  {key}")

    collection_how: dict[str, int] = {}
    if repo is not None:
        collection_how = refresh_from_collection(games, repo, covers)
        for key, count in collection_how.items():
            if count:
                log(f"    {count:5}  {key}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    summary = {"games": len(games), "genres": genre_how, "collection": collection_how,
               "with_cover": sum(1 for game in games if game.get("cover"))}
    if pack:
        if covers is None:
            raise RefreshError("--pack needs --covers, the sprite directory to pack")
        count, size = cover_pack.pack_directory(covers, pack)
        summary.update(pack_covers_count=count, pack_bytes=size)
        log(f"pack:   {count} covers in {size // 1024} KB -> {pack}")
    if catalog:
        build_catalog.build(output, catalog, catalog.with_suffix(".manifest.json"))
        summary["catalog_bytes"] = catalog.stat().st_size
        log(f"catalog: {catalog} ({catalog.stat().st_size} bytes)")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("metadata", type=Path, help="a metadata.json from a previous build")
    parser.add_argument("--coverdb", type=Path,
                        default=Path(__file__).resolve().parent.parent / "data" / "coverdb.csv")
    parser.add_argument("--collection", type=Path,
                        help="the metadata collection (zip or folder); omit to refresh genres only")
    parser.add_argument("--covers", type=Path,
                        help="the sprite directory to add to; omit to leave covers alone")
    parser.add_argument("--genres", type=Path, default=genre_map.DEFAULT_PATH,
                        help="genre consolidation map")
    parser.add_argument("--output", type=Path, help="where to write the updated metadata")
    parser.add_argument("--pack", type=Path, help="rebuild covers.pak here")
    parser.add_argument("--catalog", type=Path, help="rebuild catalog.ebc here")
    args = parser.parse_args(argv)
    repo = None
    try:
        if args.collection is not None:
            repo = MetadataRepo.open(args.collection)
        refresh(args.metadata, args.coverdb, args.output or args.metadata, repo, args.covers,
                args.pack, args.catalog, args.genres)
    except (RefreshError, RepoError, coverdb.CoverDBError, cover_pack.CoverPackError,
            genre_map.GenreMapError, build_catalog.CatalogError, make_sprite.SpriteError,
            OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    finally:
        if repo is not None:
            repo.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
