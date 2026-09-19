/* SPDX-License-Identifier: AGPL-3.0-only */
#include "ui.h"
#include "card_paths.h"
#include <stdlib.h>
#include "list_view.h"
#include "launch.h"
#include "flashcart.h"
#include "rom_db.h"
#include <libdragon.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

enum { FILTER_ROWS = 6 };

/* Where the card keeps its art. Named rather than spelled out at the one call
   site so the host test can point the browser at a directory it can create;
   the ROM build never defines it. */
#ifndef SM_COVER_PACK_PATH

#endif
#define FONT_WIDTH SM_FONT_WIDTH
/* The launch card's value column: past a label of up to five letters
   ("NEEDS"), or seven ("CHEATS" plus one), and a small gap. */
#define LABEL_COLUMN (5 * SM_FONT_WIDTH + 4)
#define LABEL_COLUMN_WIDE (7 * SM_FONT_WIDTH + 4)
#define COVER_WIDTH SM_COVER_WIDTH
#define COVER_HEIGHT SM_COVER_HEIGHT

static void draw_truncated(surface_t *surface, int x, int y, const char *text, int max_chars) {
    char line[64];
    if (max_chars < 1) return;
    if (max_chars >= (int)sizeof(line)) max_chars = sizeof(line) - 1;
    size_t length = strlen(text);
    size_t copy = length < (size_t)max_chars ? length : (size_t)max_chars;
    memcpy(line, text, copy);
    if (length > copy && copy >= 3) memcpy(line + copy - 3, "...", 3);
    line[copy] = '\0';
    graphics_draw_text(surface, x, y, line);
}

/* A paragraph, wrapped on spaces to fit `max_chars` columns, at most
   `max_lines` lines. Text that does not fit ends in "..." on its last line
   rather than being clipped mid-word. A word longer than a line is broken
   where the line ends, which a box back never needs but a hack's description
   might. Returns the number of lines drawn. */
static int draw_wrapped(surface_t *surface, int x, int y, int line_height,
    const char *text, int max_chars, int max_lines) {
    char line[64];
    int lines = 0;
    const char *at = text;

    if (max_chars < 4 || max_lines < 1) return 0;
    if (max_chars >= (int)sizeof(line)) max_chars = sizeof(line) - 1;
    while (*at == ' ') at++;
    while (*at && lines < max_lines) {
        size_t remaining = strlen(at);
        size_t take = remaining;
        bool last = lines == max_lines - 1;
        if (take > (size_t)max_chars) {
            take = (size_t)max_chars;
            /* Back up to the last space inside the line, if there is one. */
            size_t cut = take;
            while (cut > 0 && at[cut] != ' ') cut--;
            if (cut > 0) take = cut;
        }
        memcpy(line, at, take);
        line[take] = '\0';
        if (last && take < remaining) {
            /* More to come and no room for it: the ellipsis replaces the
               tail of this line so the reader knows. */
            size_t end = take;
            if (end + 3 > (size_t)max_chars) end = (size_t)max_chars - 3;
            while (end > 0 && line[end - 1] == ' ') end--;
            memcpy(line + end, "...", 4);
        }
        graphics_draw_text(surface, x, y + lines * line_height, line);
        lines++;
        at += take;
        while (*at == ' ') at++;
    }
    return lines;
}

static void draw_status(surface_t *surface, const sm_layout_t *layout, const char *text) {
    int max_chars = (layout->safe_right - layout->safe_left) / FONT_WIDTH;
    char line[64];
    const char *cursor = text;
    for (int row = 0; row < 2 && *cursor; row++) {
        while (*cursor == ' ') cursor++;
        size_t remaining = strlen(cursor), take = remaining < (size_t)max_chars ? remaining : (size_t)max_chars;
        if (remaining > take) {
            size_t split = take;
            while (split > 0 && cursor[split] != ' ') split--;
            if (split > 0) take = split;
        }
        if (take >= sizeof(line)) take = sizeof(line) - 1;
        memcpy(line, cursor, take); line[take] = '\0';
        graphics_draw_text(surface, layout->safe_left, layout->safe_bottom - 18 + row * 9, line);
        cursor += take;
    }
}

typedef struct { sm_ui_t *ui; const sm_catalog_t *catalog; const sm_layout_t *layout; } launch_draw_t;
/* Called once per whole percent of the transfer. The figures are kept on the
   UI rather than passed down, because the thing that draws them is the launch
   card and it is reached through ui_draw() like any other frame. */
static void draw_launch_progress(uint32_t loaded_kib, uint32_t total_kib, void *context) {
    launch_draw_t *draw = context;
    surface_t *surface;
    draw->ui->load_done_kib = loaded_kib;
    draw->ui->load_total_kib = total_kib;
    /* The status line says which pass this is; reading it back beats
       threading another argument through the loader for one bool. */
    draw->ui->load_verifying = strstr(launch_status_message(), "VERIFY") != NULL;
    surface = app_display_begin();
    ui_draw(surface, draw->layout, draw->catalog, draw->ui);
    app_display_end(surface);
}

static void draw_path_tail(surface_t *surface, int x, int y, const char *text, int max_chars) {
    char line[64];
    if (text == NULL || max_chars < 1) return;
    if (max_chars >= (int)sizeof(line)) max_chars = sizeof(line) - 1;
    size_t length = strlen(text);
    if (length <= (size_t)max_chars) {
        memcpy(line, text, length + 1);
    } else if (max_chars >= 3) {
        memcpy(line, "...", 3);
        memcpy(line + 3, text + length - ((size_t)max_chars - 3), (size_t)max_chars - 3);
        line[max_chars] = '\0';
    } else {
        memcpy(line, text + length - (size_t)max_chars, (size_t)max_chars);
        line[max_chars] = '\0';
    }
    graphics_draw_text(surface, x, y, line);
}

void ui_draw_loading(surface_t *s, const sm_layout_t *l, const char *phase,
    const char *note, const sm_discovery_progress_t *progress, unsigned indicator_frame) {
    static const char indicators[] = "|/-\\";
    char line[64];
    int max_chars = (l->safe_right - l->safe_left - 8) / FONT_WIDTH;
    graphics_fill_screen(s, graphics_make_color(8, 12, 20, 255));
    graphics_draw_box(s, l->safe_left, l->safe_top, l->safe_right-l->safe_left, 20,
        graphics_make_color(24, 45, 72, 255));
    graphics_set_color(graphics_make_color(245, 230, 160, 255), 0);
    graphics_draw_text(s, l->safe_left+4, l->safe_top+6, "SLEEKMENU 64");
    graphics_set_color(graphics_make_color(240, 240, 232, 255), 0);
    snprintf(line, sizeof(line), "%c %s", indicators[indicator_frame % 4], phase);
    draw_truncated(s, l->safe_left+4, l->safe_top+38, line, max_chars);
    if (progress != NULL) {
        graphics_set_color(graphics_make_color(180, 200, 220, 255), 0);
        graphics_draw_text(s, l->safe_left+4, l->safe_top+58, "PATH");
        draw_path_tail(s, l->safe_left+4, l->safe_top+69, progress->current_directory, max_chars);
        snprintf(line, sizeof(line), "DIR %lu  FILE %lu  ROM %lu", (unsigned long)progress->directories_scanned,
            (unsigned long)progress->entries_inspected, (unsigned long)progress->roms_found);
        graphics_draw_text(s, l->safe_left+4, l->safe_top+84, line);
    }
    graphics_set_color(graphics_make_color(180, 200, 220, 255), 0);
    draw_status(s, l, note ? note : "");
}

static const char *relative_part(const char *path, const char *folder) {
    if (!folder[0]) return path;
    size_t length = strlen(folder);
    return !strncmp(path, folder, length) && path[length] == '/' ? path + length + 1 : NULL;
}

/* A folder item stores the catalog index of the first game inside it. Its
   display name is the next path component after the folder being browsed --
   never that game's title, which is what made a highlighted folder look as if
   it had already been opened. */
static bool folder_label(const sm_catalog_t *catalog, uint32_t item,
    const char *base, char *out, size_t out_size) {
    sm_game_t game;
    const char *part, *slash;
    size_t length;
    if (!out || out_size < 2u || !(item & SM_UI_FOLDER_BIT)) return false;
    if (!catalog_get(catalog, item & ~SM_UI_FOLDER_BIT, &game)) return false;
    part = relative_part(game.path, base);
    if (!part) return false;
    slash = strchr(part, '/');
    if (!slash) return false;
    length = (size_t)(slash - part);
    if (length >= out_size) length = out_size - 1u;
    memcpy(out, part, length);
    out[length] = '\0';
    return true;
}

static bool same_folder_name(const sm_catalog_t *catalog, uint32_t encoded, const char *name, size_t length, const char *folder) {
    sm_game_t game;
    if (!catalog_get(catalog, encoded & ~SM_UI_FOLDER_BIT, &game)) return false;
    const char *part = relative_part(game.path, folder);
    return part && !strncmp(part, name, length) && part[length] == '/';
}

static void unload_cover(sm_ui_t *ui) {
    if (ui->cover_sprite) sprite_free(ui->cover_sprite);
    ui->cover_sprite = NULL;
    ui->cover_loaded = false;
}

static void unload_slots(sm_ui_t *ui) {
    for (int i = 0; i < SM_UI_SLOTS_MAX; i++) {
        if (ui->slot_sprites[i]) sprite_free(ui->slot_sprites[i]);
        ui->slot_sprites[i] = NULL;
        ui->slot_indices[i] = UINT32_MAX;
        ui->slot_pending[i] = false;
    }
    ui->slot_base = INT32_MIN;
    ui->slot_count = 0u;
}

static bool safe_cover_path(const char *path) {
    if (!path || !path[0] || path[0] == '/' || strchr(path, '\\')) return false;
    size_t length = strlen(path);
    if (length < 7 || strcasecmp(path + length - 7, ".sprite")) return false;
    for (const char *p = path; *p;) {
        const char *slash = strchr(p, '/');
        size_t part = slash ? (size_t)(slash - p) : strlen(p);
        if (part == 0 || (part == 1 && p[0] == '.') || (part == 2 && p[0] == '.' && p[1] == '.')) return false;
        if (!slash) break;
        p = slash + 1;
    }
    return true;
}

/* libdragon's sprite_load() does not return NULL for a missing file: the open
   path in asset.c ends in assertf(fd >= 0, "File not found: %s"), so the caller
   crashes before it can check anything. Existence has to be probed first, which
   is the same idiom app_display_load_font() already uses for the font. A
   catalog can perfectly well name a cover that is not on this card.

   Only the loose-directory fallback needs this. Reading from the pack cannot
   ask for a file that is not there, which is half of why it is faster: this
   probe is a whole second directory walk, paid on every keystroke. */
static bool cover_asset_exists(const char *path) {
    FILE *file = fopen(path, "rb");
    if (!file) return false;
    fclose(file);
    return true;
}

/* Enough of a sprite header to know the bytes are not truncated or garbage.
   sprite_load_buf asserts rather than returning NULL on a malformed sprite,
   so a short read from a damaged pack would take the browser down with it. */
static bool cover_bytes_plausible(const void *data, uint32_t length) {
    const uint8_t *bytes = data;
    uint32_t width, height;
    if (!bytes || length < 16u) return false;
    width = ((uint32_t)bytes[0] << 8) | bytes[1];
    height = ((uint32_t)bytes[2] << 8) | bytes[3];
    if (!width || !height || width > 1024u || height > 1024u) return false;
    /* RGBA16 is what the packer writes; the 8-byte header precedes the pixels
       and the extended block follows them. */
    return 8u + width * height * 2u <= length;
}

static sprite_t *load_item_cover(uint32_t item, const sm_catalog_t *catalog,
    sm_cover_pack_t *pack) {
    if (item & SM_UI_FOLDER_BIT) return NULL;
    /* A ROM load overwrites cartridge SDRAM, taking SleekMenu's own image and
       the DragonFS holding the box art with it. Code and the already-loaded
       font live in RDRAM and survive; rom:/ does not. */
    if (!sm_cart_image_intact()) return NULL;
    uint32_t index = item;
    sm_game_t game;
    if (!catalog_get(catalog, index, &game)) return NULL;
    char path[512];
    /* The catalog names the sprite, and nothing else does. The ROM used to
       carry a copy of the whole matcher and a 915-entry name-to-sprite table
       so that it could guess when the catalog stayed quiet, which cost 10 MB
       and only ever produced right answers for the one art collection that
       generated the table -- for anyone else's covers it resolved to sprite
       numbers that meant nothing. Matching happens once now, on a desktop,
       against tools/coverdb.py, and its answer arrives in the catalog. */
    if (!safe_cover_path(game.cover)) return NULL;

    sprite_t *sprite = NULL;
    if (sm_cover_pack_ready(pack)) {
        uint32_t length = 0u;
        void *bytes = sm_cover_pack_read(pack, game.cover, &length);
        if (!bytes) return NULL;
        if (!cover_bytes_plausible(bytes, length)) { free(bytes); return NULL; }
        /* In place: the buffer IS the sprite, so claiming ownership is what
           makes sprite_free release it. Copying it would double the memory
           and the time for no gain. */
        sprite = sprite_load_buf(bytes, (int)length);
        if (!sprite) { free(bytes); return NULL; }
        sprite->flags |= SPRITE_FLAGS_OWNEDBUFFER;
    } else {
        if (snprintf(path, sizeof(path), SM_COVERS_DIR "/%s", game.cover) >= (int)sizeof(path))
            return NULL;
        if (!cover_asset_exists(path)) return NULL;
        /* sprite_load uses libdragon's asset loader, which validates and
           decompresses DragonFS or SD sprite assets before exposing dimensions. */
        sprite = sprite_load(path);
    }
    if (sprite && !((sprite->width == COVER_WIDTH && sprite->height == COVER_HEIGHT) ||
                    (sprite->width == 64 && sprite->height == 48))) {
        sprite_free(sprite); sprite = NULL;
    }
    return sprite;
}

static void draw_cover(surface_t *surface, int x, int y, sprite_t *sprite) {
    graphics_draw_sprite_trans(surface, x + (COVER_WIDTH - sprite->width) / 2,
        y + (COVER_HEIGHT - sprite->height) / 2, sprite);
}

