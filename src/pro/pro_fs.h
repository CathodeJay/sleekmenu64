/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_PRO_FS_H
#define SLEEKMENU_PRO_FS_H

/* sd:/ on the EverDrive-64 Pro, as a libdragon filesystem driver.

   The Pro's MCU owns the card. It answers open, read, write, seek and list
   over a FIFO, and it holds exactly one file open at a time -- there are no
   handles in the protocol, only "the file". The browser, on the other hand,
   keeps covers.pak open for the whole session and reads the catalog,
   favourites and history around it through ordinary stdio.

   So this driver keeps the handles and the MCU keeps the file. Each stdio
   handle remembers its path, its position and its size; whichever handle is
   read or written next becomes the MCU's file, reopened and repositioned if
   it was not already. A switch costs a close, an open and a seek -- about a
   millisecond, measured -- and a run of reads on one handle costs nothing
   extra. Nothing above this layer can tell.

   The MCU is reached through sm_pro_mcu_t rather than called directly, so
   the handle logic runs on the host against a fake with the same one-file
   rule, where a bug in it is a failed test rather than a wrong cover. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SM_PRO_FS_HANDLES 8u
#define SM_PRO_FS_PATH_MAX 512u
/* The read-ahead window: one command per this many bytes of a file read
   through 1 KiB stdio buffers. A cover sprite fits in it. */
#define SM_PRO_FS_CACHE (16u * 1024u)
/* Window fills at least this long take the fast read when the cartridge
   offers one; shorter ones are not worth its fixed cost. */
#define SM_PRO_FS_FAST_MIN 4096u

/* Open modes, in the MCU's own terms (FA_* in the vendored header). */
enum {
    SM_PRO_MCU_READ = 0x01,
    SM_PRO_MCU_WRITE = 0x02,
    SM_PRO_MCU_CREATE_ALWAYS = 0x08,   /* truncate or create */
    SM_PRO_MCU_OPEN_ALWAYS = 0x10,     /* create if missing, keep if present */
    SM_PRO_MCU_MAKE_PATH = 0x80        /* create missing folders on the way */
};

/* What the driver asks of the cartridge. Every call returns 0 for success
   and the MCU's own code otherwise; paths are card-relative, no leading
   slash. */
typedef struct {
    int (*file_open)(const char *path, unsigned mode);
    int (*file_close)(void);
    int (*file_set_ptr)(uint32_t offset);
    int (*file_read)(void *dst, uint32_t length);
    int (*file_write)(const void *src, uint32_t length);
    /* Size and kind of a path that may not be open; nonzero when absent.
       Called only while the MCU holds no file, because the real cartridge
       answers this by opening the path. */
    int (*file_info)(const char *path, uint32_t *size, bool *is_dir);
    /* Load a folder listing into the MCU; count comes back with it. */
    int (*dir_load)(const char *path, uint16_t *count);
    /* One record of the loaded listing. */
    int (*dir_record)(uint16_t index, char *name, size_t name_size, uint32_t *size, bool *is_dir);
    /* Optional. The same bytes as file_read, by a faster road: the MCU
       copies them into cartridge memory and the console reads them back
       over PI, 4-20 MB/s against the FIFO's 0.7. dst is 8-byte aligned with
       room for length rounded up to 4; afterwards the MCU's file pointer is
       treated as unknown and repositioned before the next transfer. */
    int (*file_read_fast)(void *dst, uint32_t length);
} sm_pro_mcu_t;

/* Reset every handle and point the driver at a cartridge (or a fake). */
void sm_pro_fs_init(const sm_pro_mcu_t *mcu);

/* Release the MCU's file without touching the handles, so a backend can use
   the file protocol directly for a while (a ROM load) and have the next
   stdio read reopen whatever it needs. */
void sm_pro_fs_release_mcu(void);

/* Card-relative form of a path libdragon hands the driver: the stdio prefix
   is already gone, and a leading slash is stripped. Returns false when the
   result would not fit. */
bool sm_pro_fs_normalise(const char *name, char *out, size_t out_size);

#include <dir.h>
#include <system.h>
/* The table for attach_filesystem("sd:/", ...); the host tests drive the
   same table against a fake cartridge. */
filesystem_t *sm_pro_fs(void);

#endif
