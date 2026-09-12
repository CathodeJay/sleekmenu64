/* SPDX-License-Identifier: AGPL-3.0-only */
/* libdragon's dir.h, the parts the browser uses, for the host build. */
#ifndef SLEEKMENU_TEST_DIR_H
#define SLEEKMENU_TEST_DIR_H
#include <stdint.h>
#define DT_REG 1
#define DT_DIR 2
typedef struct {
    char d_name[256];
    int d_type;
    int64_t d_size;
    uint32_t d_cookie;
} dir_t;
int dir_findfirst(const char *path, dir_t *entry);
int dir_findnext(const char *path, dir_t *entry);
#endif
