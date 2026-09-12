/* SPDX-License-Identifier: AGPL-3.0-only */
#include "save_io.h"
#include <stdio.h>
#include <string.h>

size_t sm_save_bytes(sm_save_type_t type) {
    switch (type) {
        case SM_SAVE_EEP4K: return 512u;      /* 4 Kbit  */
        case SM_SAVE_EEP16K: return 2048u;    /* 16 Kbit */
        case SM_SAVE_SRM32K: return 32768u;   /* 256 Kbit, the common SRAM */
        case SM_SAVE_SRM96K: return 98304u;   /* three 32 KiB banks */
        case SM_SAVE_FLASH: return 131072u;   /* 1 Mbit FlashRAM */
        case SM_SAVE_SRM128K: return 131072u;
        case SM_SAVE_OFF: default: return 0u;
    }
}

const char *sm_save_extension(sm_save_type_t type) {
    switch (type) {
        case SM_SAVE_EEP4K:
        case SM_SAVE_EEP16K: return ".eep";
        case SM_SAVE_SRM32K:
        case SM_SAVE_SRM96K:
        case SM_SAVE_SRM128K: return ".srm";
        case SM_SAVE_FLASH: return ".fla";
        case SM_SAVE_OFF: default: return NULL;
    }
}

bool sm_save_is_battery_backed(sm_save_type_t type) {
    return sm_save_bytes(type) != 0u && type != SM_SAVE_EEP4K && type != SM_SAVE_EEP16K;
}

/* The stock firmware names a save after the ROM's filename, not after its
   header title or its id: "Super Mario 64 (USA).z64" saves to
   "Super Mario 64 (USA).eep". Two ROMs with the same filename in different
   folders therefore share one save file, which is the firmware's behaviour and
   not something to improve on here -- diverging would strand saves. */
bool sm_save_file_path(const char *rom_path, sm_save_type_t type,
    const char *dir, char *out, size_t out_size) {
    const char *extension = sm_save_extension(type);
    const char *stem;
    const char *dot;
    size_t stem_length;
    int written;

    if (!rom_path || !dir || !out || !out_size || !extension) return false;

    stem = strrchr(rom_path, '/');
    stem = stem ? stem + 1 : rom_path;
    if (!stem[0]) return false;

    dot = strrchr(stem, '.');
    /* A leading dot is part of the name, not an extension separator. */
    stem_length = (dot && dot != stem) ? (size_t)(dot - stem) : strlen(stem);
    if (!stem_length) return false;

    written = snprintf(out, out_size, "%s/%.*s%s", dir,
        (int)stem_length, stem, extension);
    return written > 0 && (size_t)written < out_size;
}

const char *sm_save_io_message(sm_save_io_result_t result) {
    switch (result) {
        case SM_SAVE_IO_OK: return "save ok";
        case SM_SAVE_IO_NO_SAVE: return "no save hardware";
        case SM_SAVE_IO_NO_FILE: return "no save file yet";
        case SM_SAVE_IO_BAD_PATH: return "save path too long";
        case SM_SAVE_IO_READ_FAILED: return "save read failed";
        case SM_SAVE_IO_WRITE_FAILED: return "save write failed";
        case SM_SAVE_IO_BLANK_REFUSED: return "cartridge save empty; kept the card copy";
        case SM_SAVE_IO_HARDWARE: default: return "save hardware absent";
    }
}

/* Save memory that reads back as one repeated byte is what a dead cell, a
   cartridge that never presented the save device, and a genuinely erased save
   all look like -- and there is no way to tell them apart from here. Refusing
   to write that over a save the card already holds is the only asymmetry worth
   having: declining costs the user a manual delete, and getting it wrong costs
   them the save.

   Any repeated byte counts, not just 0x00 and 0xFF. The card in
   docs/sd-forensics/sample-04-flushed-srm/ settled that: the stock firmware
   dumped 32 KiB of the EverDrive's battery window and everything past the
   512 bytes the game had actually used came back 0xAA. A guard that only knew
   the two obvious fills would have taken that for real data. */
bool sm_save_buffer_is_blank(const uint8_t *data, size_t size) {
    size_t i;
    for (i = 1u; i < size; i++)
        if (data[i] != data[0]) return false;
    return true;
}

#ifdef __mips__
#include <libdragon.h>
#include "x7_save_reg.h"

/* The cartridge's battery-backed save window: PI domain 2, address 2. Every
   N64 SRAM cartridge lives here and the EverDrive presents its 128 KiB battery
   RAM at the same place. FlashRAM is the same memory seen through the FPGA's
   flash protocol emulation, which is why reading it back needs the save type
   set to SRM128K rather than FLASH -- see sm_save_transfer_type(). */
#define SM_SAVE_PI_BASE 0x08000000u

