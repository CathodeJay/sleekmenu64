/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_CARD_PATHS_H
#define SLEEKMENU_CARD_PATHS_H

/* Everything the browser reads or writes on the card, derived from one name.
 *
 * One name, not five literals, and not for tidiness: catalog.c excludes the
 * browser's own folder from the library scan by comparing against this
 * name, so a folder renamed in four places and missed in the fifth would
 * leave the browser listing its own catalog and cover pack as if they were
 * games. Deriving everything from SM_CARD_FOLDER makes that impossible, and
 * makes renaming the project a one-line change here and one in
 * tools/card_layout.py.
 */
#define SM_CARD_FOLDER "sleekmenu"

#define SM_SD_ROOT "sd:/"
#define SM_CARD_DIR SM_SD_ROOT SM_CARD_FOLDER

/* Each is overridable with -D so the host tests can point them at a temporary
   directory; the console build never overrides any of them. */
#ifndef SM_CATALOG_PATH
#define SM_CATALOG_PATH SM_CARD_DIR "/catalog.ebc"
#endif
#ifndef SM_COVER_PACK_PATH
#define SM_COVER_PACK_PATH SM_CARD_DIR "/covers.pak"
#endif
#ifndef SM_COVERS_DIR
#define SM_COVERS_DIR SM_CARD_DIR "/covers"
#endif
#ifndef SM_FAVORITES_PATH
#define SM_FAVORITES_PATH SM_CARD_DIR "/favorites.txt"
#endif
#ifndef SM_HISTORY_PATH
#define SM_HISTORY_PATH SM_CARD_DIR "/history.txt"
#endif
/* Which cheats are on, per game; and where a card owner can drop .cht files
   of their own, looked up after the firmware's database. */
#ifndef SM_CHEATS_STATE_PATH
#define SM_CHEATS_STATE_PATH SM_CARD_DIR "/cheats.txt"
#endif
#ifndef SM_CHEATS_DIR
#define SM_CHEATS_DIR SM_CARD_DIR "/cheats"
#endif

/* The stock firmware's own folder. Excluded from the library scan for the same
   reason: it holds saves and system state, not games. */
#define SM_FIRMWARE_FOLDER "ED64"
/* The browser itself, at the card root: a .z64 to a folder walk, and the one
   file that must never be listed as a game. tools/card_layout.py has the
   same name. */
#define SM_BROWSER_ROM "SleekMenu64.z64"
/* The cheat database the EverDrive-64 Pro's firmware ships, one libretro
   .cht per game; the same folder serves an X7 card. */
#define SM_FIRMWARE_CHEATS_DIR SM_SD_ROOT SM_FIRMWARE_FOLDER "/CHEATS"

#endif
