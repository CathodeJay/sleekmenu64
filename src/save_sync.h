/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_SAVE_SYNC_H
#define SLEEKMENU_SAVE_SYNC_H

/* The two halves of making saves work, tied together.

   Arming, at launch: put the game's save on the cartridge and record in
   ED64/sysdata/registry.dat what is now pending, so that whichever menu boots
   next writes the save back under the right name.

   Flushing, at menu startup: read that record and move the cartridge's save
   memory back to ED64/gamedata/. The stock firmware does exactly this on every
   menu boot, and both menus reading and writing the same record is what keeps
   a card usable from either one. */

#include "save_type.h"
#include "save_io.h"
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool ran;                    /* a record existed and named a save */
    bool changed;                /* bytes actually went to or from the card */
    sm_save_type_t type;
    char detail[96];             /* one line, ready for the status bar */
} sm_save_sync_report_t;

#ifdef __mips__
/* Menu startup. Safe to call before anything else touches the card, and a
   no-op when there is no registry, no pending record or no save hardware. */
void sm_save_sync_flush(sm_save_sync_report_t *report);

/* Just before the boot handoff. header must be the normalised 64-byte ROM
   header. Returns false only when the save could not be put on the cartridge;
   a registry that cannot be updated is reported but does not block the boot,
   because the game is still perfectly playable without a writeback. */
bool sm_save_sync_arm(const char *rom_path, const uint8_t *header,
    sm_save_type_t type, sm_save_sync_report_t *report);
#endif

#endif
