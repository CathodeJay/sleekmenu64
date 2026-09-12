/* SPDX-License-Identifier: AGPL-3.0-only */
#include "x7_save_reg.h"

uint32_t sm_x7_gam_cfg_value(sm_save_type_t type) {
    /* Refuse to invent a value for anything outside krikzz's documented set;
       backup RAM off is the safe reading of an unknown save type. */
    return (unsigned)type <= SM_SAVE_TYPE_MAX ? (uint32_t)type : (uint32_t)SM_SAVE_OFF;
}

#ifdef __mips__
#include <libdragon.h>

void sm_x7_apply_save_type(sm_save_type_t type) {
    /* A plain 32-bit store to the PI window, which is how libcart drives every
       X-series register (io_write throughout cart.c). No PI timing change: the
       cartridge default is slower than libcart's tuned __cart_dom1, and slower
       is always safe for a single register write. */
    io_write(SM_X7_REG_GAM_CFG, sm_x7_gam_cfg_value(type));
}
#endif
