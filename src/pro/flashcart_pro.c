/* SPDX-License-Identifier: AGPL-3.0-only */
/* The EverDrive-64 Pro behind the cartridge interface.

   Every step was proven on a real cartridge, in this order: the MCU is
   asked its id before anything is written, the FIFO is drained before the
   first command,
   the stock firmware's game mapping is stopped before the card is touched,
   a ROM goes into cartridge memory with the MCU's own file-to-memory copy,
   the paths and the configuration are set with the device stopped, and the
   device is started again just before the jump.

   Saves need nothing from the browser on this cart. The MCU runs the save
   handler itself, caches the backup RAM to ED64/sysdata/cache_brm.dat, and
   the stock firmware writes that cache out as a file the next time it boots
   -- which it always does before this browser, because this browser is a
   ROM the stock firmware launches. So the flush is a no-op that says so, and
   arming a save is naming the file the MCU should use.

   This is one of two files allowed to include the vendored krikzz headers
   (the other is the probe); their types.h defines u8/u32 as macros and its
   errors.h redefines FatFs's FR_* names, neither of which may leak. */
#include "flashcart.h"

#ifdef __mips__
#include "launch.h"
#include "rom_boot.h"
#include "save_io.h"
#include "pro_fs.h"
#include "appmain.h"
#include <stdio.h>
#include <string.h>

/* A ROM is copied in pieces so the launch screen can show it moving; the
   MCU's copy runs at 4-20 MB/s, so a megabyte is a tick, not a stall. */
#define PRO_LOAD_CHUNK (1024u * 1024u)
/* Cartridge memory the fast file read bounces through: 2 MB in, clear of
   the browser's own image below it, and the exact offset the probe copied a
   megabyte to and read back intact. A ROM load overwrites it, and nothing
   reads a file between a load and the jump. */
#define PRO_SCRATCH_FCI 0x200000u
/* Records per listing request and the longest name asked for: eight of
   these is under the FIFO's 2 KB, the shape the probe measured as fast. */
#define PRO_DIR_BATCH 8u
#define PRO_NAME_MAX 200u

/* -- the MCU, as the filesystem driver sees it ----------------------------- */

/* The driver's open modes are the MCU's, bit for bit, so they pass through. */
_Static_assert(SM_PRO_MCU_READ == FA_READ, "mode");
_Static_assert(SM_PRO_MCU_WRITE == FA_WRITE, "mode");
_Static_assert(SM_PRO_MCU_CREATE_ALWAYS == FA_CREATE_ALWAYS, "mode");
_Static_assert(SM_PRO_MCU_OPEN_ALWAYS == FA_OPEN_ALWAYS, "mode");
_Static_assert(SM_PRO_MCU_MAKE_PATH == FS_MAKEPATH, "mode");

static int mcu_file_open(const char *path, unsigned mode) {
    return (int)ed_fs_file_open((u8 *)path, (u8)mode);
}

static int mcu_file_close(void) { return (int)ed_fs_file_close(); }

static int mcu_file_set_ptr(uint32_t offset) { return (int)ed_fs_file_set_ptr((u32)offset); }

static int mcu_file_read(void *dst, uint32_t length) {
    return (int)ed_fs_file_read(dst, (u32)length);
}

static int mcu_file_write(const void *src, uint32_t length) {
    return (int)ed_fs_file_write((void *)src, (u32)length);
}

/* The FIFO moves 0.7 MB/s with an acknowledgement every kilobyte; the MCU's
   file-to-memory copy moves 4-20 MB/s and PI reads it back at 5. So a window
   is copied into scratch cartridge memory and pulled out over PI -- both
   halves of that are what the probe measured. The PI read is rounded up to
   whole words; the driver's window has the room. */
static int mcu_file_read_fast(void *dst, uint32_t length) {
    u8 resp = ed_fs_file_read_fci(PRO_SCRATCH_FCI, (u32)length);
    if (resp) return (int)resp;
    pi_rd(dst, ADDR_PI_ROM + PRO_SCRATCH_FCI, (u32)((length + 3u) & ~3u));
    return 0;
}

