# SPDX-License-Identifier: AGPL-3.0-only
"""What the browser reads and writes on the card, named in one place.

The console side has the same constants in src/card_paths.h and the two must
agree. They used to be independent string literals scattered across five C
files and three Python ones, which is a quiet trap rather than mere
duplication: the library scan skips the browser's own folder by comparing
against this name, so renaming it everywhere but one place would leave the
browser listing its own catalog and cover pack as if they were games.

Renaming the project is a one-line change here and one in src/card_paths.h.
"""

CARD_FOLDER = "sleekmenu"

#: The stock EverDrive firmware's own folder: saves and system state, no games.
FIRMWARE_FOLDER = "ED64"

COVERS_FOLDER = "covers"
COVER_PACK_NAME = "covers.pak"
CATALOG_NAME = "catalog.ebc"

#: Folder names the library scan never descends into, case-folded for
#: comparison against a directory name from the card.
EXCLUDED_DIRECTORIES = frozenset({CARD_FOLDER.casefold(), FIRMWARE_FOLDER.casefold()})
