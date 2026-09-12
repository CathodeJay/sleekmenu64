/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_ROM_BOOT_H
#define SLEEKMENU_ROM_BOOT_H

#include <stdbool.h>
#include <stdint.h>

/* What a backend does at the point of no return, after interrupts are off
   and before the jump: the X7 writes its one save-type register here, the
   Pro needs nothing. */
typedef void (*sm_rom_boot_hook)(void);

#ifdef __mips__
/* Tears down the browser and hands off to the ROM sitting in cartridge
   memory. Does not return: on success the game runs, and on failure the
   console is wedged until it is power-cycled. There is no error path once
   the jump happens, which is why the launch screen is the confirmation.

   from_64dd starts the 64DD IPL the cartridge exposes at the drive's
   address instead of the ROM at the cartridge's. `cheats` is the GameShark
   word list for the boot code's engine, NULL for none; the engine patches
   the target's own IPL3 and keeps itself at the top of RDRAM.

   Preconditions: the ROM (or the IPL) is loaded, the save is armed, and no
   further sd:/ access will be attempted. */
void sm_rom_boot(sm_rom_boot_hook at_point_of_no_return, bool from_64dd, const uint32_t *cheats);
#endif

#endif
