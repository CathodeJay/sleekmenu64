/* SPDX-License-Identifier: AGPL-3.0-only */
#include "launch.h"
#include "cheats.h"
#include "cheats_io.h"
#include "flashcart.h"
#include "save_type.h"
#include "history.h"
#include "save_sync.h"
#include <libdragon.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

/* Everything cartridge-specific -- how a ROM gets into cartridge memory, how
   a save gets to the game, how the jump is made -- is behind sm_flashcart().
   This file reads the header through stdio, decides, and reports. */

static char selected[512];
static char status[128] = "Ready";
static uint64_t selected_size;
static uint32_t selected_boot_crc;
static sm_cic_t selected_cic;
static sm_launch_result_t last_result = SM_LAUNCH_OK;
static sm_save_decision_t selected_save;
static sm_rom_format_t selected_format = SM_ROM_FORMAT_UNKNOWN;
/* The normalised header is kept because the boot handoff needs the ROM id and
   header CRC pair for ED64/sysdata/registry.dat, and by then the file is
   closed and the cartridge holds the image instead. */
static uint8_t selected_header[SM_N64_HEADER_SIZE] __attribute__((aligned(8)));
static char save_summary[40] = "OFF default";
static sm_boot_mode_t boot_mode = SM_BOOT_FAST;

/* 64DD. A .ndd selected on its own boots from the drive's IPL and the disk
   is the game; a .ndd beside a cartridge ROM rides along as that game's
   expansion, which is the stock firmware's rule too ("the disk image located
   in the same folder will be attached automatically"). */
static bool selected_disk;                     /* the selection is a disk image */
static sm_disk_region_t selected_disk_region;
static char selected_ipl[SM_LAUNCH_PATH_SIZE]; /* "sd:/ED64/64ddipl/NDDJ2.n64" */
static uint32_t selected_ipl_bytes;
static char sibling_disk[SM_LAUNCH_PATH_SIZE]; /* a ROM's expansion disk, or "" */

/* Cheats for the selected game, read when it is selected: the firmware's
   database file if there is one, with the browser's own record of which
   entries are on. The word list is built at launch and lives here because
   the boot code reads it after the browser has been torn down. */
static sm_cheat_set_t cheats;
static sm_cheat_source_t cheats_source;
/* The Pro firmware's cheat pack, listed once at startup: every file name
   under ED64/CHEATS, so a game can be matched to its file by name and
   region rather than by luck. Empty and read on a card without the folder. */
static sm_cheat_pack_t cheat_pack;
static bool cheats_available;
static bool cheats_dirty;
static sm_cheats_hook_t cheats_hook = SM_CHEATS_HOOK_UNKNOWN_CIC;
static uint32_t cheat_words[SM_CHEAT_WORDS_MAX + 4u] __attribute__((aligned(16)));

/* The UI owns the history list -- it is drawn from it -- and lends it here so
   the record is written at the only moment that knows a launch is really
   happening. NULL until the UI hands it over, and on the host tests, where
   nothing boots. */
static sm_history_t *launch_history;

void launch_set_history(sm_history_t *history) { launch_history = history; }

void launch_set_boot_mode(sm_boot_mode_t mode) {
    boot_mode = mode == SM_BOOT_VERIFY ? SM_BOOT_VERIFY : SM_BOOT_FAST;
}
sm_boot_mode_t launch_boot_mode(void) { return boot_mode; }

/* krikzz's per-ROM override database. Read-only, and absent on most cards. */
#define SM_SAVE_DB_PATH "sd:/ED64/save_db.txt"
#define SM_SAVE_DB_MAX 32768u
static char save_db[SM_SAVE_DB_MAX];

static const char *read_save_db(void) {
    FILE *file = fopen(SM_SAVE_DB_PATH, "rb");
    size_t read;
    if (!file) return NULL;
    read = fread(save_db, 1, sizeof(save_db) - 1u, file);
    fclose(file);
    save_db[read] = '\0';
    return read ? save_db : NULL;
}

static void describe_save(void) {
    snprintf(save_summary, sizeof(save_summary), "%s %s%s%s",
        sm_save_type_name(selected_save.type),
        sm_save_source_name(selected_save.source),
        (selected_save.config & SM_SAVE_CFG_RTC) ? " +RTC" : "",
        (selected_save.config & SM_SAVE_CFG_REGION_FREE) ? " +RF" : "");
}

static void set_status(sm_launch_result_t result) {
    last_result = result;
    snprintf(status, sizeof(status), "%s", launch_result_message(result));
}

