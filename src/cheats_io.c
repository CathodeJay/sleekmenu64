/* SPDX-License-Identifier: AGPL-3.0-only */
#include "cheats_io.h"

#ifdef __mips__
#include "card_paths.h"
#include <libdragon.h>
#include <stdio.h>
#include <string.h>

/* The largest .cht in the Pro's database is under 40 KB; the buffer is
   sized for one twice that, and a bigger file is read as far as it goes. */
static char file_text[SM_CHEAT_FILE_MAX];
static char state_text[SM_CHEATS_STATE_MAX];
static char state_out[SM_CHEATS_STATE_MAX];

static size_t read_whole(const char *path, char *out, size_t out_size) {
    FILE *file = fopen(path, "rb");
    size_t read;
    if (!file) return 0;
    read = fread(out, 1, out_size - 1u, file);
    fclose(file);
    out[read] = '\0';
    return read;
}

void sm_cheats_read_pack(sm_cheat_pack_t *pack) {
    dir_t entry;
    int result;
    sm_cheat_pack_reset(pack);
    pack->read = true;
    for (result = dir_findfirst(SM_FIRMWARE_CHEATS_DIR, &entry); result == 0;
         result = dir_findnext(SM_FIRMWARE_CHEATS_DIR, &entry)) {
        if (entry.d_type != DT_REG) continue;
        sm_cheat_pack_add(pack, entry.d_name);
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
    bool found = false;
    size_t state_length;

    sm_cheats_reset(set);
    if (source) memset(source, 0, sizeof(*source));
    if (!rom_path || !set) return false;
    /* The player's own file for the game first: it is the one way to give
       a game the pack has only for another region the codes its cartridge
       takes. */
    if (sm_cheats_file_from_rom_path(rom_path, by_file, sizeof(by_file))) {
        found = try_file(SM_CHEATS_DIR, by_file, set, source);
        if (found && source) source->kind = SM_CHEAT_MATCH_EXACT;
    }
    if (!found && pack) {
        sm_cheat_match_t match = sm_cheat_pack_find(pack, rom_path, header, header_length);
        if (source) {
            source->kind = match.kind;
            source->rom_region = match.rom_region;
            source->found = match.found;
        }
        if (match.name) found = try_file(SM_FIRMWARE_CHEATS_DIR, match.name, set, source);
        if (!found && source) source->kind = match.name ? SM_CHEAT_MATCH_NONE : match.kind;
    }
    if (!found) return false;

    state_length = read_whole(SM_CHEATS_STATE_PATH, state_text, sizeof(state_text));
    if (state_length) sm_cheats_state_apply(set, state_text, state_length, rom_path);
    return true;
}

bool sm_cheats_save_state(const char *rom_path, const sm_cheat_set_t *set) {
    size_t state_length, out_length;
    FILE *file;
    bool ok;
    if (!rom_path || !set) return false;
    state_length = read_whole(SM_CHEATS_STATE_PATH, state_text, sizeof(state_text));
    out_length = sm_cheats_state_update(state_text, state_length, rom_path, set, state_out, sizeof(state_out));
    if (out_length == 0 && sm_cheats_enabled_count(set) != 0) return false;
    file = fopen(SM_CHEATS_STATE_PATH, "wb");
    if (!file) return false;
    ok = fwrite(state_out, 1, out_length, file) == out_length;
    if (fclose(file) != 0) ok = false;
    return ok;
}
#endif
