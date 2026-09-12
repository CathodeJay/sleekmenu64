/* SPDX-License-Identifier: AGPL-3.0-only */
#include "rom_load.h"
#include <stdio.h>

uint32_t sm_load_padded_size(uint32_t bytes) {
    uint32_t remainder = bytes % SM_LOAD_SECTOR;
    if (remainder == 0u) return bytes;
    if (bytes > UINT32_MAX - (SM_LOAD_SECTOR - remainder)) return bytes;
    return bytes + (SM_LOAD_SECTOR - remainder);
}

void sm_load_format(const sm_load_report_t *r, char *out, size_t out_size) {
    if (!out || out_size == 0u) return;
    if (!r) { out[0] = '\0'; return; }
    switch (r->step) {
        case SM_LOAD_OK:
            if (r->verified)
                snprintf(out, out_size, "SDRAM LOAD VERIFIED %luKiB crc=%08lX",
                    (unsigned long)(r->bytes / 1024u), (unsigned long)r->crc);
            else
                snprintf(out, out_size, "SDRAM LOAD %luKiB (not verified)",
                    (unsigned long)(r->bytes / 1024u));
            break;
        case SM_LOAD_NOT_X7:
            snprintf(out, out_size, "LOAD SKIPPED: no X-series cartridge; nothing written");
            break;
        case SM_LOAD_TOO_LARGE:
            snprintf(out, out_size, "LOAD SKIPPED: %luKiB exceeds cartridge SDRAM",
                (unsigned long)(r->bytes / 1024u));
            break;
        case SM_LOAD_READ_FAILED:
            snprintf(out, out_size, "LOAD FAIL fr=%d at %luKiB of %luKiB", r->fatfs_rc,
                (unsigned long)(r->first_diff / 1024u), (unsigned long)(r->bytes / 1024u));
            break;
        case SM_LOAD_SHORT_READ:
            snprintf(out, out_size, "LOAD FAIL: short read at %luKiB of %luKiB",
                (unsigned long)(r->first_diff / 1024u), (unsigned long)(r->bytes / 1024u));
            break;
        case SM_LOAD_VERIFY_READ_FAILED:
            snprintf(out, out_size, "VERIFY FAIL fr=%d re-reading at %luKiB", r->fatfs_rc,
                (unsigned long)(r->first_diff / 1024u));
            break;
        case SM_LOAD_MISMATCH:
            snprintf(out, out_size, "SDRAM MISMATCH at 0x%08lX file=%02X sdram=%02X crc=%08lX",
                (unsigned long)r->first_diff, r->file_byte, r->sdram_byte,
                (unsigned long)r->crc);
            break;
        default:
            snprintf(out, out_size, "LOAD: unknown result");
            break;
    }
    out[out_size - 1u] = '\0';
}

#ifdef __mips__
#include "flashcart.h"
#include "launch.h"
#include "cart.h"
#include <libdragon.h>
#include <string.h>

static uint8_t load_file_chunk[SM_LOAD_VERIFY_CHUNK] __attribute__((aligned(16)));
static uint8_t load_cart_chunk[SM_LOAD_VERIFY_CHUNK] __attribute__((aligned(16)));