/* The path the launcher actually opened, in "sd:/..." form. A catalog stores
   paths relative to the card root (older ones to a ROMS folder) and the
   resolver tries more than one candidate, so this -- not the catalog's
   shorthand -- is what names the file on the card, and what the backend is
   handed. */
static char opened_path[SM_LAUNCH_PATH_SIZE];

/* Read-only: nothing here rewrites a ROM. Records which candidate answered. */
static FILE *open_launch_rom_readonly(const char *catalog_path) {
    sm_launch_paths_t paths;
    FILE *file;
    opened_path[0] = '\0';
    if (!launch_resolve_paths(catalog_path, &paths)) return NULL;
    file = fopen(paths.primary, "rb");
    if (file) snprintf(opened_path, sizeof(opened_path), "%s", paths.primary);
    else if (paths.count > 1) {
        file = fopen(paths.fallback, "rb");
        if (file) snprintf(opened_path, sizeof(opened_path), "%s", paths.fallback);
    }
    return file;
}

/* The first .ndd in the folder of the ROM that was opened, preferring one
   named like the ROM. One listing per launch, and only on a cart with a
   drive; the stock firmware attaches by the same rule. */
static void find_sibling_disk(const char *rom_sd_path) {
    char folder[SM_LAUNCH_PATH_SIZE];
    char best[SM_LAUNCH_PATH_SIZE];
    const char *slash = strrchr(rom_sd_path, '/');
    const char *stem;
    const char *dot;
    size_t stem_length, folder_length;
    dir_t entry;
    int result;
    bool best_matches_stem = false;

    sibling_disk[0] = '\0';
    best[0] = '\0';
    if (!slash || !sm_flashcart()->attach_disk) return;
    folder_length = (size_t)(slash - rom_sd_path);
    if (folder_length == 0 || folder_length >= sizeof(folder)) return;
    memcpy(folder, rom_sd_path, folder_length);
    folder[folder_length] = '\0';
    stem = slash + 1;
    dot = strrchr(stem, '.');
    stem_length = dot ? (size_t)(dot - stem) : strlen(stem);

    for (result = dir_findfirst(folder, &entry); result == 0; result = dir_findnext(folder, &entry)) {
        bool same_stem;
        if (entry.d_type != DT_REG || !launch_suffix_is_disk(entry.d_name)) continue;
        same_stem = !strncasecmp(entry.d_name, stem, stem_length) && entry.d_name[stem_length] == '.';
        if (best[0] && !(same_stem && !best_matches_stem)) continue;
        snprintf(best, sizeof(best), "%s", entry.d_name);
        best_matches_stem = same_stem;
        if (same_stem) break;
    }
    if (best[0]) {
        int written = snprintf(sibling_disk, sizeof(sibling_disk), "%s/%s", folder, best);
        if (written < 0 || written >= (int)sizeof(sibling_disk)) sibling_disk[0] = '\0';
    }
}

/* A disk image on its own: the region decides the IPL, the IPL has to be
   on the card, and the cartridge has to have a drive. */
static sm_launch_result_t prepare_disk(const char *relative_path) {
    uint8_t head[SM_DISK_HEAD_SIZE];
    FILE *file = open_launch_rom_readonly(relative_path);
    const char *ipl_name;
    long ipl_size = -1;

    if (!file || fseek(file, 0, SEEK_END) || (selected_size = (uint64_t)ftell(file)) == (uint64_t)-1 ||
        fseek(file, 0, SEEK_SET) || fread(head, 1, sizeof(head), file) != sizeof(head)) {
        if (file) fclose(file);
        set_status(SM_LAUNCH_IO_ERROR);
        return SM_LAUNCH_IO_ERROR;
    }
    fclose(file);
    if (!sm_flashcart()->attach_disk) {
        set_status(SM_LAUNCH_NO_64DD); return SM_LAUNCH_NO_64DD;
    }
    selected_disk_region = launch_disk_region(head, sizeof(head));
    ipl_name = launch_disk_ipl_name(selected_disk_region);
    snprintf(selected_ipl, sizeof(selected_ipl), "%s/%s", SM_DISK_IPL_DIR, ipl_name ? ipl_name : "");
    file = ipl_name ? fopen(selected_ipl, "rb") : NULL;
    if (file) {
        if (!fseek(file, 0, SEEK_END)) ipl_size = ftell(file);
        fclose(file);
    }
    if (ipl_size <= 0 || (uint64_t)ipl_size > SM_DISK_IPL_MAX_BYTES) {
        snprintf(status, sizeof(status), "64DD IPL missing: ED64/64ddipl/%s", ipl_name ? ipl_name : "?");
        last_result = SM_LAUNCH_NO_IPL;
        return last_result;
    }
    selected_ipl_bytes = (uint32_t)ipl_size;
    selected_disk = true;
    snprintf(selected, sizeof(selected), "%s", relative_path);
    snprintf(status, sizeof(status), "64DD disk %s %lu MiB; IPL %.5s; Start to launch",
        launch_disk_region_name(selected_disk_region),
        (unsigned long)((selected_size + 0xFFFFFu) >> 20), ipl_name);
    last_result = SM_LAUNCH_OK;
    return SM_LAUNCH_OK;
}