/* Nearest-neighbour, straight into the framebuffer. The alternative was a
   second set of art at tile size, which would have doubled what the ROM
   carries for a view most people pass through. Twelve tiles is about 37,000
   pixels a frame, which is a few milliseconds of plain stores. */
static void draw_cover_scaled(surface_t *dst, int x, int y, sprite_t *sprite,
    int width, int height) {
    surface_t src = sprite_get_pixels(sprite);
    if (surface_get_format(dst) != FMT_RGBA16 || surface_get_format(&src) != FMT_RGBA16) {
        graphics_draw_box(dst, x, y, width, height, graphics_make_color(35, 42, 52, 255));
        return;
    }
    if (x < 0 || y < 0 || x + width > dst->width || y + height > dst->height) return;
    for (int row = 0; row < height; row++) {
        uint16_t *out = (uint16_t *)((uint8_t *)dst->buffer + (size_t)(y + row) * dst->stride) + x;
        const uint16_t *in = (const uint16_t *)((const uint8_t *)src.buffer +
            (size_t)(row * sprite->height / height) * src.stride);
        for (int col = 0; col < width; col++) out[col] = in[col * sprite->width / width];
    }
}

/* Halve or quarter a colour without leaving RGBA16. The channels are five bits
   each at 11, 6 and 1, so they have to be shifted apart and back: shifting the
   whole word bleeds each channel's low bit into the one below it. */
static uint16_t dim_rgba16(uint16_t pixel, unsigned shift) {
    unsigned r = ((pixel >> 11) & 31u) >> shift;
    unsigned g = ((pixel >> 6) & 31u) >> shift;
    unsigned b = ((pixel >> 1) & 31u) >> shift;
    return (uint16_t)((r << 11) | (g << 6) | (b << 1) | (pixel & 1u));
}

/* One cover, rotated about its vertical axis.

   Each output column gets its own height and its own slice of the source, both
   from sm_flow_* in list_view.c -- arithmetic a host can check, kept out of
   the drawing loop for that reason. What is left here is memory movement.

   near_height is the edge towards the middle of the screen, far_height the one
   towards the edge; equal heights give the centre cover, face on. */
static void draw_cover_turned(surface_t *dst, int x, int centre_y,
    const surface_t *source, int width, int near_height, int far_height,
    bool near_left, int reflection) {
    surface_t src;
    int col, src_width, src_height;
    if (!source || !source->buffer || width < 2) return;
    src = *source;
    src_width = (int)src.width;
    src_height = (int)src.height;
    if (src_width < 1 || src_height < 1) return;
    if (surface_get_format(dst) != FMT_RGBA16 || surface_get_format(&src) != FMT_RGBA16) return;

    for (col = 0; col < width; col++) {
        /* Distance along the card from its near edge, so the maths below is
           always written near-to-far whichever way the card faces. */
        int step = near_left ? col : width - 1 - col;
        int height = sm_flow_column_height(near_height, far_height, width, step);
        int top = centre_y - height / 2;
        int src_x, row, out_x = x + col;
        int visible_from, visible_to;
        if (height < 2) continue;
        if (out_x < 0 || out_x >= dst->width) continue;

        src_x = sm_flow_source_column(src_width, width, far_height, step, height);
        if (!near_left) src_x = src_width - 1 - src_x;

        /* Clipped once per column rather than tested per pixel. */
        visible_from = top < 0 ? -top : 0;
        visible_to = top + height > dst->height ? dst->height - top : height;

        for (row = visible_from; row < visible_to; row++) {
            const uint16_t *in = (const uint16_t *)((const uint8_t *)src.buffer +
                (size_t)(row * src_height / height) * src.stride);
            uint16_t *out = (uint16_t *)((uint8_t *)dst->buffer +
                (size_t)(top + row) * dst->stride) + out_x;
            *out = in[src_x];
        }

        /* The reflection: the same column mirrored below the card, fading out
           over `reflection` rows. Shelf lighting is what stops seven covers on
           a dark field from looking like seven stickers. */
        for (row = 0; row < reflection; row++) {
            int y = top + height + row;
            int source_row = height - 1 - row * height / (reflection ? reflection : 1);
            const uint16_t *in;
            uint16_t *out;
            unsigned shift = 1u + (unsigned)(row * 2 / (reflection ? reflection : 1));
            if (y < 0 || y >= dst->height) break;
            if (source_row < 0) break;
            if (shift > 4u) break;      /* past here it is black anyway */
            in = (const uint16_t *)((const uint8_t *)src.buffer +
                (size_t)(source_row * src_height / height) * src.stride);
            out = (uint16_t *)((uint8_t *)dst->buffer + (size_t)y * dst->stride) + out_x;
            *out = dim_rgba16(in[src_x], shift);
        }
    }
}

/* One 64-byte read of the highlighted ROM, resolved through the same database
   the launcher uses. The catalog cannot carry these: its records predate the
   save work, and a hack no database knows still has a real header. */
void sm_format_rom_size(uint32_t bytes, char *out, size_t size) {
    uint32_t whole, tenths;
    if (!out || !size) return;
    if (!bytes) { snprintf(out, size, "-"); return; }
    if (bytes < (1u << 20)) {
        snprintf(out, size, "%u KB", (unsigned)((bytes + 1023u) >> 10));
        return;
    }
    whole = bytes >> 20;
    /* One decimal, rounded, without floating point: the console has an FPU but
       there is no reason to start the library for this. */
    tenths = (uint32_t)((((uint64_t)(bytes & 0xFFFFFu) * 10u) + (1u << 19)) >> 20);
    if (tenths >= 10u) { whole++; tenths = 0u; }
    if (tenths) snprintf(out, size, "%u.%u MB", (unsigned)whole, (unsigned)tenths);
    else snprintf(out, size, "%u MB", (unsigned)whole);
}

static void load_selected_details(sm_ui_t *ui, const sm_catalog_t *catalog) {
    uint8_t header[SM_SAVE_MIN_HEADER] __attribute__((aligned(8)));
    sm_launch_paths_t paths;
    sm_game_t game;
    FILE *file;
    const sm_rom_db_entry_t *entry;

    ui->selected_details_loaded = false;
    ui->selected_save = SM_SAVE_OFF;
    ui->selected_features = 0u;
    ui->selected_size = 0u;
    ui->selected_disk = false;
    if (!ui->item_count || (ui->items[ui->selected] & SM_UI_FOLDER_BIT)) return;
    if (!catalog_get(catalog, ui->items[ui->selected], &game)) return;
    if (!launch_resolve_paths(game.path, &paths)) return;
    file = fopen(paths.primary, "rb");
    if (!file && paths.count > 1) file = fopen(paths.fallback, "rb");
    if (!file) return;
    /* The file is open anyway; asking how big it is costs a seek. */
    if (!fseek(file, 0, SEEK_END)) {
        long end = ftell(file);
        if (end > 0) ui->selected_size = (uint32_t)end;
    }
    rewind(file);
    if (launch_suffix_is_disk(game.path)) {
        /* A 64DD image has no cartridge header: the disk is its own save,
           and there is nothing to look up. */
        ui->selected_disk = true;
        ui->selected_details_loaded = true;
    } else if (fread(header, 1, sizeof(header), file) == sizeof(header)) {
        sm_rom_format_t format = sm_rom_format_detect(header, sizeof(header));
        if (format != SM_ROM_FORMAT_UNKNOWN) {
            sm_rom_header_normalise(header, sizeof(header), format);
            entry = sm_rom_db_lookup(header, sizeof(header));
            if (entry) {
                ui->selected_save = (sm_save_type_t)entry->save;
                ui->selected_features = entry->feat;
            }
            ui->selected_details_loaded = true;
        }
    }
    fclose(file);
}

static void load_selected_cover(sm_ui_t *ui, const sm_catalog_t *catalog) {
    unload_cover(ui);
    if (ui->item_count == 0 || (ui->items[ui->selected] & SM_UI_FOLDER_BIT)) return;
    ui->cover_loaded = true;
    ui->cover_index = ui->items[ui->selected];
    ui->cover_sprite = load_item_cover(ui->items[ui->selected], catalog, &ui->covers);
}

/* Point the slots at the current window, carrying over any sprite already
   loaded for an item that is still on screen. Pure bookkeeping: it touches no
   files, so it can run the same frame the scroll happened. Without it a
   one-row scroll would free all twelve sprites and read all twelve back,
   eight of which are the same pictures. */
static void sync_slots(sm_ui_t *ui, int32_t base, uint32_t count) {
    sprite_t *held[SM_UI_SLOTS_MAX];
    uint32_t held_index[SM_UI_SLOTS_MAX];
    bool taken[SM_UI_SLOTS_MAX];
    uint32_t slot, other;
    if (count > SM_UI_SLOTS_MAX) count = SM_UI_SLOTS_MAX;
    /* Everything the outgoing window held, including slots the incoming one
       does not use: switching from the grid's twelve to coverflow's seven has
       to release the other five rather than lose them. */
    for (slot = 0; slot < SM_UI_SLOTS_MAX; slot++) {
        held[slot] = ui->slot_sprites[slot];
        held_index[slot] = ui->slot_indices[slot];
        taken[slot] = false;
        ui->slot_sprites[slot] = NULL;
        ui->slot_indices[slot] = UINT32_MAX;
        ui->slot_pending[slot] = false;
    }
    for (slot = 0; slot < count; slot++) {
        int32_t pos = base + (int32_t)slot;
        uint32_t item = (pos >= 0 && (uint32_t)pos < ui->item_count)
            ? ui->items[(uint32_t)pos] : UINT32_MAX;
        ui->slot_indices[slot] = item;
        ui->slot_pending[slot] = item != UINT32_MAX;
        if (item == UINT32_MAX) continue;
        for (other = 0; other < SM_UI_SLOTS_MAX; other++) {
            if (taken[other] || held_index[other] != item) continue;
            ui->slot_sprites[slot] = held[other];
            taken[other] = true;
            ui->slot_pending[slot] = false;
            break;
        }
    }
    for (other = 0; other < SM_UI_SLOTS_MAX; other++)
        if (!taken[other] && held[other]) sprite_free(held[other]);
    ui->slot_base = base;
    ui->slot_count = count;
}

/* One tile per frame. Twelve covers is about a fifth of a second of card
   reads, and doing them all at once is a fifth of a second in which the
   controller does nothing. */
static void load_slot_step(sm_ui_t *ui, const sm_catalog_t *catalog) {
    for (uint32_t slot = 0; slot < ui->slot_count; slot++) {
        if (!ui->slot_pending[slot]) continue;
        ui->slot_pending[slot] = false;
        ui->slot_sprites[slot] = load_item_cover(ui->slot_indices[slot], catalog, &ui->covers);
        return;
    }
}

/* The first character of an item's title, folded and reduced to a bucket:
   letters are themselves, everything else -- digits, brackets, the sort
   prefixes people put on ROM filenames -- shares one bucket ahead of A. That
   keeps "007 GoldenEye", "1080 Snowboarding" and "[BETA] whatever" together
   rather than giving each its own stop. */
static char flow_initial(const sm_catalog_t *catalog, uint32_t item) {
    sm_game_t game;
    char c;
    if (item & SM_UI_FOLDER_BIT) return '#';
    if (!catalog_get(catalog, item, &game) || !game.title[0]) return '#';
    c = game.title[0];
    if (c >= 'a' && c <= 'z') c = (char)(c - 32);
    return (c >= 'A' && c <= 'Z') ? c : '#';
}

/* The next item whose initial differs from the current one, in the given
   direction. Stops at the ends rather than wrapping: coverflow has visible
   ends, and a jump that silently teleported to the other one would read as a
   glitch. */
static uint32_t flow_letter_jump(const sm_ui_t *ui, const sm_catalog_t *catalog,
    int direction) {
    char from;
    uint32_t at = ui->selected;
    if (!ui->item_count) return 0u;
    from = flow_initial(catalog, ui->items[at]);
    if (direction > 0) {
        for (uint32_t i = at + 1u; i < ui->item_count; i++)
            if (flow_initial(catalog, ui->items[i]) != from) return i;
        return ui->item_count - 1u;
    }
    /* Backwards means the start of the previous group, not its end: pressing
       L twice from the middle of M should reach the first L, not the last. */
    while (at > 0u && flow_initial(catalog, ui->items[at - 1u]) == from) at--;
    if (at == 0u) return 0u;
    at--;
    from = flow_initial(catalog, ui->items[at]);
    while (at > 0u && flow_initial(catalog, ui->items[at - 1u]) == from) at--;
    return at;
}

/* Put the window around the selection. Used after a jump the arrow-key path
   did not make, where first_visible has no relationship to selected yet. */
static void focus_selected(sm_ui_t *ui, const sm_layout_t *layout) {
    bool grid = ui->view == SM_VIEW_GRID;
    uint32_t visible = grid ? SM_UI_GRID_VISIBLE : (uint32_t)layout->visible_rows;
    ui->first_visible = sm_view_focus(ui->selected, visible, ui->item_count,
        grid ? SM_UI_GRID_COLUMNS : 1u);
}

/* The folder every game is under: the longest run of leading path components
   shared by every path in the catalog. Empty when the games are spread over
   two top-level folders or some sit at the root. Component by component, so
   "ROMS/N64/..." on every game opens inside ROMS/N64. */
static void find_library_root(const sm_catalog_t *catalog, char *root, size_t size) {
    sm_game_t first;
    size_t depth = 0;
    root[0] = '\0';
    if (!catalog->count || !catalog_get(catalog, 0, &first)) return;
    for (;;) {
        const char *slash = strchr(first.path + depth, '/');
        size_t candidate;
        bool shared = true;
        if (!slash) break;
        candidate = (size_t)(slash - first.path);
        for (uint32_t i = 1; i < catalog->count && shared; i++) {
            sm_game_t game;
            if (!catalog_get(catalog, i, &game) ||
                strncmp(game.path, first.path, candidate + 1u) != 0) shared = false;
        }
        if (!shared || candidate + 1u > size) break;
        depth = candidate + 1u;
    }
    if (depth) snprintf(root, size, "%.*s", (int)(depth - 1u), first.path);
}

