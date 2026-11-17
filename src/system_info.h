/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_SYSTEM_INFO_H
#define SLEEKMENU_SYSTEM_INFO_H

/* What the System screen says about the machine: the cartridge, its
   firmware, the console. ui.c is built on the host for the tests and never
   asks the hardware itself, so it is handed these. system_info.c is the
   console's version; tests/ui_host_test.c has its own. */

#include <stdbool.h>

typedef struct {
    const char *cartridge;   /* the backend's name, "EverDrive-64 Pro" */
    /* One line about the cartridge's firmware, "" when the cartridge has
       nothing to say. */
    char firmware[32];
    const char *tv;          /* "NTSC", "PAL" or "MPAL" */
    bool expansion_pak;
} sm_system_info_t;

void sm_system_info(sm_system_info_t *info);

#endif