/* Size of a file that is not open. The library has a one-command form of
   this (ed_fs_file_info); the probe never ran it, and a command whose reply
   is not what the console expects leaves the FIFO out of step with no way
   back. Open, ask, close is three commands the probe did run, so that is
   what is used until a probe proves the other. A folder does not open as a
   file, so it reads as absent here, which is all the browser asks. The
   driver has given the MCU's file up before calling this. */
static int mcu_file_info(const char *path, uint32_t *size, bool *is_dir) {
    u8 resp = ed_fs_file_open((u8 *)path, FA_READ);
    if (resp) return (int)resp;
    *size = (uint32_t)ed_fs_file_available();
    *is_dir = false;
    resp = ed_fs_file_close();
    return (int)resp;
}

/* Directory records come from the MCU in batches, because one FIFO round
   trip per record is what made the probe's 178-entry folder take a quarter
   of a second. A batch is always drained in full: a record left in the FIFO
   would shift every reply after it. */
typedef struct {
    u8 name[PRO_NAME_MAX + 1u];
    u32 size;
    bool is_dir;
} dir_record_t;

static dir_record_t dir_batch[PRO_DIR_BATCH];
static uint16_t dir_batch_start;
static uint16_t dir_batch_count;
static uint16_t dir_count;

static int mcu_dir_load(const char *path, uint16_t *count) {
    u16 size = 0;
    u8 resp = ed_fs_dir_load((u8 *)path, DIR_OPT_SORTED);
    dir_batch_count = 0;
    if (resp) return (int)resp;
    ed_fs_dir_get_size(&size);
    dir_count = (uint16_t)size;
    *count = dir_count;
    return 0;
}

static int mcu_dir_record(uint16_t index, char *name, size_t name_size, uint32_t *size,
    bool *is_dir) {
    const dir_record_t *record;
    if (index >= dir_count) return -1;
    if (dir_batch_count == 0 || index < dir_batch_start ||
        index >= dir_batch_start + dir_batch_count) {
        uint16_t want = (uint16_t)(dir_count - index);
        uint16_t i;
        if (want > PRO_DIR_BATCH) want = PRO_DIR_BATCH;
        ed_fs_dir_get_recs((u16)index, (u16)want, (u16)PRO_NAME_MAX);
        for (i = 0; i < want; i++) {
            FileInfo info;
            u8 resp;
            memset(&info, 0, sizeof(info));
            info.file_name = dir_batch[i].name;
            resp = ed_fs_rx_next_rec(&info);
            if (resp) {
                /* The MCU stopped the batch short; what it sent is kept,
                   what it did not is asked for again next time. */
                dir_batch_start = index;
                dir_batch_count = i;
                if (i == 0) return (int)resp;
                break;
            }
            dir_batch[i].size = info.size;
            dir_batch[i].is_dir = info.is_dir != 0;
        }
        if (i == want) {
            dir_batch_start = index;
            dir_batch_count = want;
        }
        if (index >= dir_batch_start + dir_batch_count) return -1;
    }
    record = &dir_batch[index - dir_batch_start];
    snprintf(name, name_size, "%s", (const char *)record->name);
    *size = (uint32_t)record->size;
    *is_dir = record->is_dir;
    return 0;
}

static const sm_pro_mcu_t mcu = {
    .file_open = mcu_file_open,
    .file_close = mcu_file_close,
    .file_set_ptr = mcu_file_set_ptr,
    .file_read = mcu_file_read,
    .file_write = mcu_file_write,
    .file_info = mcu_file_info,
    .dir_load = mcu_dir_load,
    .dir_record = mcu_dir_record,
    .file_read_fast = mcu_file_read_fast,
};

/* -- the backend ------------------------------------------------------------ */

static uint32_t max_rom_bytes;   /* what the MCU reported at startup */
static uint32_t loaded_bytes;    /* the ROM now in cartridge memory, for arming */
static bool swap_on;             /* the cartridge is un-swapping writes */
static DevCfg armed_cfg;         /* what set_cfg was last sent, for the disk to amend */
static bool armed;               /* arm or attach has configured the device */

