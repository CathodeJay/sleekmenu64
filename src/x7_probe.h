/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_X7_PROBE_H
#define SLEEKMENU_X7_PROBE_H

#include <stddef.h>
#include <stdint.h>

#define SM_PROBE_SECTOR_SIZE 512u

/* Scratch window inside cartridge SDRAM. The running SleekMenu image occupies
   roughly the first 10 MiB of SDRAM at offset 0, so the probe deliberately
   targets +32 MiB instead: nothing the console is executing or reading lives
   there. SDRAM is volatile and nothing is read back after the probe returns,
   so no persistent state is left on the cartridge or on the SD card. */
#define SM_PROBE_CART_OFFSET (32u * 1024u * 1024u)
#define SM_PROBE_CART_PHYS (0x10000000u + SM_PROBE_CART_OFFSET)
#define SM_PROBE_CART_KSEG1 (0xB0000000u + SM_PROBE_CART_OFFSET)

/* Poison pattern written into the scratch window before each transfer so that
   a transfer which silently does nothing cannot be mistaken for a success. */
#define SM_PROBE_POISON 0xA5u

typedef enum {
    SM_PROBE_OK = 0,
    SM_PROBE_NOT_X7,           /* libcart did not detect an X-series cartridge */
    SM_PROBE_NO_LBA,           /* first cluster does not map to a valid sector */
    SM_PROBE_REFERENCE_FAILED, /* the already-working FatFs read failed */
    SM_PROBE_SDRAM_UNWRITABLE, /* PI writes to the scratch window do not stick */
    SM_PROBE_CARD_FAILED,      /* cart_card_rd_cart() returned an error */
    SM_PROBE_SDRAM_MISMATCH,   /* transport ran but SDRAM does not match */
    SM_PROBE_DISPATCH_FAILED,  /* f_read into cart space returned an error */
    SM_PROBE_DISPATCH_MISMATCH /* f_read into cart space produced wrong bytes */
} sm_probe_step_t;

typedef struct {
    sm_probe_step_t step;
    uint32_t lba;           /* physical SD sector the probe transferred */
    uint32_t cart_size;     /* libcart's reported SDRAM size */
    uint32_t reference_crc; /* CRC32 of the sector as FatFs reads it to RDRAM */
    uint32_t direct_crc;    /* CRC32 read back after cart_card_rd_cart() */
    uint32_t dispatch_crc;  /* CRC32 read back after f_read() into cart space */
    uint32_t first_diff;    /* first differing byte, or SM_PROBE_SECTOR_SIZE */
    int card_rc;            /* cart_card_rd_cart() return value */
    int fatfs_rc;           /* FRESULT of the cart-space f_read() */
} sm_probe_report_t;

/* Mirror of FatFs clst2sect() for the first cluster of a file. Only the first
   sector is ever needed here, so no FAT chain has to be walked. */
int sm_probe_first_lba(uint32_t database, uint32_t csize, uint32_t n_fatent,
    uint32_t start_cluster, uint32_t *lba);

/* Index of the first differing byte, or length when the buffers are equal. */
uint32_t sm_probe_first_difference(const uint8_t *a, const uint8_t *b, uint32_t length);

/* One-line status suitable for the launch screen. Always NUL-terminates. */
void sm_probe_format(const sm_probe_report_t *report, char *out, size_t out_size);

#ifdef __mips__
#include "ff.h"

/* Read-only transport probe. Performs no SD writes, no save configuration and
   no boot. Writes only to the SM_PROBE_CART_* scratch window in SDRAM. The
   file must already be open for reading and is left open and rewound. */
sm_probe_step_t sm_x7_probe_run(FIL *file, sm_probe_report_t *report);
#endif

#endif
