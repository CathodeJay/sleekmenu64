/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_FAVORITES_H
#define SLEEKMENU_FAVORITES_H

#include "card_paths.h"

/* Favourites you can actually set.

   The catalog carries a favourite flag, but it is built on a desktop, which
   made the feature useless in the only place it matters: standing in front of
   the television with a controller. Pressing C-down said "favorites are read
   from catalog metadata" and did nothing.

   So they live on the card, in a plain text file of ROM paths, one per line.
   The catalog's flag becomes the starting set the first time, and after that
   the file is the truth -- which is what makes a favourite survive rebuilding
   the catalog with a new art pack.

   Everything except the two IO calls is pure, and tested on the host. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Overridable so the host test can point it at a temporary file; the ROM
   build never defines it and gets the card. */
#ifndef SM_FAVORITES_PATH
/* SM_FAVORITES_PATH comes from card_paths.h. */
#endif
/* 256 favourites is well past what anyone curates by hand on a controller,
   and it bounds this structure to about 18 KB. */
#define SM_FAVORITES_MAX 256u
#define SM_FAVORITES_TEXT 16384u

typedef struct {
    /* Hashes, for the lookup that runs once per game on every rebuild. The
       paths themselves are kept only as the file's text, because scanning
       16 KB of it three thousand times over would be the slowest thing the
       browser does. */
    uint64_t keys[SM_FAVORITES_MAX];
    uint32_t count;
    char text[SM_FAVORITES_TEXT];
    size_t used;
    bool loaded;
    /* Whether a file was actually there. The difference between "no
       favourites" and "never had any" is what decides whether the catalog's
       own flags get to seed the set. */
    bool present;
    /* Set when an add was refused for want of room, so the UI can say so
       rather than silently dropping it. */
    bool full;
} sm_favorites_t;

bool sm_favorites_contains(const sm_favorites_t *favorites, const char *path);
bool sm_favorites_add(sm_favorites_t *favorites, const char *path);
bool sm_favorites_remove(sm_favorites_t *favorites, const char *path);
/* Returns whether the path is a favourite afterwards. */
bool sm_favorites_toggle(sm_favorites_t *favorites, const char *path);

void sm_favorites_reset(sm_favorites_t *favorites);
/* Replace the set from file text. Malformed or over-long lines are skipped. */
void sm_favorites_parse(sm_favorites_t *favorites, const char *text, size_t length);

/* Absent file is not an error: it means nothing has been favourited yet. */
void sm_favorites_load(sm_favorites_t *favorites, const char *path);
bool sm_favorites_save(const sm_favorites_t *favorites, const char *path);

#endif
