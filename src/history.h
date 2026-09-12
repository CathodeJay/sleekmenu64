/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_HISTORY_H
#define SLEEKMENU_HISTORY_H

#include "card_paths.h"

/* The last fifteen games you launched, most recent first.

   Favourites are a list you curate; this is one you don't. On a card with
   three thousand ROMs the handful you are actually playing this month is the
   only shortlist that maintains itself, and finding one of them should not
   mean remembering which folder it lives in.

   Kept small on purpose. Fifteen is about one screen of list view and two
   turns of coverflow -- past that it stops being "what I was playing" and
   becomes another thing to scroll.

   Written at the point of no return in launch.c, after the save has been
   armed and before the handoff: the browser does not survive the jump, so
   there is no later. That means the record says "committed to booting this",
   not "this booted" -- a handoff that fails leaves an entry behind. The
   alternative is no history at all for the games that boot successfully,
   which is every game.

   Everything except the two IO calls is pure, and tested on the host. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifndef SM_HISTORY_PATH
/* SM_HISTORY_PATH comes from card_paths.h. */
#endif

#define SM_HISTORY_MAX 15u
/* Matches the launcher's own buffer, so a path that can be launched can always
   be recorded. It was 256 on the claim that this matched the catalog, which it
   did not: the launcher holds 512 and discovery allows more still, so a ROM
   with a long enough path launched perfectly and then silently never appeared
   here. Fifteen of these is 7.5 KB, which is not worth being clever about. */
#define SM_HISTORY_PATH_MAX 512u

typedef struct {
    /* Paths in full rather than hashes. Favourites hold 256 entries and pay
       for a hash set; fifteen entries is 3.8 KB of plain strings, and unlike
       a set this keeps the order, which is the whole point. */
    char paths[SM_HISTORY_MAX][SM_HISTORY_PATH_MAX];
    uint32_t count;
    bool loaded;
    /* Whether a file was there at all. Nothing depends on it yet; it is the
       difference between "never launched anything" and "history was cleared",
       which the UI says differently. */
    bool present;
} sm_history_t;

void sm_history_reset(sm_history_t *history);

/* Move to front. An entry already present moves rather than duplicating, so
   replaying one game does not push the other fourteen out. Returns false when
   the path is empty or too long to record. */
bool sm_history_record(sm_history_t *history, const char *path);

uint32_t sm_history_count(const sm_history_t *history);
/* Position in the list, or -1. Case-insensitive, like everything else that
   compares a path from a card that does not care about case either. */
int32_t sm_history_position(const sm_history_t *history, const char *path);

/* Replace the list from file text. Blank, malformed and over-long lines are
   skipped; anything past the fifteenth is dropped. */
void sm_history_parse(sm_history_t *history, const char *text, size_t length);
/* Serialise, newline terminated. Returns the length that was or would be
   written, so a caller can size a buffer. */
size_t sm_history_format(const sm_history_t *history, char *out, size_t size);

/* Absent file is not an error: it means nothing has been launched yet. */
void sm_history_load(sm_history_t *history, const char *path);
bool sm_history_save(const sm_history_t *history, const char *path);

#endif
