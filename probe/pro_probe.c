/* SPDX-License-Identifier: AGPL-3.0-only */
/* The EverDrive-64 Pro canary.

   A ROM that does nothing but ask the cartridge questions, in the order the
   browser will need the answers, and writes what it heard to
   sleekmenu/pro-probe.log on the card. It exists because nobody has run an
   open menu on the Pro: krikzz's reference library (third_party/ed64pro)
   documents the protocol, not what a real cart says, and the X7 taught us
   that the distance between those two is where the weeks go.

   Each step is a fact the browser's Pro backend will be built on:

     1  the device id register reads as an EverDrive at all
     2  the MCU answers a command and reports its firmware
     3  what the stock OS configured for us -- the paths it hands a game
     4  the card's ROMS folder can be listed, and how fast
     5  a ROM's first 64 bytes come over the FIFO
     6  a megabyte of it lands in cartridge memory and reads back identical
     7  the MCU's own CRC of that megabyte, for the verified-load option
     8  a file can be written -- the log itself

   Then, on Start and only on Start, the one step that cannot be undone:
   configure the cart for a game, load it over ourselves, and hand off. Where
   that stalls tells us what the Pro needs that the library does not say.

   Everything is printed to the screen as it happens, and the log is
   rewritten after every step, so a hang leaves evidence. */

#include "appmain.h"
#include "boot.h"

#define PROBE_VERSION "2"
#define LOG_PATH "sleekmenu/pro-probe.log"
#define TEST_ROM "ROMS/1 US - A-M/F-Zero X (USA).z64"
/* The launch target is a different game from the transfer target on purpose:
   Super Mario 64 saves to a 4 kbit EEPROM where F-Zero X used SRAM, and its
   save goes where the stock OS would put it, so the next OS boot shows
   whether the MCU or the OS turns the cache into a file. */
#define LAUNCH_ROM "ROMS/SuperMario 64.z64"
#define LAUNCH_GDATA "ED64/gamedata/SuperMario 64.z64"
#define LAUNCH_BRM "ED64/gamedata/SuperMario 64.z64/bram.eep"
#define ROMS_DIR "ROMS"
#define BIG_DIR "ROMS/1 US - A-M"
#define FCI_SCRATCH 0x200000u     /* 2 MB in: past this ROM, inside any card */
#define VERIFY_LEN 0x100000u      /* one megabyte */

static char logbuf[16384];
static size_t loglen;

static void note(const char *fmt, ...) {
    va_list ap;
    char line[256];
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    printf("%s\n", line);
    console_render();
    if (loglen + strlen(line) + 2 < sizeof(logbuf)) {
        loglen += (size_t)snprintf(logbuf + loglen, sizeof(logbuf) - loglen, "%s\n", line);
    }
}

static void save_log(void) {
    u8 resp = ed_fs_file_open((u8 *)LOG_PATH, FA_WRITE | FA_CREATE_ALWAYS | FS_MAKEPATH);
    if (resp) { printf("log: open failed 0x%02X\n", resp); console_render(); return; }
    resp = ed_fs_file_write(logbuf, (u32)loglen);
    if (resp) { printf("log: write failed 0x%02X\n", resp); console_render(); }
    resp = ed_fs_file_close();
    if (resp) { printf("log: close failed 0x%02X\n", resp); console_render(); }
}

static bool wait_button(bool *start) {
    /* A or B continue; Start is the launch. Returns false on B. */
    while (1) {
        joypad_poll();
        joypad_buttons_t joy = joypad_get_buttons_pressed(JOYPAD_PORT_1);
        console_render();
        if (joy.start) { *start = true; return true; }
        if (joy.a) { *start = false; return true; }
        if (joy.b) { *start = false; return false; }
    }
}

static u8 header[64] __attribute__((aligned(8)));
static u8 back[64] __attribute__((aligned(8)));
static u8 tail_fifo[4096] __attribute__((aligned(8)));
static u8 tail_pi[4096] __attribute__((aligned(8)));
static u8 chunk[65536] __attribute__((aligned(8)));

