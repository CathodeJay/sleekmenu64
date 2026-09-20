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
launch card, and header lines at the top of it set the facts:

    Title: Kaizo Race
    Genre: Racing
    Publisher: Nintendo
    Year: 1996
    Players: 4
    Regions: USA, JAPAN

    A hard version of the original, every course reworked.

Any of them, in any order, each winning over the database and the
collection for that field; the first line that is not a header starts the
description. Names match whatever the case, since a card is not a
case-sensitive place.

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
# A header line: one of the facts, a colon, the value.
HEADER_LINE = re.compile(r"^\s*(title|genre|publisher|year|players|regions?)\s*:\s*(.*?)\s*$",
                         re.IGNORECASE)
# The facts a header line can set, in the order the file writes them.
FACTS = ("genre", "publisher", "year", "players", "regions")
REGION_NAMES = {"USA": "USA", "US": "USA", "NTSC-U": "USA",
                "JAPAN": "JAPAN", "JPN": "JAPAN", "JP": "JAPAN", "NTSC-J": "JAPAN",
                "EUROPE": "EUROPE", "EUR": "EUROPE", "EU": "EUROPE", "PAL": "EUROPE"}


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
    """Directory listings, read once per folder, looked up the way the card
    looks names up: ignoring case, and ignoring whether an accent is one
    character or two (card_layout.fold). A ROM path in the catalog is
    composed; macOS lists the picture beside it decomposed."""

    def __init__(self) -> None:
        self._listings: dict[Path, dict[str, str]] = {}

    def lookup(self, folder: Path | None, name: str) -> Path | None:
        if folder is None:
            return None
        listing = self._listings.get(folder)
        if listing is None:
            try:
                listing = {card_layout.fold(entry): entry for entry in os.listdir(folder)}
            except OSError:
                listing = {}
            self._listings[folder] = listing
        actual = listing.get(card_layout.fold(name))
        return folder / actual if actual is not None else None


def per_rom_sprite(rom_path: str) -> str:
    digest = hashlib.sha1(card_layout.fold(PurePosixPath(rom_path).as_posix()).encode("utf-8")).hexdigest()
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
    facts: dict         # genre, publisher (str), year, players (int), regions (list): only those set
    path: Path | None = None


def parse_facts(name: str, value: str) -> tuple[str, object] | None:
    """One header line's worth of fact, checked the way the catalog checks
    it: a year in 1970..2100, players 1..8, regions from the three the
    console knows. Anything else is left unset rather than guessed."""
    name = name.casefold()
    if name in ("genre", "publisher"):
        return (name, " ".join(value.split())) if value.strip() else None
    if name == "year":
        return ("year", int(value)) if value.strip().isdigit() and 1970 <= int(value) <= 2100 else None
    if name == "players":
        return ("players", int(value)) if value.strip().isdigit() and 1 <= int(value) <= 8 else None
    if name in ("region", "regions"):
        names = [REGION_NAMES.get(part.strip().upper()) for part in re.split(r"[,/ ]+", value) if part.strip()]
        found = [region for region in dict.fromkeys(names) if region]
        return ("regions", found) if found else None
    return None


def parse_text(raw: str) -> tuple[str, str, dict]:
    """Title, description and facts out of a sidecar's text."""
    lines = raw.splitlines()
    title, facts = "", {}
    while lines:
        match = HEADER_LINE.match(lines[0])
        if not match:
            break
        name, value = match.group(1).casefold(), match.group(2)
        if name == "title":
            title = value
        else:
            parsed = parse_facts(name, value)
            if parsed is not None:
                facts[parsed[0]] = parsed[1]
        lines = lines[1:]
    description = " ".join(" ".join(lines).split())
    return title, description, facts


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
    title, description, facts = parse_text(raw)
    return Text(title, description, facts, found)


