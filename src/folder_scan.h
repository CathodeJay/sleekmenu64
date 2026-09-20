/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_FOLDER_SCAN_H
#define SLEEKMENU_FOLDER_SCAN_H

/* What the card holds in the folder being browsed that the catalog does
   not: a game copied on after the card was last prepared, or a whole new
   folder of them. The browser reads the folder off the card a few entries a
   frame while the list is already on screen, and adds what it finds to the
   catalog as extras -- listed where their names sort, playable, and with no
   box or facts until sleekmenu-prep is run again.

   The folder is read at most once per session: a finished scan is kept, so
   stepping back into a folder costs nothing. Only one thing reads the card
   at a time -- the scan gives way to the launch card and to anything else
   that opens a file, and starts over afterwards -- because a directory
   listing in progress and a file read do not always share the card cleanly
   on every cartridge. */
#include "catalog.h"
#include <libdragon.h>

/* Folders remembered per session; a folder read is cheap enough that
   forgetting the fifth one back is fine. */
enum { SM_SCAN_MEMO = 4 };
/* Extras kept per folder. A folder of more new files than this is a card
   that wants preparing, and the list says so. */
enum { SM_SCAN_MAX_EXTRAS = 1024 };
/* Directory entries read per frame. On the X7 an entry is a cached sector
   read most of the time; on the Pro eight of them are one FIFO round trip.
   Thirty-two keeps a frame's worth of reading under a frame. */
enum { SM_SCAN_ENTRIES_PER_STEP = 32 };

typedef enum {
    SM_SCAN_IDLE,       /* the extras for the wanted folder are published */
    SM_SCAN_WANTED,     /* a folder is to be read; nothing is open yet */
    SM_SCAN_RUNNING     /* a directory cursor is open on the card */
} sm_scan_state_t;

typedef struct {
    /* Finished folders, most recently used first. catalog->extras is a view
       of slots[0] whenever a folder is published. */
    sm_extras_t slots[SM_SCAN_MEMO];
    unsigned slot_count;
    /* The folder being read, and what has been found in it so far. */
    sm_extras_t found;
    sm_scan_state_t state;
    char wanted[256];
    char sd_path[272];
    dir_t entry;
    bool entry_pending;   /* dir_findfirst answered and its entry is unread */
    /* The catalog's own names in this folder -- files by name, subfolders by
       their first component -- as an open-addressing table of catalog
       indices, so each directory entry costs one lookup rather than a walk
       of the catalog. */
    uint32_t *known;
    uint32_t known_mask;
    bool failed;          /* the folder could not be read; nothing is added */
} sm_folder_scan_t;

/* The rules the whole-card scan and the folder scan share with
   tools/card_layout.py: which names are games, which are left alone. */
bool sm_name_is_rom(const char *name);
bool sm_name_is_hidden(const char *name);
bool sm_folder_excluded(const char *name);
bool sm_file_excluded(const char *name);
/* The title a file name gives a game nothing knows: the suffix dropped,
   the underscores and dashes people put in file names read as spaces, and
   the letters spelled as the font can draw them (sm_ascii_fold). Allocated;
   NULL when memory is short. */
char *sm_title_from_name(const char *name);
/* The font draws ASCII, and a name on the card is UTF-8: the accent in
   "Pokemon" is two bytes the font has no glyph for, drawn as two wrong
   ones. This spells `text` in the font's letters as tools/build_catalog.py
   console_text() spells a title -- accents dropped, "ae" for the ligature,
   straight quotes for curly ones -- for Latin-1, Latin Extended-A, the
   common punctuation and full-width ASCII, and leaves out the rest. No
   spelling is longer than what it replaces, so a buffer the size of `text`
   always holds the answer, and `out` may be `text`. Returns the length
   written; `out` is always terminated. */
size_t sm_ascii_fold(const char *text, char *out, size_t out_size);

void sm_folder_scan_init(sm_folder_scan_t *scan);
/* The folder being browsed changed. A folder read earlier this session is
   published at once and true comes back; otherwise the extras are empty, a
   read is queued, and the answer arrives through sm_folder_scan_step. */
bool sm_folder_scan_select(sm_folder_scan_t *scan, sm_catalog_t *catalog, const char *folder);
/* One frame's worth of reading. True when the folder just finished and
   catalog->extras now holds what it had. */
bool sm_folder_scan_step(sm_folder_scan_t *scan, sm_catalog_t *catalog);
/* Something else is about to use the card: drop the cursor. The read starts
   over at the next step; what was already published stays. */
void sm_folder_scan_yield(sm_folder_scan_t *scan);
/* A cursor is open: the card is the scan's until it finishes. */
bool sm_folder_scan_busy(const sm_folder_scan_t *scan);
void sm_folder_scan_close(sm_folder_scan_t *scan, sm_catalog_t *catalog);

#endif
