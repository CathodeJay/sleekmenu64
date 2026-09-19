# SPDX-License-Identifier: AGPL-3.0-only
"""Where every field of every game came from, in words.

The tool builds a catalog from four places -- the ROM header, the shipped
database, the collection on the card, and the card owner's own files -- and
the window's catalog tab shows which one answered for each field, so "what
did I change?" is a filter and "why is this the wrong box?" is a column.
Nothing here is a hidden flag: a picture's source is where the file is
(tools/custom_art.py, tools/hires.py) and a fact's source is which lookup
found it (tools/build_metadata.py). The vocabulary is fixed here so the
builders, the JSON on the card and the window all say the same words.

The console never sees any of this: the .ebc it reads carries the result and
nothing about where it came from.
"""

from __future__ import annotations

# -- the cover ---------------------------------------------------------------
COVER_YOURS_ROM = "yours (this ROM)"
COVER_YOURS_CODE = "yours (code {code})"
COVER_LIBRETRO = "libretro"
COVER_LIBRETRO_MODIFIED = "libretro, modified"
COVER_COLLECTION = "collection"
COVER_COLLECTION_REGION = "collection (another region's box)"

# -- the title and the description ------------------------------------------
TITLE_FILE_NAME = "file name"
YOURS = "yours"
TEXT_COLLECTION = "collection"
#: The collection's text is filed by game code, and a hack carries the code
#: of the game it was built on: when the database does not know this exact
#: dump, the text is that game's.
TEXT_COLLECTION_BY_CODE = "collection (by game code)"

# -- genre, publisher, year, players ----------------------------------------
DATABASE = "database"
COLLECTION = "collection"

#: A per-game corrections file (tools/build_metadata.py --overrides).
OVERRIDE = "override"

NONE = "none"

FIELDS = ("cover", "title", "description", "genre", "publisher", "year", "players")


def yours_code(code: str) -> str:
    return COVER_YOURS_CODE.format(code=code)


def is_yours(label: str) -> bool:
    """Whether a source label names the card owner's own file."""
    return label.startswith("yours")


def edited(sources: dict) -> bool:
    """Whether any field of a game is the card owner's own."""
    return any(is_yours(str(sources.get(field, ""))) for field in FIELDS)


def notes(game: dict) -> list[str]:
    """What a person looking at one game should know about where it came
    from -- the fallbacks, in plain words. Empty for a game whose every
    field came from the obvious place."""
    sources = game.get("sources") or {}
    cover = sources.get("cover", NONE)
    text = sources.get("description", NONE)
    out = []
    if cover == COVER_COLLECTION_REGION:
        out.append("The box is another region's scan; the collection has none for this one.")
    elif cover == COVER_LIBRETRO_MODIFIED:
        out.append("The high-resolution box was fetched from libretro and has been changed since.")
    elif cover == NONE:
        out.append("No box anywhere: the browser draws a placeholder.")
    if text == TEXT_COLLECTION_BY_CODE:
        out.append("The text is the collection's for this game code; for a hack, "
                   "that is the parent game's.")
    elif text == NONE:
        out.append("No description.")
    if sources.get("title") == YOURS:
        out.append("The title is yours; the file is named differently.")
    identified = game.get("identified", "")
    if identified == "":
        out.append("The database does not know this dump or its game code.")
    elif identified != "crc":
        out.append("The database knows the game code, not this exact dump.")
    return out
