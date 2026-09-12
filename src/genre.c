/* SPDX-License-Identifier: AGPL-3.0-only */
#include "genre.h"
#include <stdio.h>
#include <string.h>

/* Codes worth spelling out, because the first three letters would be wrong or
   ambiguous. Everything else falls back to its own opening letters, which is
   right far more often than it is not: Racing -> RAC, Puzzle -> PUZ. */
static const struct { const char *name; const char *code; } NAMED[] = {
    /* The consolidated names data/genres.csv produces. Action-Adventure has
       to be spelled out or it collides with Action, and two tabs reading ACT
       would be worse than no tabs at all. */
    {"Action-Adventure", "ADV"},
    {"Role Playing Games", "RPG"},
    {"Shooters", "SHT"},
    {"Platforms", "PLT"},
    {"Other", "ETC"},
    /* And the raw libretro spellings, for a card built without the map. */
    {"Role-playing (RPG)", "RPG"},
    {"Platform", "PLT"},
    {"Shooter", "SHT"},
    {"Shoot'em Up", "SHM"},
    {"Beat'em Up", "BTM"},
    {"Fighting", "FGT"},
    {"Sports", "SPT"},
    {"Sports with Animals", "SPA"},
    {"Simulation", "SIM"},
    {"Strategy", "STR"},
    {"Adventure", "ADV"},
    {"Hunting and Fishing", "HNT"},
    {"Music / Dancing", "MUS"},
    {"Lightgun Shooter", "LGN"},
    {"Educational", "EDU"},
    {"Compilation", "CMP"},
    {"Casual Game", "CAS"},
};

void sm_genre_code(const char *genre, char out[SM_GENRE_CODE_LEN + 1u]) {
    size_t written = 0;
    if (!out) return;
    out[0] = '\0';
    if (!genre || !genre[0]) return;
    for (size_t i = 0; i < sizeof(NAMED) / sizeof(*NAMED); i++) {
        if (!strcmp(genre, NAMED[i].name)) {
            memcpy(out, NAMED[i].code, SM_GENRE_CODE_LEN + 1u);
            return;
        }
    }
    for (const char *c = genre; *c && written < SM_GENRE_CODE_LEN; c++) {
        if (*c >= 'a' && *c <= 'z') out[written++] = (char)(*c - 'a' + 'A');
        else if ((*c >= 'A' && *c <= 'Z') || (*c >= '0' && *c <= '9')) out[written++] = *c;
    }
    out[written] = '\0';
}

/* FNV-1a over the name. Hashing rather than counting off tab positions is what
   keeps a genre's colour the same in the tab strip, beside a row, on a grid
   tile and in the filter screen. */
unsigned sm_genre_colour_index(const char *genre, unsigned palette_size) {
    uint32_t hash = 2166136261u;
    if (!palette_size) return 0u;
    if (!genre || !genre[0]) return 0u;
    for (const char *c = genre; *c; c++) {
        hash ^= (uint32_t)(unsigned char)*c;
        hash *= 16777619u;
    }
    return (unsigned)(hash % palette_size);
}

void sm_genre_build_tabs(const sm_catalog_t *catalog, sm_genre_tabs_t *out) {
    uint32_t i, slot;
    if (!out) return;
    memset(out, 0, sizeof(*out));
    out->tabs[0].name[0] = '\0';
    memcpy(out->tabs[0].code, "ALL", 4);
    out->count = 1u;
    if (!catalog) return;

    /* One pass, counting every genre on the card -- all of them, not the
       first eight met, or the tabs would depend on the order the catalog
       happens to be in and the rest of the library would be unreachable. */
    for (i = 0; i < catalog->count; i++) {
        sm_game_t game;
        if (!catalog_get(catalog, i, &game) || !game.genre[0]) continue;
        slot = 1u;
        while (slot < out->count && strcmp(out->tabs[slot].name, game.genre)) slot++;
        if (slot < out->count) { out->tabs[slot].count++; continue; }
        if (out->count >= SM_GENRE_TABS_MAX) continue;
        snprintf(out->tabs[slot].name, sizeof(out->tabs[slot].name), "%s", game.genre);
        sm_genre_code(game.genre, out->tabs[slot].code);
        out->tabs[slot].count = 1u;
        out->count++;
    }
    out->tabs[0].count = catalog->count;

    /* Most common first, so the genres worth cycling to come first. The "all"
       tab stays put at index 0. */
    for (i = 1u; i + 1u < out->count; i++)
        for (slot = i + 1u; slot < out->count; slot++)
            if (out->tabs[slot].count > out->tabs[i].count) {
                sm_genre_tab_t swap = out->tabs[i];
                out->tabs[i] = out->tabs[slot];
                out->tabs[slot] = swap;
            }
}

uint32_t sm_genre_tab_window(uint32_t active, uint32_t count, uint32_t visible) {
    uint32_t first;
    if (!visible || count <= visible) return 0u;
    if (active >= count) active = count - 1u;
    /* Centred, then clamped. Centring alone walks off the right-hand end and
       leaves the last tabs undrawable; clamping alone pins the window to the
       left until the selection reaches the edge, which makes the strip look
       stuck. */
    first = active > visible / 2u ? active - visible / 2u : 0u;
    if (first + visible > count) first = count - visible;
    return first;
}