/* The swap setting is a command the probe never sent, so a session that
   only ever loads native dumps never sends it either; it is written only
   to turn on for a byteswapped dump and to turn off again afterwards. */
static void set_swap(bool on) {
    if (on == swap_on) return;
    ed_dev_wr_swap(on ? 1 : 0);
    swap_on = on;
}

bool sm_flashcart_pro_present(void) {
    u32 id = ed_get_cart_id();
    return (id >> 16) == 0xED64ul && (id & 0xFFul) == DEVID_ED64PRO;
}

static uint32_t pro_max(void) { return max_rom_bytes; }

static void pro_fail(char *out, size_t out_size, const char *what, unsigned code) {
    if (out && out_size) snprintf(out, out_size, "Pro: %s (0x%02X)", what, code);
}

static bool pro_init(char *error, size_t error_size) {
    u8 resp;
    u32 info[1] = { INFS_MAX_ROM_SIZE };

    /* Whatever the stock firmware left in the FIFO goes first, or every
       reply from here on is shifted by it. */
    ed_fifo_flush();
    resp = ed_check_status();
    if (resp) { pro_fail(error, error_size, "MCU did not answer", resp); return false; }
    /* The firmware started this browser as a game; that mapping ends now,
       the way the probe did it, before the card is asked anything. */
    resp = ed_init_hw();
    if (resp) { pro_fail(error, error_size, "device would not stop", resp); return false; }
    resp = ed_fs_init();
    if (resp) { pro_fail(error, error_size, "SD card unavailable", resp); return false; }
    ed_sys_get_inf(info, 1);
    max_rom_bytes = (uint32_t)info[0];
    if (max_rom_bytes == 0u || max_rom_bytes > SIZE_RAM) max_rom_bytes = SM_LAUNCH_MAX_ROM;

    sm_pro_fs_init(&mcu);
    if (attach_filesystem("sd:/", sm_pro_fs()) != 0) {
        pro_fail(error, error_size, "could not mount sd:/", 0);
        return false;
    }
    loaded_bytes = 0;
    return true;
}

static void pro_flush(sm_save_sync_report_t *report) {
    if (!report) return;
    memset(report, 0, sizeof(*report));
    snprintf(report->detail, sizeof(report->detail), "Pro: the stock OS syncs saves");
}

/* "sd:/ROMS/x.z64" -> "ROMS/x.z64", the form the MCU takes. */
static bool card_relative(const char *sd_path, char *out, size_t out_size) {
    static const char prefix[] = "sd:/";
    if (!sd_path) return false;
    if (!strncmp(sd_path, prefix, sizeof(prefix) - 1)) sd_path += sizeof(prefix) - 1;
    return sm_pro_fs_normalise(sd_path, out, out_size);
}

static u8 header_back[64] __attribute__((aligned(8)));

/* The MCU's open file into cartridge memory at `fci`, a megabyte at a time
   with the file positioned before every piece. 0 or the MCU's code; on
   failure `*failed_at` is how far it got. */
static u8 copy_to_cart(u32 fci, uint32_t bytes, sm_flashcart_progress_cb progress, void *context,
    uint32_t *failed_at) {
    uint32_t offset;
    for (offset = 0u; offset < bytes; ) {
        uint32_t remaining = bytes - offset;
        uint32_t want = remaining > PRO_LOAD_CHUNK ? PRO_LOAD_CHUNK : remaining;
        /* Positioned before every piece rather than trusting the file
           pointer to advance across copies: one cheap command per megabyte
           buys independence from a detail the probe did not test. */
        u8 resp = ed_fs_file_set_ptr((u32)offset);
        if (!resp) resp = ed_fs_file_read_fci(fci + (u32)offset, (u32)want);
        if (resp) { *failed_at = offset; return resp; }
        offset += want;
        if (progress) progress(offset, bytes, false, context);
    }
    return 0;
}

