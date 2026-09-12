/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_SAVE_IO_H
#define SLEEKMENU_SAVE_IO_H

/* Moving cartridge save memory to and from ED64/gamedata/ the way the stock
   firmware does, so a save written by either menu is readable by the other.

   The stock EverDrive-64 OS keeps one file per ROM, named after the ROM's own
   filename with the extension swapped, in a single flat directory. That is the
   whole convention -- there is no index, no per-folder nesting, and no header.
   sample-03 in docs/sd-forensics/ is a save the firmware itself wrote, and the
   file this module produces for the same ROM has to match it byte for byte. */

#include "save_type.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Where the stock firmware keeps saves. Flat since OS 3.07 merged the old
   save/ and cheats/ directories into one. */
#define SM_GAMEDATA_DIR "ED64/gamedata"

/* The largest save any type needs, so callers can size one static buffer.
   SRM128K is the cartridge's whole 128 KiB battery window. */
#define SM_SAVE_MAX_BYTES 131072u

/* Bytes the stock firmware writes for each type. 0 means nothing is written:
   OFF has no backing store, and an unknown id is treated as OFF rather than
   guessed at. */
size_t sm_save_bytes(sm_save_type_t type);

/* ".eep", ".srm" or ".fla", lowercase, or NULL for a type with no file.
   EEPROM sizes share one extension, and so do all three SRAM sizes: the stock
   firmware distinguishes them by file length, not by name. */
const char *sm_save_extension(sm_save_type_t type);

/* Build "<dir>/<rom filename stem><ext>" from a ROM path in any of the forms
   the catalog produces ("sd:/ROMS/x.z64", "/ROMS/x.z64", "ROMS/x.z64").
   Returns false if the type has no file or the result would not fit. */
bool sm_save_file_path(const char *rom_path, sm_save_type_t type,
    const char *dir, char *out, size_t out_size);

/* True when the save lives in the cartridge's battery window rather than on
   the joybus. EEPROM is a separate serial device and needs a different path
   through the hardware entirely. */
bool sm_save_is_battery_backed(sm_save_type_t type);

typedef enum {
    SM_SAVE_IO_OK = 0,
    SM_SAVE_IO_NO_SAVE,     /* the type has no backing store; nothing to do */
    SM_SAVE_IO_NO_FILE,     /* no save on the card yet; not an error */
    SM_SAVE_IO_BAD_PATH,
    SM_SAVE_IO_READ_FAILED,
    SM_SAVE_IO_WRITE_FAILED,
    SM_SAVE_IO_BLANK_REFUSED, /* cartridge read back empty over a real save */
    SM_SAVE_IO_HARDWARE     /* the cartridge did not present the save device */
} sm_save_io_result_t;

const char *sm_save_io_message(sm_save_io_result_t result);

/* True when every byte is the same. Save memory that reads back this way is
   not a save, whatever the fill byte happens to be. */
bool sm_save_buffer_is_blank(const uint8_t *data, size_t size);

#ifdef __mips__

/* ED64/gamedata/<stem><ext> -> cartridge, before booting a ROM. A missing file
   is SM_SAVE_IO_NO_FILE and leaves the cartridge zeroed, which is what a fresh
   save looks like to a game. */
sm_save_io_result_t sm_save_restore(const char *rom_path, sm_save_type_t type);

/* Cartridge -> ED64/gamedata/<stem><ext>, on the way back into the menu.
   Writes only when the bytes differ from what is already on the card, so a
   menu boot that follows another menu boot does not churn the SD, and never
   writes an empty cartridge over a save the card already holds. */
sm_save_io_result_t sm_save_backup(const char *rom_path, sm_save_type_t type);
#endif

#endif