sm_launch_result_t launch_prepare(const char *relative_path) {
    uint8_t header[SM_N64_HEADER_SIZE] __attribute__((aligned(16)));
    FILE *file = NULL;
    uint32_t boot_crc = 0;
    selected[0] = '\0';
    selected_size = 0;
    selected_boot_crc = 0;
    selected_cic = SM_CIC_UNKNOWN;
    selected_format = SM_ROM_FORMAT_UNKNOWN;
    selected_disk = false;
    selected_disk_region = SM_DISK_REGION_UNKNOWN;
    selected_ipl[0] = '\0';
    selected_ipl_bytes = 0;
    sibling_disk[0] = '\0';
    sm_cheats_reset(&cheats);
    memset(&cheats_source, 0, sizeof(cheats_source));
    cheats_available = false;
    cheats_dirty = false;
    cheats_hook = SM_CHEATS_HOOK_UNKNOWN_CIC;
    memset(&selected_save, 0, sizeof(selected_save));
    describe_save();
    last_result = SM_LAUNCH_IO_ERROR;
    sm_launch_paths_t resolved;
    if (!launch_resolve_paths(relative_path, &resolved)) {
        set_status(SM_LAUNCH_IO_ERROR); return SM_LAUNCH_IO_ERROR;
    }
    if (launch_suffix_is_disk(relative_path)) return prepare_disk(relative_path);
    if (!launch_suffix_is_rom(relative_path)) {
        set_status(SM_LAUNCH_BAD_SUFFIX); return SM_LAUNCH_BAD_SUFFIX;
    }
    file = open_launch_rom_readonly(relative_path);
    if (!file || fseek(file, 0, SEEK_END) || (selected_size = (uint64_t)ftell(file)) == (uint64_t)-1 ||
        fseek(file, 0, SEEK_SET) || fread(header, 1, sizeof(header), file) != sizeof(header)) {
        if (file) fclose(file);
        set_status(SM_LAUNCH_IO_ERROR);
        return SM_LAUNCH_IO_ERROR;
    }
    fclose(file);
    /* Judge by the header, not the filename: the library holds byteswapped
       dumps named .z64 and native dumps named .n64. Normalising the copy in
       RAM means the CRC, the CIC and the save lookup all read real bytes. */
    selected_format = sm_rom_format_detect(header, sizeof(header));
    if (selected_format == SM_ROM_FORMAT_N64) {
        set_status(SM_LAUNCH_WORD_SWAPPED); return SM_LAUNCH_WORD_SWAPPED;
    }
    sm_rom_header_normalise(header, sizeof(header), selected_format);
    memcpy(selected_header, header, sizeof(selected_header));
    sm_launch_result_t result = launch_validate(relative_path, selected_size,
        sm_flashcart()->max_rom_bytes(), header, &boot_crc, &selected_cic);
    selected_boot_crc = boot_crc;
    if (result != SM_LAUNCH_OK) {
        if (result == SM_LAUNCH_BAD_SIZE)
            /* The limit is the cartridge's own: 64 MiB on the X7, what the
               MCU reported on the Pro. */
            snprintf(status, sizeof(status), "Invalid size; 4 KiB to %lu MiB, even",
                (unsigned long)(sm_flashcart()->max_rom_bytes() >> 20));
        else set_status(result);
        return result;
    }
    if (sm_flashcart()->kind == SM_FLASHCART_NONE) {
        set_status(SM_LAUNCH_WRONG_CARTRIDGE); return SM_LAUNCH_WRONG_CARTRIDGE;
    }
    snprintf(selected, sizeof(selected), "%s", relative_path);
    sm_save_resolve(header, sizeof(header), read_save_db(), &selected_save);
    describe_save();
    find_sibling_disk(opened_path);
    cheats_available = sm_cheats_load(selected, header, sizeof(header), &cheat_pack, &cheats, &cheats_source);
    cheats_hook = sm_cheats_hook_check(header, sizeof(header));
    snprintf(status, sizeof(status), "%s CIC %u %lu MiB; save %s%s; Start to launch",
        sm_rom_format_name(selected_format), (unsigned)selected_cic,
        (unsigned long)((selected_size + 0xFFFFFu) >> 20), save_summary,
        sibling_disk[0] ? " +64DD" : "");
    last_result = SM_LAUNCH_OK;
    return SM_LAUNCH_OK;
}

