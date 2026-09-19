# SPDX-License-Identifier: AGPL-3.0-only
"""sleekmenu/catalog.json: the catalog as the tool built it, with where
every field came from.

The console reads catalog.ebc, a packed binary that carries the result and
nothing else. This is the same catalog kept legible beside it, written by
every Prepare, so the window can show the card without scanning it again
and say for each game which of the four sources answered (tools/
provenance.py). It is the metadata the tool builds anyway plus the cover
plan's word on each picture and a note of when and from what it was
built, and it is the file `make refresh` re-derives from.

Nothing here is read by the browser, and nothing here is written to the
card by hand.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from tools import card_layout, cover_pack, make_sprite

SCHEMA_VERSION = 1


class CatalogJsonError(ValueError):
    pass


def path_on(card: Path) -> Path:
    return card / card_layout.CARD_FOLDER / card_layout.CATALOG_JSON_NAME


def write(card: Path, document: dict) -> Path:
    """The metadata document onto the card, stamped. The document is what
    tools/build_metadata.py built: its records already carry `sources`."""
    out = dict(document)
    out["built"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out["card_folder"] = card_layout.CARD_FOLDER
    target = path_on(card)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return target


def load(card: Path) -> dict | None:
    """The catalog on a card, or None when the card has none yet. A file
    that is not a catalog is an error with the file's name in it."""
    target = path_on(card)
    if not target.is_file():
        return None
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CatalogJsonError(f"{target}: {error}") from error
    if not isinstance(document, dict) or not isinstance(document.get("games"), list):
        raise CatalogJsonError(f"{target}: not a catalog")
    return document


def why_missing(card: Path) -> str:
    """What to say when a card has no catalog.json: a card prepared before
    the file existed still has the packed catalog the console reads, and
    that is worth saying, since "no catalog" would be untrue."""
    packed = card / card_layout.CARD_FOLDER / card_layout.CATALOG_NAME
    if packed.is_file():
        return (f"This card has a {card_layout.CATALOG_NAME} the console can read, built by an "
                "earlier version of this tool; press Prepare once and it shows here.")
    return "No catalog on this card yet: press Prepare."


def tree(games: list[dict]) -> dict:
    """The games as the browser shows them: folders nested from the card
    root, each holding its own games in title order. A folder is a dict
    with `folders` (name -> folder) and `games` (records)."""
    root = {"folders": {}, "games": []}
    for game in sorted(games, key=lambda g: (str(g.get("path", "")).casefold())):
        parts = PurePosixPath(str(game.get("path", ""))).parts
        node = root
        for name in parts[:-1]:
            node = node["folders"].setdefault(name, {"folders": {}, "games": []})
        node["games"].append(game)
    for node in _walk(root):
        node["games"].sort(key=lambda g: str(g.get("title", "")).casefold())
    return root


def _walk(node: dict):
    yield node
    for child in node["folders"].values():
        yield from _walk(child)


def count(node: dict) -> int:
    """Games in a folder and everything under it."""
    return len(node["games"]) + sum(count(child) for child in node["folders"].values())


class Covers:
    """covers.pak, read once, for looking at the boxes exactly as the
    console will draw them: the sprite out of the pack, decoded -- never
    the picture the sprite was made from."""

    def __init__(self, blob: bytes):
        self.blob = blob
        self.entries = {entry.hash: entry for entry in cover_pack.read_index(blob)}

    @classmethod
    def open(cls, card: Path) -> "Covers | None":
        """None when the card has no pack, or a pack that will not read."""
        pack = card / card_layout.CARD_FOLDER / card_layout.COVER_PACK_NAME
        try:
            return cls(pack.read_bytes())
        except (OSError, cover_pack.CoverPackError):
            return None

    def pixels(self, game: dict) -> tuple[int, int, bytes] | None:
        """Width, height and packed RGB rows of the game's box; None when
        the game has no cover or the pack lacks it."""
        name = game.get("cover")
        if not name:
            return None
        entry = self.entries.get(cover_pack.cover_hash(str(name)))
        if entry is None:
            return None
        try:
            return make_sprite.decode(self.blob[entry.offset:entry.offset + entry.length])
        except make_sprite.SpriteError:
            return None
