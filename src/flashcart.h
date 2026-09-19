/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_FLASHCART_H
#define SLEEKMENU_FLASHCART_H

/* The cartridge, behind one interface, so one ROM serves both EverDrives.

   The two carts could hardly be more different underneath. The X7 shows the
   console a raw SD card over its own registers; libcart drives it, libdragon
   mounts FatFs on it, a ROM is streamed sector by sector into cartridge
   SDRAM, saves are moved by the console between battery RAM and files, and
   the stock firmware is told what is pending through ED64/sysdata/registry.dat.
   The Pro shows the console nothing of the kind: an MCU on the cartridge owns
   the card and the filesystem, answers a command protocol over a FIFO, copies
   files straight into cartridge memory on request, and runs the save handlers
   itself -- the console only names the paths.

   What the browser needs from either is the same short list, in the same
   order, and that list is this struct. Everything above it -- the catalog,
   the covers, favourites, history, the launch screen -- reads and writes
   sd:/ through stdio and never learns which cart it is on. The one thing it
   is told is a name for the status line.

   Detection reads the Pro's id register first, because a read is harmless
   on any cart, whereas libcart's X-series probe writes to an address the Pro
   maps as backup RAM. */

#include "save_sync.h"
#include "save_type.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    SM_FLASHCART_NONE = 0,   /* no supported cartridge answered */
    SM_FLASHCART_X7,         /* EverDrive-64 X-series, through libcart */
    SM_FLASHCART_PRO         /* EverDrive-64 Pro, through its MCU protocol */
} sm_flashcart_kind_t;

typedef void (*sm_flashcart_progress_cb)(uint32_t done, uint32_t total, bool verifying,
    void *context);

/* What a load attempt came to. The status text is the backend's own account
   of it, ready for the launch screen. */
typedef enum {
    SM_FLASHCART_LOAD_OK = 0,
    SM_FLASHCART_LOAD_WRONG_CART,
    SM_FLASHCART_LOAD_TOO_LARGE,
    SM_FLASHCART_LOAD_IO_ERROR,
    SM_FLASHCART_LOAD_MISMATCH
} sm_flashcart_load_t;

typedef struct {
    sm_flashcart_kind_t kind;
    const char *name;            /* "EverDrive-64 X7", for the status line */
    /* The largest ROM the cart can hold, once it has been asked. */
    uint32_t (*max_rom_bytes)(void);

    /* Mount sd:/ and whatever else the cart needs before the first file is
       read. False with a message means the browser runs with no library. */
    bool (*init)(char *error, size_t error_size);

    /* Menu startup: whatever the previous game left in the cartridge's save
       memory goes back to the card. The X7 does this from the registry; the
       Pro's stock OS has already done it by the time the browser runs. */
    void (*save_sync_flush)(sm_save_sync_report_t *report);

    /* The whole ROM into cartridge memory at offset 0. `sd_path` is the file
       as it was opened, "sd:/ROMS/...". Overwrites the browser's own image by
       design; sm_cart_image_intact() reports that afterwards. */
    sm_flashcart_load_t (*load_rom)(const char *sd_path, uint32_t bytes, bool byteswap,
        bool verify, sm_flashcart_progress_cb progress, void *context,
        char *status, size_t status_size);

    /* Cartridge memory as the load left it, before the jump: `bytes` from
       `offset` of the ROM area into `dst` (a multiple of 8, aligned), and
       `bytes` from `src` into it. This is how the boot code's checksum is
       summed and, when the header's words are stale, corrected in place
       (launch.c). A write is confirmed by the caller reading back, so a
       cart whose memory the console cannot write into fails that read-back
       rather than anything worse. NULL on a cart without the access. */
    bool (*read_rom)(uint32_t offset, void *dst, uint32_t bytes);
    bool (*write_rom)(uint32_t offset, const void *src, uint32_t bytes);

    /* Between the load and the jump: put the game's save where the cart
       will find it and record what is pending. False stops the boot. */
    bool (*arm_save)(const char *sd_path, const uint8_t *header, sm_save_type_t type,
        unsigned config, sm_save_sync_report_t *report);

    /* 64DD, on a cart that emulates the drive; NULL on one that does not.
       Attaches the disk image the cart will serve, and when ipl_sd_path is
       given -- a disk-only game -- copies that IPL into the cart's IPL area
       first, so the boot below can start from it. Called after arm_save and
       before boot; false with a status stops the launch. */
    bool (*attach_disk)(const char *disk_sd_path, const char *ipl_sd_path, uint32_t ipl_bytes,
        sm_flashcart_progress_cb progress, void *context, char *status, size_t status_size);

    /* Tear the browser down and hand off, from the ROM or -- from_disk --
       from the 64DD IPL. `cheats` is the GameShark list for the boot code's
       engine (code word, value word, ... 0, 0), or NULL for none. Returns
       only when the cart refused the handoff before the point of no return,
       with a status saying why. */
    bool (*boot)(sm_save_type_t type, unsigned config, bool from_disk, const uint32_t *cheats,
        char *status, size_t status_size);

    /* The read-only transport diagnostic, where the cart has one; NULL where
       it has not. */
    bool (*probe)(const char *sd_path, char *status, size_t status_size);
} sm_flashcart_t;

/* Ask each cart in turn; the first that answers is the one for the session. */
const sm_flashcart_t *sm_flashcart_detect(void);
/* The cart chosen by sm_flashcart_detect(), or a NONE placeholder that
   refuses everything, so callers need not check for NULL. */
const sm_flashcart_t *sm_flashcart(void);

/* The two backends. Each is a static table in its own file. */
extern const sm_flashcart_t sm_flashcart_x7;
extern const sm_flashcart_t sm_flashcart_pro;
extern const sm_flashcart_t sm_flashcart_none;

/* Whether a Pro is answering on its id register. Implemented by the Pro
   backend; the only thing detection needs from it before choosing. */
bool sm_flashcart_pro_present(void);

/* False once cartridge memory has been overwritten by a load. The browser
   keeps running from RDRAM, but its own ROM image and the DragonFS holding
   the font are gone, so rom:/ must not be touched again until reset. Both
   backends latch it before the first byte lands. */
bool sm_cart_image_intact(void);
void sm_cart_image_overwritten(void);

#endif
