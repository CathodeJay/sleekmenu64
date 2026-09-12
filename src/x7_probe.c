/* SPDX-License-Identifier: AGPL-3.0-only */
#include "x7_probe.h"
#include <stdio.h>

int sm_probe_first_lba(uint32_t database, uint32_t csize, uint32_t n_fatent,
    uint32_t start_cluster, uint32_t *lba) {
    uint32_t index;
    if (!lba || csize == 0u || n_fatent < 2u || start_cluster < 2u) return -1;
    index = start_cluster - 2u;
    /* Same bound FatFs clst2sect() applies before trusting a cluster number. */
    if (index >= n_fatent - 2u) return -1;
    if (index != 0u && csize > 0xFFFFFFFFu / index) return -1;
    if (database > 0xFFFFFFFFu - csize * index) return -1;
    *lba = database + csize * index;
    return 0;
}

uint32_t sm_probe_first_difference(const uint8_t *a, const uint8_t *b, uint32_t length) {
    uint32_t i;
    if (!a || !b) return 0u;
    for (i = 0u; i < length; i++)
        if (a[i] != b[i]) return i;
    return length;
}

void sm_probe_format(const sm_probe_report_t *r, char *out, size_t out_size) {
    if (!out || out_size == 0u) return;
    if (!r) { out[0] = '\0'; return; }
    switch (r->step) {
        case SM_PROBE_OK:
            snprintf(out, out_size, "X7 TRANSPORT OK lba=%lu crc=%08lX direct+dispatch verified",
                (unsigned long)r->lba, (unsigned long)r->reference_crc);
            break;
        case SM_PROBE_NOT_X7:
            snprintf(out, out_size, "X7 PROBE SKIPPED: no X-series cartridge or SDRAM too small; nothing written");
            break;
        case SM_PROBE_NO_LBA:
            snprintf(out, out_size, "X7 PROBE SKIPPED: first cluster does not map to a sector");
            break;
        case SM_PROBE_REFERENCE_FAILED:
            snprintf(out, out_size, "X7 PROBE: FatFs reference read failed; SD path is the problem");
            break;
        case SM_PROBE_SDRAM_UNWRITABLE:
            snprintf(out, out_size, "X7 PROBE: SDRAM +32MiB not writable over PI; transport untested");
            break;
        case SM_PROBE_CARD_FAILED:
            snprintf(out, out_size, "X7 PROBE CARD FAIL lba=%lu rc=%d ref=%08lX",
                (unsigned long)r->lba, r->card_rc, (unsigned long)r->reference_crc);
            break;
        case SM_PROBE_SDRAM_MISMATCH:
            snprintf(out, out_size, "X7 PROBE SDRAM MISMATCH lba=%lu off=0x%03lX ref=%08lX got=%08lX",
                (unsigned long)r->lba, (unsigned long)r->first_diff,
                (unsigned long)r->reference_crc, (unsigned long)r->direct_crc);
            break;
        case SM_PROBE_DISPATCH_FAILED:
            snprintf(out, out_size, "X7 DISPATCH FAIL fr=%d lba=%lu; direct DMA passed crc=%08lX",
                r->fatfs_rc, (unsigned long)r->lba, (unsigned long)r->direct_crc);
            break;
        case SM_PROBE_DISPATCH_MISMATCH:
            snprintf(out, out_size, "X7 DISPATCH MISMATCH lba=%lu off=0x%03lX ref=%08lX got=%08lX",
                (unsigned long)r->lba, (unsigned long)r->first_diff,
                (unsigned long)r->reference_crc, (unsigned long)r->dispatch_crc);
            break;
        default:
            snprintf(out, out_size, "X7 PROBE: unknown result");
            break;
    }
    out[out_size - 1u] = '\0';
}

#ifdef __mips__
#include "launch.h"
#include "cart.h"
#include <libdragon.h>
#include <string.h>

/* 16-byte aligned so both PI DMA and the cache maintenance below operate on
   whole 16-byte D-cache lines and never share a line with other data. */
static uint8_t probe_reference[SM_PROBE_SECTOR_SIZE] __attribute__((aligned(16)));
static uint8_t probe_readback[SM_PROBE_SECTOR_SIZE] __attribute__((aligned(16)));
static uint8_t probe_poison[SM_PROBE_SECTOR_SIZE] __attribute__((aligned(16)));

/* dma_read()/dma_write() move data through the uncached alias and perform no
   cache maintenance of their own, so the caller owns it on both sides. */
static void probe_cart_write(const uint8_t *source) {
    data_cache_hit_writeback(source, SM_PROBE_SECTOR_SIZE);
    dma_write(source, SM_PROBE_CART_PHYS, SM_PROBE_SECTOR_SIZE);
}

static void probe_cart_read(uint8_t *destination) {
    data_cache_hit_writeback_invalidate(destination, SM_PROBE_SECTOR_SIZE);
    dma_read(destination, SM_PROBE_CART_PHYS, SM_PROBE_SECTOR_SIZE);
    data_cache_hit_invalidate(destination, SM_PROBE_SECTOR_SIZE);
}

