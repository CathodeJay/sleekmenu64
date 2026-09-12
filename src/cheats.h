/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_CHEATS_H
#define SLEEKMENU_CHEATS_H

/* GameShark cheats, from the files the EverDrive-64 Pro's firmware ships.

   The Pro's OS carries a database under ED64/CHEATS: one file per game in
   libretro's .cht form, named the GoodN64 way (cheat_pack.h says how a
   game finds its file there) --

       cheats = 11
       cheat0_desc = "Invincible"
       cheat0_enable = false
       cheat0_code = "811147D8 0101"
       cheat1_code = "81103B66 0021;50000D01 0000;80118F38 0001"

   -- and the same text files serve an X7 card. This module reads one into a
   set, remembers which entries the player turned on in a small file of the
   browser's own (sleekmenu/cheats.txt, one section per game), and turns the
   enabled entries into the word list the vendored boot code's engine takes:
   code word, value word, pairs in order, two zero words to end it.

   Everything here is pure and runs on the host; the launcher does the file
   reads. Sizes come from the real database: the largest file holds 223
   cheats and 1,269 code pairs, the longest description 95 characters. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SM_CHEATS_MAX 256u
#define SM_CHEAT_WORDS_MAX 4096u
#define SM_CHEAT_DESC_MAX 64u
/* One entry's codes as text: the database's longest has 94 pairs. */
#define SM_CHEAT_CODE_TEXT_MAX 1536u
/* The largest .cht the launcher will read into memory. */
#define SM_CHEAT_FILE_MAX (96u * 1024u)

typedef struct {
    char desc[SM_CHEAT_DESC_MAX];
    uint16_t first;      /* index of the first word in the set's pool */
    uint16_t pairs;      /* code/value pairs; words used = pairs * 2 */
    bool enabled;
    /* The database leaves "XXXX" where the player is meant to choose a value
       (a level number, an item id). Nothing can be done with that on a
       console, so the entry is shown and cannot be turned on. */
    bool incomplete;
} sm_cheat_t;

typedef struct {
    sm_cheat_t cheats[SM_CHEATS_MAX];
    uint32_t words[SM_CHEAT_WORDS_MAX];
    uint32_t count;
    uint32_t word_count;
    uint32_t skipped;    /* entries the file had that did not fit or parse */
} sm_cheat_set_t;

void sm_cheats_reset(sm_cheat_set_t *set);

/* Read a .cht text into the set. Lines may come in any order and any
   cheatN may be missing a field; an entry needs at least a code to count.
   Returns the number of cheats kept. */
uint32_t sm_cheats_parse(sm_cheat_set_t *set, const char *text, size_t length);

/* One code, "811147D8 0101", into a code word and a value word. */
bool sm_cheats_parse_code(const char *text, size_t length, uint32_t *code, uint32_t *value);

/* The name a game's own file goes by: the ROM's file name with the
   extension swapped for .cht. False when it would not fit. */
bool sm_cheats_file_from_rom_path(const char *rom_path, char *out, size_t out_size);

/* Enabled entries, in file order, as the engine's list. Returns the words
   written including the terminator, or 0 when nothing is enabled (the
   caller passes no list). The engine stages itself at 7 MB and settles near
   the top of 8 MB, so the list is only worth building on a console with an
   Expansion Pak; the launcher checks that, not this. */
uint32_t sm_cheats_build_list(const sm_cheat_set_t *set, uint32_t *out, size_t out_words);
uint32_t sm_cheats_enabled_count(const sm_cheat_set_t *set);

/* Whether the engine can get into this game at all. It hooks the boot code
   by overwriting one instruction of the retail IPL3 -- the `jr $t1` that
   jumps to the game's entry point -- at an offset that depends on the CIC.
   A homebrew or re-signed IPL3 has no such instruction there, and the boot
   code then quietly boots the game without cheats. This is the same test the
   boot code makes, run ahead of time on the ROM's first 4 KiB so the card
   can say so before the player wonders why nothing happened. */
typedef enum {
    SM_CHEATS_HOOK_OK = 0,
    SM_CHEATS_HOOK_UNKNOWN_CIC,   /* not a retail boot code the engine knows */
    SM_CHEATS_HOOK_NO_JUMP        /* retail CIC, but the instruction is not there */
} sm_cheats_hook_t;
sm_cheats_hook_t sm_cheats_hook_check(const uint8_t *header, size_t header_length);

/* Where a game's cheats came from, for the page to say: the file, and how
   sure the match is (cheat_pack.h). When nothing was loaded, `kind` may
   still say why -- OTHER_REGION, with `found` naming the regions the pack
   does have the game for. */
#include "cheat_pack.h"
#define SM_CHEAT_SOURCE_MAX 96u
typedef struct {
    char path[SM_CHEAT_SOURCE_MAX];  /* card-relative, "ED64/CHEATS/X.cht" */
    sm_cheat_match_kind_t kind;
    uint16_t rom_region;
    uint16_t found;
} sm_cheat_source_t;

/* The browser's own record of what is on, sleekmenu/cheats.txt:

       [ROMS/1 US/F-Zero X (USA).z64]
       811147D8 0101
       81103B66 0021;50000D01 0000;80118F38 0001

   An entry is identified by its code text, not its position, so a database
   file that gains or loses an entry does not turn on the wrong one. */
#define SM_CHEATS_STATE_MAX (32u * 1024u)

/* Mark the set's entries from the state text's section for rom_path. */
void sm_cheats_state_apply(sm_cheat_set_t *set, const char *state, size_t state_length,
    const char *rom_path);
/* Rewrite the state text with this game's section replaced by the set's
   enabled entries (or removed when none are). Returns the new length, or 0
   with out[0] == '\0' if it would not fit. */
size_t sm_cheats_state_update(const char *state, size_t state_length, const char *rom_path,
    const sm_cheat_set_t *set, char *out, size_t out_size);
/* The code text of one entry, as the state file records it. */
size_t sm_cheats_format_code(const sm_cheat_set_t *set, uint32_t index, char *out, size_t out_size);

#endif