def format_text(title: str, description: str, facts: dict | None) -> str:
    """The sidecar's text for what the window collected: header lines for
    the title and every fact given, a blank line, the description."""
    lines = []
    if title.strip():
        lines.append(f"Title: {title.strip()}")
    for name in FACTS:
        value = (facts or {}).get(name)
        if value in (None, "", 0, []):
            continue
        if name == "regions":
            value = ", ".join(str(region) for region in value)
        lines.append(f"{name.capitalize()}: {value}")
    if lines and description.strip():
        lines.append("")
    if description.strip():
        lines.append(" ".join(description.split()))
    return "\n".join(lines).rstrip() + "\n"


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
         scope: str = SCOPE_ROM, facts: dict | None = None) -> list[Path]:
    """Write the owner's picture and text for a game into sleekmenu/art/,
    under the ROM's name or its game code. The picture is copied as it is
    (PNG or JPEG; anything else is refused), replacing one of the other
    suffix so the lookup cannot find a stale file first. The text file is
    written when there is a title, a fact or a description, and removed
    when there is none of them. Returns the files written or removed."""
    folder = art_dir(card)
    key = key_for(game, scope)
    touched: list[Path] = []
    facts = {name: value for name, value in (facts or {}).items()
             if name in FACTS and value not in (None, "", 0, [])}
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
    if title or description or facts:
        folder.mkdir(parents=True, exist_ok=True)
        text_file.write_text(format_text(title, description, facts), encoding="utf-8")
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


# -- what the next Prepare will change -----------------------------------------

@dataclass(frozen=True)
class Pending:
    """An edit on the card that the catalog does not carry yet: the fields
    the next Prepare will change to what the owner's file says, a picture
    written since the catalog was built, and the fields the catalog has as
    the owner's whose file has since gone."""
    fields: dict
    picture: Path | None
    removed: tuple


def _built_epoch(document: dict) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(document.get("built", ""))).timestamp()
    except (TypeError, ValueError):
        return 0.0


def pending_edits(card: Path, roms_root: Path, document: dict) -> dict[str, Pending]:
    """Every game whose owner's files disagree with the catalog, keyed by
    ROM path. Text is compared field by field, so a file the last Prepare
    already read is not pending; a picture is pending when it is not the
    file the catalog's sprite was made from -- by the size and time the
    catalog recorded, so a picture copied in with an old date still
    counts -- or, for a catalog that recorded nothing, when it is newer
    than the catalog or the catalog's box is not the owner's."""
    from tools import metadata_repo, provenance
    folder = art_dir(card)
    index = Index()
    built = _built_epoch(document)
    sprites = document.get("sprites") if isinstance(document.get("sprites"), dict) else None
    out: dict[str, Pending] = {}
    for game in document.get("games", []):
        rom_path = str(game.get("path", ""))
        code = str(game.get("code") or "")
        sources = game.get("sources") or {}
        text = find_text(index, roms_root, rom_path, folder, code)
        art = find_art(index, roms_root, rom_path, folder, code)
        fields: dict = {}
        removed: list[str] = []
        given = {}
        if text is not None:
            given = dict(text.facts)
            if text.title:
                given["title"] = text.title
            if text.description:
                given["description"] = text.description
        for name, value in given.items():
            blank = [] if name == "regions" else ("" if name in ("genre", "publisher", "title", "description") else 0)
            if value != game.get(name, blank):
                fields[name] = value
        # What the catalog has as the owner's that no file gives any more:
        # the next Prepare takes it back to the collection's or nothing.
        for name in ("title", "description", "genre", "publisher", "year", "players"):
            if sources.get(name) == provenance.YOURS and name not in given:
                removed.append(name)
        picture = None
        if art is not None:
            if sprites is not None:
                recorded = str(sprites.get(art.sprite, ""))
                changed = recorded.split("|", 1)[-1] != metadata_repo.file_identity(art.path)
            else:
                # The catalog's stamp is whole seconds; a picture written the
                # second before a Prepare is not newer than it.
                try:
                    changed = art.path.stat().st_mtime > built + 1.0
                except OSError:
                    changed = False
            if changed or not provenance.is_yours(str(sources.get("cover", ""))):
                picture = art.path
        elif provenance.is_yours(str(sources.get("cover", ""))):
            removed.append("cover")
        if fields or picture is not None or removed:
            out[rom_path] = Pending(fields, picture, tuple(removed))
    return out