/* The folder as the header shows it: relative to the root, so a card whose
   library is all under ROMS/ shows "/" at the top and "/1 US" inside, not
   "/ROMS/1 US". */
static const char *folder_for_display(const sm_ui_t *ui) {
    size_t root_length = strlen(ui->root);
    if (!root_length || strncmp(ui->folder, ui->root, root_length)) return ui->folder;
    return ui->folder[root_length] == '/' ? ui->folder + root_length + 1 : ui->folder + root_length;
}

/* Backing out of a folder should land on the folder just left, not on the top
   of the parent -- otherwise every step back loses your place. */
static void select_folder_named(sm_ui_t *ui, const sm_catalog_t *catalog,
    const char *name, const sm_layout_t *layout) {
    char label[64];
    if (!name[0]) return;
    for (uint32_t i = 0; i < ui->item_count; i++) {
        if (!folder_label(catalog, ui->items[i], ui->folder, label, sizeof(label))) continue;
        if (strcmp(label, name)) continue;
        ui->selected = i;
        /* Correct today only because the one caller rebuilds first, which is
           exactly the shape settle_on_a_new_list() exists to stop repeating. */
        ui->flow_frames = 0;
        focus_selected(ui, layout);
        unload_cover(ui);
        unload_slots(ui);
        return;
    }
}

/* The catalog's favourite flag is what the card was built with; the file on
   the card is what has been pressed since. The file wins, which is what makes
   a favourite survive rebuilding the catalog. */
static bool item_matches(const sm_ui_t *ui, sm_game_t *game) {
    if (sm_favorites_contains(&ui->favorites, game->path)) game->flags |= SM_FLAG_FAVORITE;
    else game->flags &= (uint8_t)~SM_FLAG_FAVORITE;
    return catalog_matches(game, &ui->filter);
}

/* Folders first, then the games in this folder -- unless the view is flat, in
   which case there are no folders at all and every match is listed wherever it
   lives. A shortlist that only showed the favourites in the folder you happen
   to be standing in would not be a shortlist. */
enum { SM_STRIP_ALL = 0u, SM_STRIP_FAVORITES = 1u, SM_STRIP_HISTORY = 2u,
       SM_STRIP_GENRE_BASE = 3u };

/* Everything that has to be true after the item list changes under the
   cursor. Written once because it was written twice: history's own rebuild
   path had its own copy, and the copy is where a later addition -- clearing
   the coverflow slide -- was missed. */
static void settle_on_a_new_list(sm_ui_t *ui) {
    ui->selected = 0;
    ui->first_visible = 0;
    ui->marquee = 0;
    ui->status = NULL;
    ui->settle = SM_UI_SETTLE_FRAMES;
    /* A slide describes a step from one shelf to the next one along. After a
       rebuild there is no previous shelf to have come from. */
    ui->flow_frames = 0;
    unload_cover(ui);
    unload_slots(ui);
}

/* History is the one view that is not in catalog order, so it gets its own
   pass. One walk of the catalog asking each game where it sits in the list,
   dropped into a slot by that position -- rather than fifteen walks looking
   for one path each. Gaps are left by games that have since come off the
   card, and compacted away afterwards. */
static void rebuild_history(sm_ui_t *ui, const sm_catalog_t *catalog) {
    uint32_t slots[SM_HISTORY_MAX];
    uint32_t i;
    for (i = 0; i < SM_HISTORY_MAX; i++) slots[i] = UINT32_MAX;
    for (i = 0; i < catalog->count; i++) {
        sm_game_t game;
        int32_t at;
        if (!catalog_get(catalog, i, &game) || !item_matches(ui, &game)) continue;
        at = sm_history_position(&ui->history, game.path);
        if (at >= 0 && (uint32_t)at < SM_HISTORY_MAX) slots[at] = i;
    }
    for (i = 0; i < SM_HISTORY_MAX && ui->item_count < SM_UI_MAX_ITEMS; i++)
        if (slots[i] != UINT32_MAX) ui->items[ui->item_count++] = slots[i];
}

static void rebuild(sm_ui_t *ui, const sm_catalog_t *catalog) {
    ui->item_count = 0;
    if (ui->genre_tab == SM_STRIP_HISTORY) {
        rebuild_history(ui, catalog);
        settle_on_a_new_list(ui);
        return;
    }
    if (!ui->flat) {
        for (uint32_t i = 0; i < catalog->count && ui->item_count < SM_UI_MAX_ITEMS; i++) {
            sm_game_t game;
            if (!catalog_get(catalog, i, &game) || !item_matches(ui, &game)) continue;
            const char *part = relative_part(game.path, ui->folder);
            if (!part) continue;
            const char *slash = strchr(part, '/');
            if (slash) {
                bool found = false;
                for (uint32_t j = 0; j < ui->item_count; j++)
                    if ((ui->items[j] & SM_UI_FOLDER_BIT) && same_folder_name(catalog, ui->items[j], part, (size_t)(slash - part), ui->folder)) found = true;
                if (!found) ui->items[ui->item_count++] = i | SM_UI_FOLDER_BIT;
            }
        }
    }
    for (uint32_t i = 0; i < catalog->count && ui->item_count < SM_UI_MAX_ITEMS; i++) {
        sm_game_t game;
        if (!catalog_get(catalog, i, &game) || !item_matches(ui, &game)) continue;
        const char *part = relative_part(game.path, ui->folder);
        if (!part) continue;
        if (ui->flat || !strchr(part, '/')) ui->items[ui->item_count++] = i;
    }
    settle_on_a_new_list(ui);
}

/* The tab strip describes the whole card, not the folder being browsed: a
   genre that vanishes on entering a subfolder would make the tabs jump about
   under the cursor. Rebuilt only when the catalog itself changes. */
/* The strip the browser cycles is not quite the genre list: ALL, then
   FAVOURITES, then every genre. Favourites is a subset like any other, and
   putting it here is what makes "show me my list" one button rather than five
   presses down a filter screen -- which is where it was, and which is why
   nobody could find it. The genre table itself stays pure genre data; the
   offset lives here. */
/* Every genre, plus the fixed tabs that are not genres. tabs[0] doubles as
   the "all" tab, so the total is the genre count plus one per extra fixed
   tab -- favourites and history. */
static uint32_t strip_count(const sm_ui_t *ui) {
    return ui->genres.count + (SM_STRIP_GENRE_BASE - 1u);
}

static const sm_genre_tab_t *strip_genre(const sm_ui_t *ui, uint32_t index) {
    if (index == SM_STRIP_ALL) return &ui->genres.tabs[0];
    if (index < SM_STRIP_GENRE_BASE) return NULL;   /* favourites, history */
    /* tabs[0] is the "all" tab, already answered above, so the genres proper
       start at tabs[1] -- which is SM_STRIP_GENRE_BASE - 1 strip slots along.
       Getting this offset wrong silently turns the last genre into a second
       favourites tab, so it is derived rather than written out. */
    {
        uint32_t at = index - (SM_STRIP_GENRE_BASE - 1u);
        return at < ui->genres.count ? &ui->genres.tabs[at] : NULL;
    }
}

static void ensure_genre_tabs(sm_ui_t *ui, const sm_catalog_t *catalog) {
    if (ui->genres.count) return;
    sm_genre_build_tabs(catalog, &ui->genres);
    if (ui->genre_tab >= strip_count(ui)) ui->genre_tab = 0;
}

/* One subset at a time from the strip. The filter screen is still where a
   combination is built -- favourite racing games for two players -- and when
   one is active the strip marks the favourites tab as well as the genre. */
static void apply_strip_tab(sm_ui_t *ui, const sm_catalog_t *catalog, uint32_t index) {
    const sm_genre_tab_t *tab = strip_genre(ui, index);
    /* Both shortlists are flat. Standing in a folder and being shown only the
       favourites that happen to live in it is not a shortlist, and the same
       goes for the last fifteen games you played. */
    bool wanted_flat = index == SM_STRIP_FAVORITES || index == SM_STRIP_HISTORY;
    if (wanted_flat && !ui->flat) {
        /* Step out of the folder tree, remembering where we were: dipping into
           the shortlist and coming back to the same shelf is the whole point
           of it being one button away. */
        snprintf(ui->folder_before_flat, sizeof(ui->folder_before_flat), "%s", ui->folder);
        ui->folder[0] = '\0';
    } else if (!wanted_flat && ui->flat) {
        snprintf(ui->folder, sizeof(ui->folder), "%s", ui->folder_before_flat);
        ui->folder_before_flat[0] = '\0';
    }
    ui->flat = wanted_flat;
    ui->genre_tab = index;
    ui->filter.favorites_only = index == SM_STRIP_FAVORITES;
    ui->filter.genre = (tab && tab->name[0]) ? tab->name : NULL;
    rebuild(ui, catalog);
}

static void select_genre_tab(sm_ui_t *ui, const sm_catalog_t *catalog, int direction) {
    uint32_t count = strip_count(ui);
    if (count < 2u) return;
    apply_strip_tab(ui, catalog,
        (ui->genre_tab + (direction > 0 ? 1u : count - 1u)) % count);
}

/* The next distinct value in alphabetical order, or NULL for "Any".

   Alphabetical rather than storage order, so the list reads the way a list
   should; and "Any" is one step away in either direction, so clearing the
   filter on a card with two hundred publishers is one press, not two
   hundred. */
static const char *next_text_value(const sm_catalog_t *catalog, const char *current, bool publisher, int direction) {
    const char *best = NULL;
    if (!catalog->count) return NULL;
    for (uint32_t i = 0; i < catalog->count; i++) {
        sm_game_t game;
        const char *value;
        if (!catalog_get(catalog, i, &game)) continue;
        value = publisher ? game.publisher : game.genre;
        if (!value[0]) continue;
        if (current) {
            /* Strictly past the current one, in the direction of travel. */
            int order = strcmp(value, current);
            if (direction > 0 ? order <= 0 : order >= 0) continue;
        }
        /* Nearest such value, so nothing in between is skipped. */
        if (!best || (direction > 0 ? strcmp(value, best) < 0 : strcmp(value, best) > 0))
            best = value;
    }
    return best;
}

/* The next year in numeric order, or 0 for "Any". Same story as above: a
   filter you cannot clear is a filter you cannot use. */
static uint16_t next_year(const sm_catalog_t *catalog, uint16_t current, int direction) {
    uint16_t best = 0;
    for (uint32_t i = 0; i < catalog->count; i++) {
        sm_game_t game;
        if (!catalog_get(catalog, i, &game) || !game.year) continue;
        if (current) {
            if (direction > 0 ? game.year <= current : game.year >= current) continue;
        }
        if (!best || (direction > 0 ? game.year < best : game.year > best))
            best = game.year;
    }
    return best;
}

static void change_filter(sm_ui_t *ui, const sm_catalog_t *catalog, int direction) {
    switch (ui->filter_row) {
        /* The same cursor the tab strip moves, so the two screens can never
           disagree about which genre is selected. */
        case 0: select_genre_tab(ui, catalog, direction); break;
        case 1: { static const uint8_t v[] = {0, SM_REGION_USA, SM_REGION_JAPAN, SM_REGION_EUROPE};
            int at = 0; for (int i=0;i<4;i++) if (v[i] == ui->filter.regions) at=i;
            ui->filter.regions = v[(at + (direction > 0 ? 1 : 3)) % 4]; break; }
        case 2: ui->filter.players = (uint8_t)((ui->filter.players + (direction > 0 ? 1 : 4)) % 5); break;
        case 3: ui->filter.publisher = next_text_value(catalog, ui->filter.publisher, true, direction); break;
        case 4: ui->filter.year = next_year(catalog, ui->filter.year, direction); break;
        /* Favourites alone is the FAV tab, flat and card-wide; favourites
           with a genre is a composition the strip cannot show, so it stays
           folder-scoped and only marks the tab. Both directions have to land
           in the same state the strip would, or the two screens disagree
           about what is being filtered. */
        case 5:
            if (ui->filter.favorites_only) {
                if (ui->flat) apply_strip_tab(ui, catalog, SM_STRIP_ALL);
                else ui->filter.favorites_only = false;
            } else if (!ui->filter.genre) {
                apply_strip_tab(ui, catalog, SM_STRIP_FAVORITES);
            } else {
                ui->filter.favorites_only = true;
            }
            break;
    }
    /* The header counts what the filter would show. Leaving it until the
       screen closes meant composing a filter blind, which is when the count
       is worth the most. Some branches above rebuilt already; one more pass
       over the catalog is a few milliseconds and not worth threading a flag
       through to avoid. */
    rebuild(ui, catalog);
}

/* Why the enabled cheats would not run, or NULL. Shown on the card and at
   the top of the page, because the engine itself says nothing: it boots the
   game clean and leaves the player to wonder. */
static const char *cheat_warning(void) {
    if (!launch_cheats_possible()) return "No Expansion Pak: cheats need one";
    switch (launch_cheats_hook()) {
    case SM_CHEATS_HOOK_OK: return NULL;
    case SM_CHEATS_HOOK_UNKNOWN_CIC: return "Not a retail boot code: cheats can't hook it";
    default: return "Boot code can't be hooked: cheats won't run";
    }
}

/* How sure the match is, when it is not sure: a PAL cartridge given the
   Europe file, or a file the pack never said the region of. */
static const char *cheat_region_note(void) {
    static char note[64];
    const sm_cheat_source_t *source = launch_cheats_source();
    switch (source->kind) {
    case SM_CHEAT_MATCH_PAL:
        snprintf(note, sizeof(note), "Europe codes, cartridge is %s",
            sm_region_name(source->rom_region));
        return note;
    case SM_CHEAT_MATCH_UNVERIFIED:
        return "No region tag: codes may be another region's";
    default:
        return NULL;
    }
}

/* Why C-down opened nothing. */
static const char *cheat_absent_status(void) {
    static char status[96];
    const sm_cheat_source_t *source = launch_cheats_source();
    if (source->kind == SM_CHEAT_MATCH_OTHER_REGION) {
        char found[48];
        sm_region_list(source->found, found, sizeof(found));
        snprintf(status, sizeof(status), "Cheat pack has this game for %s; yours is %s", found,
            source->rom_region ? sm_region_name(source->rom_region) : "unknown");
        return status;
    }
    if (launch_cheat_pack()->count == 0)
        return "No cheat pack on the card (" SM_FIRMWARE_FOLDER "/CHEATS), nothing in "
            SM_CARD_FOLDER "/cheats";
    snprintf(status, sizeof(status), "Not in the cheat pack (%lu files) or " SM_CARD_FOLDER "/cheats",
        (unsigned long)launch_cheat_pack()->count);
    return status;
}

