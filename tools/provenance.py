# SPDX-License-Identifier: AGPL-3.0-only
"""Where every field of every game came from, in words.

The tool builds a catalog from four places -- the ROM header, the shipped
database, the collection on the card, and the card owner's own files -- and
catalog.json records which one answered for each field. The window's Games
tab reads that to mark what is the owner's own, to list what they changed,
and to say when a box is another region's. Nothing here is a hidden flag: a picture's source is where the file is
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
    return any(is_yours(str(source)) for source in sources.values())