static sm_flashcart_load_t pro_load(const char *sd_path, uint32_t bytes, bool byteswap,
    bool verify, sm_flashcart_progress_cb progress, void *context,
    char *status, size_t status_size) {
    char path[SM_PRO_FS_PATH_MAX];
    u8 resp;
    uint32_t offset;
    u32 size;

    if (!card_relative(sd_path, path, sizeof(path)) || bytes == 0u) {
        if (status && status_size) snprintf(status, status_size, "Could not open the ROM");
        return SM_FLASHCART_LOAD_IO_ERROR;
    }
    if (bytes > max_rom_bytes) {
        if (status && status_size)
            snprintf(status, status_size, "LOAD SKIPPED: %luKiB exceeds the cartridge",
                (unsigned long)(bytes / 1024u));
        return SM_FLASHCART_LOAD_TOO_LARGE;
    }

    /* The file protocol is used directly from here: the driver gives up
       whatever it had open so the MCU's one file is this ROM. */
    sm_pro_fs_release_mcu();
    resp = ed_fs_file_open((u8 *)path, FA_READ);
    if (resp) { pro_fail(status, status_size, "could not open the ROM", resp); return SM_FLASHCART_LOAD_IO_ERROR; }
    size = ed_fs_file_available();
    if (size != (u32)bytes) {
        ed_fs_file_close();
        if (status && status_size) snprintf(status, status_size, "ROM size changed on the card");
        return SM_FLASHCART_LOAD_IO_ERROR;
    }
    resp = ed_fs_file_set_ptr(0);
    if (resp) { ed_fs_file_close(); pro_fail(status, status_size, "could not seek", resp); return SM_FLASHCART_LOAD_IO_ERROR; }

    /* Past this point the browser's own cartridge image is being
       overwritten. Code and data already live in RDRAM; rom:/ is gone. */
    sm_cart_image_overwritten();
    loaded_bytes = 0;
    armed = false;

    /* A byteswapped dump is un-swapped by the cartridge as the MCU writes
       it, so the file on the card is never rewritten. Off again on every
       exit: stale state here would corrupt every load after it. */
    set_swap(byteswap);
    resp = copy_to_cart(ADDR_FCI_ROM, bytes, progress, context, &offset);
    set_swap(false);
    if (resp) {
        ed_fs_file_close();
        if (status && status_size)
            snprintf(status, status_size, "LOAD FAIL 0x%02X at %luKiB of %luKiB", resp,
                (unsigned long)(offset / 1024u), (unsigned long)(bytes / 1024u));
        return SM_FLASHCART_LOAD_IO_ERROR;
    }

    /* The first bytes back out over PI must be a native header, whatever
       the file was: this is the only check on the swap, and a cheap check
       that the copy landed at offset 0 at all. */
    pi_rd(header_back, ADDR_PI_ROM, sizeof(header_back));
    if (header_back[0] != 0x80 || header_back[1] != 0x37 || header_back[2] != 0x12 ||
        header_back[3] != 0x40) {
        ed_fs_file_close();
        if (status && status_size)
            snprintf(status, status_size, "CART MISMATCH: header reads %02X%02X%02X%02X%s",
                header_back[0], header_back[1], header_back[2], header_back[3],
                byteswap ? " after swap" : "");
        return SM_FLASHCART_LOAD_MISMATCH;
    }

    if (verify && !byteswap) {
        /* The MCU checksums both ends itself: the file as it reads it back
           from the card, and cartridge memory as it now stands. Base 0 on
           both sides is the standard CRC32. */
        u32 file_crc = 0, cart_crc = 0;
        resp = ed_fs_file_set_ptr(0);
        if (!resp) resp = ed_fs_file_crc((u32)bytes, &file_crc);
        if (resp) {
            ed_fs_file_close();
            pro_fail(status, status_size, "could not checksum the file", resp);
            return SM_FLASHCART_LOAD_IO_ERROR;
        }
        if (progress) progress(bytes / 2u, bytes, true, context);
        ed_fci_crc(ADDR_FCI_ROM, (u32)bytes, &cart_crc);
        if (progress) progress(bytes, bytes, true, context);
        ed_fs_file_close();
        if (file_crc != cart_crc) {
            if (status && status_size)
                snprintf(status, status_size, "CART MISMATCH file=%08lX cart=%08lX",
                    (unsigned long)file_crc, (unsigned long)cart_crc);
            return SM_FLASHCART_LOAD_MISMATCH;
        }
        loaded_bytes = bytes;
        if (status && status_size)
            snprintf(status, status_size, "CART LOAD VERIFIED %luKiB crc=%08lX",
                (unsigned long)(bytes / 1024u), (unsigned long)cart_crc);
        return SM_FLASHCART_LOAD_OK;
    }

    ed_fs_file_close();
    loaded_bytes = bytes;
    if (status && status_size)
        snprintf(status, status_size, "CART LOAD %luKiB (%s)", (unsigned long)(bytes / 1024u),
            byteswap ? "swapped; header checked" : "not verified");
    return SM_FLASHCART_LOAD_OK;
}

