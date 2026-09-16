/* SPDX-License-Identifier: AGPL-3.0-only */
#include "rom_boot.h"

#ifdef __mips__
#include "boot.h"
#include <libdragon.h>

void sm_rom_boot(sm_rom_boot_hook at_point_of_no_return, bool from_64dd, const uint32_t *cheats) {
    boot_params_t params;

    /* Shut the browser down while sd:/ and the display are still coherent.
       boot() quiesces SP, PI, VI and AI itself, but it cannot unwind
       libdragon's own interrupt handlers. */
    joypad_close();
    display_close();
    disable_interrupts();

    /* The backend's last word. On the X7 this selects the incoming game's
       backup RAM and RTC enable state, so nothing may touch the SD card
       after this line. */
    if (at_point_of_no_return) at_point_of_no_return();

    /* The console's own TV type is what IPL3 must be told, whatever region the
       ROM came from, so the handoff always passes it through. */
    params.device_type = from_64dd ? BOOT_DEVICE_TYPE_64DD : BOOT_DEVICE_TYPE_ROM;
    params.tv_type = BOOT_TV_TYPE_PASSTHROUGH;
    params.detect_cic_seed = true;  /* fingerprint the target's own IPL3 */
    params.cic_seed = 0;
    /* The list is read by cheats_install() inside boot(), before the jump;
       with NULL it declines and the game boots clean. A retail IPL3 is
       required for the engine to find its patch point; anything else boots
       without cheats rather than not at all. */
    params.cheat_list = (uint32_t *)cheats;

    boot(&params);

    /* boot() does not return. */
    while (1) {}
}
#endif
