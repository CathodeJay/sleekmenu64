/* SPDX-License-Identifier: AGPL-3.0-only */
#include "cheats_io.h"

#ifdef __mips__
#include "card_paths.h"
#include <libdragon.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

/* The largest .cht in the Pro's pack is under 40 KB; the buffer is sized for
   one twice that, and a bigger file -- libretro has a few of a megabyte and
   more -- is read as far as it goes. */
static char file_text[SM_CHEAT_FILE_MAX];
static char state_out[SM_CHEATS_STATE_MAX];
/* sleekmenu/cheats.txt, read the first time it is needed and kept: only
   sm_cheats_save_state writes it, and it keeps the copy up to date. */
static char state_text[SM_CHEATS_STATE_MAX];
static size_t state_length;
static bool state_loaded;
/* What sleekmenu/cheats/ held when the pack was listed: any .cht of the
   player's own, and the folder of fetched files. Until then, both are
   tried. */
static bool own_files = true;
static bool fetched_folder = true;

static size_t read_whole(const char *path, char *out, size_t out_size) {
    FILE *file = fopen(path, "rb");
    size_t read;
    if (!file) return 0;
    read = fread(out, 1, out_size - 1u, file);
    fclose(file);
    out[read] = '\0';
    return read;
}

static void load_state(void) {
    if (state_loaded) return;
    state_length = read_whole(SM_CHEATS_STATE_PATH, state_text, sizeof(state_text));
    state_loaded = true;
}

void sm_cheats_read_pack(sm_cheat_pack_t *pack) {
    /* The fetched files' folder by its name inside SM_CHEATS_DIR. */
    const char *fetched_name = SM_CHEATS_FETCHED_DIR + sizeof(SM_CHEATS_DIR);
    dir_t entry;
    int result;
    sm_cheat_pack_reset(pack);
    pack->read = true;
    for (result = dir_findfirst(SM_FIRMWARE_CHEATS_DIR, &entry); result == 0;
         result = dir_findnext(SM_FIRMWARE_CHEATS_DIR, &entry)) {
        if (entry.d_type != DT_REG) continue;
        sm_cheat_pack_add(pack, entry.d_name);
    }
    own_files = false;
    fetched_folder = false;
    for (result = dir_findfirst(SM_CHEATS_DIR, &entry); result == 0;
         result = dir_findnext(SM_CHEATS_DIR, &entry)) {
        size_t length = strlen(entry.d_name);
        if (entry.d_type == DT_REG && length > 4u && !strcasecmp(entry.d_name + length - 4u, ".cht"))
            own_files = true;
        else if (entry.d_type == DT_DIR && !strcasecmp(entry.d_name, fetched_name))
            fetched_folder = true;
    }
}

/* One file: returns true when it was there and parsed, and records where,
   without the "sd:/" the card does not show. */
static bool try_file(const char *directory, const char *name, sm_cheat_set_t *set,
    sm_cheat_source_t *source) {
    char path[600];
    size_t length;
    if (snprintf(path, sizeof(path), "%s/%s", directory, name) >= (int)sizeof(path)) return false;
    length = read_whole(path, file_text, sizeof(file_text));
    if (!length) return false;
    sm_cheats_parse(set, file_text, length);
    if (source) {
        const char *shown = strncmp(path, SM_SD_ROOT, strlen(SM_SD_ROOT)) == 0 ? path + strlen(SM_SD_ROOT) : path;
        /* A name too long for the line is cut, not refused: the page only
           shows it. */
        size_t n = strlen(shown);
        if (n >= sizeof(source->path)) n = sizeof(source->path) - 1u;
        memcpy(source->path, shown, n);
        source->path[n] = '\0';
    }
    return true;
}

bool sm_cheats_load(const char *rom_path, const uint8_t *header, size_t header_length,
    const sm_cheat_pack_t *pack, sm_cheat_set_t *set, sm_cheat_source_t *source) {
    char by_file[300];
    sm_cheat_match_t match = { SM_CHEAT_MATCH_NONE, NULL, 0, 0 };
    bool found = false;

    sm_cheats_reset(set);
    if (source) memset(source, 0, sizeof(*source));
    if (!rom_path || !set) return false;
    /* The player's own file for the game first: it is the one way to give
       a game the pack has only for another region the codes its cartridge
       takes. */
    if (own_files && sm_cheats_file_from_rom_path(rom_path, by_file, sizeof(by_file))) {
        found = try_file(SM_CHEATS_DIR, by_file, set, source);
        if (found && source) source->kind = SM_CHEAT_MATCH_EXACT;
    }
    /* Then the pack's file, when the pack is sure of it. */
    if (!found && pack) {
        match = sm_cheat_pack_find(pack, rom_path, header, header_length);
        if (source) {
            source->kind = match.kind;
            source->rom_region = match.rom_region;
            source->found = match.found;
        }
        if (sm_cheat_match_sure(&match)) found = try_file(SM_FIRMWARE_CHEATS_DIR, match.name, set, source);
    }
    /* Then the file the Game Catalog Manager fetched for this very dump,
       named by the header's checksum words: for the games the pack does
       not have, has for another region only, or can only guess at. */
    if (!found && fetched_folder && sm_cheats_file_from_header(header, header_length, by_file, sizeof(by_file))) {
        found = try_file(SM_CHEATS_FETCHED_DIR, by_file, set, source);
        if (found && source) source->kind = SM_CHEAT_MATCH_EXACT;
    }
    /* Last, the pack's guess. */
    if (!found && match.name && !sm_cheat_match_sure(&match))
        found = try_file(SM_FIRMWARE_CHEATS_DIR, match.name, set, source);
    if (!found && pack && source) source->kind = match.name ? SM_CHEAT_MATCH_NONE : match.kind;
    if (!found) return false;

    load_state();
    if (state_length) sm_cheats_state_apply(set, state_text, state_length, rom_path);
    return true;
}

bool sm_cheats_save_state(const char *rom_path, const sm_cheat_set_t *set) {
    size_t out_length;
    FILE *file;
    bool ok;
    if (!rom_path || !set) return false;
    load_state();
    out_length = sm_cheats_state_update(state_text, state_length, rom_path, set, state_out, sizeof(state_out));
    if (out_length == 0 && sm_cheats_enabled_count(set) != 0) return false;
    file = fopen(SM_CHEATS_STATE_PATH, "wb");
    if (!file) return false;
    ok = fwrite(state_out, 1, out_length, file) == out_length;
    if (fclose(file) != 0) ok = false;
    if (ok) {
        /* The copy is what was written. */
        memcpy(state_text, state_out, out_length);
        state_text[out_length] = '\0';
        state_length = out_length;
    } else {
        /* Whatever reached the card is read again the next time. */
        state_loaded = false;
    }
    return ok;
}
#endif
