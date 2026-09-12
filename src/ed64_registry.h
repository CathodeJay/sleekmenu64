/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_ED64_REGISTRY_H
#define SLEEKMENU_ED64_REGISTRY_H

/* ED64/sysdata/registry.dat -- the stock firmware's record of what it last
   launched, and the only thing that tells it which save file to write on the
   next menu boot.

   SleekMenu reads and writes the same file rather than keeping a record of
   its own. That is the whole point: a game launched from SleekMenu and then
   powered off must have its save flushed correctly even if the next thing the
   console boots is krikzz's menu, and the reverse has to work too. A private
   side file would make the two menus disagree about whose save is pending.

   The layout was recovered by diffing snapshots from a real card, kept in
   tests/fixtures/registry/ and documented in tools/ed64_registry.py. Only four
   things are ever rewritten here -- the path, the ROM id, the ROM's header CRC
   pair and the save type. Every other byte is carried through untouched,
   because the file also holds the user's menu settings and browser position
   and we have no business rewriting what we have not decoded. */

#include "save_type.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SM_REGISTRY_PATH "sd:/ED64/sysdata/registry.dat"
#define SM_REGISTRY_SIZE 2256u
#define SM_REGISTRY_PATH_MAX 256u

typedef struct {
    char path[SM_REGISTRY_PATH_MAX]; /* card-absolute, as the firmware stores it */
    char rom_id[SM_SAVE_FULL_ID_LEN + 1u];
    uint8_t rom_crc[8];              /* ROM header 0x10..0x17, verbatim */
    sm_save_type_t save_type;
} sm_registry_record_t;

/* True when the blob is the right length and its trailing CRC-32 matches.
   A file that fails this is never rewritten: the firmware would reject it, and
   more to the point we would be guessing at 2252 bytes we did not decode. */
bool sm_registry_verify(const uint8_t *blob, size_t size);

/* Read back what a blob says. Returns false if it does not verify. */
bool sm_registry_read(const uint8_t *blob, size_t size, sm_registry_record_t *out);

/* Rewrite the four decoded fields in place and reseal the CRC. Returns false
   if the blob does not verify, the path does not fit, or the id is not the
   six symbols the firmware expects. */
bool sm_registry_write(uint8_t *blob, size_t size, const sm_registry_record_t *record);

/* Turn any of the path forms the catalog produces ("sd:/ROMS/x.z64",
   "ROMS/x.z64", "/ROMS/x.z64") into the card-absolute form the firmware
   stores ("/ROMS/x.z64"). */
bool sm_registry_normalise_path(const char *path, char *out, size_t out_size);

/* Turn the "sd:/..." path the loader actually opened into the card-absolute
   form the firmware stores. Prefer this over normalising a catalog path: the
   catalog's paths are relative to the ROMS root and are not what is on the
   card. */
bool sm_registry_path_for_launch(const char *resolved_sd_path, char *out, size_t out_size);

#ifdef __mips__
/* Read the card's registry.dat. False when it is missing or does not verify;
   in both cases the caller must not write one. */
bool sm_registry_load(sm_registry_record_t *out);

/* Read, patch the four fields, reseal and write back. False on any of the
   above, or if the card refuses the write. */
bool sm_registry_store(const sm_registry_record_t *record);
#endif

#endif