/* Entries that fit on the cheats page between its header -- and the lines
   under it naming the file and carrying the notes -- and its footer. */
static uint32_t cheat_rows(const sm_layout_t *l) {
    int height = l->footer_top - 4 - (l->safe_top + SM_HEADER_HEIGHT + 6);
    int taken = 1 + (cheat_region_note() ? 1 : 0) + (cheat_warning() ? 1 : 0);
    int rows = height / 11 - taken;
    return rows > 1 ? (uint32_t)rows : 1u;
}

void ui_update(sm_ui_t *ui, const sm_catalog_t *catalog, sm_actions_t actions, const sm_layout_t *layout) {
    if (!ui->initialized) {
        ui->initialized = true;
        /* The first run has no file, so the catalog's own flags become the
           starting set and are written out. After that the file is the truth
           and the catalog's flags are history. */
        /* Opened once and held: after this, a cover costs a seek and a read
           rather than a walk through a directory of 745 long filenames. */
        sm_cover_pack_open(&ui->covers, SM_COVER_PACK_PATH);
        sm_favorites_load(&ui->favorites, SM_FAVORITES_PATH);
        sm_history_load(&ui->history, SM_HISTORY_PATH);
        /* The launcher writes the entry itself, at the point of no return. */
        launch_set_history(&ui->history);
        if (!ui->favorites.present) {
            for (uint32_t i = 0; i < catalog->count; i++) {
                sm_game_t game;
                if (catalog_get(catalog, i, &game) && (game.flags & SM_FLAG_FAVORITE))
                    sm_favorites_add(&ui->favorites, game.path);
            }
            if (ui->favorites.count) sm_favorites_save(&ui->favorites, SM_FAVORITES_PATH);
        }
        find_library_root(catalog, ui->root, sizeof(ui->root));
        snprintf(ui->folder, sizeof(ui->folder), "%s", ui->root);
        rebuild(ui, catalog);
    }
    ensure_genre_tabs(ui, catalog);
    ui->marquee++;
    /* Before any early return. The settle delay and the launch card both bail
       out of this function, and a slide frozen half way through because the
       controller stopped is worse than no slide at all. */
    if (ui->flow_frames) ui->flow_frames--;
    if (ui->screen == SM_SCREEN_LAUNCH_DETAILS) {
        if (actions.back) {
            if (ui->diagnostics) { ui->diagnostics = false; return; }
            launch_cancel(); ui->screen = SM_SCREEN_LIBRARY;
            ui->status = launch_status_message();
            return;
        }
        if (actions.toggle_view)
            launch_set_boot_mode(launch_boot_mode() == SM_BOOT_FAST ? SM_BOOT_VERIFY : SM_BOOT_FAST);
        if (actions.filter) ui->diagnostics = !ui->diagnostics;
        if (actions.favorite && !ui->diagnostics) {
            if (launch_cheats_available()) {
                ui->screen = SM_SCREEN_CHEATS;
                ui->cheat_row = 0;
                ui->cheat_first = 0;
            } else {
                ui->status = cheat_absent_status();
            }
            return;
        }
        /* The transport probe reads one sector into scratch space well clear
           of the image and reports what came back. It belongs with the other
           numbers, not on the way in to a game. */
        if (ui->diagnostics && (actions.left || actions.right) && launch_selected_path()[0]) {
            launch_probe();
            ui->status = launch_status_message();
        }
        if (actions.start && launch_selected_path()[0]) {
            launch_draw_t draw = { ui, catalog, layout };
            ui->load_done_kib = 0;
            ui->load_total_kib = 0;
            ui->load_verifying = false;
            launch_rom(draw_launch_progress, &draw);
            /* Only reached when the handoff did not happen. The bar has to go
               with it, or a refusal is left sitting under a full progress bar
               that says the opposite. */
            ui->load_total_kib = 0;
            ui->status = launch_status_message();
        }
        return;
    }
    if (ui->screen == SM_SCREEN_CHEATS) {
        const sm_cheat_set_t *set = launch_cheats();
        uint32_t count = set->count;
        uint32_t rows = cheat_rows(layout);
        if (actions.back) {
            /* Leaving is when the record is written: one write per visit
               rather than one per press, and nothing on the card is touched
               if nothing changed. */
            if (!launch_cheats_save())
                ui->status = "Could not write " SM_CARD_FOLDER "/cheats.txt";
            ui->screen = SM_SCREEN_LAUNCH_DETAILS;
            return;
        }
        if (count) {
            if (actions.up) ui->cheat_row = (ui->cheat_row + count - 1u) % count;
            if (actions.down) ui->cheat_row = (ui->cheat_row + 1u) % count;
            if (actions.page_up) ui->cheat_row = ui->cheat_row >= rows ? ui->cheat_row - rows : 0;
            if (actions.page_down) ui->cheat_row = ui->cheat_row + rows < count ? ui->cheat_row + rows : count - 1u;
            if (actions.select || actions.favorite) {
                if (!launch_cheat_toggle(ui->cheat_row))
                    ui->status = "This entry needs a value the file does not give";
            }
            if (ui->cheat_row < ui->cheat_first) ui->cheat_first = ui->cheat_row;
            if (ui->cheat_row >= ui->cheat_first + rows) ui->cheat_first = ui->cheat_row + 1u - rows;
        }
        return;
    }
    if (ui->screen == SM_SCREEN_FILTERS) {
        if (actions.up) ui->filter_row = (ui->filter_row + FILTER_ROWS - 1) % FILTER_ROWS;
        if (actions.down) ui->filter_row = (ui->filter_row + 1) % FILTER_ROWS;
        if (actions.back) { ui->screen = SM_SCREEN_LIBRARY; rebuild(ui, catalog); return; }
        if (actions.filter) { memset(&ui->filter, 0, sizeof(ui->filter)); ui->status = "Filters cleared"; }
        if (actions.right || actions.left) change_filter(ui, catalog, actions.right ? 1 : -1);
        return;
    }
    if (actions.filter) { ui->screen = SM_SCREEN_FILTERS; return; }
    if (actions.genre_prev || actions.genre_next) {
        select_genre_tab(ui, catalog, actions.genre_next ? 1 : -1);
        return;
    }
    if (actions.toggle_view) {
        /* List for finding a game you can name, grid for scanning a folder,
           coverflow for not knowing what you want yet. */
        ui->view = ui->view == SM_VIEW_LIST ? SM_VIEW_GRID
                 : ui->view == SM_VIEW_GRID ? SM_VIEW_COVERFLOW
                 : SM_VIEW_LIST;
        ui->status = NULL;
        ui->flow_frames = 0;
        focus_selected(ui, layout);
        unload_cover(ui); unload_slots(ui);
    }
    if (actions.back && ui->flat) {
        /* There is no parent of a shortlist. B means out, and out is where we
           came in. */
        apply_strip_tab(ui, catalog, SM_STRIP_ALL);
        return;
    }
    if (actions.back && strlen(ui->folder) > strlen(ui->root)) {
        /* Sized to match folder_label's buffer, so a name that fits there fits
           here too and the two always agree. */
        char leaving[64];
        char *slash = strrchr(ui->folder, '/');
        snprintf(leaving, sizeof(leaving), "%.*s", (int)sizeof(leaving) - 1,
            slash ? slash + 1 : ui->folder);
        if (slash) *slash = '\0'; else ui->folder[0] = '\0';
        rebuild(ui, catalog);
        select_folder_named(ui, catalog, leaving, layout);
        return;
    }
    if (!ui->item_count) return;
    uint32_t old = ui->selected, old_first = ui->first_visible;
    uint32_t visible = ui->view == SM_VIEW_GRID ? SM_UI_GRID_VISIBLE : (uint32_t)layout->visible_rows;
    if (ui->view == SM_VIEW_GRID) {
        if (actions.up && ui->selected >= SM_UI_GRID_COLUMNS) ui->selected -= SM_UI_GRID_COLUMNS;
        if (actions.down && ui->selected + SM_UI_GRID_COLUMNS < ui->item_count) ui->selected += SM_UI_GRID_COLUMNS;
        /* Left and right walk the whole grid, not just the row: stopping at a
           row end makes a 4-wide grid feel like four separate lists. */
        if (actions.left && ui->selected) ui->selected--;
        if (actions.right && ui->selected + 1u < ui->item_count) ui->selected++;
    } else if (ui->view == SM_VIEW_COVERFLOW) {
        /* The shelf runs left to right, so left and right walk it. Up and down
           do the same rather than nothing, because a d-pad in a hand does not
           know which axis a view thinks it is. */
        if ((actions.left || actions.up) && ui->selected) ui->selected--;
        if ((actions.right || actions.down) && ui->selected + 1u < ui->item_count)
            ui->selected++;
    } else {
        if (actions.up && ui->selected > 0) ui->selected--;
        if (actions.down && ui->selected + 1 < ui->item_count) ui->selected++;
    }
    if (ui->view == SM_VIEW_COVERFLOW) {
        /* One cover at a time is fine for fifteen and hopeless for three
           thousand, and a page of seven is barely better. L and R jump to the
           next initial instead, which crosses a full library in about as many
           presses as there are letters. */
        if (actions.page_up) ui->selected = flow_letter_jump(ui, catalog, -1);
        if (actions.page_down) ui->selected = flow_letter_jump(ui, catalog, 1);
    } else {
        if (actions.page_up) ui->selected = ui->selected > visible ? ui->selected - visible : 0;
        if (actions.page_down) { uint32_t next = ui->selected + visible; ui->selected = next < ui->item_count ? next : ui->item_count - 1; }
    }
    ui->first_visible = sm_view_first_visible(ui->first_visible, ui->selected,
        visible, ui->item_count, ui->view == SM_VIEW_GRID ? SM_UI_GRID_COLUMNS : 1u);
    if (old != ui->selected) {
        ui->status = NULL;
        unload_cover(ui);
        if (ui->view == SM_VIEW_COVERFLOW) {
            /* A letter jump animates as one step too. That is not a claim
               about how far it went -- it is a transition, and six frames of
               movement reads better than a hard cut whatever the distance. */
            ui->flow_dir = ui->selected > old ? 1 : -1;
            /* One short of the full count. The countdown runs at the top of
               this function, before the movement is handled, so starting at
               the full value would leave the press frame drawing the shelf
               exactly where it already was -- a frame of stillness at the
               front of every step, which is where it shows most. */
            ui->flow_frames = SM_UI_FLOW_FRAMES - 1u;
        }
        /* In the grid the cursor moving inside the window costs nothing, so
           only a scroll is worth waiting out. Coverflow has no inside: every
           step slides the whole shelf and pulls one new cover off the card, so
           it waits like the list does. */
        if (ui->view != SM_VIEW_GRID) ui->settle = SM_UI_SETTLE_FRAMES;
    }
    if (old_first != ui->first_visible) ui->settle = SM_UI_SETTLE_FRAMES;
    if (actions.select) {
        uint32_t item = ui->items[ui->selected]; sm_game_t game;
        if ((item & SM_UI_FOLDER_BIT) && catalog_get(catalog, item & ~SM_UI_FOLDER_BIT, &game)) {
            const char *part = relative_part(game.path, ui->folder); const char *slash = strchr(part, '/');
            size_t used = strlen(ui->folder), add = (size_t)(slash - part);
            if (used + (used ? 1 : 0) + add < sizeof(ui->folder)) { if (used) ui->folder[used++]='/'; memcpy(ui->folder+used,part,add); ui->folder[used+add]='\0'; rebuild(ui,catalog); }
        } else if (catalog_get(catalog, item, &game)) {
            launch_prepare(game.path);
            ui->status = launch_status_message();
            ui->diagnostics = false;
            /* The grid keeps its covers in slot_sprites and never touches
               cover_sprite, which is what the launch card draws -- so coming
               here from the grid showed a game with no box and "..." where its
               save type should be. Both are wanted now, whichever view we
               arrived from, and the settle delay does not apply: the card is
               already on screen and waiting for it. */
            if (!ui->cover_loaded || ui->cover_index != item)
                load_selected_cover(ui, catalog);
            if (!ui->selected_details_loaded)
                load_selected_details(ui, catalog);
            ui->screen = SM_SCREEN_LAUNCH_DETAILS;
        }
    }
    if (actions.favorite) {
        sm_game_t game;
        uint32_t item = ui->items[ui->selected];
        if (item & SM_UI_FOLDER_BIT) ui->status = "Folders cannot be favourited";
        else if (catalog_get(catalog, item, &game)) {
            bool now = sm_favorites_toggle(&ui->favorites, game.path);
            if (!now && ui->favorites.full) ui->status = "Favourites are full";
            else if (!sm_favorites_save(&ui->favorites, SM_FAVORITES_PATH))
                ui->status = "Could not write " SM_CARD_FOLDER "/favorites.txt";
            else ui->status = now ? "Added to favourites" : "Removed from favourites";
            /* Only a rebuild while the favourites filter is on, because that
               changes which items exist; otherwise the star simply appears. */
            if (ui->filter.favorites_only) rebuild(ui, catalog);
        }
    }
    /* Repointing the slots is free; reading the pictures is not. The window
       follows the scroll immediately so the right tiles are on screen, and
       the reads wait until the controller stops.

       The grid's window starts at first_visible; coverflow's is centred on the
       selection, which is what puts the chosen cover under the reflection in
       the middle of the screen. */
    if (ui->view == SM_VIEW_GRID || ui->view == SM_VIEW_COVERFLOW) {
        int32_t base = ui->view == SM_VIEW_GRID
            ? (int32_t)ui->first_visible
            : (int32_t)ui->selected - SM_UI_FLOW_OUTER;
        uint32_t count = ui->view == SM_VIEW_GRID
            ? SM_UI_GRID_VISIBLE : SM_UI_FLOW_SLOTS;
        if (ui->slot_base != base || ui->slot_count != count)
            sync_slots(ui, base, count);
    }
    if (ui->settle) { ui->settle--; return; }
    /* Both slot views draw from slot_sprites and never need cover_sprite until
       A is pressed, which the select handler covers. Loading it here as well
       would read the middle cover off the card a second time on every step,
       which is the one cost this view cannot afford. */
    if (ui->view == SM_VIEW_GRID || ui->view == SM_VIEW_COVERFLOW) {
        load_slot_step(ui, catalog);
    } else if (!ui->cover_loaded) {
        load_selected_cover(ui, catalog);
        load_selected_details(ui, catalog);
    }
}