static u32 rom_size;

static void step_device(void) {
    u32 id = ed_get_cart_id();
    note("[1] EDID = %08lX (%s)", id,
         ((id >> 16) == 0xED64ul) ? "an EverDrive" : "NOT an EverDrive id");
    note("    device byte 0x%02lX, expected 0x%02X for ED64 Pro", id & 0xFF, DEVID_ED64PRO);
}

static void step_mcu(void) {
    /* Drain whatever the FIFO holds before the first command, so a stale
       byte cannot shift every reply that follows; the device is left as the
       OS configured it until step 4. */
    ed_fifo_flush();
    u8 resp = ed_check_status();
    note("[2] status before touching anything -> 0x%02X", resp);
    u32 list[8] = { INFS_DEV_ID, INFS_HW_VER, INFS_TS_FW, INFS_TS_BOOT,
                    INFS_MAX_ROM_SIZE, INFS_FLA_SIZE, INFD_BOOT_MODE, INFD_GAME_CTR };
    ed_sys_get_inf(list, 8);
    note("    dev_id %08lX hw_ver %08lX fw %08lX boot %08lX", list[0], list[1], list[2], list[3]);
    note("    max_rom_size %lu (0x%08lX) fla_size %lu boot_mode %lu games %lu",
         list[4], list[4], list[5], list[6], list[7]);
}

static void step_paths(void) {
    static u8 path[1025];
    static const char *names[] = { "gpak", "gdata", "bram", "appf", "disk" };
    static const DevPathType types[] = { DEV_PATH_GPAK, DEV_PATH_GDATA, DEV_PATH_BRM,
                                         DEV_PATH_APPF, DEV_PATH_DISK };
    HanStatus stat;
    note("[3] what the stock OS set for this ROM:");
    for (int i = 0; i < 5; i++) {
        path[0] = 0;
        u8 resp = ed_dev_get_path(path, types[i]);
        note("    %-5s -> 0x%02X '%s'", names[i], resp, path);
    }
    ed_dev_han_stat(&stat);
    note("    handlers brm %u disk %u rtc %u ddrom %u cache_brm %u cache_rtc %u",
         stat.han_brm, stat.han_disk, stat.han_rtc, stat.han_ddrom,
         stat.cache_brm, stat.cache_rtc);
}

static void step_list(void) {
    static u8 name[512];
    FileInfo inf = { .file_name = name };
    u16 size = 0, filtered = 0;
    u8 resp = ed_init_hw();
    note("[4] ed_init_hw (dev stop, after the paths were read) -> 0x%02X", resp);
    resp = ed_fs_init();
    note("    ed_fs_init -> 0x%02X", resp);
    u32 t0 = ed_get_ticks();
    resp = ed_fs_dir_load((u8 *)ROMS_DIR, DIR_OPT_SORTED);
    u32 t1 = ed_get_ticks();
    ed_fs_dir_get_size(&size);
    note("    dir_load '%s' sorted -> 0x%02X, %u entries, %lu ms", ROMS_DIR, resp, size, t1 - t0);
    for (u16 i = 0; i < size && i < 6; i++) {
        ed_fs_dir_get_recs(i, 1, sizeof(name) - 1);
        resp = ed_fs_rx_next_rec(&inf);
        if (resp) { note("    rec %u -> 0x%02X", i, resp); break; }
        note("    %s %8lu %s", inf.is_dir ? "dir " : "file", inf.size, inf.file_name);
    }
    resp = ed_fs_dir_load((u8 *)ROMS_DIR, DIR_OPT_SORTED | DIR_OPT_FILTROM);
    ed_fs_dir_get_size(&filtered);
    note("    with FILTROM -> 0x%02X, %u entries", resp, filtered);
    resp = ed_fs_dir_load((u8 *)"", DIR_OPT_SORTED | DIR_OPT_HIDESYS);
    ed_fs_dir_get_size(&filtered);
    note("    root with HIDESYS -> 0x%02X, %u entries", resp, filtered);
    /* A folder the size the browser actually meets, and records in bulk:
       the FIFO holds 2 KB, so twenty short names per request is the shape
       of a fast listing. */
    t0 = ed_get_ticks();
    resp = ed_fs_dir_load((u8 *)BIG_DIR, DIR_OPT_SORTED);
    t1 = ed_get_ticks();
    ed_fs_dir_get_size(&size);
    note("    dir_load '%s' -> 0x%02X, %u entries, %lu ms", BIG_DIR, resp, size, t1 - t0);
    t0 = ed_get_ticks();
    {
        u16 got = 0;
        for (u16 at = 0; at < size; at += 16) {
            u16 want = (u16)((size - at) < 16 ? (size - at) : 16);
            ed_fs_dir_get_recs(at, want, 96);
            for (u16 i = 0; i < want; i++) {
                resp = ed_fs_rx_next_rec(&inf);
                if (resp) { note("    rec %u -> 0x%02X", at + i, resp); at = size; break; }
                got++;
            }
        }
        t1 = ed_get_ticks();
        note("    %u records, 16 per request, 96-char names: %lu ms", got, t1 - t0);
        note("    last one: %s %lu '%s'", inf.is_dir ? "dir" : "file", inf.size, inf.file_name);
    }
}

