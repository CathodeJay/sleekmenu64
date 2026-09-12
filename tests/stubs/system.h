/* SPDX-License-Identifier: AGPL-3.0-only */
/* libdragon's system.h, the filesystem driver contract, for the host build.
   Same members in the same order as the real header, so a driver written
   with designated initialisers compiles identically on both. */
#ifndef SLEEKMENU_TEST_SYSTEM_H
#define SLEEKMENU_TEST_SYSTEM_H
#include <stdint.h>
#include <sys/stat.h>
#include <sys/types.h>
#include "dir.h"
typedef struct {
    void *(*open)(char *name, int flags);
    int (*fstat)(void *file, struct stat *st);
    int (*stat)(char *name, struct stat *st);
    int (*lseek)(void *file, int ptr, int dir);
    int (*read)(void *file, uint8_t *ptr, int len);
    int (*write)(void *file, uint8_t *ptr, int len);
    int (*close)(void *file);
    int (*unlink)(char *name);
    int (*findfirst)(char *path, dir_t *dir);
    int (*findnext)(dir_t *dir);
    int (*findnext2)(const char *path, dir_t *dir);
    int (*ftruncate)(void *file, int length);
    int (*mkdir)(char *path, mode_t mode);
    int (*ioctl)(void *file, unsigned long cmd, void *argp);
} filesystem_t;
int attach_filesystem(const char *const prefix, filesystem_t *filesystem);
#endif