/* One colour per genre, picked by hashing the name so a genre keeps its chip
   wherever it appears. Index 0 is reserved for "no genre known". */
static uint32_t genre_colour(const char *genre) {
    static const uint8_t PALETTE[][3] = {
        {110, 124, 142},  /* unknown -- deliberately grey, not a colour */
        {120, 180, 240}, {240, 150,  90}, {230, 110, 110}, {200, 130, 220},
        {150, 220, 170}, {240, 220, 120}, {120, 215, 220}, {235, 120, 170},
    };
    unsigned count = sizeof(PALETTE) / sizeof(*PALETTE);
    unsigned index = 0u;
    if (genre && genre[0]) index = 1u + sm_genre_colour_index(genre, count - 1u);
    return graphics_make_color(PALETTE[index][0], PALETTE[index][1], PALETTE[index][2], 255);
}

static void draw_chip(surface_t *s, int x, int y, const char *genre) {
    graphics_draw_box(s, x, y, 4, 4, genre_colour(genre));
}

/* A favourite has to be visible without filtering for them, or pressing the
   button looks like it did nothing -- which is exactly how the feature felt
   before it did anything. */
static void draw_star(surface_t *s, int x, int y) {
    uint32_t gold = graphics_make_color(250, 210, 90, 255);
    graphics_draw_box(s, x + 2, y, 1, 5, gold);
    graphics_draw_box(s, x, y + 2, 5, 1, gold);
    graphics_draw_box(s, x + 1, y + 1, 3, 3, gold);
}

static bool item_is_favorite(const sm_ui_t *ui, uint32_t item, const sm_game_t *game) {
    return !(item & SM_UI_FOLDER_BIT) && sm_favorites_contains(&ui->favorites, game->path);
}

/* The row's title, scrolled horizontally when it does not fit. Only the
   selected row ever moves -- fifteen rows of drifting text would be unreadable
   and would cost a redraw every frame. */
static void draw_row_title(surface_t *s, int x, int y, int width, const char *title,
    bool selected, unsigned marquee) {
    int room = width / SM_FONT_WIDTH;
    int length = (int)strlen(title);
    if (!selected || length <= room) { draw_truncated(s, x, y, title, room); return; }
    {
        /* Hold at each end for a moment, then slide. The pause is what makes a
           long name readable at all; a constant crawl never settles. */
        int overflow = length - room;
        unsigned span = (unsigned)overflow * 8u;
        unsigned hold = 48u;
        unsigned cycle = span + hold * 2u;
        unsigned phase = marquee % (cycle ? cycle : 1u);
        int shift = phase < hold ? 0
                  : phase < hold + span ? (int)((phase - hold) / 8u)
                  : overflow;
        draw_truncated(s, x, y, title + shift, room);
    }
}

/* The grid gives up the detail panel for cover size, so the bar carries the
   selected title instead of a key map. The list keeps the key map, because the
   panel already says what is selected. */
static const char *footer_hint(const sm_catalog_t *c, const sm_ui_t *ui) {
    static char line[64];
    sm_game_t game;
    /* The line has to fit the safe area, or its tail -- where the favourite
       key is named -- is lost. C-left and C-right walk the tab strip, which
       is "all", favourites, then the genres -- so the word is TABS rather
       than GENRE, and starring a game is STAR rather than FAV, which would
       otherwise name two different things in one line. */
    /* Coverflow answers to different buttons: the strip is gone, and L and R
       jump by initial instead of by page. */
    if (ui->view == SM_VIEW_COVERFLOW)
        return "A PLAY B UP L/R LETTER C^ VIEW Cv STAR Z FILTER";
    if (ui->view != SM_VIEW_GRID)
        return "A PLAY B UP C</C> TABS C^ VIEW Cv STAR Z FILTER";
    if (ui->item_count) {
        uint32_t item = ui->items[ui->selected];
        /* A folder item carries the catalog index of the first game inside it,
           so reading its title here named the folder after a game. */
        if (folder_label(c, item, ui->folder, line, sizeof(line))) return line;
        if (catalog_get(c, item, &game)) {
            snprintf(line, sizeof(line), "%s", game.title);
            return line;
        }
    }
    return "A PLAY B UP C</C> TABS C^ VIEW Cv STAR Z FILTER";
}

static void draw_genre_tabs(surface_t *s, const sm_layout_t *l, const sm_ui_t *ui) {
    int x = l->safe_left + 3;
    /* Eight codes is all that fits, and a real card has two dozen genres. The
       strip scrolls with the selection instead of stopping at eight, which is
       what left Puzzle and Beat'em Up on a card and unreachable from it. */
    uint32_t count = strip_count(ui);
    uint32_t first = sm_genre_tab_window(ui->genre_tab, count, SM_GENRE_TABS_VISIBLE);
    graphics_draw_box(s, l->safe_left, l->tabs_top, l->list_width, SM_TABS_HEIGHT,
        graphics_make_color(14, 20, 30, 255));
    for (uint32_t i = first; i < count; i++) {
        const sm_genre_tab_t *tab = strip_genre(ui, i);
        const char *code = tab ? tab->code
            : (i == SM_STRIP_HISTORY ? "HIS" : "FAV");
        int width = (int)strlen(code) * SM_FONT_WIDTH;
        bool active = i == ui->genre_tab;
        /* Favourites can also be on underneath a genre, set from the filter
           screen. Marking the tab is the only sign the browser gives that a
           filter you cannot see is narrowing the list. */
        bool marked = i == SM_STRIP_FAVORITES && ui->filter.favorites_only;
        if (x + width > l->safe_left + l->list_width) break;
        if (active || marked)
            graphics_draw_box(s, x - 2, l->tabs_top, width + 3, SM_TABS_HEIGHT,
                active ? graphics_make_color(45, 75, 110, 255)
                       : graphics_make_color(30, 44, 62, 255));
        graphics_set_color(active ? graphics_make_color(255, 255, 255, 255)
            : tab ? genre_colour(tab->name) : graphics_make_color(245, 230, 160, 255), 0);
        graphics_draw_text(s, x, l->tabs_top + 2, code);
        x += width + 3;
    }
}

static void draw_scrollbar(surface_t *s, const sm_layout_t *l, const sm_ui_t *ui) {
    int track = l->list_height;
    int height, top;
    graphics_draw_box(s, l->scrollbar_x, l->list_top, 1, track,
        graphics_make_color(28, 38, 54, 255));
    if (ui->item_count <= (uint32_t)l->visible_rows) return;
    height = track * l->visible_rows / (int)ui->item_count;
    if (height < 8) height = 8;
    top = l->list_top + (track - height) * (int)ui->first_visible /
        (int)(ui->item_count - (uint32_t)l->visible_rows);
    graphics_draw_box(s, l->scrollbar_x, top, 1, height,
        graphics_make_color(90, 120, 155, 255));
}

static void draw_list(surface_t *s, const sm_layout_t *l, const sm_catalog_t *c,
    const sm_ui_t *ui) {
    for (int row = 0; row < l->visible_rows; row++) {
        uint32_t pos = ui->first_visible + (uint32_t)row;
        uint32_t item;
        sm_game_t game;
        char name[64], label[68];
        const char *title;
        bool selected;
        int y;
        if (pos >= ui->item_count) break;
        item = ui->items[pos];
        if (!catalog_get(c, item & ~SM_UI_FOLDER_BIT, &game)) continue;
        title = game.title;
        y = l->list_top + row * l->row_height;
        selected = pos == ui->selected;

        if (folder_label(c, item, ui->folder, name, sizeof(name))) {
            snprintf(label, sizeof(label), "[%s]", name);
            title = label;
            if (!selected)
                graphics_draw_box(s, l->safe_left, y, l->list_width, l->row_height,
                    graphics_make_color(20, 32, 48, 255));
        }
        if (selected) {
            graphics_draw_box(s, l->safe_left, y, l->list_width, l->row_height,
                graphics_make_color(45, 75, 110, 255));
            graphics_draw_box(s, l->safe_left, y, 2, l->row_height,
                graphics_make_color(245, 230, 160, 255));
        }
        if (!(item & SM_UI_FOLDER_BIT)) draw_chip(s, l->safe_left + 6, y + 3, game.genre);
        graphics_set_color(selected ? graphics_make_color(255, 255, 255, 255)
            : (item & SM_UI_FOLDER_BIT) ? graphics_make_color(245, 230, 160, 255)
            : graphics_make_color(200, 208, 220, 255), 0);
        {
            bool favorite = item_is_favorite(ui, item, &game);
            int text_x = l->safe_left + ((item & SM_UI_FOLDER_BIT) ? 6 : 12);
            int width = l->safe_left + l->list_width - text_x - 2 - (favorite ? 7 : 0);
            draw_row_title(s, text_x, y + 1, width, title, selected, ui->marquee);
            if (favorite)
                draw_star(s, l->safe_left + l->list_width - 7, y + (l->row_height - 5) / 2);
        }
    }
    draw_scrollbar(s, l, ui);
}

/* A folder tile. A folder item stores the first game inside it; drawing
   that game's cover would make a folder look like a game that had already
   been opened, and give four different folders four different, wrong
   names. */
static void draw_folder_tile(surface_t *s, int x, int y, const char *name, bool selected) {
    const int w = SM_UI_TILE_WIDTH, h = SM_UI_TILE_HEIGHT;
    uint32_t body = selected ? graphics_make_color(70, 95, 130, 255)
                             : graphics_make_color(44, 60, 84, 255);
    uint32_t edge = graphics_make_color(245, 230, 160, 255);
    int top = y + 12, tab = w / 3;
    graphics_draw_box(s, x, y, w, h, graphics_make_color(24, 32, 44, 255));
    graphics_draw_box(s, x + 6, y + 7, tab, 5, edge);          /* the raised tab */
    graphics_draw_box(s, x + 6, top, w - 12, h - 22, body);
    graphics_draw_box(s, x + 6, top, w - 12, 1, edge);         /* lit top edge */
    graphics_set_color(selected ? graphics_make_color(255, 255, 255, 255) : edge, 0);
    draw_truncated(s, x + 2, y + h - 9, name, (w - 4) / SM_FONT_WIDTH);
}

static void draw_grid(surface_t *s, const sm_layout_t *l, const sm_catalog_t *c,
    const sm_ui_t *ui) {
    const int step_x = SM_UI_TILE_WIDTH + 4, step_y = SM_UI_TILE_HEIGHT + 8;
    int origin = l->tabs_top;   /* the grid takes the tab strip's row too */
    for (int slot = 0; slot < SM_UI_GRID_VISIBLE; slot++) {
        uint32_t pos = ui->first_visible + (uint32_t)slot;
        sm_game_t game;
        char name[64];
        bool selected;
        int x, y;
        if (pos >= ui->item_count) break;
        if (!catalog_get(c, ui->items[pos] & ~SM_UI_FOLDER_BIT, &game)) continue;
        x = l->safe_left + 3 + (slot % SM_UI_GRID_COLUMNS) * step_x;
        y = origin + (slot / SM_UI_GRID_COLUMNS) * step_y;
        if (y + SM_UI_TILE_HEIGHT > l->footer_top - 2) break;
        selected = pos == ui->selected;
        if (selected)
            graphics_draw_box(s, x - 2, y - 2, SM_UI_TILE_WIDTH + 4, SM_UI_TILE_HEIGHT + 4,
                graphics_make_color(245, 230, 160, 255));
        if (folder_label(c, ui->items[pos], ui->folder, name, sizeof(name))) {
            draw_folder_tile(s, x, y, name, selected);
            continue;
        }
        if (ui->slot_sprites[slot])
            draw_cover_scaled(s, x, y, ui->slot_sprites[slot],
                SM_UI_TILE_WIDTH, SM_UI_TILE_HEIGHT);
        else {
            graphics_draw_box(s, x, y, SM_UI_TILE_WIDTH, SM_UI_TILE_HEIGHT,
                graphics_make_color(35, 42, 52, 255));
            graphics_set_color(graphics_make_color(150, 165, 185, 255), 0);
            draw_truncated(s, x + 2, y + SM_UI_TILE_HEIGHT / 2 - 4, game.title,
                (SM_UI_TILE_WIDTH - 4) / SM_FONT_WIDTH);
        }
        if (!(ui->items[pos] & SM_UI_FOLDER_BIT)) draw_chip(s, x + 2, y + 2, game.genre);
        if (item_is_favorite(ui, ui->items[pos], &game))
            draw_star(s, x + SM_UI_TILE_WIDTH - 7, y + 2);
    }
}

/* The panel beside the list: cover, name, and the six facts worth knowing
   before pressing Start. Four come from the catalog; SAVE and PAK are read
   from the cartridge's own header, which is why they are right even for a ROM
   no database has ever heard of. */
/* Coverflow. The shelf runs across the screen with the selection face on in
   the middle and three covers turning away either side.

   The geometry is a table rather than a formula because there are only three
   depths and a table is easier to tune against a real television than a
   perspective divide nobody can see the units of. Widths shrink and the far
   edge of each card drops faster than its near edge, which is what makes the
   row read as receding rather than as covers of different sizes. */
static const sm_flow_step_t FLOW_DEPTH[SM_UI_FLOW_OUTER + 1] = {
    { 96, 72, 72, 0 },     /* the selection, face on */
    { 34, 68, 54, -7 },
    { 27, 60, 45, -4 },
    { 21, 52, 38, -3 },
    /* Only drawn mid-slide, and then only on its way somewhere. The gap is a
       positive number where every other rung overlaps, which pushes this one
       clear of the safe area: a cover entering has to start off the screen, or
       it materialises twenty pixels inside it and the pop is still there. */
    { 17, 45, 32, 32 },
};

