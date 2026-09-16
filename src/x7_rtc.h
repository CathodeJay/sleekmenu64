/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_X7_RTC_H
#define SLEEKMENU_X7_RTC_H

#include <stdbool.h>

#ifdef __mips__
/* Before arming a save, with interrupts available for Joybus. A non-RTC
   launch does no clock IO. Does not change the physical clock or GAM_CFG. */
bool sm_x7_rtc_prepare(unsigned config);
#endif

#endif