/* Fill the scratch window with a pattern that is not the sector under test, so
   a transfer that quietly does nothing cannot read as a pass. */
static int probe_poison_cart(void) {
    memset(probe_poison, SM_PROBE_POISON, sizeof(probe_poison));
    probe_cart_write(probe_poison);
    probe_cart_read(probe_readback);
    return memcmp(probe_readback, probe_poison, sizeof(probe_poison)) == 0 ? 0 : -1;
}

sm_probe_step_t sm_x7_probe_run(FIL *file, sm_probe_report_t *report) {
    sm_probe_report_t local;
    FATFS *fs;
    UINT got = 0;
    FRESULT fr;

    memset(&local, 0, sizeof(local));
    local.first_diff = SM_PROBE_SECTOR_SIZE;
    local.cart_size = cart_size;
    if (report) *report = local;
    if (!file || !file->obj.fs) {
        local.step = SM_PROBE_REFERENCE_FAILED;
        if (report) *report = local;
        return local.step;
    }
    fs = file->obj.fs;

    /* Never touch cartridge memory unless libcart says this is an X-series and
       the scratch window is actually inside the reported SDRAM. */
    if (cart_type != CART_EDX ||
        SM_PROBE_CART_OFFSET + SM_PROBE_SECTOR_SIZE > cart_size) {
        local.step = SM_PROBE_NOT_X7;
        if (report) *report = local;
        return local.step;
    }

    /* The probe compares SDRAM against the file byte for byte, so the FPGA
       byteswap must be off or a byteswapped ROM would fail a healthy cart. */
    cart_card_byteswap = 0;

    /* Step 1 - reference. This is the path that already works today. */
    if (f_lseek(file, 0) != FR_OK ||
        f_read(file, probe_reference, SM_PROBE_SECTOR_SIZE, &got) != FR_OK ||
        got != SM_PROBE_SECTOR_SIZE) {
        local.step = SM_PROBE_REFERENCE_FAILED;
        if (report) *report = local;
        return local.step;
    }
    local.reference_crc = launch_crc32(probe_reference, SM_PROBE_SECTOR_SIZE);

    /* The first sector of the file is the only one the probe needs, so the
       first cluster is enough and no FAT chain has to be walked. */
    if (sm_probe_first_lba((uint32_t)fs->database, fs->csize, fs->n_fatent,
            file->obj.sclust, &local.lba) != 0) {
        local.step = SM_PROBE_NO_LBA;
        if (report) *report = local;
        return local.step;
    }

    /* Step 2 - the transport under test: SD to SDRAM by hardware DMA. */
    if (probe_poison_cart() != 0) {
        local.step = SM_PROBE_SDRAM_UNWRITABLE;
        if (report) *report = local;
        return local.step;
    }
    local.card_rc = cart_card_rd_cart(SM_PROBE_CART_PHYS, local.lba, 1u);
    if (local.card_rc != 0) {
        local.step = SM_PROBE_CARD_FAILED;
        if (report) *report = local;
        return local.step;
    }

    /* Step 3 and 4 - read SDRAM back and compare byte for byte. */
    probe_cart_read(probe_readback);
    local.direct_crc = launch_crc32(probe_readback, SM_PROBE_SECTOR_SIZE);
    local.first_diff = sm_probe_first_difference(probe_reference, probe_readback,
        SM_PROBE_SECTOR_SIZE);
    if (local.first_diff != SM_PROBE_SECTOR_SIZE) {
        local.step = SM_PROBE_SDRAM_MISMATCH;
        if (report) *report = local;
        return local.step;
    }

    /* Step 5 - the dispatch the real loader depends on. Handing FatFs a cart
       address routes disk_read() to disk_read_sdram() and on to
       cart_card_rd_cart(), which is how the ROM loader will work. */
    if (probe_poison_cart() != 0) {
        local.step = SM_PROBE_SDRAM_UNWRITABLE;
        if (report) *report = local;
        return local.step;
    }
    got = 0;
    fr = f_lseek(file, 0);
    if (fr == FR_OK)
        fr = f_read(file, (void *)(uintptr_t)SM_PROBE_CART_KSEG1, SM_PROBE_SECTOR_SIZE, &got);
    local.fatfs_rc = (int)fr;
    if (fr != FR_OK || got != SM_PROBE_SECTOR_SIZE) {
        local.step = SM_PROBE_DISPATCH_FAILED;
        if (report) *report = local;
        return local.step;
    }
    probe_cart_read(probe_readback);
    local.dispatch_crc = launch_crc32(probe_readback, SM_PROBE_SECTOR_SIZE);
    local.first_diff = sm_probe_first_difference(probe_reference, probe_readback,
        SM_PROBE_SECTOR_SIZE);
    if (local.first_diff != SM_PROBE_SECTOR_SIZE) {
        local.step = SM_PROBE_DISPATCH_MISMATCH;
        if (report) *report = local;
        return local.step;
    }

    (void)f_lseek(file, 0);
    local.step = SM_PROBE_OK;
    if (report) *report = local;
    return local.step;
}
#endif