/* Cartridge memory after a load: read over the PI, as the header check
   above does; written through the MCU's own memory write, which is how the
   Pro takes anything into its memory. */
static bool pro_read_rom(uint32_t offset, void *dst, uint32_t bytes) {
    if (loaded_bytes == 0u) return false;
    pi_rd(dst, ADDR_PI_ROM + offset, (u32)bytes);
    return true;
}

static bool pro_write_rom(uint32_t offset, const void *src, uint32_t bytes) {
    if (loaded_bytes == 0u) return false;
    ed_fci_wr(ADDR_FCI_ROM + offset, (void *)src, (u32)bytes);
    return true;
}

static u32 bram_type_of(sm_save_type_t type) {
    switch (type) {
        case SM_SAVE_EEP4K: return DEV_BRM_EEP4K;
        case SM_SAVE_EEP16K: return DEV_BRM_EEP16K;
        case SM_SAVE_SRM32K: return DEV_BRM_SRM32K;
        case SM_SAVE_SRM96K: return DEV_BRM_SRM96K;
        case SM_SAVE_FLASH: return DEV_BRM_FLASH;
        case SM_SAVE_SRM128K: return DEV_BRM_SRM128K;
        case SM_SAVE_OFF: default: return DEV_BRM_OFF;
    }
}

/* The stock firmware's own naming, read back from it by the probe: the
   game is "/ROMS/x.z64", its folder is "ed64/gamedata/x.z64", and the save
   inside that folder is bram.<eep|srm|fla>. Nothing is invented here, so a
   game saved from either menu is found by the other. */
static bool pro_paths(const char *sd_path, sm_save_type_t type, char *gpak, size_t gpak_size,
    char *gdata, size_t gdata_size, char *bram, size_t bram_size) {
    char relative[SM_PRO_FS_PATH_MAX];
    const char *filename;
    const char *extension = sm_save_extension(type);
    if (!card_relative(sd_path, relative, sizeof(relative))) return false;
    filename = strrchr(relative, '/');
    filename = filename ? filename + 1 : relative;
    if (!*filename) return false;
    if (snprintf(gpak, gpak_size, "/%s", relative) >= (int)gpak_size) return false;
    if (snprintf(gdata, gdata_size, "ed64/gamedata/%s", filename) >= (int)gdata_size) return false;
    if (extension) {
        if (snprintf(bram, bram_size, "%s/bram%s", gdata, extension) >= (int)bram_size) return false;
    } else {
        bram[0] = '\0';
    }
    return true;
}

