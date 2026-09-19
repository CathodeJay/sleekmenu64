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
in `sleekmenu/art/`, or `<game code>.txt` there, is the description on the
launch card, and a first line of `Title: ...` renames the game. Names match
whatever the case, since a card is not a case-sensitive place.

Read when the tool runs, never by the browser: a new picture needs a re-run
of the tool, like a new game does. The window writes these same files from
its catalog tab (save() and remove() below) and nothing else: the picture
is copied as it is, the sizes are derived at build time, and reverting an
edit is deleting the file, since the original was never touched.
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


def find_text(index: Index, roms_root: Path, rom_path: str, art_folder: Path | None,
              code: str = "") -> Text | None:
    """The `.txt` for this ROM: beside it, in the art folder by its name,
    or in the art folder by its game code."""
    stem = PurePosixPath(rom_path).stem
    found = index.lookup((roms_root / rom_path).parent, stem + TEXT_SUFFIX) \
        or index.lookup(art_folder, stem + TEXT_SUFFIX) \
        or (index.lookup(art_folder, code + TEXT_SUFFIX) if code else None)
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


# -- the window's edits --------------------------------------------------------

SCOPE_ROM = "rom"      # this ROM only: files named after it
SCOPE_CODE = "code"    # every ROM with this game code: files named after the code


class EditError(ValueError):
    pass


def key_for(game: dict, scope: str) -> str:
    """The file stem an edit is saved under."""
    if scope == SCOPE_CODE:
        code = str(game.get("code") or "")
        if not code.strip("\0 "):
            raise EditError("this ROM carries no game code; save for this ROM only")
        return code
    return PurePosixPath(str(game["path"])).stem


def save(card: Path, game: dict, picture: Path | None, title: str, description: str,
         scope: str = SCOPE_ROM) -> list[Path]:
    """Write the owner's picture and text for a game into sleekmenu/art/,
    under the ROM's name or its game code. The picture is copied as it is
    (PNG or JPEG; anything else is refused), replacing one of the other
    suffix so the lookup cannot find a stale file first. The text file is
    written when there is a title or a description, and removed when both
    are empty. Returns the files written or removed."""
    folder = art_dir(card)
    key = key_for(game, scope)
    touched: list[Path] = []
    if picture is not None:
        suffix = picture.suffix.casefold()
        if suffix == ".jpeg":
            suffix = ".jpg"
        if suffix not in (".png", ".jpg"):
            raise EditError(f"not a PNG or JPEG: {picture.name}")
        try:
            from PIL import Image
            with Image.open(picture) as image:
                image.verify()
        except ImportError:
            pass
        except (OSError, ValueError) as error:
            raise EditError(f"cannot read {picture.name}: {error}") from error
        folder.mkdir(parents=True, exist_ok=True)
        index = Index()
        for other in ART_SUFFIXES:
            stale = index.lookup(folder, key + other)
            if stale is not None and stale.suffix.casefold() != suffix:
                stale.unlink()
                touched.append(stale)
        target = folder / (key + suffix)
        target.write_bytes(picture.read_bytes())
        touched.append(target)
    title, description = title.strip(), " ".join(description.split())
    text_file = Index().lookup(folder, key + TEXT_SUFFIX) or folder / (key + TEXT_SUFFIX)
    if title or description:
        folder.mkdir(parents=True, exist_ok=True)
        lines = [f"Title: {title}", ""] if title else []
        lines.append(description)
        text_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        touched.append(text_file)
    elif text_file.exists() and picture is None:
        text_file.unlink()
        touched.append(text_file)
    return touched


def edits_of(card: Path, roms_root: Path, game: dict) -> tuple[list[Path], list[Path]]:
    """The owner's files this game currently uses: those in sleekmenu/art/,
    which the window may remove, and those beside the ROM, which it only
    names."""
    folder = art_dir(card)
    index = Index()
    rom_path = str(game["path"])
    code = str(game.get("code") or "")
    removable: list[Path] = []
    beside: list[Path] = []
    art = find_art(index, roms_root, rom_path, folder, code)
    if art is not None:
        (removable if art.path.parent == folder else beside).append(art.path)
    stem = PurePosixPath(rom_path).stem
    text = (index.lookup((roms_root / rom_path).parent, stem + TEXT_SUFFIX)
            or index.lookup(folder, stem + TEXT_SUFFIX)
            or (index.lookup(folder, code + TEXT_SUFFIX) if code else None))
    if text is not None:
        (removable if text.parent == folder else beside).append(text)
    return removable, beside


def remove(card: Path, roms_root: Path, game: dict) -> list[Path]:
    """Delete the owner's files in sleekmenu/art/ that this game uses, so
    the original comes back at the next Prepare. Files beside the ROM are
    left alone. Returns what was deleted."""
    removable, _beside = edits_of(card, roms_root, game)
    for path in removable:
        path.unlink()
    return removable


def sharing_code(games: list[dict], game: dict) -> int:
    """How many games on the card carry this game's code, itself included:
    what an edit saved by code reaches."""
    code = str(game.get("code") or "")
    if not code.strip("\0 "):
        return 1
    return sum(1 for other in games if str(other.get("code") or "") == code)
