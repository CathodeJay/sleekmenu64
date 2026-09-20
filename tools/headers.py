# SPDX-License-Identifier: AGPL-3.0-only
"""Read ROM headers off the card once, however many passes ask for them --
and once across runs, not once per run.

A card build asks three times which cartridge each file is: to know what art
to fetch, to match covers, and to build the metadata. Each of those used to
open every ROM and read its first 64 bytes -- on a 3,371-game card over USB,
about a minute a pass, in silence, three times. The answer does not change
between passes, so it is kept.

Nor does it change between runs, for a file that has not: the catalog the
last run wrote on the card carries every header it read, with the file's
size and modification time beside it, and the next run seeds the cache from
that (remember()). A ROM whose size and time still match costs a stat; only
a new or changed file is opened. That is what makes a second Prepare of a
card of thousands a matter of seconds.

The cache is keyed on the file's size and modification time as well as its
path, so a ROM replaced during a run is re-read rather than remembered wrong,
and it is cleared between test cases by the fixtures that write ROMs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from tools import rom_header

_cache: dict[tuple[str, int, int], Optional[object]] = {}
_raw: dict[tuple[str, int, int], bytes] = {}
# How many of the reads since the last clear() were answered from what a
# previous run remembered, and how many opened the file.
remembered_hits = 0
opened = 0


def clear() -> None:
    global remembered_hits, opened
    _cache.clear()
    _raw.clear()
    remembered_hits = opened = 0


def _key(path: Path):
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_size, stat.st_mtime_ns)


def read(path: Path):
    """The parsed header, or None for anything that cannot be read or is not
    a ROM. Never raises: a file that vanished mid-run is a None, not a crash."""
    global remembered_hits, opened
    key = _key(path)
    if key is None:
        return None
    if key in _cache:
        return _cache[key]
    try:
        with path.open("rb") as handle:
            data = handle.read(rom_header.HEADER_SIZE)
    except OSError:
        data = b""
    opened += 1
    header = rom_header.parse(data)
    _cache[key] = header
    _raw[key] = data if header is not None else b""
    return header


def raw(path: Path) -> bytes | None:
    """The header's bytes as read, "" for a file that is not a ROM, None for
    a file never read."""
    key = _key(path)
    if key is None or key not in _cache:
        return None
    return _raw.get(key, b"")


def _spellings(path: Path) -> list[Path]:
    """The path as given and as the filesystem resolves it: the passes read
    through whichever spelling their root came with, and a cache that
    missed on a symlink would be a cache that never hit."""
    try:
        resolved = path.resolve()
    except OSError:
        return [path]
    return [path] if resolved == path else [path, resolved]


def record(path: Path) -> dict | None:
    """What a catalog carries so the next run need not open this file: its
    size and time, and the header bytes (empty for a file set aside)."""
    for spelling in _spellings(path):
        key = _key(spelling)
        if key is not None and key in _cache:
            return {"size": key[1], "mtime": key[2], "header": _raw.get(key, b"").hex()}
    return None


def remember(root: Path, records: dict[str, dict]) -> int:
    """Seed the cache from what a previous run wrote: `records` maps a path
    relative to `root` to record()'s dict. A file whose size and time still
    match is answered without being opened. Returns how many were taken."""
    taken = 0
    roots = _spellings(root)
    for relative, entry in records.items():
        try:
            size, mtime = int(entry["size"]), int(entry["mtime"])
            blob = bytes.fromhex(str(entry.get("header", "")))
        except (KeyError, TypeError, ValueError):
            continue
        header = rom_header.parse(blob) if blob else None
        for spelling in roots:
            key = (str(spelling / relative), size, mtime)
            _cache[key] = header
            _raw[key] = blob
        taken += 1
    return taken


def scan(root: Path, rom_paths: list[str], progress=None) -> int:
    """Warm the cache for a whole library, reporting as it goes. Returns how
    many parsed as ROMs. This is the one pass that touches the card; the
    later ones are lookups -- and with remember() before it, most of this
    pass is lookups too."""
    global remembered_hits
    found = 0
    for rom_path in rom_paths:
        key = _key(root / rom_path)
        if key is not None and key in _cache:
            remembered_hits += 1
        if read(root / rom_path) is not None:
            found += 1
        if progress is not None:
            progress.step(Path(rom_path).name)
    return found