/* libcart's tuned PI domain 2 timing for the EverDrive, from its own
   initialisation (third_party/libdragon/src/libcart/cart.c: __cart_dom1 is set
   to 0x80370C04 for the X-series and __cart_dom2 falls back to it). Using the
   driver's number rather than inventing one keeps this module honest, and the
   previous values are put back afterwards so libcart's acquire/release
   bracket saves and restores whatever it expects to see. */
#define SM_SAVE_DOM2 0x80370C04u
#define PI_BSD_DOM2_LAT_REG 0x04600024u
#define PI_BSD_DOM2_PWD_REG 0x04600028u
#define PI_BSD_DOM2_PGS_REG 0x0460002Cu
#define PI_BSD_DOM2_RLS_REG 0x04600030u

typedef struct { uint32_t lat, pwd, pgs, rls; } sm_dom2_t;

static sm_dom2_t dom2_apply(uint32_t packed) {
    sm_dom2_t previous;
    previous.lat = io_read(PI_BSD_DOM2_LAT_REG);
    previous.pwd = io_read(PI_BSD_DOM2_PWD_REG);
    previous.pgs = io_read(PI_BSD_DOM2_PGS_REG);
    previous.rls = io_read(PI_BSD_DOM2_RLS_REG);
    io_write(PI_BSD_DOM2_LAT_REG, packed >> 0);
    io_write(PI_BSD_DOM2_PWD_REG, packed >> 8);
    io_write(PI_BSD_DOM2_PGS_REG, packed >> 16);
    io_write(PI_BSD_DOM2_RLS_REG, packed >> 20);
    return previous;
}

static void dom2_restore(const sm_dom2_t *previous) {
    io_write(PI_BSD_DOM2_LAT_REG, previous->lat);
    io_write(PI_BSD_DOM2_PWD_REG, previous->pwd);
    io_write(PI_BSD_DOM2_PGS_REG, previous->pgs);
    io_write(PI_BSD_DOM2_RLS_REG, previous->rls);
}

/* What to put in REG_GAM_CFG while moving bytes, which is not always the
   game's own save type. FlashRAM read back through the flash protocol would
   need the command sequence the game issues; presented as 128 KiB of SRAM the
   same memory is a flat window. */
static sm_save_type_t sm_save_transfer_type(sm_save_type_t type) {
    return type == SM_SAVE_FLASH ? SM_SAVE_SRM128K : type;
}

/* The EEPROM the console talks to is the FPGA pretending to be one, and it
   only starts answering the joybus once REG_GAM_CFG says so. The retries are
   there because how long that takes is not documented anywhere; a handful of
   milliseconds has been plenty in practice, and reporting absent hardware
   wrongly would look like a lost save. */
static bool eeprom_ready(sm_save_type_t type) {
    sm_x7_apply_save_type(type);
    for (int attempt = 0; attempt < 10; attempt++) {
        if (eeprom_present() != EEPROM_NONE) return true;
        wait_ms(2);
    }
    return false;
}

/* No file access happens between configuring the cartridge and moving the
   bytes: these two helpers only talk to hardware, so an SD transaction can
   never be caught in the middle of a save-type change. */
/* Cartridge save memory -> buffer, and buffer -> cartridge save memory.
   Both expect sm_save_bytes(type) bytes and configure the cartridge for the
   type first; neither is safe to call once interrupts are off. */
static sm_save_io_result_t sm_save_read_hardware(sm_save_type_t type, void *dst, size_t size) {
    if (!dst || size != sm_save_bytes(type) || !size) return SM_SAVE_IO_NO_SAVE;
    if (!sm_save_is_battery_backed(type)) {
        if (!eeprom_ready(type)) return SM_SAVE_IO_HARDWARE;
        eeprom_read_bytes(dst, 0, size);
        return SM_SAVE_IO_OK;
    }
    {
        sm_dom2_t previous;
        sm_x7_apply_save_type(sm_save_transfer_type(type));
        previous = dom2_apply(SM_SAVE_DOM2);
        data_cache_hit_writeback_invalidate(dst, size);
        dma_read_async(dst, SM_SAVE_PI_BASE, size);
        dma_wait();
        data_cache_hit_invalidate(dst, size);
        dom2_restore(&previous);
    }
    return SM_SAVE_IO_OK;
}

static sm_save_io_result_t sm_save_write_hardware(sm_save_type_t type, const void *src, size_t size) {
    if (!src || size != sm_save_bytes(type) || !size) return SM_SAVE_IO_NO_SAVE;
    if (!sm_save_is_battery_backed(type)) {
        if (!eeprom_ready(type)) return SM_SAVE_IO_HARDWARE;
        eeprom_write_bytes(src, 0, size);
        return SM_SAVE_IO_OK;
    }
    {
        sm_dom2_t previous;
        sm_x7_apply_save_type(sm_save_transfer_type(type));
        previous = dom2_apply(SM_SAVE_DOM2);
        data_cache_hit_writeback(src, size);
        /* dma_write() forces its address into the 0x10000000 ROM window, which
           would land this transfer in the middle of the loaded game. The raw
           call is the only one that reaches domain 2. */
        dma_write_raw_async(src, SM_SAVE_PI_BASE, size);
        dma_wait();
        dom2_restore(&previous);
    }
    return SM_SAVE_IO_OK;
}