typedef struct {
    sm_launch_progress_cb callback;
    void *context;
    uint32_t last_percent;
    bool started;
} progress_bridge_t;

/* Redrawing on every chunk would cost more wall-clock than the transfer, so
   the screen is refreshed only when the whole-percent figure moves. */
static void load_progress(uint32_t done, uint32_t total, bool verifying, void *context) {
    progress_bridge_t *bridge = context;
    uint32_t percent = total ? (uint32_t)(((uint64_t)done * 100u) / total) : 100u;
    if (bridge->started && percent == bridge->last_percent) return;
    bridge->started = true;
    bridge->last_percent = percent;
    snprintf(status, sizeof(status), "%s %lu%% (%lu/%lu KiB)",
        verifying ? "VERIFYING CARTRIDGE" : "LOADING TO CARTRIDGE",
        (unsigned long)percent, (unsigned long)(done / 1024u),
        (unsigned long)(total / 1024u));
    if (bridge->callback) bridge->callback(done / 1024u, total / 1024u, bridge->context);
}

sm_launch_result_t launch_probe(void) {
    const sm_flashcart_t *cart = sm_flashcart();

    if (!selected[0] || cart->kind == SM_FLASHCART_NONE) {
        set_status(SM_LAUNCH_WRONG_CARTRIDGE);
        return SM_LAUNCH_WRONG_CARTRIDGE;
    }
    if (selected_disk) {
        snprintf(status, sizeof(status), "No transport probe for a disk image");
        last_result = SM_LAUNCH_OK;
        return last_result;
    }
    if (!cart->probe) {
        snprintf(status, sizeof(status), "%s has no transport probe", cart->name);
        last_result = SM_LAUNCH_OK;
        return last_result;
    }
    if (cart->probe(opened_path, status, sizeof(status))) {
        last_result = SM_LAUNCH_OK;
    } else {
        last_result = SM_LAUNCH_IO_ERROR;
    }
    return last_result;
}