/* Straight-line interpolation between two values, `phase` of `total` of the
   way from `from` to `to`. Integer, because the console has no reason to start
   the FPU for a hundred of these a frame. */
static int lerp(int from, int to, uint32_t phase, uint32_t total) {
    if (!total) return to;
    return from + (to - from) * (int)phase / (int)total;
}

/* A folder, drawn once into a cover-shaped buffer.

   It must not look like the blank rectangle a cover shows before it has
   streamed off the card: on a shelf that is constantly loading, you could
   not tell a folder from a picture that was about to appear.

   Rendering it into a buffer, rather than as a special case in the draw loop,
   is what lets it turn, slide and reflect through exactly the same code that
   moves a box. The shapes are deliberately chunky: this ends up as little as
   seventeen pixels wide at the far end of the shelf, and anything finer than a
   fifth of the width is gone by then.

   Colours follow the grid's folder tile, so the two views agree about what a
   folder looks like. */
static uint16_t rgba16(unsigned red, unsigned green, unsigned blue) {
    return (uint16_t)(((red >> 3) << 11) | ((green >> 3) << 6) |
                      ((blue >> 3) << 1) | 1u);
}

static const surface_t *flow_folder_surface(void) {
    static uint16_t pixels[SM_COVER_WIDTH * SM_COVER_HEIGHT];
    static surface_t surface;
    static bool ready;
    const int w = SM_COVER_WIDTH, h = SM_COVER_HEIGHT;
    const uint16_t backing = rgba16(24, 32, 44);
    const uint16_t body = rgba16(78, 108, 150);
    const uint16_t edge = rgba16(245, 230, 160);
    const uint16_t shade = rgba16(40, 56, 80);
    int x, y;

    if (ready) return &surface;
    /* The folder fills its card, the way a cover fills its own. The first
       attempt drew a small icon on a dark field, which was legible face on and
       became an empty black rectangle the moment it turned -- most of what
       survives foreshortening is whatever colour covers the most area.
       Fractions of the cover, so the shape holds if the size ever changes. */
    const int margin = w / 16, tab_w = w / 3, top = h / 5;

    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++) {
            uint16_t pixel = backing;
            bool in_tab = x >= margin && x < margin + tab_w && y < top;
            bool in_body = x >= margin && x < w - margin &&
                           y >= top && y < h - margin;
            if (in_tab) pixel = edge;
            else if (in_body) {
                pixel = body;
                /* A lit lip along the top of the body, and a shaded strip down
                   the right: two horizontal bands of contrast, which is what a
                   card squeezed to a fifth of its width still has room for. */
                if (y < top + 3) pixel = edge;
                else if (x >= w - margin - 5) pixel = shade;
            }
            pixels[y * w + x] = pixel;
        }

    surface.flags = FMT_RGBA16;
    surface.width = (uint16_t)w;
    surface.height = (uint16_t)h;
    surface.stride = (uint16_t)(w * 2);
    surface.buffer = pixels;
    ready = true;
    return &surface;
}

/* One cover on the shelf, resolved to what is actually being drawn: mid-slide
   none of this comes straight from the depth table. Gathered first so the
   drawing pass can order them by width. */
typedef struct {
    int slot, x, width, near_height, far_height;
    bool near_left, placeholder, folder;
} flow_cover_t;

static void draw_flow_placeholder(surface_t *s, int x, int centre_y, int width,
    int near_height, int far_height) {
    int height = near_height < far_height ? near_height : far_height;
    graphics_draw_box(s, x, centre_y - height / 2, width, height,
        graphics_make_color(28, 36, 48, 255));
}

static void draw_coverflow(surface_t *s, const sm_layout_t *l, const sm_catalog_t *c,
    const sm_ui_t *ui) {
    const int centre_x = (l->safe_left + l->safe_right) / 2;
    /* High enough that the reflection has somewhere to fall and the title
       still clears the footer. */
    const int centre_y = l->list_top + SM_COVER_HEIGHT / 2 + 6;
    sm_game_t game;
    char label[80];
    int slot_x[SM_UI_FLOW_SLOTS];
    flow_cover_t covers[SM_UI_FLOW_SLOTS];
    int shown = 0;
    int chars = (l->safe_right - l->safe_left - 6) / SM_FONT_WIDTH;

    if (!ui->item_count) {
        graphics_set_color(graphics_make_color(150, 165, 185, 255), 0);
        draw_truncated(s, l->safe_left + 6, centre_y,
            ui->genre_tab == SM_STRIP_HISTORY
                ? "Nothing played yet. Launch something and it lands here."
                : "Nothing here.", chars);
        return;
    }

    /* One position per slot, including the two off-screen rungs at each end.
       Slot SM_UI_FLOW_OUTER is the selection, face on in the middle. */
    sm_flow_positions(centre_x, FLOW_DEPTH, SM_UI_FLOW_OUTER, slot_x);

    for (int slot = 0; slot < SM_UI_FLOW_SLOTS; slot++) {
        int depth = slot - SM_UI_FLOW_OUTER;
        int side = depth < 0 ? -1 : 1;
        uint32_t item = ui->slot_indices[slot];
        flow_cover_t *cover = &covers[shown];
        if (depth < 0) depth = -depth;

        if (item == UINT32_MAX) continue;
        /* The outer rungs are off the side of the screen and exist only to be
           slid to and from. Nothing sits there once the shelf has settled. */
        if (depth == SM_UI_FLOW_OUTER && !ui->flow_frames) continue;

        cover->slot = slot;
        cover->x = slot_x[slot];
        cover->width = FLOW_DEPTH[depth].width;
        cover->near_height = FLOW_DEPTH[depth].near_height;
        cover->far_height = FLOW_DEPTH[depth].far_height;
        cover->near_left = side > 0 || depth == 0;

        if (ui->flow_frames) {
            /* Where this cover was one step ago. The shelf moved by flow_dir,
               so it was that many slots further along in that direction; the
               outer rungs are what keep `was` on the shelf at both ends. */
            int was = slot + (int)ui->flow_dir;
            int was_depth, was_side;
            uint32_t done = SM_UI_FLOW_FRAMES - ui->flow_frames;
            if (was < 0) was = 0;
            if (was > 2 * SM_UI_FLOW_OUTER) was = 2 * SM_UI_FLOW_OUTER;
            was_depth = was - SM_UI_FLOW_OUTER;
            was_side = was_depth < 0 ? -1 : 1;
            if (was_depth < 0) was_depth = -was_depth;
            if (done > SM_UI_FLOW_FRAMES) done = SM_UI_FLOW_FRAMES;

            /* How far along the step is, NOT how much is left: lerp runs from
               `was` at 0 to here at SM_UI_FLOW_FRAMES, so passing the
               remaining count plays the slide backwards -- the shelf arrives
               first and then retreats to where it came from. */
            cover->x = lerp(slot_x[was], cover->x, done, SM_UI_FLOW_FRAMES);
            cover->width = lerp(FLOW_DEPTH[was_depth].width, cover->width,
                done, SM_UI_FLOW_FRAMES);
            cover->near_height = lerp(FLOW_DEPTH[was_depth].near_height,
                cover->near_height, done, SM_UI_FLOW_FRAMES);
            cover->far_height = lerp(FLOW_DEPTH[was_depth].far_height,
                cover->far_height, done, SM_UI_FLOW_FRAMES);
            /* A cover crossing the middle faces the way it came for the first
               half of the step and the way it is going for the second. Setting
               it from the destination alone mirrors the picture in one frame,
               at the moment the card is most turned -- which is exactly when
               it shows. */
            if (done * 2u < SM_UI_FLOW_FRAMES)
                cover->near_left = was_side > 0 || was_depth == 0;
        }
        cover->folder = (item & SM_UI_FOLDER_BIT) != 0u;
        /* A blank tile now means one thing only: a cover that has not come off
           the card yet. */
        cover->placeholder = !cover->folder && !ui->slot_sprites[slot];
        shown++;
    }

    /* Narrowest first, so each nearer cover overlaps the ones behind it --
       which is the whole illusion. Sorted by the width actually being drawn
       rather than by the slot's resting depth: mid-slide the incoming centre
       cover is still narrow while the outgoing one is still wide, and drawing
       by resting depth painted the small one over the large one's edge. Nine
       items, so the simplest sort that is obviously right. */
    for (int i = 1; i < shown; i++) {
        flow_cover_t key = covers[i];
        int j = i - 1;
        while (j >= 0 && covers[j].width > key.width) { covers[j + 1] = covers[j]; j--; }
        covers[j + 1] = key;
    }

    for (int i = 0; i < shown; i++) {
        const flow_cover_t *cover = &covers[i];
        if (cover->placeholder) {
            draw_flow_placeholder(s, cover->x, centre_y, cover->width,
                cover->near_height, cover->far_height);
            continue;
        }
        /* A card on the left of the screen has its near edge on the right,
           facing the middle, and the other way about on the right. A folder
           goes through the identical path -- it is just a different picture. */
        {
            surface_t pixels;
            const surface_t *source;
            if (cover->folder) {
                source = flow_folder_surface();
            } else {
                pixels = sprite_get_pixels(ui->slot_sprites[cover->slot]);
                source = &pixels;
            }
            draw_cover_turned(s, cover->x, centre_y, source,
                cover->width, cover->near_height, cover->far_height,
                cover->near_left, cover->near_height / 3);
        }
    }

    /* The title under the shelf, and the genre beside it. Coverflow gives up
       the list's columns, so this is the only place the selection is named. */
    if (catalog_get(c, ui->items[ui->selected] & ~SM_UI_FOLDER_BIT, &game)) {
        int y = centre_y + SM_COVER_HEIGHT / 2 + SM_COVER_HEIGHT / 3 + 6;
        if (y > l->footer_top - 22) y = l->footer_top - 22;
        char name[64];
        if (folder_label(c, ui->items[ui->selected], ui->folder, name, sizeof(name)))
            snprintf(label, sizeof(label), "[%s]", name);
        else
            snprintf(label, sizeof(label), "%s", game.title);
        graphics_set_color(graphics_make_color(255, 255, 255, 255), 0);
        draw_truncated(s, l->safe_left + 6, y, label, chars);
        if (game.genre[0]) {
            graphics_set_color(graphics_make_color(150, 165, 185, 255), 0);
            draw_truncated(s, l->safe_left + 6, y + 11, game.genre, chars);
        }
    }
}

static void draw_panel(surface_t *s, const sm_layout_t *l, const sm_catalog_t *c,
    const sm_ui_t *ui) {
    sm_game_t game;
    int x = l->panel_x, y = l->list_top;
    int chars = (l->safe_right - x) / SM_FONT_WIDTH;
    char line[48];

    if (!ui->item_count || !catalog_get(c, ui->items[ui->selected] & ~SM_UI_FOLDER_BIT, &game))
        return;
    if (ui->items[ui->selected] & SM_UI_FOLDER_BIT) {
        char name[64];
        graphics_set_color(graphics_make_color(130, 145, 160, 255), 0);
        if (folder_label(c, ui->items[ui->selected], ui->folder, name, sizeof(name)))
            draw_truncated(s, x, y + 2, name, chars);
        graphics_draw_text(s, x, y + 14, "FOLDER");
        return;
    }

    if (ui->cover_sprite) draw_cover(s, x, y, ui->cover_sprite);
    else {
        graphics_draw_box(s, x, y, SM_COVER_WIDTH, SM_COVER_HEIGHT,
            graphics_make_color(35, 42, 52, 255));
        graphics_set_color(graphics_make_color(130, 145, 160, 255), 0);
        graphics_draw_text(s, x + (SM_COVER_WIDTH - 6 * SM_FONT_WIDTH) / 2, y + 32, "NO ART");
    }
    y += SM_COVER_HEIGHT + 4;
    graphics_set_color(graphics_make_color(240, 240, 232, 255), 0);
    draw_truncated(s, x, y, game.title, chars);
    y += 12;

    {
        static const char *LABELS[] = {"YEAR", "PUB", "GENRE", "REGION", "SAVE", "PAK", "SIZE"};
        char values[7][40];
        snprintf(values[0], sizeof(values[0]), "%s", "");
        if (game.year) snprintf(values[0], sizeof(values[0]), "%u", (unsigned)game.year);
        snprintf(values[1], sizeof(values[1]), "%s", game.publisher);
        snprintf(values[2], sizeof(values[2]), "%s", game.genre);
        snprintf(values[3], sizeof(values[3]), "%s%s%s%s",
            (game.regions & SM_REGION_USA) ? "USA " : "",
            (game.regions & SM_REGION_JAPAN) ? "JPN " : "",
            (game.regions & SM_REGION_EUROPE) ? "EUR " : "",
            game.regions ? "" : "-");
        if (game.players) {
            size_t used = strlen(values[3]);
            snprintf(values[3] + used, sizeof(values[3]) - used, " %uP", (unsigned)game.players);
        }
        snprintf(values[4], sizeof(values[4]), "%s",
            !ui->selected_details_loaded ? "..." : ui->selected_disk ? "64DD DISK"
            : sm_save_type_name(ui->selected_save));
        if (!ui->selected_details_loaded) snprintf(values[5], sizeof(values[5]), "...");
        else snprintf(values[5], sizeof(values[5]), "%s%s%s%s",
            (ui->selected_features & SM_FEAT_CPAK) ? "CTRL " : "",
            (ui->selected_features & SM_FEAT_RPAK) ? "RMBL " : "",
            (ui->selected_features & SM_FEAT_TPAK) ? "XFER " : "",
            ui->selected_features ? "" : "-");
        if (!ui->selected_details_loaded) snprintf(values[6], sizeof(values[6]), "...");
        else sm_format_rom_size(ui->selected_size, values[6], sizeof(values[6]));

        for (int row = 0; row < 7; row++) {
            int label_width = 6 * SM_FONT_WIDTH;
            if (y + SM_FONT_HEIGHT > l->footer_top - 10) break;
            graphics_set_color(graphics_make_color(110, 128, 150, 255), 0);
            graphics_draw_text(s, x, y, LABELS[row]);
            graphics_set_color(row == 4
                ? graphics_make_color(245, 230, 160, 255)
                : graphics_make_color(240, 240, 232, 255), 0);
            if (row == 2) draw_chip(s, x + label_width, y + 2, game.genre);
            draw_truncated(s, x + label_width + (row == 2 ? 6 : 0), y,
                values[row][0] ? values[row] : "-",
                chars - 6 - (row == 2 ? 1 : 0));
            y += 9;
        }
        graphics_set_color(graphics_make_color(90, 105, 125, 255), 0);
        snprintf(line, sizeof(line), "%s", game.path);
        if (y + SM_FONT_HEIGHT <= l->footer_top - 2)
            draw_path_tail(s, x, l->footer_top - 10, line, chars);
    }
}

