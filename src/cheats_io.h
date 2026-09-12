/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_CHEATS_IO_H
#define SLEEKMENU_CHEATS_IO_H

/* The card side of cheats: listing the pack, finding a game's .cht, and
   keeping the browser's own record of what is on. Everything that decides
   is in cheats.c and cheat_pack.c; this is the listing, the two reads and
   the one write. */

#include "cheat_pack.h"
#include "cheats.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __mips__
/* List ED64/CHEATS into the pack, once. An absent folder leaves it empty
   and read. */
void sm_cheats_read_pack(sm_cheat_pack_t *pack);

/* Fill the set for a game: the browser's own folder by file name, then
   the pack's file for the game and region (cheat_pack.h); then the state
   file's section for the game. `rom_path` is the catalog's card-relative
   form, `header` the normalised header. `source`, when given, says which
   file answered and how sure the match is, or why none did. False, with
   an empty set, when no file fits the game -- which is most games and not
   an error. */
bool sm_cheats_load(const char *rom_path, const uint8_t *header, size_t header_length,
    const sm_cheat_pack_t *pack, sm_cheat_set_t *set, sm_cheat_source_t *source);

/* Rewrite the state file's section for the game from the set. */
bool sm_cheats_save_state(const char *rom_path, const sm_cheat_set_t *set);
#endif

#endif
