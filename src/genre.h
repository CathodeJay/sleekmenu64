/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_GENRE_H
#define SLEEKMENU_GENRE_H

/* Turning a genre string into something that fits on a 320-pixel screen.

   The catalog carries genre as libretro-database spells it -- "Role-playing
   (RPG)", "Hunting and Fishing", "Beat'em Up" -- which is far too long for a
   tab strip six pixels per character wide. Each becomes a three-letter code
   and a colour, and both have to be stable: a genre must keep the same colour
   whatever else is on the card, or the chips beside every row become
   meaningless the moment a folder is entered. */

#include "catalog.h"
#include <stdbool.h>
#include <stdint.h>

#define SM_GENRE_CODE_LEN 3u
/* Eight tabs is what the strip can DRAW: 168 pixels, three characters at six
   pixels each, three between tabs. It is not how many can EXIST. Building only
   eight meant a real library -- twenty-four genres on the card this was
   written against -- simply had no way to reach Puzzle or Beat'em Up: not from
   the strip, and not from the filter screen either, which cycles the same
   list. So every genre gets a tab, and the strip shows a window of them around
   the one selected. */
#define SM_GENRE_TABS_MAX 32u
#define SM_GENRE_TABS_VISIBLE 8u

typedef struct {
    char name[24];               /* the catalog's spelling; empty for "all" */
    char code[SM_GENRE_CODE_LEN + 1u];
    uint32_t count;
} sm_genre_tab_t;

typedef struct {
    sm_genre_tab_t tabs[SM_GENRE_TABS_MAX];
    uint32_t count;              /* at least 1: the "all" tab is always there */
} sm_genre_tabs_t;

/* "Role-playing (RPG)" -> "RPG", "Beat'em Up" -> "BTM". */
void sm_genre_code(const char *genre, char out[SM_GENRE_CODE_LEN + 1u]);

/* An index into the caller's palette, derived from the name alone so it never
   shifts as the library changes. Genre "" (unknown) always answers 0. */
unsigned sm_genre_colour_index(const char *genre, unsigned palette_size);

/* The tab strip for a catalog: "all", then every genre on the card, most
   common first. A library with no metadata gets just the one tab. */
void sm_genre_build_tabs(const sm_catalog_t *catalog, sm_genre_tabs_t *out);

/* Which tab the strip should start drawing at, so that `active` is on screen.
   Keeps the selection roughly centred and never scrolls past either end. */
uint32_t sm_genre_tab_window(uint32_t active, uint32_t count, uint32_t visible);

#endif
