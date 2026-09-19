/* SPDX-License-Identifier: AGPL-3.0-only */
#include "flashcart.h"
#include <stdio.h>
#include <string.h>

static const sm_flashcart_t *active = &sm_flashcart_none;
static bool cart_image_intact = true;

bool sm_cart_image_intact(void) { return cart_image_intact; }
void sm_cart_image_overwritten(void) { cart_image_intact = false; }

/* -- the placeholder ---------------------------------------------------- */

static bool none_init(char *error, size_t error_size) {
    if (error && error_size) snprintf(error, error_size, "No supported cartridge found");
    return false;
}

static void none_flush(sm_save_sync_report_t *report) {
    if (!report) return;
    memset(report, 0, sizeof(*report));
    snprintf(report->detail, sizeof(report->detail), "no cartridge");
}

static sm_flashcart_load_t none_load(const char *sd_path, uint32_t bytes, bool byteswap,
    bool verify, sm_flashcart_progress_cb progress, void *context,
    char *status, size_t status_size) {
    (void)sd_path; (void)bytes; (void)byteswap; (void)verify; (void)progress; (void)context;
    if (status && status_size) snprintf(status, status_size, "No supported cartridge");
    return SM_FLASHCART_LOAD_WRONG_CART;
}

static bool none_arm(const char *sd_path, const uint8_t *header, sm_save_type_t type,
    unsigned config, sm_save_sync_report_t *report) {
    (void)sd_path; (void)header; (void)type; (void)config;
    none_flush(report);
    return false;
}

static bool none_boot(sm_save_type_t type, unsigned config, bool from_disk,
    const uint32_t *cheats, char *status, size_t status_size) {
    (void)type; (void)config; (void)from_disk; (void)cheats;
    if (status && status_size) snprintf(status, status_size, "No supported cartridge");
    return false;
}

static uint32_t none_max(void) { return 0; }

const sm_flashcart_t sm_flashcart_none = {
    .kind = SM_FLASHCART_NONE,
    .name = "no cartridge",
    .max_rom_bytes = none_max,
    .init = none_init,
    .save_sync_flush = none_flush,
    .load_rom = none_load,
    .read_rom = NULL,
    .write_rom = NULL,
    .arm_save = none_arm,
    .attach_disk = NULL,
    .boot = none_boot,
    .probe = NULL,
};

/* -- detection ------------------------------------------------------------ */

const sm_flashcart_t *sm_flashcart_detect(void) {
#ifdef __mips__
    /* The Pro first. Reading its id register is harmless on any cartridge;
       libcart's X-series probe is not harmless on a Pro, where the address
       it writes is the backup RAM window. */
    if (sm_flashcart_pro_present()) active = &sm_flashcart_pro;
    else active = &sm_flashcart_x7;
#else
    active = &sm_flashcart_none;
#endif
    return active;
}

const sm_flashcart_t *sm_flashcart(void) { return active; }
