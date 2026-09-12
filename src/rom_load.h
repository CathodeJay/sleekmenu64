/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_ROM_LOAD_H
#define SLEEKMENU_ROM_LOAD_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Cartridge SDRAM, offset 0 — where a launched ROM must land, and where
   SleekMenu's own image currently sits. See sm_cart_image_intact() in
   flashcart.h. */
#define SM_LOAD_CART_KSEG1 0xB0000000u
#define SM_LOAD_CART_PHYS 0x10000000u
#define SM_LOAD_SECTOR 512u
#define SM_LOAD_CHUNK (128u * 1024u)
#define SM_LOAD_VERIFY_CHUNK (32u * 1024u)

typedef enum {
    SM_LOAD_OK = 0,
    SM_LOAD_NOT_X7,
    SM_LOAD_TOO_LARGE,
    SM_LOAD_READ_FAILED,
    SM_LOAD_SHORT_READ,
    SM_LOAD_VERIFY_READ_FAILED,
    SM_LOAD_MISMATCH
} sm_load_step_t;

typedef struct {
    sm_load_step_t step;
    uint32_t bytes;         /* real payload size */
    uint32_t padded_bytes;  /* rounded up to a whole sector for FatFs */
    uint32_t crc;           /* CRC32 of the file stream, 0 when not verified */
    bool verified;          /* the SDRAM was read back and compared */
    uint32_t first_diff;    /* byte offset of the first mismatch, else UINT32_MAX */
    uint8_t file_byte;
    uint8_t sdram_byte;
    int fatfs_rc;
} sm_load_report_t;

typedef void (*sm_load_progress_cb)(uint32_t done, uint32_t total, bool verifying,
    void *context);

/* Round a payload up to a whole 512-byte sector. FatFs stages a partial
   trailing sector through its RDRAM window, which cannot target cartridge
   space, so the transfer has to be sector-aligned end to end. */
uint32_t sm_load_padded_size(uint32_t bytes);

void sm_load_format(const sm_load_report_t *report, char *out, size_t out_size);

#ifdef __mips__
#include "ff.h"

/* Load the whole ROM into cartridge SDRAM at offset 0. With verify set, read
   the range back out over PI and compare it byte for byte against the file,
   which costs a second full pass and roughly doubles the wall clock.

   Verification earned its keep while the SD transport was unproven. Now that
   it is, a corrupt load shows up as a game that crashes rather than as a
   message, which is a fair trade for halving the wait -- and the check is
   still one button away when a ROM misbehaves.

   Does not boot, does not configure save hardware, does not write to the SD
   card. Destroys SleekMenu's own cart image by design -- see
   sm_cart_image_intact() in flashcart.h. */
sm_load_step_t sm_rom_load(FIL *file, uint32_t bytes, bool byteswap, bool verify,
    sm_load_progress_cb progress, void *context, sm_load_report_t *report);
#endif

#endif