static void step_header(void) {
    u8 resp = ed_fs_file_open((u8 *)TEST_ROM, FA_READ);
    note("[5] open '%s' -> 0x%02X", TEST_ROM, resp);
    if (resp) return;
    rom_size = ed_fs_file_available();
    note("    size %lu bytes", rom_size);
    u32 t0 = ed_get_ticks();
    resp = ed_fs_file_read(header, 64);
    u32 t1 = ed_get_ticks();
    note("    fifo read 64 bytes -> 0x%02X in %lu ms", resp, t1 - t0);
    note("    magic %02X%02X%02X%02X title '%.20s' code %c%c%c%c crc %02X%02X%02X%02X %02X%02X%02X%02X",
         header[0], header[1], header[2], header[3], (const char *)header + 0x20,
         header[0x3B], header[0x3C], header[0x3D], header[0x3E],
         header[0x10], header[0x11], header[0x12], header[0x13],
         header[0x14], header[0x15], header[0x16], header[0x17]);
    /* How fast the FIFO path is, for the things that cannot go through
       cartridge memory: a 14 KB cover, a 570 KB catalog. */
    t0 = ed_get_ticks();
    resp = ed_fs_file_read(chunk, sizeof(chunk));
    t1 = ed_get_ticks();
    note("    fifo read 64 KB -> 0x%02X in %lu ms (%lu KB/s)", resp, t1 - t0,
         (t1 - t0) ? 64ul * 1000 / (t1 - t0) : 0);
    t0 = ed_get_ticks();
    for (int i = 0; i < 8 && !resp; i++) resp = ed_fs_file_read(chunk, sizeof(chunk));
    t1 = ed_get_ticks();
    note("    fifo read 512 KB -> 0x%02X in %lu ms (%lu KB/s)", resp, t1 - t0,
         (t1 - t0) ? 512ul * 1000 / (t1 - t0) : 0);
    resp = ed_fs_file_close();
    note("    close -> 0x%02X", resp);
}

