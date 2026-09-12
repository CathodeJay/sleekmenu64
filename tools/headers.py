# SPDX-License-Identifier: AGPL-3.0-only
"""Read ROM headers off the card once, however many passes ask for them.

A card build asks three times which cartridge each file is: to know what art
to fetch, to match covers, and to build the metadata. Each of those used to
open every ROM and read its first 64 bytes -- on a 3,371-game card over USB,
about a minute a pass, in silence, three times. The answer does not change
between passes, so it is kept.

The cache is keyed on the file's size and modification time as well as its
path, so a ROM replaced during a run is re-read rather than remembered wrong,
and it is cleared between test cases by the fixtures that write ROMs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from tools import rom_header

_cache: dict[tuple[str, int, int], Optional[object]] = {}


def clear() -> None:
    _cache.clear()


def read(path: Path):
    """The parsed header, or None for anything that cannot be read or is not
    a ROM. Never raises: a file that vanished mid-run is a None, not a crash."""
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key in _cache:
        return _cache[key]
    try:
        with path.open("rb") as handle:
            header = rom_header.parse(handle.read(rom_header.HEADER_SIZE))
    except OSError:
        header = None
    _cache[key] = header
    return header


def scan(root: Path, rom_paths: list[str], progress=None) -> int:
    """Warm the cache for a whole library, reporting as it goes. Returns how
    many parsed as ROMs. This is the one pass that touches the card; the
    later ones are lookups."""
    found = 0
    for rom_path in rom_paths:
        if read(root / rom_path) is not None:
            found += 1
        if progress is not None:
            progress.step(Path(rom_path).name)
    return found