sm_load_step_t sm_rom_load(FIL *file, uint32_t bytes, bool byteswap, bool verify,
    sm_load_progress_cb progress, void *context, sm_load_report_t *report) {
    sm_load_report_t local;
    FSIZE_t real_size;
    uint32_t offset;
    FRESULT fr;
    UINT got = 0;

    memset(&local, 0, sizeof(local));
    local.bytes = bytes;
    local.padded_bytes = sm_load_padded_size(bytes);
    local.first_diff = UINT32_MAX;
    if (report) *report = local;
    if (!file || !file->obj.fs || bytes == 0u) {
        local.step = SM_LOAD_READ_FAILED;
        if (report) *report = local;
        return local.step;
    }
    if (cart_type != CART_EDX) {
        local.step = SM_LOAD_NOT_X7;
        if (report) *report = local;
        return local.step;
    }
    if (local.padded_bytes > cart_size || bytes > SM_LAUNCH_MAX_ROM) {
        local.step = SM_LOAD_TOO_LARGE;
        if (report) *report = local;
        return local.step;
    }

    /* Byteswapped dumps are un-swapped by the FPGA during the SD to SDRAM
       transfer, at no cost. This is a libcart global, so it is always written
       explicitly: stale state here would corrupt every transfer. */
    cart_card_byteswap = byteswap ? 1 : 0;

    /* FatFs clamps a read to obj.objsize, so a ROM whose length is not a whole
       number of sectors would end on a partial sector and get staged through
       fs->win in RDRAM, which cannot target cartridge space. Widening objsize
       for the load pass keeps every transfer sector-aligned; the tail bytes
       read past end-of-file are cluster padding and land harmlessly above the
       ROM. It is restored before verification so only real bytes are compared. */
    real_size = file->obj.objsize;
    file->obj.objsize = (FSIZE_t)local.padded_bytes;

    fr = f_lseek(file, 0);
    if (fr != FR_OK) {
        file->obj.objsize = real_size;
        local.fatfs_rc = (int)fr;
        local.first_diff = 0u;
        local.step = SM_LOAD_READ_FAILED;
        if (report) *report = local;
        return local.step;
    }

    /* Past this point SleekMenu's own cartridge image is being overwritten.
       Code and data already live in RDRAM, but rom:/ is gone for good. */
    sm_cart_image_overwritten();

    for (offset = 0u; offset < local.padded_bytes; ) {
        uint32_t remaining = local.padded_bytes - offset;
        UINT want = (UINT)(remaining > SM_LOAD_CHUNK ? SM_LOAD_CHUNK : remaining);
        void *destination = (void *)(uintptr_t)(SM_LOAD_CART_KSEG1 + offset);
        got = 0;
        fr = f_read(file, destination, want, &got);
        if (fr != FR_OK) {
            file->obj.objsize = real_size;
            local.fatfs_rc = (int)fr;
            local.first_diff = offset;
            local.step = SM_LOAD_READ_FAILED;
            if (report) *report = local;
            return local.step;
        }
        if (got != want) {
            file->obj.objsize = real_size;
            local.first_diff = offset + (uint32_t)got;
            local.step = SM_LOAD_SHORT_READ;
            if (report) *report = local;
            return local.step;
        }
        offset += want;
        if (progress) progress(offset, local.padded_bytes, false, context);
    }

    file->obj.objsize = real_size;

    if (!verify) {
        cart_card_byteswap = 0;
        local.first_diff = UINT32_MAX;
        local.step = SM_LOAD_OK;
        if (report) *report = local;
        return local.step;
    }

    /* Verification: re-read the file into RDRAM and pull the same range back
       out of SDRAM over PI, comparing byte for byte. memcmp decides pass or
       fail; the CRC is only there to give the status line a number. */
    fr = f_lseek(file, 0);
    if (fr != FR_OK) {
        local.fatfs_rc = (int)fr;
        local.first_diff = 0u;
        local.step = SM_LOAD_VERIFY_READ_FAILED;
        if (report) *report = local;
        return local.step;
    }
    local.crc = 0xFFFFFFFFu;
    for (offset = 0u; offset < bytes; ) {
        uint32_t remaining = bytes - offset;
        UINT want = (UINT)(remaining > SM_LOAD_VERIFY_CHUNK ? SM_LOAD_VERIFY_CHUNK : remaining);
        uint32_t aligned = (want + 15u) & ~15u;
        got = 0;
        fr = f_read(file, load_file_chunk, want, &got);
        if (fr != FR_OK || got != want) {
            local.fatfs_rc = (int)fr;
            local.first_diff = offset + (uint32_t)got;
            local.step = SM_LOAD_VERIFY_READ_FAILED;
            if (report) *report = local;
            return local.step;
        }
        data_cache_hit_writeback_invalidate(load_cart_chunk, aligned);
        dma_read(load_cart_chunk, SM_LOAD_CART_PHYS + offset, aligned);
        data_cache_hit_invalidate(load_cart_chunk, aligned);
        if (memcmp(load_file_chunk, load_cart_chunk, want) != 0) {
            uint32_t i = 0u;
            while (i < want && load_file_chunk[i] == load_cart_chunk[i]) i++;
            local.first_diff = offset + i;
            local.file_byte = load_file_chunk[i];
            local.sdram_byte = load_cart_chunk[i];
            local.crc = ~local.crc;
            local.step = SM_LOAD_MISMATCH;
            if (report) *report = local;
            return local.step;
        }
        local.crc = launch_crc32_update(local.crc, load_file_chunk, want);
        offset += want;
        if (progress) progress(offset, bytes, true, context);
    }
    cart_card_byteswap = 0;
    local.crc = ~local.crc;
    local.first_diff = UINT32_MAX;
    local.verified = true;
    local.step = SM_LOAD_OK;
    if (report) *report = local;
    return local.step;
}
#endif
