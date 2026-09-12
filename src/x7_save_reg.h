/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_X7_SAVE_REG_H
#define SLEEKMENU_X7_SAVE_REG_H

#include "save_type.h"
#include <stdint.h>

/* The one EverDrive register SleekMenu has to write for itself.
   libcart covers storage only: REG_GAM_CFG appears nowhere in
   third_party/libdragon/src/libcart/cart.c, so there is no library call to
   defer to. Address and semantics come from krikzz/ed64-x-pub,
   ED64-XIO/src/bios.c:
       #define REG_BASE    0x1F800000
       #define REG_GAM_CFG 0x8018
       void bi_game_cfg_set(u8 type) { bi_reg_wr(REG_GAM_CFG, type); }
   The value written is the save-type ID verbatim (SAVE_OFF..SAVE_SRM128K),
   which is why sm_save_type_t carries krikzz's numbering rather than its own.

   Deliberately NOT touched here: EDX_KEY. libcart's edx_init() writes 0xAA55
   once and never re-locks, so the register window is already open; writing
   KEY again — or writing 0 to it — is what broke the previous canary. */
#define SM_X7_REG_GAM_CFG 0x1F808018u

/* The word bi_game_cfg_set() would write for this save type. Pure. */
uint32_t sm_x7_gam_cfg_value(sm_save_type_t type);

#ifdef __mips__
/* Point of no return only: interrupts disabled, no further sd:/ access, boot
   immediately after. Reconfiguring backup RAM under a live FatFs mount is not
   something this is safe for. Nothing calls this yet — boot is still gated. */
void sm_x7_apply_save_type(sm_save_type_t type);
#endif

#endif
