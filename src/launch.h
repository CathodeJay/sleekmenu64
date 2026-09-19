/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_LAUNCH_H
#define SLEEKMENU_LAUNCH_H

#include "history.h"

#include "save_type.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* The X7's cartridge SDRAM. The Pro reports its own ceiling at startup. */
#define SM_LAUNCH_MAX_ROM (64u * 1024u * 1024u)
#define SM_N64_HEADER_SIZE 0x1000u

typedef enum {
    SM_CIC_UNKNOWN = 0,
    SM_CIC_6101 = 6101,
    SM_CIC_6102 = 6102,
    SM_CIC_6103 = 6103,
    SM_CIC_6105 = 6105,
    SM_CIC_6106 = 6106
} sm_cic_t;

/* How the bytes sit in the file, judged by the header magic rather than by the
   filename: a large minority of dumps carry the wrong extension. The X7 can
   swap v64 in hardware during the SD to SDRAM transfer (EDX_CFG_BYTESWAP, set
   through libcart's cart_card_byteswap); n64 is a 32-bit word swap the
   cartridge cannot do, so it stays unsupported. */
typedef enum {
    SM_ROM_FORMAT_UNKNOWN = 0,
    SM_ROM_FORMAT_Z64,  /* 80 37 12 40 - native big endian */
    SM_ROM_FORMAT_V64,  /* 37 80 40 12 - 16-bit byte swapped */
    SM_ROM_FORMAT_N64   /* 40 12 37 80 - 32-bit word swapped */
} sm_rom_format_t;

sm_rom_format_t sm_rom_format_detect(const uint8_t *header, size_t length);
const char *sm_rom_format_name(sm_rom_format_t format);
/* Rewrite a header in place into z64 order so every other check reads real
   bytes. Only the buffer is touched; the file on the card is never modified. */
void sm_rom_header_normalise(uint8_t *header, size_t length, sm_rom_format_t format);

typedef enum {
    SM_LAUNCH_OK = 0,
    SM_LAUNCH_BAD_SUFFIX,
    SM_LAUNCH_BAD_SIZE,
    SM_LAUNCH_BAD_MAGIC,
    SM_LAUNCH_IO_ERROR,
    SM_LAUNCH_WRONG_CARTRIDGE,
    SM_LAUNCH_VERIFY_FAILED,
    SM_LAUNCH_WORD_SWAPPED,
    SM_LAUNCH_NO_64DD,      /* a disk image on a cartridge that has no drive */
    SM_LAUNCH_NO_IPL,       /* the 64DD IPL for the disk's region is not on the card */
    SM_LAUNCH_BAD_CHECKSUM  /* the header's checksum is stale and could not be corrected */
} sm_launch_result_t;

/* What became of the boot code's checksum at the last launch: summed over
   cartridge memory after the load, and corrected there when the header's
   words were stale (rom_checksum.h). UNFIXABLE stops the first launch with
   a message; the next Start goes ahead regardless, which is the person's
   call to make. */
typedef enum {
    SM_CHECKSUM_UNCHECKED = 0,   /* no launch yet, or the cart offers no access */
    SM_CHECKSUM_UNKNOWN_BOOT,    /* not a retail boot code: its own rules */
    SM_CHECKSUM_OK,
    SM_CHECKSUM_FIXED,
    SM_CHECKSUM_UNFIXABLE
} sm_checksum_state_t;

/* 64DD disk images (.ndd). The retail image starts with the system area,
   whose first word says which drive it was made for; the drive's IPL must
   match, and the stock EverDrive-64 Pro firmware keeps the three IPLs in
   ED64/64ddipl under their product codes. */
typedef enum {
    SM_DISK_REGION_UNKNOWN = 0,
    SM_DISK_REGION_JAPAN,     /* retail Japanese: NDDJ2 */
    SM_DISK_REGION_USA,       /* retail American: NDDE0 */
    SM_DISK_REGION_DEVELOPMENT /* anything else: the development IPL, NDXJ0 */
} sm_disk_region_t;

#define SM_DISK_IPL_DIR "sd:/ED64/64ddipl"
#define SM_DISK_IPL_MAX_BYTES (8u * 1024u * 1024u)
#define SM_DISK_HEAD_SIZE 4u

bool launch_suffix_is_disk(const char *path);
sm_disk_region_t launch_disk_region(const uint8_t *head, size_t length);
const char *launch_disk_region_name(sm_disk_region_t region);
/* "NDDJ2.n64" and friends: the file name under SM_DISK_IPL_DIR. */
const char *launch_disk_ipl_name(sm_disk_region_t region);

