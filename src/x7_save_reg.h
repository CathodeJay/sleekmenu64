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
   Save transfers write the save-type ID verbatim (SAVE_OFF..SAVE_SRM128K).
   For launch, OS 3.11 also sets bit 0x1000 when RTC is requested. This bit
   is absent from the older public bios.h; tools/trace_x7_rtc.py is the evidence.

   Deliberately NOT touched here: EDX_KEY. libcart's edx_init() writes 0xAA55
   once and never re-locks, so the register window is already open; writing
   KEY again — or writing 0 to it — is what broke the previous canary. */
#define SM_X7_REG_GAM_CFG 0x1F808018u
#define SM_X7_GAM_CFG_RTC 0x1000u

/* The word bi_game_cfg_set() would write for this save type. Pure. */
uint32_t sm_x7_gam_cfg_value(sm_save_type_t type);
uint32_t sm_x7_launch_cfg_value(sm_save_type_t type, unsigned config);

#ifdef __mips__
/* Save transfers use the plain type with RTC off. No SD transaction may be
   in flight. Launch applies the full config at the point of no return. */
void sm_x7_apply_save_type(sm_save_type_t type);
void sm_x7_apply_launch_config(sm_save_type_t type, unsigned config);
#endif

#endif