/* Genre first, as a grid of every genre on the card with its count, then the
   fields that can still narrow what is left. SAVE and PAK are deliberately
   absent: they are read per-ROM from the cartridge header, so filtering on
   them would mean opening 3371 files. Drawing controls that cannot work is
   worse than leaving them out. */
static void draw_filters(surface_t *s, const sm_layout_t *l, const sm_catalog_t *c,
    const sm_ui_t *ui) {
    static const char *LABELS[] = {"GENRE", "REGION", "PLAYERS", "PUBLISHER",
                                   "YEAR", "FAVORITES"};
    int y = l->safe_top + SM_HEADER_HEIGHT + 6;
    int width = l->safe_right - l->safe_left;
    char value[48];
    /* Wide enough for any 32-bit count plus the word, which the compiler can
       see for itself once the value is not widened to unsigned long. */
    char count[24];

    graphics_draw_box(s, l->safe_left, l->safe_top, width, SM_HEADER_HEIGHT,
        graphics_make_color(24, 45, 72, 255));
    graphics_set_color(graphics_make_color(245, 230, 160, 255), 0);
    graphics_draw_text(s, l->safe_left + 3, l->safe_top + 3, "FILTERS");
    snprintf(count, sizeof(count), "%u shown", (unsigned)ui->item_count);
    graphics_set_color(graphics_make_color(180, 200, 220, 255), 0);
    graphics_draw_text(s, l->safe_right - 3 - (int)strlen(count) * SM_FONT_WIDTH,
        l->safe_top + 3, count);

    /* The genre grid: three across, every tab the card produced. */
    if (ui->filter_row == 0)
        graphics_draw_box(s, l->safe_left, y - 2, width, 12,
            graphics_make_color(45, 75, 110, 255));
    graphics_set_color(ui->filter_row == 0
        ? graphics_make_color(255, 255, 255, 255)
        : graphics_make_color(240, 240, 232, 255), 0);
    graphics_draw_text(s, l->safe_left + 4, y, "GENRE");
    y += 13;
    {
        int cell = width / 3;
        uint32_t total = strip_count(ui);
        for (uint32_t i = 0; i < total; i++) {
            const sm_genre_tab_t *tab = strip_genre(ui, i);
            int x = l->safe_left + (int)(i % 3u) * cell;
            int row_y = y + (int)(i / 3u) * 12;
            bool active = i == ui->genre_tab;
            const char *label = tab ? (tab->name[0] ? tab->name : "All genres")
                : (i == SM_STRIP_HISTORY ? "Recently played" : "Favourites");
            graphics_draw_box(s, x, row_y - 1, cell - 3, 11,
                active ? graphics_make_color(45, 75, 110, 255)
                       : graphics_make_color(18, 25, 36, 255));
            if (tab) draw_chip(s, x + 3, row_y + 2, tab->name);
            else draw_star(s, x + 2, row_y + 2);
            graphics_set_color(active ? graphics_make_color(255, 255, 255, 255)
                : graphics_make_color(210, 218, 230, 255), 0);
            draw_truncated(s, x + 9, row_y, label, (cell - 30) / SM_FONT_WIDTH);
            snprintf(count, sizeof(count), "%lu", (unsigned long)(tab ? tab->count
                : i == SM_STRIP_HISTORY ? sm_history_count(&ui->history)
                                        : ui->favorites.count));
            graphics_set_color(graphics_make_color(110, 128, 150, 255), 0);
            graphics_draw_text(s, x + cell - 6 - (int)strlen(count) * SM_FONT_WIDTH,
                row_y, count);
        }
        y += (int)((total + 2u) / 3u) * 12 + 6;
    }

    for (int row = 1; row < FILTER_ROWS; row++) {
        const char *shown = "Any";
        if (row == 1 && ui->filter.regions)
            shown = ui->filter.regions == SM_REGION_USA ? "USA"
                  : ui->filter.regions == SM_REGION_JAPAN ? "Japan" : "Europe";
        if (row == 2 && ui->filter.players) {
            snprintf(value, sizeof(value), "%u or more", (unsigned)ui->filter.players);
            shown = value;
        }
        if (row == 3 && ui->filter.publisher) shown = ui->filter.publisher;
        if (row == 4 && ui->filter.year) {
            snprintf(value, sizeof(value), "%u", (unsigned)ui->filter.year);
            shown = value;
        }
        if (row == 5) shown = ui->filter.favorites_only ? "Only" : "Any";
        if (row == ui->filter_row)
            graphics_draw_box(s, l->safe_left, y - 2, width, 11,
                graphics_make_color(45, 75, 110, 255));
        graphics_set_color(graphics_make_color(110, 128, 150, 255), 0);
        graphics_draw_text(s, l->safe_left + 4, y, LABELS[row]);
        graphics_set_color(row == ui->filter_row
            ? graphics_make_color(255, 255, 255, 255)
            : graphics_make_color(240, 240, 232, 255), 0);
        draw_truncated(s, l->safe_left + 10 * SM_FONT_WIDTH + 4, y, shown,
            (l->safe_right - l->safe_left - 10 * SM_FONT_WIDTH - 8) / SM_FONT_WIDTH);
        y += 12;
    }

    graphics_draw_box(s, l->safe_left, l->footer_top, width, SM_FOOTER_HEIGHT,
        graphics_make_color(16, 22, 32, 255));
    graphics_set_color(graphics_make_color(180, 200, 220, 255), 0);
    draw_truncated(s, l->safe_left + 3, l->footer_top + 2,
        c->discovery_mode ? "No catalog: only folders filter.  B APPLY"
                          : "UP/DOWN ROW   D-PAD <> CHANGE   Z CLEAR   B APPLY",
        (width - 6) / SM_FONT_WIDTH);
}

/* What someone about to play a game wants to know, and nothing else: what it
   is, whether the save will work, and which button starts it. The CIC seed,
   the boot CRC and the transport probe were on this screen because it was
   built to prove the loader worked -- they are a keypress away now, which is
   where they belong once it does. */
/* The progress bar for a ROM going into cartridge memory.

   Eight megabytes at SD speeds is several seconds with nothing on screen but a
   line of text, which is long enough that people press buttons to find out
   whether anything is happening. A bar answers that without being read.

   Two passes share it: the load, and -- when the boot mode is VERIFY -- the
   read-back that compares every byte. They are told apart by colour and by the
   label, because a bar that reaches the end and starts again with no
   explanation looks like a failure. */
static void draw_load_bar(surface_t *s, const sm_layout_t *l, const sm_ui_t *ui) {
    int x = l->safe_left + 4;
    int width = l->safe_right - l->safe_left - 8;
    int y = l->footer_top - 16;
    uint32_t percent;
    int filled;
    char line[48];

    if (!ui->load_total_kib) return;
    percent = (uint32_t)(((uint64_t)ui->load_done_kib * 100u) / ui->load_total_kib);
    if (percent > 100u) percent = 100u;
    filled = width * (int)percent / 100;

    /* Track first, then its top edge, then the fill over both -- in that
       order. Drawing the edge last put a dark line along the top of the
       filled part, which is the opposite of what it is for. */
    graphics_draw_box(s, x, y, width, 7, graphics_make_color(20, 28, 40, 255));
    graphics_draw_box(s, x, y, width, 1, graphics_make_color(40, 54, 74, 255));
    if (filled > 0)
        graphics_draw_box(s, x, y, filled, 7, ui->load_verifying
            ? graphics_make_color(200, 170, 70, 255)
            : graphics_make_color(70, 140, 200, 255));
    /* A bright leading edge, so a bar at 3% reads as a bar and not a smudge. */
    if (filled > 0 && filled < width)
        graphics_draw_box(s, x + filled - 1, y, 1, 7,
            graphics_make_color(235, 245, 255, 255));

    /* Rounded up, not truncated: a 700 KiB homebrew showed "0/0 MB" beside a
       perfectly correct percentage. */
    snprintf(line, sizeof(line), "%s  %lu%%  %lu/%lu MB",
        ui->load_verifying ? "VERIFYING" : "LOADING",
        (unsigned long)percent,
        (unsigned long)((ui->load_done_kib + 1023u) >> 10),
        (unsigned long)((ui->load_total_kib + 1023u) >> 10));
    graphics_set_color(graphics_make_color(200, 214, 232, 255), 0);
    draw_truncated(s, x, y - 10, line, (width) / SM_FONT_WIDTH);
}

