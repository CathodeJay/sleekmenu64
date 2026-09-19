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
CATALOG_NAME = "catalog.ebc"
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