static void step_fci(void) {
    u8 resp = ed_fs_file_open((u8 *)TEST_ROM, FA_READ);
    note("[6] open again -> 0x%02X; DMA %lu KB to cart +0x%lX", resp, VERIFY_LEN / 1024, FCI_SCRATCH);
    if (resp) return;
    u32 t0 = ed_get_ticks();
    resp = ed_fs_file_read_fci(ADDR_FCI_ROM + FCI_SCRATCH, VERIFY_LEN);
    u32 t1 = ed_get_ticks();
    note("    read_fci -> 0x%02X in %lu ms (%lu KB/s)", resp, t1 - t0,
         (t1 - t0) ? (VERIFY_LEN / 1024) * 1000 / (t1 - t0) : 0);
    pi_rd(back, ADDR_PI_ROM + FCI_SCRATCH, 64);
    note("    head via PI: %s", memcmp(back, header, 64) == 0 ? "MATCHES the fifo header" : "DIFFERS");
    if (memcmp(back, header, 64) != 0)
        note("    pi %02X%02X%02X%02X ... fifo %02X%02X%02X%02X", back[0], back[1], back[2], back[3],
             header[0], header[1], header[2], header[3]);
    resp = ed_fs_file_set_ptr(VERIFY_LEN - sizeof(tail_fifo));
    u8 resp2 = ed_fs_file_read(tail_fifo, sizeof(tail_fifo));
    pi_rd(tail_pi, ADDR_PI_ROM + FCI_SCRATCH + VERIFY_LEN - sizeof(tail_pi), sizeof(tail_pi));
    note("    tail 4 KB: set_ptr 0x%02X read 0x%02X, %s", resp, resp2,
         memcmp(tail_fifo, tail_pi, sizeof(tail_pi)) == 0 ? "MATCHES" : "DIFFERS");
    /* Whole-megabyte CPU CRC over PI reads, for step 7. */
    u32 crc = 0xFFFFFFFFul;
    for (u32 off = 0; off < VERIFY_LEN; off += sizeof(chunk)) {
        pi_rd(chunk, ADDR_PI_ROM + FCI_SCRATCH + off, sizeof(chunk));
        for (u32 i = 0; i < sizeof(chunk); i++) {
            crc ^= chunk[i];
            for (int bit = 0; bit < 8; bit++)
                crc = (crc >> 1) ^ (0xEDB88320ul & (u32)-(s32)(crc & 1ul));
        }
    }
    crc = ~crc;
    note("    CPU crc32 of the megabyte via PI: %08lX", crc);
    /* And a bigger transfer for the speed figure, if the file allows. */
    if (rom_size >= FCI_SCRATCH + 0x400000u + VERIFY_LEN) {
        resp = ed_fs_file_set_ptr(0);
        t0 = ed_get_ticks();
        resp2 = ed_fs_file_read_fci(ADDR_FCI_ROM + FCI_SCRATCH + VERIFY_LEN, 0x400000u);
        t1 = ed_get_ticks();
        note("    4 MB read_fci -> 0x%02X/0x%02X in %lu ms (%lu KB/s)", resp, resp2, t1 - t0,
             (t1 - t0) ? 4096ul * 1000 / (t1 - t0) : 0);
    }
    resp = ed_fs_file_close();
    note("    close -> 0x%02X", resp);
}

static void step_crc(void) {
    u32 crc = 0;
    u8 resp = ed_fs_file_open((u8 *)TEST_ROM, FA_READ);
    if (resp) { note("[7] open -> 0x%02X", resp); return; }
    u32 t0 = ed_get_ticks();
    crc = 0;
    resp = ed_fs_file_crc(VERIFY_LEN, &crc);
    u32 t1 = ed_get_ticks();
    note("[7] MCU file crc of first MB (base 0) -> 0x%02X %08lX in %lu ms", resp, crc, t1 - t0);
    crc = 0xFFFFFFFFul;
    resp = ed_fs_file_set_ptr(0);
    resp = ed_fs_file_crc(VERIFY_LEN, &crc);
    note("    MCU file crc (base FFFFFFFF) -> 0x%02X %08lX", resp, crc);
    crc = 0;
    t0 = ed_get_ticks();
    ed_fci_crc(ADDR_FCI_ROM + FCI_SCRATCH, VERIFY_LEN, &crc);
    t1 = ed_get_ticks();
    note("    MCU fci crc of the copy (base 0) -> %08lX in %lu ms", crc, t1 - t0);
    ed_fs_file_close();
}

