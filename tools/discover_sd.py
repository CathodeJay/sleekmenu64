#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Scan a mounted SD card and build an SleekMenu catalog (stdlib only)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath
# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import card_layout

from tools import build_catalog

EXCLUDED_DIRECTORIES = card_layout.EXCLUDED_DIRECTORIES
MAX_GAMES = 8192


def normalize_rom_path(path: str) -> str:
    normalized = str(PurePosixPath(path.replace("\\", "/")))
    if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
        raise build_catalog.CatalogError(f"unsafe ROM path: {path}")
    return normalized


def infer_title(path: str) -> str:
    stem = PurePosixPath(path).stem
    title = re.sub(r"[_-]+", " ", stem)
    title = re.sub(r"\s+", " ", title).strip()
    return title or stem


def _metadata_by_path(metadata_path: Path | None) -> dict[str, dict[str, object]]:
    if metadata_path is None:
        return {}
    try:
        document = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise build_catalog.CatalogError(f"cannot read optional metadata: {exc}") from exc
    games = document.get("games") if isinstance(document, dict) else None
    if not isinstance(games, list):
        raise build_catalog.CatalogError("optional metadata must contain a games array")
    result: dict[str, dict[str, object]] = {}
    for index, game in enumerate(games):
        if not isinstance(game, dict) or not isinstance(game.get("path"), str):
            raise build_catalog.CatalogError(f"metadata games[{index}] must contain a string path")
        path = normalize_rom_path(game["path"])
        key = path.casefold()
        if key in result:
            raise build_catalog.CatalogError(f"duplicate metadata ROM path: {path}")
        result[key] = game
    return result


def _covers_by_path(cover_map_path: Path | None) -> dict[str, str]:
    if cover_map_path is None:
        return {}
    try:
        document = json.loads(cover_map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise build_catalog.CatalogError(f"cannot read optional cover map: {exc}") from exc
    covers = document.get("covers") if isinstance(document, dict) else None
    if not isinstance(document, dict) or document.get("schema_version") != 1 or not isinstance(covers, dict):
        raise build_catalog.CatalogError("optional cover map must contain schema_version: 1 and a covers object")
    result: dict[str, str] = {}
    for raw_rom, raw_cover in covers.items():
        rom = normalize_rom_path(raw_rom) if isinstance(raw_rom, str) else ""
        cover = normalize_rom_path(raw_cover) if isinstance(raw_cover, str) else ""
        if not rom or PurePosixPath(rom).suffix.casefold() not in build_catalog.ROM_SUFFIXES:
            raise build_catalog.CatalogError(f"invalid cover-map ROM path: {raw_rom!r}")
        if not cover or PurePosixPath(cover).suffix.casefold() != ".sprite":
            raise build_catalog.CatalogError(f"invalid cover-map sprite path for {rom}")
        key = rom.casefold()
        if key in result:
            raise build_catalog.CatalogError(f"duplicate cover-map ROM path: {rom}")
        result[key] = cover
    return result


def scan(sd_root: Path, metadata_path: Path | None = None,
         cover_map_path: Path | None = None) -> dict[str, object]:
    if not sd_root.is_dir():
        raise build_catalog.CatalogError(f"SD root is not a directory: {sd_root}")
    metadata = _metadata_by_path(metadata_path)
    covers = _covers_by_path(cover_map_path)
    games: list[dict[str, object]] = []
    for directory, names, files in os.walk(sd_root):
        names[:] = sorted(name for name in names if not card_layout.excluded_directory(name))
        base = Path(directory)
        for filename in sorted(files):
            if Path(filename).suffix.casefold() not in build_catalog.ROM_SUFFIXES:
                continue
            path = normalize_rom_path(card_layout.card_name((base / filename).relative_to(sd_root).as_posix()))
            game: dict[str, object] = {
                "title": infer_title(path),
                "path": path,
                "genre": "Unknown",
                "regions": ["USA", "JAPAN", "EUROPE"],
                "players": 1,
                "publisher": "Unknown",
                "year": 1970,
            }
            cover = covers.get(path.casefold())
            if cover is not None:
                game["cover"] = cover
            override = metadata.get(path.casefold())
            if override is not None:
                game.update({key: value for key, value in override.items() if key != "path"})
            games.append(game)
            if len(games) > MAX_GAMES:
                raise build_catalog.CatalogError(
                    f"ROM scan exceeds the tested {MAX_GAMES}-game catalog cap")
    return {"schema_version": 1, "games": games}


def discover_and_build(sd_root: Path, metadata_path: Path | None, input_path: Path,
                       output_path: Path, manifest_path: Path,
                       cover_map_path: Path | None = None) -> None:
    document = scan(sd_root, metadata_path, cover_map_path)
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    build_catalog.build(input_path, output_path, manifest_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sd_root", type=Path, help="mounted SD card root")
    parser.add_argument("--metadata", type=Path, help="optional JSON metadata merged by normalized ROM path")
    parser.add_argument("--cover-map", type=Path, help="optional post-conversion ROM-to-sprite JSON map")
    parser.add_argument("--input", type=Path, help="generated builder input JSON")
    parser.add_argument("--output", type=Path, help="catalog output")
    parser.add_argument("--manifest", type=Path, help="manifest output")
    args = parser.parse_args(argv)
    destination = args.sd_root / card_layout.CARD_FOLDER
    try:
        discover_and_build(
            args.sd_root, args.metadata,
            args.input or destination / "catalog.input.json",
            args.output or destination / "catalog.ebc",
            args.manifest or destination / "catalog.manifest.json",
            args.cover_map,
        )
    except build_catalog.CatalogError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
