/* SPDX-License-Identifier: AGPL-3.0-only */
#include "system_info.h"

#ifdef __mips__
#include "flashcart.h"
#include <libdragon.h>
#include <string.h>

void sm_system_info(sm_system_info_t *info) {
    const sm_flashcart_t *cart = sm_flashcart();
    tv_type_t tv = get_tv_type();
    memset(info, 0, sizeof(*info));
    info->cartridge = cart->name;
    if (cart->describe) cart->describe(info->firmware, sizeof(info->firmware));
    info->tv = tv == TV_PAL ? "PAL" : tv == TV_MPAL ? "MPAL" : "NTSC";
    info->expansion_pak = is_memory_expanded();
}
#endif