sm_launch_result_t launch_rom(sm_launch_progress_cb progress, void *context) {
    const sm_flashcart_t *cart = sm_flashcart();
    progress_bridge_t bridge = { progress, context, 0u, false };
    sm_flashcart_load_t loaded;

    if (!selected[0] || cart->kind == SM_FLASHCART_NONE) {
        set_status(SM_LAUNCH_WRONG_CARTRIDGE);
        return SM_LAUNCH_WRONG_CARTRIDGE;
    }
    if (selected_disk) {
        /* A disk-only game: nothing goes into the ROM area, no save is armed
           -- the disk is the save -- and the IPL is what gets booted. */
        if (!cart->attach_disk) {
            set_status(SM_LAUNCH_NO_64DD);
            return SM_LAUNCH_NO_64DD;
        }
        if (!cart->attach_disk(opened_path, selected_ipl, selected_ipl_bytes,
                load_progress, &bridge, status, sizeof(status))) {
            last_result = SM_LAUNCH_IO_ERROR;
            return last_result;
        }
    } else {
        loaded = cart->load_rom(opened_path, (uint32_t)selected_size,
            selected_format == SM_ROM_FORMAT_V64, boot_mode == SM_BOOT_VERIFY,
            load_progress, &bridge, status, sizeof(status));
        if (loaded != SM_FLASHCART_LOAD_OK) {
            switch (loaded) {
                case SM_FLASHCART_LOAD_WRONG_CART: last_result = SM_LAUNCH_WRONG_CARTRIDGE; break;
                case SM_FLASHCART_LOAD_MISMATCH: last_result = SM_LAUNCH_VERIFY_FAILED; break;
                case SM_FLASHCART_LOAD_TOO_LARGE: last_result = SM_LAUNCH_BAD_SIZE; break;
                default: last_result = SM_LAUNCH_IO_ERROR; break;
            }
            return last_result;
        }

        /* Put this game's save where the cartridge will find it and record it
           as pending before the point of no return. A game booted with the
           previous game's battery RAM would either read someone else's file or
           overwrite it, so a failure here stops the boot rather than risking
           the card. */
        {
            sm_save_sync_report_t sync;
            if (!cart->arm_save(opened_path[0] ? opened_path : selected, selected_header,
                    selected_save.type, selected_save.config, &sync)) {
                snprintf(status, sizeof(status), "%s; not booted", sync.detail);
                last_result = SM_LAUNCH_IO_ERROR;
                return last_result;
            }
        }
        /* The expansion disk, if one sits beside the ROM. */
        if (sibling_disk[0] && cart->attach_disk &&
            !cart->attach_disk(sibling_disk, NULL, 0, NULL, NULL, status, sizeof(status))) {
            last_result = SM_LAUNCH_IO_ERROR;
            return last_result;
        }
    }

    /* Record the launch before the jump, because there is no after: the
       browser does not survive the boot. That makes this "committed to
       booting", not "booted" -- a failed handoff leaves an entry behind. The
       alternative records nothing for the games that work, which is all of
       them. A card that will not take the write is not worth refusing a boot
       over, so the result is deliberately ignored. */
    if (launch_history) {
        /* `selected`, not `opened_path`. They are two forms of the same file
           and the difference matters: opened_path is what was actually
           opened, "sd:/ROMS/...", which is what the backend needs because it
           has to name the file on the card. History is matched against
           catalog entries instead, and the catalog stores the card-relative
           "ROMS/..." form. Recording the sd:/ form meant every lookup missed
           and the tab was always empty. */
        sm_history_record(launch_history, selected);
        (void)sm_history_save(launch_history, SM_HISTORY_PATH);
    }

    /* The GameShark list, if anything is on. The engine stages itself at
       7 MB and lives near the top of 8 MB, so without an Expansion Pak there
       is nowhere to put it and the game boots clean -- the launch card said
       so beforehand. A disk boots through the 64DD IPL, which the engine
       cannot patch, so a disk gets no list either. */
    {
        const uint32_t *list = NULL;
        if (!selected_disk && cheats_available && launch_cheats_possible() &&
            cheats_hook == SM_CHEATS_HOOK_OK) {
            uint32_t words = sm_cheats_build_list(&cheats, cheat_words,
                sizeof(cheat_words) / sizeof(cheat_words[0]));
            if (words) list = cheat_words;
        }
        /* The backend tears the browser down, applies the save type and
           jumps; it comes back only if the cartridge refused before the point
           of no return, with its own account of why. */
        if (!cart->boot(selected_save.type, selected_save.config, selected_disk, list,
                status, sizeof(status))) {
            last_result = SM_LAUNCH_IO_ERROR;
            return last_result;
        }
    }
    snprintf(status, sizeof(status), "BOOT RETURNED - handoff failed");
    last_result = SM_LAUNCH_IO_ERROR;
    return last_result;
}

void launch_cancel(void) { selected[0] = '\0'; selected_size = 0; selected_boot_crc = 0; selected_cic = SM_CIC_UNKNOWN; selected_disk = false; sibling_disk[0] = '\0'; last_result = SM_LAUNCH_OK; snprintf(status, sizeof(status), "Launch cancelled"); }
const char *launch_status_message(void) { return status; }
const char *launch_selected_path(void) { return selected; }
uint32_t launch_boot_crc(void) { return selected_boot_crc; }
sm_cic_t launch_detected_cic(void) { return selected_cic; }
sm_launch_result_t launch_last_result(void) { return last_result; }
const char *launch_save_summary(void) { return save_summary; }
sm_save_type_t launch_save_type(void) { return selected_save.type; }
bool launch_selected_is_disk(void) { return selected_disk; }
const char *launch_sibling_disk(void) { return sibling_disk; }

void launch_read_cheat_pack(void) { sm_cheats_read_pack(&cheat_pack); }
const sm_cheat_pack_t *launch_cheat_pack(void) { return &cheat_pack; }
bool launch_cheats_available(void) { return cheats_available; }
const sm_cheat_set_t *launch_cheats(void) { return &cheats; }
const sm_cheat_source_t *launch_cheats_source(void) { return &cheats_source; }
bool launch_cheats_possible(void) { return is_memory_expanded(); }
sm_cheats_hook_t launch_cheats_hook(void) { return cheats_hook; }

bool launch_cheat_toggle(uint32_t index) {
    sm_cheat_t *cheat;
    if (!cheats_available || index >= cheats.count) return false;
    cheat = &cheats.cheats[index];
    if (cheat->incomplete) return false;
    cheat->enabled = !cheat->enabled;
    cheats_dirty = true;
    return true;
}

bool launch_cheats_save(void) {
    if (!cheats_available || !cheats_dirty) return true;
    if (!sm_cheats_save_state(selected, &cheats)) return false;
    cheats_dirty = false;
    return true;
}