/* How much work Start does before it jumps. The three-press ladder this
   replaced -- probe, then load and verify, then boot -- was scaffolding for
   bringing the SD transport up, and it has done its job: transport, load and
   boot are all proven on hardware. Paying for it on every launch is not.

   SM_BOOT_FAST loads and jumps. SM_BOOT_VERIFY reads the whole image back out
   of SDRAM and compares it against the file first, which roughly doubles the
   wait and is what to reach for when a particular ROM misbehaves. */
typedef enum { SM_BOOT_FAST = 0, SM_BOOT_VERIFY } sm_boot_mode_t;

void launch_set_boot_mode(sm_boot_mode_t mode);
sm_boot_mode_t launch_boot_mode(void);

typedef void (*sm_launch_progress_cb)(uint32_t loaded_kib, uint32_t total_kib, void *context);

#define SM_LAUNCH_PATH_SIZE 520u
typedef struct {
    char primary[SM_LAUNCH_PATH_SIZE];
    char fallback[SM_LAUNCH_PATH_SIZE];
    size_t count;
} sm_launch_paths_t;

bool launch_suffix_is_rom(const char *path);
sm_launch_result_t launch_validate(const char *path, uint64_t size, uint64_t max_bytes, const uint8_t header[SM_N64_HEADER_SIZE], uint32_t *boot_crc, sm_cic_t *cic);
uint32_t launch_crc32(const void *data, size_t length);
/* Incremental form for streaming verification. Seed with 0xFFFFFFFF and
   finalise with ~crc; launch_crc32() is exactly that wrapper. */
uint32_t launch_crc32_update(uint32_t crc, const void *data, size_t length);
sm_cic_t launch_cic_from_crc(uint32_t boot_crc);
const char *launch_result_message(sm_launch_result_t result);
bool launch_resolve_paths(const char *path, sm_launch_paths_t *paths);

sm_launch_result_t launch_prepare(const char *relative_path);
sm_launch_result_t launch_rom(sm_launch_progress_cb progress, void *context);
void launch_cancel(void);
const char *launch_status_message(void);
const char *launch_selected_path(void);
uint32_t launch_boot_crc(void);
sm_cic_t launch_detected_cic(void);
sm_launch_result_t launch_last_result(void);

/* Lend the launcher the UI's history list, so a launch is recorded at the
   point of no return rather than optimistically when a game is selected.
   sm_history_t is a typedef of an anonymous struct, so it cannot be forward
   declared -- the header comes in whole, which costs nothing. */
void launch_set_history(sm_history_t *history);

/* The read-only SD -> SDRAM transport check, kept as a diagnostic. It writes
   only to scratch space well clear of the loaded image and never boots. */
sm_launch_result_t launch_probe(void);
/* e.g. "SRAM db:crc +RTC" — resolved save type, its source, and config. */
const char *launch_save_summary(void);

/* The save type resolved for the selected ROM: header override, then the
   card's save_db.txt, then the built-in database. This is what will be written
   to REG_GAM_CFG, so it is the honest answer to "will my save work". */
sm_save_type_t launch_save_type(void);
/* Whether the selection is a 64DD disk image, and the expansion disk found
   beside a selected ROM ("" when none). */
bool launch_selected_is_disk(void);
const char *launch_sibling_disk(void);

/* GameShark cheats for the selected ROM, from the firmware's database
   (ED64/CHEATS) or the browser's own folder. `available` says a file named
   the game; the set is what the cheats screen lists and toggles. A toggle
   is refused for an entry whose code the database left incomplete. Saving
   writes the browser's record of what is on; the list itself is built at
   launch and handed to the boot code. */
#include "cheats.h"
/* List the firmware's cheat pack, once, at startup; the launcher keeps it
   for every game selected after. */
void launch_read_cheat_pack(void);
const sm_cheat_pack_t *launch_cheat_pack(void);
bool launch_cheats_available(void);
const sm_cheat_set_t *launch_cheats(void);
/* The file the set came from and how sure the match is -- or, when none
   was loaded, why (the pack has the game for other regions only). */
const sm_cheat_source_t *launch_cheats_source(void);
/* Whether the console can run the engine at all: it needs the Expansion
   Pak. Without one the game boots clean and the launch card says why. */
bool launch_cheats_possible(void);
/* Whether the engine can hook the selected ROM's boot code; the card says
   so when it cannot, and no list is handed over. */
sm_cheats_hook_t launch_cheats_hook(void);
sm_checksum_state_t launch_checksum_state(void);
bool launch_cheat_toggle(uint32_t index);
bool launch_cheats_save(void);

#endif
