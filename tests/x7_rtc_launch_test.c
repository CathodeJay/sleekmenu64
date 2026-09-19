/* SPDX-License-Identifier: AGPL-3.0-only */
/* Exercise the actual backend's ordering, with hardware dependencies stubbed.
   Unused SD/probe functions are discarded by --gc-sections. */
#include "../src/flashcart_x7.c"
#include <assert.h>

static bool clock_ok, save_ok;
static unsigned clock_calls, save_calls, boot_calls, seen_config;
static sm_save_type_t seen_type;

bool sm_x7_rtc_prepare(unsigned config) {
    clock_calls++;
    seen_config = config;
    return clock_ok;
}
const char *sm_x7_rtc_error(void) { return "X7 clock: Joybus stop failed"; }
bool sm_save_sync_arm(const char *path, const uint8_t *header,
    sm_save_type_t type, sm_save_sync_report_t *report) {
    (void)path; (void)header; (void)type; (void)report;
    assert(clock_calls > 0 && clock_ok);
    save_calls++;
    return save_ok;
}
void sm_x7_apply_launch_config(sm_save_type_t type, unsigned config) {
    seen_type = type;
    seen_config = config;
}
void sm_rom_boot(sm_rom_boot_hook hook, bool disk, const uint32_t *cheats) {
    (void)cheats;
    assert(!disk);
    boot_calls++;
    hook();
}

int main(void) {
    uint8_t header[64] = {0};
    sm_save_sync_report_t report;
    char status[96];
    clock_ok = false;
    save_ok = true;
    memset(&report, 0xFF, sizeof(report));
    assert(!x7_arm("sd:/game.z64", header, SM_SAVE_FLASH, SM_SAVE_CFG_RTC, &report));
    assert(save_calls == 0 && boot_calls == 0);
    assert(!report.ran && !report.changed && report.type == SM_SAVE_FLASH);
    assert(!strcmp(report.detail, "X7 clock: Joybus stop failed"));
    assert(!x7_arm("sd:/game.z64", header, SM_SAVE_FLASH, SM_SAVE_CFG_RTC, NULL));
    clock_ok = true;
    assert(x7_arm("sd:/game.z64", header, SM_SAVE_FLASH, SM_SAVE_CFG_RTC, &report));
    assert(save_calls == 1 && seen_config == SM_SAVE_CFG_RTC);
    assert(x7_boot(SM_SAVE_FLASH, SM_SAVE_CFG_RTC, false, NULL, status, sizeof(status)));
    assert(seen_type == SM_SAVE_FLASH && seen_config == SM_SAVE_CFG_RTC);
    /* A subsequent ordinary launch cannot inherit the RTC config. */
    assert(x7_arm("sd:/normal.z64", header, SM_SAVE_EEP4K, 0, &report));
    assert(x7_boot(SM_SAVE_EEP4K, 0, false, NULL, status, sizeof(status)));
    assert(seen_type == SM_SAVE_EEP4K && seen_config == 0);
    save_ok = false;
    assert(!x7_arm("sd:/normal.z64", header, SM_SAVE_EEP4K, 0, &report));
    assert(!x7_boot(SM_SAVE_FLASH, SM_SAVE_CFG_RTC, true, NULL, status, sizeof(status)));
    assert(boot_calls == 2);
    return 0;
}