static uint8_t save_buffer[SM_SAVE_MAX_BYTES] __attribute__((aligned(16)));
/* Comparison is chunked rather than buffered whole: a second 128 KiB static
   would cost more RDRAM than the check is worth. */
#define SM_SAVE_COMPARE_CHUNK 4096u
static uint8_t save_compare[SM_SAVE_COMPARE_CHUNK] __attribute__((aligned(16)));

#define SM_SAVE_SD_PREFIX "sd:/"

static bool save_sd_path(const char *rom_path, sm_save_type_t type,
    char *out, size_t out_size) {
    return sm_save_file_path(rom_path, type, SM_SAVE_SD_PREFIX SM_GAMEDATA_DIR,
        out, out_size);
}

sm_save_io_result_t sm_save_restore(const char *rom_path, sm_save_type_t type) {
    char path[320];
    size_t size = sm_save_bytes(type);
    FILE *file;
    size_t read;

    if (!size) return SM_SAVE_IO_NO_SAVE;
    if (!save_sd_path(rom_path, type, path, sizeof(path))) return SM_SAVE_IO_BAD_PATH;
    file = fopen(path, "rb");
    if (!file) {
        /* A game that has never been saved gets an erased backup store.
           Leaving the previous game's bytes there is what makes a save turn up
           under the wrong name, or a game load someone else's file. FlashRAM
           erases to 0xFF on the real part and some games check for it; SRAM and
           EEPROM have no erased value worth preserving, so they get zero. */
        memset(save_buffer, type == SM_SAVE_FLASH ? 0xFF : 0x00, size);
        sm_save_write_hardware(type, save_buffer, size);
        return SM_SAVE_IO_NO_FILE;
    }
    read = fread(save_buffer, 1, size, file);
    fclose(file);
    /* A short file is padded rather than rejected: the firmware writes the
       full length, but a save moved from an emulator may be trimmed. */
    if (read < size) memset(save_buffer + read, 0, size - read);
    return sm_save_write_hardware(type, save_buffer, size);
}


static bool file_has_content(const char *path, size_t size) {
    FILE *file = fopen(path, "rb");
    size_t offset = 0;
    bool content = false;
    if (!file) return false;
    while (!content && offset < size) {
        size_t want = size - offset;
        size_t read;
        if (want > SM_SAVE_COMPARE_CHUNK) want = SM_SAVE_COMPARE_CHUNK;
        read = fread(save_compare, 1, want, file);
        if (!read) break;
        content = !sm_save_buffer_is_blank(save_compare, read);
        offset += read;
    }
    fclose(file);
    return content;
}

sm_save_io_result_t sm_save_backup(const char *rom_path, sm_save_type_t type) {
    char path[320];
    size_t size = sm_save_bytes(type);
    sm_save_io_result_t result;
    FILE *file;
    size_t written;

    if (!size) return SM_SAVE_IO_NO_SAVE;
    if (!save_sd_path(rom_path, type, path, sizeof(path))) return SM_SAVE_IO_BAD_PATH;
    result = sm_save_read_hardware(type, save_buffer, size);
    if (result != SM_SAVE_IO_OK) return result;
    if (sm_save_buffer_is_blank(save_buffer, size) && file_has_content(path, size))
        return SM_SAVE_IO_BLANK_REFUSED;

    /* Rewriting an identical file would cost an SD erase cycle on every menu
       boot, and would also touch the timestamp of a save the stock firmware
       had already flushed. */
    file = fopen(path, "rb");
    if (file) {
        size_t offset = 0;
        bool same = true;
        while (same && offset < size) {
            size_t want = size - offset;
            size_t read;
            if (want > SM_SAVE_COMPARE_CHUNK) want = SM_SAVE_COMPARE_CHUNK;
            read = fread(save_compare, 1, want, file);
            same = read == want && !memcmp(save_compare, save_buffer + offset, want);
            offset += read;
        }
        /* A longer file on the card is a different file, not a match. */
        if (same && fgetc(file) != EOF) same = false;
        fclose(file);
        if (same) return SM_SAVE_IO_OK;
    }
    file = fopen(path, "wb");
    if (!file) return SM_SAVE_IO_WRITE_FAILED;
    written = fwrite(save_buffer, 1, size, file);
    if (fclose(file) || written != size) return SM_SAVE_IO_WRITE_FAILED;
    return SM_SAVE_IO_OK;
}
#endif
