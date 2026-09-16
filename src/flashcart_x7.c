/* SPDX-License-Identifier: AGPL-3.0-only */
/* The EverDrive-64 X-series behind the cartridge interface.

   Nothing here is new: this is what launch.c did directly before the Pro
   existed, moved behind sm_flashcart_t so the launcher stops knowing which
   cart it is on. libcart owns the SD hardware from debug_init_sdfs() onward,
   FatFs streams the ROM straight into cartridge SDRAM, saves move through
   save_io.c, and the stock firmware is told what is pending through
   ED64/sysdata/registry.dat -- all exactly as proven on hardware. */
#include "flashcart.h"

#ifdef __mips__
#include "launch.h"
#include "rom_boot.h"
#include "rom_load.h"
#include "save_sync.h"
#include "x7_probe.h"
#include "x7_save_reg.h"
#include <libdragon.h>
#include "ff.h"
#include "cart.h"
#include <stdio.h>
#include <string.h>

/* FatFs is mounted as its default logical volume by debug_init_sdfs. Its
   native f_open API cannot consume the stdio adapter's "sd:/" prefix. */
static const char *fatfs_relative_path(const char *sdfs_path) {
    static const char prefix[] = "sd:/";
    return !strncmp(sdfs_path, prefix, sizeof(prefix) - 1) ? sdfs_path + sizeof(prefix) - 1 : NULL;
}

/* FatFs is used directly rather than through stdio because the load hands
   f_read a cartridge address; newlib would buffer that through RDRAM. */
static bool open_fat_readonly(const char *sd_path, uint32_t bytes, FIL *file) {
    const char *relative = fatfs_relative_path(sd_path);
    if (!relative) return false;
    if (f_open(file, relative, FA_READ | FA_OPEN_EXISTING) != FR_OK) return false;
    if (file->obj.objsize != bytes) { f_close(file); return false; }
    return true;
}

static uint32_t x7_max(void) { return SM_LAUNCH_MAX_ROM; }

static bool x7_init(char *error, size_t error_size) {
    if (!debug_init_sdfs("sd:/", -1)) {
        if (error && error_size) snprintf(error, error_size, "SD unavailable; library not loaded");
        return false;
    }
    if (cart_type != CART_EDX) {
        if (error && error_size) snprintf(error, error_size, "Not an EverDrive X-series cartridge");
        return false;
    }
    return true;
}

static void x7_flush(sm_save_sync_report_t *report) {
    sm_save_sync_flush(report);
}

static sm_flashcart_load_t x7_load(const char *sd_path, uint32_t bytes, bool byteswap,
    bool verify, sm_flashcart_progress_cb progress, void *context,
    char *status, size_t status_size) {
    FIL file;
    sm_load_report_t report;
    sm_load_step_t step;

    if (cart_type != CART_EDX) {
        if (status && status_size) snprintf(status, status_size, "Not an X-series cartridge");
        return SM_FLASHCART_LOAD_WRONG_CART;
    }
    if (!open_fat_readonly(sd_path, bytes, &file)) {
        if (status && status_size) snprintf(status, status_size, "Could not open the ROM");
        return SM_FLASHCART_LOAD_IO_ERROR;
    }
    step = sm_rom_load(&file, bytes, byteswap, verify, progress, context, &report);
    f_close(&file);
    sm_load_format(&report, status, status_size);
    switch (step) {
        case SM_LOAD_OK: return SM_FLASHCART_LOAD_OK;
        case SM_LOAD_NOT_X7: return SM_FLASHCART_LOAD_WRONG_CART;
        case SM_LOAD_TOO_LARGE: return SM_FLASHCART_LOAD_TOO_LARGE;
        case SM_LOAD_MISMATCH: return SM_FLASHCART_LOAD_MISMATCH;
        default: return SM_FLASHCART_LOAD_IO_ERROR;
    }
}

static bool x7_arm(const char *sd_path, const uint8_t *header, sm_save_type_t type,
    unsigned config, sm_save_sync_report_t *report) {
    (void)config;
    return sm_save_sync_arm(sd_path, header, type, report);
}

/* The one EverDrive register SleekMenu writes, and the only place it is
   written on a launch: inside the handoff, after interrupts are off. The
   region-free config bit is about defeating a cartridge-side region lock,
   which this loader does not impose in the first place. */
static sm_save_type_t pending_save_type;

static void x7_point_of_no_return(void) {
    sm_x7_apply_save_type(pending_save_type);
}

static bool x7_boot(sm_save_type_t type, unsigned config, bool from_disk,
    const uint32_t *cheats, char *status, size_t status_size) {
    /* The menu's ROM header requests RTC initialisation from the stock OS.
       The loaded game inherits that clock; GAM_CFG selects only the save
       type, not RTC. See docs/X7_RTC.md for the hardware validation needed. */
    (void)config;
    if (from_disk) {
        /* The X-series has no drive emulation; the launcher refuses disks
           before getting here, and this is the backstop. */
        if (status && status_size) snprintf(status, status_size, "64DD disks need an EverDrive-64 Pro");
        return false;
    }
    pending_save_type = type;
    sm_rom_boot(x7_point_of_no_return, false, cheats);
    return true;    /* not reached */
}

/* The read-only SD -> SDRAM transport check, kept as a diagnostic. It writes
   only to scratch space well clear of the loaded image and never boots. */
static bool x7_probe(const char *sd_path, char *status, size_t status_size) {
    FIL file;
    sm_probe_report_t report;
    sm_probe_step_t step;
    const char *relative = fatfs_relative_path(sd_path);

    if (cart_type != CART_EDX || !relative) {
        if (status && status_size) snprintf(status, status_size, "Not an X-series cartridge");
        return false;
    }
    if (f_open(&file, relative, FA_READ | FA_OPEN_EXISTING) != FR_OK) {
        if (status && status_size) snprintf(status, status_size, "Could not open the ROM");
        return false;
    }
    step = sm_x7_probe_run(&file, &report);
    f_close(&file);
    sm_probe_format(&report, status, status_size);
    return step == SM_PROBE_OK;
}

const sm_flashcart_t sm_flashcart_x7 = {
    .kind = SM_FLASHCART_X7,
    .name = "EverDrive-64 X7",
    .max_rom_bytes = x7_max,
    .init = x7_init,
    .save_sync_flush = x7_flush,
    .load_rom = x7_load,
    .arm_save = x7_arm,
    .attach_disk = NULL,
    .boot = x7_boot,
    .probe = x7_probe,
};
#else
/* The host has no cartridge; the table exists so the launcher links. */
const sm_flashcart_t sm_flashcart_x7 = { .kind = SM_FLASHCART_X7, .name = "EverDrive-64 X7" };
#endif
