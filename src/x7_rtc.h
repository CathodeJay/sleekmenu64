/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_X7_RTC_H
#define SLEEKMENU_X7_RTC_H

#include <stdbool.h>

#ifdef __mips__
/* Before arming a save, with interrupts available for Joybus. A non-RTC
   launch does no clock IO. Temporarily enables the cartridge RTC for Joybus
   writes, then disables it before returning. Never changes the physical clock. */
bool sm_x7_rtc_prepare(unsigned config);
const char *sm_x7_rtc_error(void);
#endif

#endif
