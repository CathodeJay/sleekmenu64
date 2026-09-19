/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef TEST_X7_FF_H
#define TEST_X7_FF_H
#include <stdint.h>
typedef struct { struct { uint32_t objsize; } obj; } FIL;
#define FR_OK 0
#define FA_READ 1
#define FA_OPEN_EXISTING 0
int f_open(FIL *file, const char *path, int mode);
int f_close(FIL *file);
#endif