static void step_launch(void) {
    DevCfg cfg;
    u8 resp;
    boot_params_t params;
    memset(&cfg, 0, sizeof(cfg));
    note("[9] LAUNCH: %s", LAUNCH_ROM);
    resp = ed_fs_file_open((u8 *)LAUNCH_ROM, FA_READ);
    rom_size = ed_fs_file_available();
    ed_fs_file_close();
    note("    open -> 0x%02X, %lu bytes", resp, rom_size);
    if (resp) return;
    resp = ed_dev_stop(0);
    note("    dev_stop -> 0x%02X", resp);
    resp = ed_dev_set_path((u8 *)LAUNCH_ROM, DEV_PATH_GPAK);
    note("    set_path gpak -> 0x%02X", resp);
    resp = ed_dev_set_path((u8 *)LAUNCH_GDATA, DEV_PATH_GDATA);
    note("    set_path gdata -> 0x%02X", resp);
    resp = ed_dev_set_path((u8 *)LAUNCH_BRM, DEV_PATH_BRM);
    note("    set_path bram -> 0x%02X", resp);
    cfg.brom_type = DEV_ROM_GPAK;
    cfg.gpak_size = rom_size;
    cfg.brm_size = 512;
    cfg.brm_type = DEV_BRM_EEP4K;
    cfg.rtc_mode = DEV_RTCMODE_OFF;
    cfg.dd_en = 0;
    cfg.gpak_wren = 0;
    cfg.gpak_key = 0;
    resp = ed_dev_set_cfg(&cfg);
    note("    set_cfg (gpak %lu, eep4k) -> 0x%02X", cfg.gpak_size, resp);
    save_log();
    resp = ed_fs_file_open((u8 *)LAUNCH_ROM, FA_READ);
    note("    open -> 0x%02X; loading %lu bytes to cart 0 (over this probe)", resp, rom_size);
    u32 t0 = ed_get_ticks();
    resp = ed_fs_file_read_fci(ADDR_FCI_ROM, rom_size);
    u32 t1 = ed_get_ticks();
    note("    read_fci -> 0x%02X in %lu ms (%lu KB/s)", resp, t1 - t0,
         (t1 - t0) ? (rom_size / 1024) * 1000 / (t1 - t0) : 0);
    ed_fs_file_close();
    pi_rd(back, ADDR_PI_ROM, 64);
    note("    cart 0 now starts %02X%02X%02X%02X '%.20s'", back[0], back[1], back[2], back[3],
         (const char *)back + 0x20);
    resp = ed_dev_start();
    note("    dev_start -> 0x%02X", resp);
    {
        HanStatus stat;
        ed_dev_han_stat(&stat);
        note("    handlers brm %u disk %u rtc %u ddrom %u", stat.han_brm, stat.han_disk,
             stat.han_rtc, stat.han_ddrom);
    }
    note("    handing off with the N64FlashcartMenu boot code, CIC from IPL3...");
    save_log();
    joypad_close();
    console_close();
    disable_interrupts();
    params.device_type = BOOT_DEVICE_TYPE_ROM;
    params.tv_type = BOOT_TV_TYPE_PASSTHROUGH;
    params.detect_cic_seed = true;
    params.cic_seed = 0;
    params.cheat_list = NULL;
    boot(&params);
    while (1) {}
}

int main(void) {
    bool start = false;
    console_init();
    joypad_init();
    timer_init();
    console_set_render_mode(RENDER_MANUAL);
    console_clear();
    note("SleekMenu 64 -- EverDrive-64 Pro probe v" PROBE_VERSION);
    note("log: %s", LOG_PATH);
    step_device();
    step_mcu();
    step_paths();
    step_list();
    save_log();
    step_header();
    save_log();
    step_fci();
    save_log();
    step_crc();
    save_log();
    note("[8] log written to %s", LOG_PATH);
    note("");
    note("START = load Super Mario 64 and boot it (cannot be undone)");
    note("B     = stop here");
    while (1) {
        if (!wait_button(&start)) { note("stopped."); while (1) { console_render(); } }
        if (start) step_launch();
    }
}