static void draw_launch_card(surface_t *s, const sm_layout_t *l, const sm_catalog_t *c,
    const sm_ui_t *ui) {
    sm_game_t game;
    bool have = ui->item_count &&
        catalog_get(c, ui->items[ui->selected] & ~SM_UI_FOLDER_BIT, &game);
    int width = l->safe_right - l->safe_left;
    int chars = (width - 6) / SM_FONT_WIDTH;
    int text_x = l->safe_left + SM_COVER_WIDTH + 10;
    int text_chars = (l->safe_right - text_x) / SM_FONT_WIDTH;
    int y;
    char line[64];

    graphics_draw_box(s, l->safe_left, l->safe_top, width, SM_HEADER_HEIGHT,
        graphics_make_color(24, 45, 72, 255));
    graphics_set_color(graphics_make_color(245, 230, 160, 255), 0);
    draw_truncated(s, l->safe_left + 3, l->safe_top + 3,
        ui->diagnostics ? "DIAGNOSTICS" : have ? game.title : "LAUNCH", chars);

    if (ui->diagnostics) {
        /* The only place the build identifies itself. SleekMenu is AGPL-3.0,
           and a copyleft program that never says so anywhere a user can see is
           relying on people finding the repository by luck. */
        static const char *LABELS[] = {"CIC", "BOOT CRC", "FORMAT", "PATH", "PROBE", "ABOUT"};
        char values[6][64];
        y = l->safe_top + SM_HEADER_HEIGHT + 8;
        snprintf(values[0], sizeof(values[0]), "%u", (unsigned)launch_detected_cic());
        snprintf(values[1], sizeof(values[1]), "%08lX", (unsigned long)launch_boot_crc());
        snprintf(values[2], sizeof(values[2]), "%s", launch_save_summary());
        snprintf(values[3], sizeof(values[3]), "%s", launch_selected_path());
        snprintf(values[4], sizeof(values[4]), "%s", "D-PAD to run");
        snprintf(values[5], sizeof(values[5]), "%s", SM_ABOUT);
        for (int row = 0; row < 6; row++) {
            graphics_set_color(graphics_make_color(110, 128, 150, 255), 0);
            graphics_draw_text(s, l->safe_left + 3, y, LABELS[row]);
            graphics_set_color(graphics_make_color(240, 240, 232, 255), 0);
            if (row == 3) draw_path_tail(s, l->safe_left + 9 * SM_FONT_WIDTH + 6, y, values[row],
                (l->safe_right - l->safe_left - 9 * SM_FONT_WIDTH - 10) / SM_FONT_WIDTH);
            else draw_truncated(s, l->safe_left + 9 * SM_FONT_WIDTH + 6, y, values[row],
                (l->safe_right - l->safe_left - 9 * SM_FONT_WIDTH - 10) / SM_FONT_WIDTH);
            y += 11;
        }
        graphics_set_color(graphics_make_color(180, 200, 220, 255), 0);
        /* A load can be started with the diagnostics page open -- Start is not
           gated on it -- and this branch returns before the card's own bar. */
        draw_load_bar(s, l, ui);
        draw_status(s, l, launch_status_message());
        graphics_draw_box(s, l->safe_left, l->footer_top, width, SM_FOOTER_HEIGHT,
            graphics_make_color(16, 22, 32, 255));
        draw_truncated(s, l->safe_left + 3, l->footer_top + 2,
            "D-PAD RUN PROBE   Z BACK TO GAME   B CANCEL", chars);
        return;
    }

    y = l->safe_top + SM_HEADER_HEIGHT + 6;
    if (ui->cover_sprite) draw_cover(s, l->safe_left + 3, y, ui->cover_sprite);
    else {
        graphics_draw_box(s, l->safe_left + 3, y, SM_COVER_WIDTH, SM_COVER_HEIGHT,
            graphics_make_color(35, 42, 52, 255));
        graphics_set_color(graphics_make_color(130, 145, 160, 255), 0);
        graphics_draw_text(s, l->safe_left + 3 + (SM_COVER_WIDTH - 6 * SM_FONT_WIDTH) / 2, y + 32, "NO ART");
    }

    {
        int info_y = y;
        graphics_set_color(graphics_make_color(240, 240, 232, 255), 0);
        if (have) draw_truncated(s, text_x, info_y, game.title, text_chars);
        info_y += 12;
        if (have && (game.year || game.publisher[0])) {
            if (game.year && game.publisher[0])
                snprintf(line, sizeof(line), "%u  %s", (unsigned)game.year, game.publisher);
            else if (game.year) snprintf(line, sizeof(line), "%u", (unsigned)game.year);
            else snprintf(line, sizeof(line), "%s", game.publisher);
            graphics_set_color(graphics_make_color(150, 165, 185, 255), 0);
            draw_truncated(s, text_x, info_y, line, text_chars);
        }
        info_y += 11;
        if (have && game.genre[0]) {
            draw_chip(s, text_x, info_y + 2, game.genre);
            graphics_set_color(graphics_make_color(150, 165, 185, 255), 0);
            draw_truncated(s, text_x + 6, info_y, game.genre, text_chars - 1);
        }
        info_y += 11;
        if (have) {
            snprintf(line, sizeof(line), "%s%s%s%s",
                (game.regions & SM_REGION_USA) ? "USA " : "",
                (game.regions & SM_REGION_JAPAN) ? "JPN " : "",
                (game.regions & SM_REGION_EUROPE) ? "EUR " : "", "");
            if (game.players) {
                size_t used = strlen(line);
                snprintf(line + used, sizeof(line) - used, "%uP", (unsigned)game.players);
            }
            graphics_set_color(graphics_make_color(150, 165, 185, 255), 0);
            draw_truncated(s, text_x, info_y, line[0] ? line : "-", text_chars);
        }
        info_y += 15;

        /* The two technical facts worth a player's attention: what it saves
           to, and how big it is -- the second because a 64 MB image takes
           visibly longer to load than an 8 MB one, and because it is the first
           thing anyone checks about a hack. */
        graphics_set_color(graphics_make_color(110, 128, 150, 255), 0);
        graphics_draw_text(s, text_x, info_y, "SAVE");
        graphics_set_color(graphics_make_color(245, 230, 160, 255), 0);
        draw_truncated(s, text_x + LABEL_COLUMN, info_y,
            launch_selected_is_disk() ? "ON THE 64DD DISK" : sm_save_type_name(launch_save_type()),
            text_chars - 6);
        info_y += 11;
        if (launch_sibling_disk()[0]) {
            /* The expansion disk found beside the ROM, by its file name. */
            const char *name = strrchr(launch_sibling_disk(), '/');
            graphics_set_color(graphics_make_color(110, 128, 150, 255), 0);
            graphics_draw_text(s, text_x, info_y, "64DD");
            graphics_set_color(graphics_make_color(240, 240, 232, 255), 0);
            draw_truncated(s, text_x + LABEL_COLUMN, info_y, name ? name + 1 : launch_sibling_disk(), text_chars - 6);
            info_y += 11;
        }
        if (launch_cheats_available()) {
            const sm_cheat_set_t *set = launch_cheats();
            uint32_t on = sm_cheats_enabled_count(set);
            graphics_set_color(graphics_make_color(110, 128, 150, 255), 0);
            graphics_draw_text(s, text_x, info_y, "CHEATS");
            if (on && cheat_warning()) {
                /* The column beside the cover is nineteen characters wide;
                   the reason is on the cheats page, one press away. */
                snprintf(line, sizeof(line), "%lu on, WILL NOT RUN", (unsigned long)on);
                graphics_set_color(graphics_make_color(255, 96, 80, 255), 0);
            } else {
                snprintf(line, sizeof(line), "%lu of %lu on", (unsigned long)on, (unsigned long)set->count);
                graphics_set_color(on ? graphics_make_color(245, 230, 160, 255)
                                      : graphics_make_color(240, 240, 232, 255), 0);
            }
            draw_truncated(s, text_x + LABEL_COLUMN_WIDE, info_y, line, text_chars - 8);
            info_y += 11;
        }
        graphics_set_color(graphics_make_color(110, 128, 150, 255), 0);
        graphics_draw_text(s, text_x, info_y, "SIZE");
        sm_format_rom_size(ui->selected_size, line, sizeof(line));
        graphics_set_color(graphics_make_color(240, 240, 232, 255), 0);
        draw_truncated(s, text_x + LABEL_COLUMN, info_y, line, text_chars - 6);
        info_y += 11;
        if (ui->selected_features) {
            graphics_set_color(graphics_make_color(110, 128, 150, 255), 0);
            graphics_draw_text(s, text_x, info_y, "NEEDS");
            snprintf(line, sizeof(line), "%s%s%s",
                (ui->selected_features & SM_FEAT_CPAK) ? "CTRL PAK " : "",
                (ui->selected_features & SM_FEAT_RPAK) ? "RUMBLE " : "",
                (ui->selected_features & SM_FEAT_TPAK) ? "TRANSFER" : "");
            graphics_set_color(graphics_make_color(240, 240, 232, 255), 0);
            draw_truncated(s, text_x + LABEL_COLUMN, info_y, line, text_chars - 6);
            info_y += 11;
        }

        /* The box back, under the cover and the facts, in the space that was
           empty. It stops short of the prompts; what does not fit ends in an
           ellipsis. NTSC gives it five or six lines, PAL a dozen. */
        if (have && game.description[0]) {
            int top = (info_y > y + SM_COVER_HEIGHT ? info_y : y + SM_COVER_HEIGHT) + 6;
            int bottom = l->footer_top - 26 - 4;
            int max_lines = (bottom - top) / 9;
            graphics_set_color(graphics_make_color(190, 200, 214, 255), 0);
            draw_wrapped(s, l->safe_left + 3, top, 9, game.description,
                (l->safe_right - l->safe_left - 6) / SM_FONT_WIDTH, max_lines);
        }
    }

    y = l->footer_top - 26;
    if (ui->load_total_kib) {
        /* Mid-transfer. The prompts below are about a decision that has
           already been made, so the bar takes their place rather than sitting
           under "START play" while the ROM is already halfway in. */
        draw_load_bar(s, l, ui);
    } else if (launch_last_result() != SM_LAUNCH_OK) {
        graphics_set_color(graphics_make_color(255, 96, 80, 255), 0);
        draw_truncated(s, l->safe_left + 3, y, launch_status_message(), chars);
    } else {
        graphics_set_color(graphics_make_color(255, 255, 255, 255), 0);
        graphics_draw_text(s, l->safe_left + 3, y, "START   play");
        graphics_set_color(graphics_make_color(150, 165, 185, 255), 0);
        graphics_draw_text(s, l->safe_left + 3, y + 11, "B       back");
    }

    graphics_draw_box(s, l->safe_left, l->footer_top, width, SM_FOOTER_HEIGHT,
        graphics_make_color(16, 22, 32, 255));
    graphics_set_color(graphics_make_color(180, 200, 220, 255), 0);
    snprintf(line, sizeof(line), "%s LOAD   C^ SWITCH   Z DETAILS%s",
        launch_boot_mode() == SM_BOOT_VERIFY ? "VERIFIED" : "FAST",
        launch_cheats_available() ? "   Cv CHEATS" : "");
    draw_truncated(s, l->safe_left + 3, l->footer_top + 2, line, chars);
}

/* The cheats page: every entry the game's file holds, on or off, one per
   row, the cursor's row lit. An entry the file left without a value is drawn
   dim and cannot be turned on. */
static void draw_cheats(surface_t *s, const sm_layout_t *l, const sm_ui_t *ui) {
    const sm_cheat_set_t *set = launch_cheats();
    int width = l->safe_right - l->safe_left;
    int chars = width / SM_FONT_WIDTH;
    int y = l->safe_top + SM_HEADER_HEIGHT + 6;
    uint32_t rows = cheat_rows(l);
    uint32_t i;
    char line[96];

    graphics_draw_box(s, l->safe_left, l->safe_top, width, SM_HEADER_HEIGHT,
        graphics_make_color(24, 45, 72, 255));
    graphics_set_color(graphics_make_color(245, 230, 160, 255), 0);
    graphics_draw_text(s, l->safe_left + 3, l->safe_top + 3, "CHEATS");
    snprintf(line, sizeof(line), "%lu of %lu on", (unsigned long)sm_cheats_enabled_count(set),
        (unsigned long)set->count);
    graphics_set_color(graphics_make_color(180, 200, 220, 255), 0);
    graphics_draw_text(s, l->safe_right - 3 - (int)strlen(line) * SM_FONT_WIDTH, l->safe_top + 3, line);

    /* The file the entries came from, then the notes: how it was found,
       and why nothing would happen. */
    graphics_set_color(graphics_make_color(110, 128, 150, 255), 0);
    draw_truncated(s, l->safe_left + 3, y, launch_cheats_source()->path, chars - 1);
    y += 11;
    if (cheat_region_note()) {
        graphics_set_color(graphics_make_color(255, 170, 80, 255), 0);
        draw_truncated(s, l->safe_left + 3, y, cheat_region_note(), chars - 1);
        y += 11;
    }
    if (cheat_warning()) {
        graphics_set_color(graphics_make_color(255, 96, 80, 255), 0);
        draw_truncated(s, l->safe_left + 3, y, cheat_warning(), chars - 1);
        y += 11;
    }

    for (i = ui->cheat_first; i < set->count && i < ui->cheat_first + rows; i++) {
        const sm_cheat_t *cheat = &set->cheats[i];
        bool current = i == ui->cheat_row;
        if (current)
            graphics_draw_box(s, l->safe_left, y - 2, width, 11, graphics_make_color(45, 75, 110, 255));
        graphics_set_color(cheat->incomplete ? graphics_make_color(110, 120, 135, 255)
            : cheat->enabled ? graphics_make_color(245, 230, 160, 255)
            : current ? graphics_make_color(255, 255, 255, 255)
            : graphics_make_color(210, 218, 230, 255), 0);
        snprintf(line, sizeof(line), "%s %s", cheat->incomplete ? "[?]" : cheat->enabled ? "[x]" : "[ ]",
            cheat->desc[0] ? cheat->desc : "(no description)");
        draw_truncated(s, l->safe_left + 3, y, line, chars - 1);
        y += 11;
    }
    if (set->count == 0) {
        graphics_set_color(graphics_make_color(150, 165, 185, 255), 0);
        graphics_draw_text(s, l->safe_left + 3, y, "The file holds no usable entries");
    }

    graphics_draw_box(s, l->safe_left, l->footer_top, width, SM_FOOTER_HEIGHT,
        graphics_make_color(16, 22, 32, 255));
    graphics_set_color(graphics_make_color(180, 200, 220, 255), 0);
    draw_truncated(s, l->safe_left + 3, l->footer_top + 2, "A TOGGLE   L/R PAGE   B BACK", chars);
}

void ui_draw(surface_t *s, const sm_layout_t *l, const sm_catalog_t *c, const sm_ui_t *ui) {
    graphics_fill_screen(s,graphics_make_color(8,12,20,255));
    graphics_draw_box(s,l->safe_left,l->safe_top,l->safe_right-l->safe_left,20,graphics_make_color(24,45,72,255));
    graphics_set_color(graphics_make_color(245,230,160,255),0);
    if (ui->screen == SM_SCREEN_LAUNCH_DETAILS) {
        draw_launch_card(s, l, c, ui);
        return;
    }
    if (ui->screen == SM_SCREEN_CHEATS) {
        draw_cheats(s, l, ui);
        return;
    }
    if (ui->screen==SM_SCREEN_FILTERS) { graphics_draw_text(s,l->safe_left+4,l->safe_top+6,"FILTERS"); draw_filters(s,l,c,ui); return; }
    if (!sm_cart_image_intact()) {
        graphics_set_color(graphics_make_color(255,190,90,255),0);
        graphics_draw_text(s,l->safe_left+4,l->safe_top+6,"CART IMAGE OVERWRITTEN - RESET FOR ART");
        graphics_set_color(graphics_make_color(245,230,160,255),0);
    }
    /* --- the library, dense --------------------------------------------- */
    {
        char header[64];
        int counter_chars = (l->safe_right - l->safe_left) / SM_FONT_WIDTH;
        char counter[24];

        /* Title bar: where you are on the left, where you are in the list on
           the right. The count is what a folder of 400 ROMs needs most. */
        graphics_draw_box(s, l->safe_left, l->safe_top, l->safe_right - l->safe_left,
            SM_HEADER_HEIGHT, graphics_make_color(24, 45, 72, 255));
        /* The folder can be longer than the bar; draw_truncated trims it, and
           the precision keeps the compiler from worrying about the copy. */
        /* The grid has no room for the strip, so the bar carries the active
           genre instead -- otherwise a filtered grid looks like a short card. */
        /* Both shortlists are flat, so "flat" is not the same question as
           "favourites": the history list needs its own name here. */
        if (ui->genre_tab == SM_STRIP_HISTORY)
            snprintf(header, sizeof(header), "RECENTLY PLAYED");
        else if (ui->flat)
            snprintf(header, sizeof(header), "FAVOURITES");
        else if (ui->view != SM_VIEW_LIST && ui->genre_tab) {
            const sm_genre_tab_t *tab = strip_genre(ui, ui->genre_tab);
            snprintf(header, sizeof(header), "%s  /%.*s", tab ? tab->code : "FAV",
                (int)sizeof(header) - 8, folder_for_display(ui));
        } else
            snprintf(header, sizeof(header), "/%.*s", (int)sizeof(header) - 2, folder_for_display(ui));
        graphics_set_color(graphics_make_color(245, 230, 160, 255), 0);
        draw_truncated(s, l->safe_left + 3, l->safe_top + 3, header, counter_chars - 10);
        if (ui->item_count) {
            snprintf(counter, sizeof(counter), "%u/%u",
                (unsigned)(ui->selected + 1u), (unsigned)ui->item_count);
            graphics_set_color(graphics_make_color(180, 200, 220, 255), 0);
            graphics_draw_text(s, l->safe_right - 3 - (int)strlen(counter) * SM_FONT_WIDTH,
                l->safe_top + 3, counter);
        }

        /* Neither the grid nor coverflow has room for the strip; the title
           bar carries the active genre for them instead. */
        if (ui->view == SM_VIEW_LIST) draw_genre_tabs(s, l, ui);

        if (ui->view == SM_VIEW_GRID) {
            draw_grid(s, l, c, ui);
        } else if (ui->view == SM_VIEW_COVERFLOW) {
            draw_coverflow(s, l, c, ui);
        } else {
            draw_list(s, l, c, ui);
            draw_panel(s, l, c, ui);
        }

        /* Help bar. The list and the grid answer to different buttons, so it
           says what the screen in front of you actually does. */
        graphics_draw_box(s, l->safe_left, l->footer_top, l->safe_right - l->safe_left,
            SM_FOOTER_HEIGHT, graphics_make_color(16, 22, 32, 255));
        graphics_set_color(graphics_make_color(180, 200, 220, 255), 0);
        draw_truncated(s, l->safe_left + 3, l->footer_top + 2,
            ui->status ? ui->status : footer_hint(c, ui),
            (l->safe_right - l->safe_left - 6) / SM_FONT_WIDTH);
    }
}

void ui_close(sm_ui_t *ui) {
    unload_cover(ui);
    unload_slots(ui);
    sm_cover_pack_close(&ui->covers);
}
