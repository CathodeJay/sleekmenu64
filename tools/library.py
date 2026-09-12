# SPDX-License-Identifier: AGPL-3.0-only
"""Walk a ROM library the way every tool must agree to walk it.

Five tools listed the same folder in five slightly different ways -- one
descended into the browser's own folder, one sorted by byte value so upper
case came first on one platform and not another. The catalog is only usable
if the ROM paths in it are exactly the ones the browser resolves, so the walk
lives in one place.
"""

from __future__ import annotations

import os
from pathlib import Path

from tools import card_layout

ROM_SUFFIXES = frozenset({".z64", ".v64", ".n64"})
# 64DD disk images are games in the list too. Whether one can be started is
# the browser's call per cartridge: the EverDrive-64 Pro emulates the drive,
# the X7 does not.
DISK_SUFFIXES = frozenset({".ndd"})
LIBRARY_SUFFIXES = ROM_SUFFIXES | DISK_SUFFIXES


def is_disk(path: str) -> bool:
    return Path(path).suffix.casefold() in DISK_SUFFIXES


# The first word of a retail disk's system area names the drive it was made
# for; the launcher picks the matching IPL by the same word.
DISK_REGIONS = {b"\xe8\x48\xd3\x16": "JAPAN", b"\x22\x63\xee\x56": "USA"}


def disk_region(path: Path) -> str:
    """"JAPAN", "USA", or "" for a development or unreadable image."""
    try:
        with path.open("rb") as handle:
            return DISK_REGIONS.get(handle.read(4), "")
    except OSError:
        return ""


class LibraryError(ValueError):
    pass


def walk(root: Path, suffixes=LIBRARY_SUFFIXES, excluded=card_layout.EXCLUDED_DIRECTORIES) -> list[str]:
    """Every file under `root` with one of the suffixes, as forward-slash
    paths relative to `root`, in a case-folded order that is the same on
    every platform. Folders named in `excluded` are never entered."""
    if not root.is_dir():
        raise LibraryError(f"not a folder: {root}")
    found: list[str] = []
    for directory, names, files in os.walk(root):
        names[:] = sorted(
            (name for name in names if excluded is None or name.casefold() not in excluded),
            key=str.casefold,
        )
        base = Path(directory)
        for filename in sorted(files, key=str.casefold):
            if Path(filename).suffix.casefold() in suffixes:
                found.append((base / filename).relative_to(root).as_posix())
    return sorted(found, key=lambda value: (value.casefold(), value))
