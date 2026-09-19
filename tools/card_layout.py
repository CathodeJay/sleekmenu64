# SPDX-License-Identifier: AGPL-3.0-only
"""What the browser reads and writes on the card, named in one place.

The console side has the same constants in src/card_paths.h and the two must
agree. One name rather than a literal in every file, and not for tidiness:
the library scan skips the browser's own folder by comparing against this
name, so renaming it everywhere but one place would leave the browser
listing its own catalog and cover pack as if they were games.

Renaming the project is a one-line change here and one in src/card_paths.h.
"""

CARD_FOLDER = "sleekmenu"

#: The stock EverDrive firmware's own folder: saves and system state, no games.
FIRMWARE_FOLDER = "ED64"

#: The browser itself, at the card root. A .z64 like any other to a folder
#: walk, and the one file that must never be listed as a game.
BROWSER_ROM = "SleekMenu64.z64"

COVERS_FOLDER = "covers"
COVER_PACK_NAME = "covers.pak"
#: The box view's covers, 256x180 against the thumbnails' 96x72: the same
#: container and the same names, in a second pack the browser opens beside
#: the first. Optional: a card without it still browses.
COVER_PACK_LARGE_NAME = "covers-large.pak"
COVERS_LARGE_FOLDER = "covers-large"
CATALOG_NAME = "catalog.ebc"
#: Under CARD_FOLDER: the catalog as the tool built it, with where every
#: field came from (tools/card_catalog.py). Read by the tool's window and by
#: `make refresh`, never by the browser.
CATALOG_JSON_NAME = "catalog.json"
#: Under CARD_FOLDER: the card owner's own pictures and text, by ROM name
#: or game code (tools/custom_art.py). Read by the tool, never the browser.
ART_FOLDER = "art"

#: Folder names the library scan never descends into, case-folded for
#: comparison against a directory name from the card: the browser's own, the
#: firmware's, the N64FlashcartMenu's (its menu ROM is a .n64 file), an
#: unpacked art collection (thousands of entries, no games), and the folder
#: Windows keeps on every removable disk. Hidden entries (a leading dot, the
#: recycle bin's `$`) are skipped by name shape rather than listed here.
EXCLUDED_DIRECTORIES = frozenset({CARD_FOLDER.casefold(), FIRMWARE_FOLDER.casefold(),
                                  "menu", "metadata", "system volume information"})


def hidden(name: str) -> bool:
    """Bookkeeping the operating systems leave on a card: `._Game.z64`
    AppleDouble twins, `.Trashes`, `.Spotlight-V100`, `$RECYCLE.BIN`."""
    return name.startswith((".", "$"))


def excluded_directory(name: str, excluded=EXCLUDED_DIRECTORIES) -> bool:
    """Whether a folder is one a library scan never enters: hidden, in the
    list above, or a copy of the firmware folder -- `ED64.bk2`, `ED64.old`
    -- which holds the firmware's apps and 64DD IPLs, ROM-shaped files that
    are not games. src/catalog.c applies the same rule."""
    folded = name.casefold()
    return (hidden(name) or (excluded is not None and folded in excluded)
            or folded.startswith(FIRMWARE_FOLDER.casefold() + "."))