static bool pro_arm(const char *sd_path, const uint8_t *header, sm_save_type_t type,
    unsigned config, sm_save_sync_report_t *report) {
    static char gpak[SM_PRO_FS_PATH_MAX + 2u];
    static char gdata[SM_PRO_FS_PATH_MAX + 16u];
    static char bram[SM_PRO_FS_PATH_MAX + 32u];
    DevCfg cfg;
    u8 resp;
    (void)header;

    if (report) { memset(report, 0, sizeof(*report)); report->type = type; }
    if (loaded_bytes == 0u) {
        if (report) snprintf(report->detail, sizeof(report->detail), "Pro: nothing loaded");
        return false;
    }
    if (!pro_paths(sd_path, type, gpak, sizeof(gpak), gdata, sizeof(gdata), bram, sizeof(bram))) {
        if (report) snprintf(report->detail, sizeof(report->detail), "Pro: ROM path too long");
        return false;
    }

    /* The device is already stopped since startup; stopping it again costs
       nothing and is the state set_path and set_cfg are documented for. */
    resp = ed_dev_stop(0);
    if (!resp) resp = ed_dev_set_path((u8 *)gpak, DEV_PATH_GPAK);
    if (!resp) resp = ed_dev_set_path((u8 *)gdata, DEV_PATH_GDATA);
    /* No save, no save path: with the backup type off the MCU runs no
       handler, and an empty path is a message the probe never sent. */
    if (!resp && bram[0]) resp = ed_dev_set_path((u8 *)bram, DEV_PATH_BRM);
    if (resp) {
        if (report) snprintf(report->detail, sizeof(report->detail), "Pro: set_path failed (0x%02X)", resp);
        return false;
    }
    memset(&cfg, 0, sizeof(cfg));
    cfg.brom_type = DEV_ROM_GPAK;
    cfg.gpak_size = (u32)loaded_bytes;
    cfg.brm_size = (u32)sm_save_bytes(type);
    cfg.brm_type = bram_type_of(type);
    cfg.rtc_mode = (config & SM_SAVE_CFG_RTC) ? DEV_RTCMODE_STD : DEV_RTCMODE_OFF;
    cfg.dd_en = 0;
    cfg.gpak_wren = 0;
    cfg.gpak_key = 0;
    resp = ed_dev_set_cfg(&cfg);
    if (resp) {
        if (report) snprintf(report->detail, sizeof(report->detail), "Pro: set_cfg failed (0x%02X)", resp);
        return false;
    }
    armed_cfg = cfg;
    armed = true;
    if (report) {
        report->ran = type != SM_SAVE_OFF;
        snprintf(report->detail, sizeof(report->detail), "Pro: %s -> %s",
            sm_save_type_name(type), bram[0] ? bram : "no save file");
    }
    return true;
}

/* 64DD. The cartridge emulates the drive itself: the MCU serves sectors out
   of the .ndd named as DEV_PATH_DISK and the FPGA answers the drive's
   registers, once dd_en is set. A disk-only game boots from the drive's IPL,
   which the stock firmware keeps in ED64/64ddipl and which goes into the
   cartridge's IPL area (ADDR_FCI_IPL4) rather than the ROM area; a cartridge
   game with a disk beside it keeps the ROM configuration arm_save sent and
   gains the disk. The drive has a clock the games read, so the RTC is on.

   None of this has run on hardware yet: the disk handler, the IPL mapping and
   the boot device flag are krikzz's definitions read straight, and pro_boot
   checks the one thing it can -- that the IPL is visible where the boot code
   will look -- before it jumps. */
