# SPDX-License-Identifier: AGPL-3.0-only
"""Your own pictures and text for the games the collection cannot know.

The collection is keyed by the game code in the header, which a hack
shares with the game it was built on and which homebrew leaves blank: a
hack gets its parent's box and homebrew gets none, and nothing but the
file tells two hacks of one game apart. So a picture is looked up by the
file's name, in three places, first match wins:

    <folder of the ROM>/<ROM name>.png      beside the game
    sleekmenu/art/<ROM name>.png            for a clean ROM folder
    sleekmenu/art/<game code>.png           NSME.png: every ROM with that code

and only then the collection. PNG or JPEG, any size; the picture is fitted
the way the scans are. Text the same way: `<ROM name>.txt` beside the ROM or
in `sleekmenu/art/` is the description on the launch card, and a first line
of `Title: ...` renames the game. Names match whatever the case, since a
card is not a case-sensitive place.

Read when the tool runs, never by the browser: a new picture needs a re-run
of the tool, like a new game does.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tools import card_layout

ART_SUFFIXES = (".png", ".jpg", ".jpeg")
TEXT_SUFFIX = ".txt"
TITLE_LINE = re.compile(r"^\s*title\s*:\s*(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Custom:
    """A picture on disk, and the sprite it becomes. Per-ROM art is named by
    a hash of the ROM's path so two files of the same name in different
    folders never share a sprite; a code override takes the collection's
    own name for that code, so it replaces the collection's box wherever
    that box would have been used."""
    path: Path
    sprite: str


def art_dir(card: Path | None) -> Path | None:
    """`sleekmenu/art/` on the card, whether or not it exists."""
    return None if card is None else card / card_layout.CARD_FOLDER / card_layout.ART_FOLDER


class Index:
    """Directory listings, case-folded, read once per folder."""

    def __init__(self) -> None:
        self._listings: dict[Path, dict[str, str]] = {}

    def lookup(self, folder: Path | None, name: str) -> Path | None:
        if folder is None:
            return None
        listing = self._listings.get(folder)
        if listing is None:
            try:
                listing = {entry.casefold(): entry for entry in os.listdir(folder)}
            except OSError:
                listing = {}
            self._listings[folder] = listing
        actual = listing.get(name.casefold())
        return folder / actual if actual is not None else None


def per_rom_sprite(rom_path: str) -> str:
    digest = hashlib.sha1(PurePosixPath(rom_path).as_posix().casefold().encode("utf-8")).hexdigest()
    return f"custom-{digest[:8]}.sprite"


def code_sprite(code: str) -> str:
    return code + ".sprite"


def find_art(index: Index, roms_root: Path, rom_path: str, art_folder: Path | None,
             code: str) -> Custom | None:
    """The picture for this ROM, by the rules in the module docstring."""
    stem = PurePosixPath(rom_path).stem
    beside = (roms_root / rom_path).parent
    for suffix in ART_SUFFIXES:
        found = index.lookup(beside, stem + suffix)
        if found is not None:
            return Custom(found, per_rom_sprite(rom_path))
    for suffix in ART_SUFFIXES:
        found = index.lookup(art_folder, stem + suffix)
        if found is not None:
            return Custom(found, per_rom_sprite(rom_path))
    if code:
        for suffix in ART_SUFFIXES:
            found = index.lookup(art_folder, code + suffix)
            if found is not None:
                return Custom(found, code_sprite(code))
    return None


@dataclass(frozen=True)
class Text:
    title: str          # "" when the file sets none
    description: str    # whitespace collapsed, the way the collection's is


def find_text(index: Index, roms_root: Path, rom_path: str, art_folder: Path | None) -> Text | None:
    """The `.txt` for this ROM, beside it or in the art folder."""
    stem = PurePosixPath(rom_path).stem
    found = index.lookup((roms_root / rom_path).parent, stem + TEXT_SUFFIX) \
        or index.lookup(art_folder, stem + TEXT_SUFFIX)
    if found is None:
        return None
    try:
        raw = found.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    lines = raw.splitlines()
    title = ""
    if lines:
        match = TITLE_LINE.match(lines[0])
        if match:
            title = match.group(1)
            lines = lines[1:]
    description = " ".join(" ".join(lines).split())
    return Text(title, description)