static bool pro_attach_disk(const char *disk_sd_path, const char *ipl_sd_path, uint32_t ipl_bytes,
    sm_flashcart_progress_cb progress, void *context, char *status, size_t status_size) {
    static char disk[SM_PRO_FS_PATH_MAX];
    static char ipl[SM_PRO_FS_PATH_MAX];
    static char gdata[SM_PRO_FS_PATH_MAX + 16u];
    u8 resp;

    if (!card_relative(disk_sd_path, disk, sizeof(disk))) {
        if (status && status_size) snprintf(status, status_size, "Pro: disk path too long");
        return false;
    }
    if (ipl_sd_path) {
        const char *filename;
        u32 size;
        uint32_t failed_at = 0;
        if (!card_relative(ipl_sd_path, ipl, sizeof(ipl)) || ipl_bytes == 0u ||
            ipl_bytes > SM_DISK_IPL_MAX_BYTES) {
            if (status && status_size) snprintf(status, status_size, "Pro: bad IPL");
            return false;
        }
        sm_pro_fs_release_mcu();
        resp = ed_fs_file_open((u8 *)ipl, FA_READ);
        if (resp) { pro_fail(status, status_size, "could not open the IPL", resp); return false; }
        size = ed_fs_file_available();
        if (size != (u32)ipl_bytes) {
            ed_fs_file_close();
            if (status && status_size) snprintf(status, status_size, "IPL size changed on the card");
            return false;
        }
        set_swap(false);
        resp = copy_to_cart(ADDR_FCI_IPL4, ipl_bytes, progress, context, &failed_at);
        ed_fs_file_close();
        if (resp) {
            if (status && status_size)
                snprintf(status, status_size, "IPL LOAD FAIL 0x%02X at %luKiB", resp,
                    (unsigned long)(failed_at / 1024u));
            return false;
        }
        /* A disk-only game: no ROM was armed, so the device is configured
           here from scratch. The disk's own folder under gamedata follows the
           firmware's per-game convention. */
        filename = strrchr(disk, '/');
        filename = filename ? filename + 1 : disk;
        snprintf(gdata, sizeof(gdata), "ed64/gamedata/%s", filename);
        resp = ed_dev_stop(0);
        if (!resp) resp = ed_dev_set_path((u8 *)gdata, DEV_PATH_GDATA);
        if (resp) { pro_fail(status, status_size, "set_path failed", resp); return false; }
        memset(&armed_cfg, 0, sizeof(armed_cfg));
        armed_cfg.brom_type = DEV_ROM_IPL;
        armed_cfg.brm_type = DEV_BRM_OFF;
        loaded_bytes = 0;
    } else if (!armed) {
        if (status && status_size) snprintf(status, status_size, "Pro: no game armed for the disk");
        return false;
    }
    resp = ed_dev_set_path((u8 *)disk, DEV_PATH_DISK);
    if (resp) { pro_fail(status, status_size, "set_path disk failed", resp); return false; }
    armed_cfg.dd_en = 1;
    armed_cfg.rtc_mode = DEV_RTCMODE_STD;
    resp = ed_dev_set_cfg(&armed_cfg);
    if (resp) { pro_fail(status, status_size, "set_cfg failed", resp); return false; }
    armed = true;
    if (status && status_size)
        snprintf(status, status_size, "64DD %s attached%s", disk, ipl_sd_path ? "; IPL in place" : "");
    return true;
}

static bool pro_boot(sm_save_type_t type, unsigned config, bool from_disk,
    const uint32_t *cheats, char *status, size_t status_size) {
    u8 resp;
    (void)type; (void)config;
    /* The MCU takes over the save handler and the game's mapping here; the
       probe did this with interrupts still on and the FIFO still usable, so
       the browser is torn down afterwards, not before. */
    resp = ed_dev_start();
    if (resp) { pro_fail(status, status_size, "dev_start failed", resp); return false; }
    if (from_disk) {
        /* The boot code will read IPL3 from the drive's address. If the IPL
           is not there, a jump is a black screen; a refusal is a message. */
        pi_rd(header_back, ADDR_PI_DDIPL, sizeof(header_back));
        if (header_back[0] != 0x80 || header_back[1] != 0x27 || header_back[2] != 0x07 ||
            header_back[3] != 0x40) {
            ed_dev_stop(0);
            if (status && status_size)
                snprintf(status, status_size, "64DD IPL not mapped: reads %02X%02X%02X%02X; not booted",
                    header_back[0], header_back[1], header_back[2], header_back[3]);
            return false;
        }
    }
    sm_rom_boot(NULL, from_disk, cheats);
    return true;    /* not reached */
}

const sm_flashcart_t sm_flashcart_pro = {
    .kind = SM_FLASHCART_PRO,
    .name = "EverDrive-64 Pro",
    .max_rom_bytes = pro_max,
    .init = pro_init,
    .save_sync_flush = pro_flush,
    .load_rom = pro_load,
    .read_rom = pro_read_rom,
    .write_rom = pro_write_rom,
    .arm_save = pro_arm,
    .attach_disk = pro_attach_disk,
    .boot = pro_boot,
    .probe = NULL,
};
#else
/* The host has no cartridge; the table exists so the launcher links. */
bool sm_flashcart_pro_present(void) { return false; }
const sm_flashcart_t sm_flashcart_pro = { .kind = SM_FLASHCART_PRO, .name = "EverDrive-64 Pro" };
#endif
