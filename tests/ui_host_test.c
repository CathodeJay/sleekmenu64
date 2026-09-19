/* SPDX-License-Identifier: AGPL-3.0-only */
/* The browser, actually run.

   Four bugs reached hardware in a row -- a folder in the grid drawn as the
   first game inside it, genres that existed on the card and could be selected
   from nowhere, a favourite button that only printed a sentence, and a cover
   read from the card on every single keypress. Every one is behaviour, and
   none of them is visible in a source scan. So the UI gets driven here, with
   libdragon stood in for and the card counted. */
#include "ui.h"
#include "favorites.h"
#include "launch.h"
#include "rom_load.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

/* --- the catalog, as a fixture ---------------------------------------- */
typedef struct {
    const char *path, *title, *genre;
    uint8_t flags;
    const char *publisher;      /* optional; "" when the fixture does not care */
    uint16_t year;
    const char *description;    /* optional */
} row_t;
static const row_t *ROWS;
static uint32_t ROW_COUNT;
static sm_catalog_t CATALOG;

bool catalog_get(const sm_catalog_t *catalog, uint32_t index, sm_game_t *game) {
    (void)catalog;
    if (index >= ROW_COUNT) return false;
    memset(game, 0, sizeof(*game));
    game->title = ROWS[index].title;
    game->path = ROWS[index].path;
    game->cover = "cover.sprite";
    game->publisher = ROWS[index].publisher ? ROWS[index].publisher : "";
    game->genre = ROWS[index].genre;
    game->description = ROWS[index].description ? ROWS[index].description : "";
    game->year = ROWS[index].year;
    game->flags = ROWS[index].flags;
    return true;
}

bool catalog_matches(const sm_game_t *game, const sm_filter_t *filter) {
    if (filter->genre && strcmp(game->genre, filter->genre)) return false;
    if (filter->publisher && strcmp(game->publisher, filter->publisher)) return false;
    if (filter->year && game->year != filter->year) return false;
    if (filter->favorites_only && !(game->flags & SM_FLAG_FAVORITE)) return false;
    return true;
}

/* --- everything the launch screen would reach ------------------------- */
static surface_t screen;
bool sm_cart_image_intact(void) { return true; }
/* The prepared game, the way launch.c keeps it: set by prepare, cleared by
   cancel, and what the card's Start checks before it plays. */
static char fake_selected[256];
sm_launch_result_t launch_prepare(const char *path) {
    snprintf(fake_selected, sizeof(fake_selected), "%s", path);
    return SM_LAUNCH_OK;
}
const char *launch_status_message(void) { return "ready"; }
const char *launch_selected_path(void) { return fake_selected; }
/* The UI lends the launcher its history list at startup; nothing boots
   here, so the loan is simply taken and dropped. */
void launch_set_history(sm_history_t *history) { (void)history; }
void launch_cancel(void) { fake_selected[0] = '\0'; }
sm_launch_result_t launch_probe(void) { return SM_LAUNCH_OK; }
/* Launches are counted rather than made, and the launcher's verdict on the
   selected file is whatever a test says it is. */
static int fake_launches;
static sm_launch_result_t fake_last_result = SM_LAUNCH_OK;
sm_launch_result_t launch_rom(sm_launch_progress_cb cb, void *ctx) {
    (void)cb; (void)ctx; fake_launches++; return SM_LAUNCH_OK;
}
sm_boot_mode_t launch_boot_mode(void) { return SM_BOOT_FAST; }
void launch_set_boot_mode(sm_boot_mode_t mode) { (void)mode; }
uint32_t launch_boot_crc(void) { return 0; }
sm_cic_t launch_detected_cic(void) { return (sm_cic_t)0; }
sm_launch_result_t launch_last_result(void) { return fake_last_result; }
const char *launch_save_summary(void) { return ""; }
bool launch_selected_is_disk(void) { return false; }
const char *launch_sibling_disk(void) { return ""; }
/* The cheat set the launcher would have read for the selected game. Empty
   and "no file" until a test fills it in. */
static sm_cheat_set_t fake_cheats;
static sm_cheat_source_t fake_cheats_source;
static sm_cheat_pack_t fake_cheat_pack;
const sm_cheat_pack_t *launch_cheat_pack(void) { return &fake_cheat_pack; }
static bool fake_cheats_available;
static bool fake_cheats_possible = true;
static sm_cheats_hook_t fake_cheats_hook = SM_CHEATS_HOOK_OK;
static int fake_cheat_saves;
bool launch_cheats_available(void) { return fake_cheats_available; }
bool launch_cheats_possible(void) { return fake_cheats_possible; }
sm_cheats_hook_t launch_cheats_hook(void) { return fake_cheats_hook; }
const sm_cheat_set_t *launch_cheats(void) { return &fake_cheats; }
const sm_cheat_source_t *launch_cheats_source(void) { return &fake_cheats_source; }
bool launch_cheat_toggle(uint32_t index) {
    if (index >= fake_cheats.count || fake_cheats.cheats[index].incomplete) return false;
    fake_cheats.cheats[index].enabled = !fake_cheats.cheats[index].enabled;
    return true;
}
bool launch_cheats_save(void) { fake_cheat_saves++; return true; }
sm_save_type_t launch_save_type(void) { return SM_SAVE_OFF; }
/* launch_policy.c owns these two, and it drags in the rest of the launcher. */
sm_rom_format_t sm_rom_format_detect(const uint8_t *header, size_t length) {
    (void)header; (void)length; return SM_ROM_FORMAT_UNKNOWN;
}
void sm_rom_header_normalise(uint8_t *header, size_t length, sm_rom_format_t format) {
    (void)header; (void)length; (void)format;
}
bool launch_suffix_is_disk(const char *path) {
    size_t n = path ? strlen(path) : 0;
    return n >= 4 && !strcasecmp(path + n - 4, ".ndd");
}
surface_t *app_display_begin(void) { return &screen; }
void app_display_end(surface_t *surface) { (void)surface; }
bool launch_resolve_paths(const char *path, sm_launch_paths_t *paths) {
    if (!paths) return false;
    memset(paths, 0, sizeof(*paths));
    snprintf(paths->primary, sizeof(paths->primary), "/nonexistent/%s", path);
    paths->count = 1;
    return true;
}

/* --- harness ----------------------------------------------------------- */
static sm_ui_t ui;
static sm_layout_t layout;
static uint16_t screen_pixels[320 * 240];

static void layout_ntsc(void) {
    memset(&layout, 0, sizeof(layout));
    layout.width = 320; layout.height = 240;
    layout.safe_left = 24; layout.safe_top = 20;
    layout.safe_right = 296; layout.safe_bottom = 220;
    layout.row_height = SM_ROW_HEIGHT;
    layout.tabs_top = 36; layout.list_top = 49; layout.list_height = 157;
    layout.list_width = 168; layout.scrollbar_x = 192; layout.panel_x = 198;
    layout.footer_top = 210;
    layout.visible_rows = layout.list_height / layout.row_height;
}

static const sm_actions_t NONE;

static void frame(sm_actions_t actions) { ui_update(&ui, &CATALOG, actions, &layout); }
static void idle(int frames) { while (frames-- > 0) frame(NONE); }
static void settle(void) { idle(SM_UI_SETTLE_FRAMES + 2); }

/* Coverflow writes its covers straight into the framebuffer rather than
   through graphics_draw_box, so counting a colour is how a test sees what it
   drew. The stub's fill_screen is a no-op, hence the explicit clear. */
static uint16_t rgba16_of(unsigned red, unsigned green, unsigned blue) {
    return (uint16_t)(((red >> 3) << 11) | ((green >> 3) << 6) |
                      ((blue >> 3) << 1) | 1u);
}
static int count_pixels(uint16_t colour) {
    int found = 0;
    for (size_t i = 0; i < sizeof(screen_pixels) / sizeof(screen_pixels[0]); i++)
        if (screen_pixels[i] == colour) found++;
    return found;
}
static void draw_clean(void);

static void draw(void) {
    memset(&screen, 0, sizeof(screen));
    screen.flags = FMT_RGBA16;
    screen.width = 320; screen.height = 240;
    screen.stride = 320 * 2;
    screen.buffer = screen_pixels;
    sm_test_reset();
    ui_draw(&screen, &layout, &CATALOG, &ui);
}

/* The browser probes for a cover before loading it, so one has to exist. */
static void draw_clean(void) {
    memset(screen_pixels, 0, sizeof(screen_pixels));
    draw();
}

static void make_cover(void) {
    FILE *file;
    if (system("mkdir -p " SM_COVERS_DIR)) return;
    file = fopen(SM_COVERS_DIR "/cover.sprite", "wb");
    if (file) { fputs("sprite", file); fclose(file); }
}

static void start(const row_t *rows, uint32_t count) {
    remove(SM_FAVORITES_PATH);
    ui_close(&ui);
    memset(&ui, 0, sizeof(ui));
    ROWS = rows; ROW_COUNT = count;
    memset(&CATALOG, 0, sizeof(CATALOG));
    CATALOG.count = count;
    frame(NONE);
}

static sm_actions_t press_of(size_t offset) {
    sm_actions_t a;
    memset(&a, 0, sizeof(a));
    ((bool *)&a)[offset] = true;
    return a;
}
#define PRESS(field) press_of(offsetof(sm_actions_t, field))

int main(void) {
    layout_ntsc();
    make_cover();

    /* ---- a folder in the grid is a folder -------------------------- */
    {
        static const row_t rows[] = {
            {"Racing/Wave Race 64.z64", "Wave Race 64", "Racing", 0, "", 0, NULL},
            {"Racing/Mario Kart 64.z64", "Mario Kart 64", "Racing", 0, "", 0, NULL},
            {"Zelda.z64", "Zelda", "Action", 0, "", 0, NULL},
        };
        start(rows, 3u);
        frame(PRESS(toggle_view));
        settle();
        draw();
        /* The folder is named after the folder. The game that happens to sort
           first inside it is not on screen at all. */
        assert(sm_test_drew("Racing"));
        assert(!sm_test_drew("Wave Race 64"));
    }

    /* ---- the card is left alone while the cursor is moving ---------- */
    {
        static const row_t rows[] = {
            {"a.z64", "A", "Racing", 0, "", 0, NULL}, {"b.z64", "B", "Racing", 0, "", 0, NULL},
            {"c.z64", "C", "Racing", 0, "", 0, NULL}, {"d.z64", "D", "Racing", 0, "", 0, NULL},
        };
        int after_move;
        start(rows, 4u);
        settle();
        sm_test_reset();
        /* Holding down: four moves, and not one read. */
        frame(PRESS(down)); frame(PRESS(down)); frame(PRESS(down)); frame(PRESS(down));
        after_move = sm_test_sprite_loads;
        assert(after_move == 0);
        settle();
        /* One read once it stops, for the game now under the cursor. */
        assert(sm_test_sprite_loads == 1);
    }

    /* ---- scrolling the grid keeps what it already has --------------- */
    {
        static row_t rows[24];
        static char paths[24][16], titles[24][8];
        int filled, after_scroll;
        for (int i = 0; i < 24; i++) {
            snprintf(paths[i], sizeof(paths[i]), "g%02d.z64", i);
            snprintf(titles[i], sizeof(titles[i]), "G%02d", i);
            rows[i].path = paths[i]; rows[i].title = titles[i];
            rows[i].genre = "Racing"; rows[i].flags = 0;
        }
        start(rows, 24u);
        sm_test_reset();
        frame(PRESS(toggle_view));
        idle(40);                                  /* one tile per frame */
        filled = sm_test_sprite_loads;
        if (filled != SM_UI_GRID_VISIBLE)
            fprintf(stderr, "grid filled %d of %d\n", filled, SM_UI_GRID_VISIBLE);
        assert(filled == SM_UI_GRID_VISIBLE);
        sm_test_reset();
        /* Down from the last row scrolls by one row of four. Eight tiles stay
           where they are and must not be read again. */
        ui.selected = SM_UI_GRID_VISIBLE - 1u;
        frame(PRESS(down));
        idle(40);
        after_scroll = sm_test_sprite_loads;
        if (after_scroll != SM_UI_GRID_COLUMNS)
            fprintf(stderr, "scroll re-read %d tiles, expected %d\n",
                    after_scroll, SM_UI_GRID_COLUMNS);
        assert(after_scroll == SM_UI_GRID_COLUMNS);
    }

    /* ---- the favourite button favourites -------------------------- */
    {
        static const row_t rows[] = {
            {"a.z64", "A", "Racing", 0, "", 0, NULL}, {"b.z64", "B", "Racing", 0, "", 0, NULL},
        };
        start(rows, 2u);
        settle();
        assert(!sm_favorites_contains(&ui.favorites, "a.z64"));
        frame(PRESS(favorite));
        assert(sm_favorites_contains(&ui.favorites, "a.z64"));
        assert(!strcmp(ui.status, "Added to favourites"));
        /* It reached the card, so a power cycle keeps it. */
        {
            sm_favorites_t reloaded;
            sm_favorites_load(&reloaded, SM_FAVORITES_PATH);
            assert(sm_favorites_contains(&reloaded, "a.z64"));
        }
        /* And the list shows which one it is without filtering for them. */
        draw();
        assert(sm_test_drew("A"));
        frame(PRESS(favorite));
        assert(!sm_favorites_contains(&ui.favorites, "a.z64"));
        assert(!strcmp(ui.status, "Removed from favourites"));
    }

    /* ---- the favourites filter uses what was pressed --------------- */
    {
        static const row_t rows[] = {
            {"a.z64", "Alpha", "Racing", 0, "", 0, NULL}, {"b.z64", "Beta", "Racing", 0, "", 0, NULL},
        };
        start(rows, 2u);
        settle();
        frame(PRESS(down));                         /* onto Beta */
        frame(PRESS(favorite));
        ui.filter.favorites_only = true;
        frame(PRESS(filter));                       /* into filters */
        frame(PRESS(back));                         /* out, which rebuilds */
        assert(ui.item_count == 1u);
        draw();
        assert(sm_test_drew("Beta"));
        assert(!sm_test_drew("Alpha"));
    }

    /* ---- a favourite survives a catalog that never heard of it ------ */
    {
        static const row_t before[] = {{"a.z64", "A", "Racing", 0, "", 0, NULL}};
        static const row_t after[] = {{"a.z64", "A (USA)", "Puzzle", 0, "", 0, NULL}};
        start(before, 1u);
        settle();
        frame(PRESS(favorite));
        /* Same card, a catalog rebuilt with different metadata. */
        ui_close(&ui);
        memset(&ui, 0, sizeof(ui));
        ROWS = after; ROW_COUNT = 1u;
        memset(&CATALOG, 0, sizeof(CATALOG));
        CATALOG.count = 1u;
        frame(NONE);
        assert(sm_favorites_contains(&ui.favorites, "a.z64"));
        ui.filter.favorites_only = true;
        frame(PRESS(filter));
        frame(PRESS(back));
        assert(ui.item_count == 1u);
    }

    /* ---- every genre on the card can be selected ------------------- */
    {
        static row_t rows[24];
        static char paths[24][16], genres[24][12];
        int seen[24];
        start(rows, 0u);
        for (int i = 0; i < 24; i++) {
            snprintf(paths[i], sizeof(paths[i]), "g%02d.z64", i);
            snprintf(genres[i], sizeof(genres[i]), "Genre%02d", i);
            rows[i].path = paths[i]; rows[i].title = "T";
            rows[i].genre = genres[i]; rows[i].flags = 0;
            seen[i] = 0;
        }
        start(rows, 24u);
        /* The strip is "all", the fixed shortlists, then all twenty-four
           genres. Walked until it comes back round rather than a fixed number
           of presses, so adding another fixed tab cannot quietly leave the far
           end of the strip untested -- which is exactly what it did when
           history was added. Before any of this it held eight and the rest of
           the card was unreachable. */
        {
            int saw_favourites = 0, saw_history = 0, steps = 0;
            do {
                if (ui.filter.genre)
                    for (int i = 0; i < 24; i++)
                        if (!strcmp(ui.filter.genre, genres[i])) seen[i] = 1;
                if (ui.filter.favorites_only) saw_favourites = 1;
                if (ui.genre_tab == 2u) saw_history = 1;   /* SM_STRIP_HISTORY */
                frame(PRESS(genre_next));
                assert(++steps < 64);       /* the strip must be a ring */
            } while (ui.genre_tab != 0u);
            for (int i = 0; i < 24; i++) assert(seen[i]);
            assert(saw_favourites);
            assert(saw_history);
            /* All twenty-four genres plus "all", favourites and history. */
            assert(steps == 27);
        }
        /* and the strip draws only what fits, wherever the cursor is */
        for (int step = 0; step < 24; step++) {
            draw();
            frame(PRESS(genre_next));
        }
    }

    /* ---- favourites are one button away, not five ----------------- */
    {
        /* Nobody could find the favourites list, because reaching it meant
           opening the filter screen and pressing down five times. It is a
           subset like a genre, so it lives on the strip beside them: one
           press of C-left from "all". */
        static const row_t rows[] = {
            {"a.z64", "Alpha", "Racing", 0, "", 0, NULL},
            {"b.z64", "Beta", "Racing", 0, "", 0, NULL},
            {"c.z64", "Gamma", "Sports", 0, "", 0, NULL},
        };
        start(rows, 3u);
        frame(PRESS(down));                  /* onto Beta */
        frame(PRESS(favorite));              /* star it */
        assert(sm_favorites_contains(&ui.favorites, "b.z64"));

        assert(!ui.filter.favorites_only);
        frame(PRESS(genre_next));            /* one step right from "all" */
        assert(ui.filter.favorites_only);
        assert(ui.filter.genre == NULL);
        assert(ui.item_count == 1u);         /* just the starred one */

        /* Next along is history, the other shortlist. Nothing has been
           launched here, so it is empty -- and empty is a state the browser
           has to sit in without a filter left switched on behind it. */
        frame(PRESS(genre_next));
        assert(!ui.filter.favorites_only);
        assert(ui.filter.genre == NULL);
        assert(ui.flat);                     /* flat, like favourites */
        assert(ui.item_count == 0u);

        /* Stepping on to a genre clears both rather than compounding: the
           strip shows one subset, and the filter screen is where they
           combine. */
        frame(PRESS(genre_next));
        assert(!ui.filter.favorites_only);
        assert(ui.filter.genre != NULL);
        assert(!ui.flat);

        /* And back the other way returns through history to favourites, then
           to "all". */
        frame(PRESS(genre_prev));
        assert(ui.item_count == 0u);         /* history again */
        frame(PRESS(genre_prev));
        assert(ui.filter.favorites_only);
        assert(ui.item_count == 1u);
        frame(PRESS(genre_prev));
        assert(!ui.filter.favorites_only);
        assert(ui.filter.genre == NULL);
        assert(ui.item_count == 3u);

        draw();
        assert(sm_test_drew("FAV"));
    }

    /* ---- the shortlist ignores folders --------------------------- */
    {
        /* A favourite in "1 US - A-M" and one in "2 Japan" are one list.
           Showing only the ones in the folder you happen to be standing in
           would make the shortlist useless exactly when it is most wanted. */
        static const row_t rows[] = {
            {"1 US - A-M/Blast Corps.z64", "Blast Corps", "Action", 0, "", 0, NULL},
            {"1 US - A-M/Cruisn.z64", "Cruisn", "Racing", 0, "", 0, NULL},
            {"2 Japan/Sin to Punishment.z64", "Sin", "Shooters", 0, "", 0, NULL},
            {"3 Europe/Lylat Wars.z64", "Lylat", "Shooters", 0, "", 0, NULL},
        };
        start(rows, 4u);
        /* Root shows three folders and no games. */
        assert(ui.item_count == 3u);

        /* Star one in the first folder... */
        frame(PRESS(select));                     /* into 1 US - A-M */
        assert(ui.item_count == 2u);
        frame(PRESS(favorite));
        assert(sm_favorites_contains(&ui.favorites, "1 US - A-M/Blast Corps.z64"));

        /* ...and one two folders away. */
        frame(PRESS(back));
        frame(PRESS(down)); frame(PRESS(down));   /* onto 3 Europe */
        frame(PRESS(select));
        frame(PRESS(favorite));
        assert(sm_favorites_contains(&ui.favorites, "3 Europe/Lylat Wars.z64"));

        /* Standing inside 3 Europe, the shortlist still holds both, and no
           folder rows at all. */
        frame(PRESS(genre_next));
        assert(ui.filter.favorites_only);
        assert(ui.item_count == 2u);
        for (uint32_t i = 0; i < ui.item_count; i++)
            assert(!(ui.items[i] & SM_UI_FOLDER_BIT));

        /* B is "out", not "up": there is no parent of a shortlist. It puts
           back the folder we were in. */
        frame(PRESS(back));
        assert(!ui.filter.favorites_only);
        assert(!strcmp(ui.folder, "3 Europe"));
        assert(ui.item_count == 1u);
    }

    /* ---- the two screens agree about favourites ------------------ */
    {
        static const row_t rows[] = {
            {"US/a.z64", "Alpha", "Racing", 0, "", 0, NULL},
            {"US/b.z64", "Beta", "Racing", 0, "", 0, NULL},
            {"JP/c.z64", "Gamma", "Sports", 0, "", 0, NULL},
        };
        start(rows, 3u);
        frame(PRESS(select));                 /* into US */
        frame(PRESS(favorite));               /* star Alpha */

        /* Turning favourites on from the filter screen, with no genre set,
           has to land in the same state as pressing the tab: flat and
           card-wide. Otherwise the strip says one thing and the list shows
           another. */
        frame(PRESS(filter));                 /* Z */
        for (int i = 0; i < 5; i++) frame(PRESS(down));
        frame(PRESS(right));                  /* FAVORITES -> Only */
        assert(ui.filter.favorites_only);
        assert(ui.flat);
        assert(ui.genre_tab == 1u);           /* the FAV tab */
        /* and the count in the header is live while the screen is still open */
        assert(ui.item_count == 1u);

        frame(PRESS(right));                  /* back to Any */
        assert(!ui.filter.favorites_only);
        assert(!ui.flat);
        assert(!strcmp(ui.folder, "US"));     /* put back where we were */
        frame(PRESS(back));
        assert(ui.item_count == 2u);
    }

    /* ---- the launch card has a cover, whichever view you came from --- */
    {
        /* The grid keeps its covers in slot_sprites; the launch card draws
           cover_sprite, which only the list view ever filled in. Selecting a
           game from the grid therefore showed a card with no box on it, and
           "..." where the save type belongs. */
        static const row_t rows[] = {
            {"a.z64", "Alpha", "Racing", 0, "", 0, NULL},
            {"b.z64", "Beta", "Racing", 0, "", 0, NULL},
        };
        start(rows, 2u);
        frame(PRESS(toggle_view));            /* into the grid */
        assert(ui.view == SM_VIEW_GRID);
        settle();
        assert(ui.cover_sprite == NULL);      /* the grid has not needed it */

        frame(PRESS(select));                 /* A on a game */
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS);
        assert(ui.cover_sprite != NULL);
        draw();                               /* and the card can draw it */
        /* The other half of the same fix -- the save type, which also only
           the list view used to load -- cannot be asserted here: it is read
           from the ROM's own header, and the host has no ROMs. It goes down
           the identical path, one line above this in ui_update. */

        frame(PRESS(back));
        assert(ui.screen == SM_SCREEN_LIBRARY);
    }

    /* ---- a filter you cannot clear is a filter you cannot use -------- */
    {
        /* Publisher and year used to step through the catalog in storage
           order, reaching "Any" only by falling off one end of it. On a card
           with two hundred publishers that is two hundred presses, which is
           the same as no way back at all. */
        static const row_t rows[] = {
            {"a.z64", "Alpha", "Racing", 0, "Nintendo", 1996, NULL},
            {"b.z64", "Beta", "Racing", 0, "Acclaim", 1998, NULL},
            {"c.z64", "Gamma", "Sports", 0, "Midway", 1997, NULL},
            {"d.z64", "Delta", "Sports", 0, "Acclaim", 1996, NULL},
        };
        start(rows, 4u);
        frame(PRESS(filter));
        for (int i = 0; i < 3; i++) frame(PRESS(down));   /* onto PUBLISHER */
        assert(ui.filter_row == 3);

        /* Alphabetical, and back to Any after the last one. */
        frame(PRESS(right)); assert(!strcmp(ui.filter.publisher, "Acclaim"));
        frame(PRESS(right)); assert(!strcmp(ui.filter.publisher, "Midway"));
        frame(PRESS(right)); assert(!strcmp(ui.filter.publisher, "Nintendo"));
        frame(PRESS(right)); assert(ui.filter.publisher == NULL);   /* Any */

        /* And the other way round from Any lands on the last one. */
        frame(PRESS(left)); assert(!strcmp(ui.filter.publisher, "Nintendo"));
        frame(PRESS(left)); assert(!strcmp(ui.filter.publisher, "Midway"));
        frame(PRESS(left)); assert(!strcmp(ui.filter.publisher, "Acclaim"));
        frame(PRESS(left)); assert(ui.filter.publisher == NULL);

        /* Year, in numeric order, with the same escape. */
        frame(PRESS(down));
        assert(ui.filter_row == 4);
        frame(PRESS(right)); assert(ui.filter.year == 1996);
        frame(PRESS(right)); assert(ui.filter.year == 1997);
        frame(PRESS(right)); assert(ui.filter.year == 1998);
        frame(PRESS(right)); assert(ui.filter.year == 0);           /* Any */
        frame(PRESS(left));  assert(ui.filter.year == 1998);
        frame(PRESS(left));  assert(ui.filter.year == 1997);

        /* The count in the header tracks it while the screen is still open. */
        assert(ui.item_count == 1u);
        frame(PRESS(right)); frame(PRESS(right));                   /* back to Any */
        assert(ui.filter.year == 0);
        assert(ui.item_count == 4u);
    }

    /* ---- how big the thing is ------------------------------------ */
    {
        /* Cartridge images are powers of two and read better whole. A trimmed
           or homebrew image is not, and rounding it to "8 MB" would make it
           look like something it is not. */
        char size[24];
        struct { uint32_t bytes; const char *want; } cases[] = {
            {0u, "-"},
            {8u << 20, "8 MB"},
            {64u << 20, "64 MB"},
            {12u << 20, "12 MB"},
            {8668496u, "8.3 MB"},          /* Golden Sun 64, a total conversion */
            {12801336u, "12.2 MB"},        /* a GoldenEye hack */
            {(1u << 20) - 1u, "1024 KB"},  /* just under, still not "1 MB" */
            {512u << 10, "512 KB"},
            {1u, "1 KB"},                  /* rounded up: never "0 KB" */
        };
        for (size_t i = 0; i < sizeof(cases) / sizeof(*cases); i++) {
            sm_format_rom_size(cases[i].bytes, size, sizeof(size));
            if (strcmp(size, cases[i].want)) {
                fprintf(stderr, "size of %u\n  got  %s\n  want %s\n",
                        (unsigned)cases[i].bytes, size, cases[i].want);
                assert(0);
            }
        }
        /* A buffer too small must truncate rather than run over. */
        char tiny[3];
        sm_format_rom_size(8u << 20, tiny, sizeof(tiny));
        assert(strlen(tiny) < sizeof(tiny));
        sm_format_rom_size(8u << 20, NULL, 0);      /* must not crash */

        /* And it reaches the screen: the panel carries a SIZE row now. */
        {
            static const row_t rows[] = {{"a.z64", "Alpha", "Racing", 0, "", 0, NULL}};
            start(rows, 1u);
            settle();
            draw();
            assert(sm_test_drew("SIZE"));
            /* Seven rows is what the NTSC panel holds exactly; the path along
               the bottom is the thing a row too many would push off. */
            assert(sm_test_drew("a.z64"));
            assert(sm_test_drew("SAVE"));
            assert(sm_test_drew("PAK"));
        }
    }

    /* ---- the history tab lists what was launched -------------------- */
    {
        static const row_t rows[] = {
            {"ROMS/US/Alpha.z64", "Alpha", "Racing", 0, "", 0, NULL},
            {"ROMS/US/Beta.z64",  "Beta",  "Racing", 0, "", 0, NULL},
            {"ROMS/JP/Gamma.z64", "Gamma", "Puzzle", 0, "", 0, NULL},
        };
        start(rows, 3u);

        /* Nothing launched yet: the tab exists and is empty. */
        frame(PRESS(genre_next));            /* favourites */
        frame(PRESS(genre_next));            /* history */
        assert(ui.genre_tab == 2u);
        assert(ui.item_count == 0u);

        /* Record two launches the way launch.c does, most recent last. */
        sm_history_record(&ui.history, "ROMS/US/Alpha.z64");
        sm_history_record(&ui.history, "ROMS/JP/Gamma.z64");
        frame(PRESS(genre_prev)); frame(PRESS(genre_next));   /* re-enter */
        assert(ui.item_count == 2u);

        /* Recency order, not catalog order: Gamma was launched last and is
           catalog index 2, so a catalog-ordered list would put it second. */
        assert(ui.items[0] == 2u);           /* Gamma */
        assert(ui.items[1] == 0u);           /* Alpha */

        /* It ignores folders, like the other shortlist: Alpha lives in US and
           Gamma in JP, and both are here. */
        assert(ui.flat);

        /* THE BUG THIS EXISTS FOR. launch.c has two forms of the same path in
           scope: `opened_path`, which is what the loader opened ("sd:/ROMS/
           ..."), and `selected`, the catalog's card-relative form. It recorded
           the first, so every lookup here missed and the tab was permanently
           empty however much you played. Nothing about the sd:/ form is
           malformed -- it just names the same file in the other vocabulary. */
        sm_history_record(&ui.history, "sd:/ROMS/US/Beta.z64");
        frame(PRESS(genre_prev)); frame(PRESS(genre_next));
        assert(sm_history_count(&ui.history) == 3u);   /* it was recorded... */
        assert(ui.item_count == 2u);                   /* ...and matches nothing */

        /* The card-relative form does match, which is the whole point. */
        sm_history_record(&ui.history, "ROMS/US/Beta.z64");
        frame(PRESS(genre_prev)); frame(PRESS(genre_next));
        assert(ui.item_count == 3u);
        assert(ui.items[0] == 1u);           /* Beta, most recent */

        /* And the header says what you are looking at. Every flat view used to
           be labelled FAVOURITES, history included. */
        draw();
        assert(sm_test_drew("RECENTLY PLAYED"));
        assert(!sm_test_drew("FAVOURITES"));
        frame(PRESS(genre_prev));            /* back to favourites */
        draw();
        assert(sm_test_drew("FAVOURITES"));
    }

    /* ---- a library all under one folder opens inside it -------------- */
    {
        static const row_t rows[] = {
            {"ROMS/US/Alpha.z64", "Alpha", "Racing", 0, "", 0, NULL},
            {"ROMS/US/Beta.z64",  "Beta",  "Racing", 0, "", 0, NULL},
            {"ROMS/JP/Gamma.z64", "Gamma", "Puzzle", 0, "", 0, NULL},
        };
        start(rows, 3u);
        /* Every game is under ROMS/, so the first thing on screen is US and
           JP, not a list with one entry called ROMS in it. */
        assert(!strcmp(ui.root, "ROMS"));
        assert(!strcmp(ui.folder, "ROMS"));
        assert(ui.item_count == 2u);
        assert((ui.items[0] & SM_UI_FOLDER_BIT) && (ui.items[1] & SM_UI_FOLDER_BIT));
        draw();
        assert(!sm_test_drew("ROMS"));
        /* B at the root stays put: there is nothing above the library. */
        frame(PRESS(back));
        assert(!strcmp(ui.folder, "ROMS"));
        assert(ui.item_count == 2u);
        /* Into US and back out lands on US, as before, without leaving. */
        frame(PRESS(select));
        assert(!strcmp(ui.folder, "ROMS/US"));
        assert(ui.item_count == 2u);
        draw();
        assert(sm_test_drew("/US"));
        frame(PRESS(back));
        assert(!strcmp(ui.folder, "ROMS"));
        /* The shortlists still hold full paths, so a favourite is found. */
        frame(PRESS(select)); frame(PRESS(favorite));
        frame(PRESS(genre_next));            /* favourites, flat */
        assert(ui.flat && ui.item_count == 1u);
        frame(PRESS(back));                  /* out of the shortlist */
        assert(!ui.flat && !strcmp(ui.folder, "ROMS/US"));
    }

    /* ---- games in two places open at the card root ------------------ */
    {
        static const row_t rows[] = {
            {"ROMS/Alpha.z64", "Alpha", "Racing", 0, "", 0, NULL},
            {"Homebrew/Beta.z64", "Beta", "Racing", 0, "", 0, NULL},
        };
        start(rows, 2u);
        assert(ui.root[0] == '\0' && ui.folder[0] == '\0');
        assert(ui.item_count == 2u);
        draw();
        assert(sm_test_drew("ROMS") && sm_test_drew("Homebrew"));
    }

    /* ---- and a nested common folder is followed all the way down ------ */
    {
        static const row_t rows[] = {
            {"ROMS/N64/A/Alpha.z64", "Alpha", "Racing", 0, "", 0, NULL},
            {"ROMS/N64/Beta.z64", "Beta", "Racing", 0, "", 0, NULL},
        };
        start(rows, 2u);
        assert(!strcmp(ui.root, "ROMS/N64"));
        assert(ui.item_count == 2u);         /* the folder A and the game Beta */
    }

    /* ---- coverflow -------------------------------------------------- */
    {
        static row_t rows[30];
        static char paths[30][16], titles[30][12];
        /* Six initials, five games each, so a letter jump has somewhere to go
           and the groups are long enough that stepping is visibly worse. */
        static const char INITIALS[] = "ABCMXZ";
        for (int i = 0; i < 30; i++) {
            snprintf(paths[i], sizeof(paths[i]), "g%02d.z64", i);
            snprintf(titles[i], sizeof(titles[i]), "%c game %d", INITIALS[i / 5], i);
            rows[i].path = paths[i]; rows[i].title = titles[i];
            rows[i].genre = "Racing"; rows[i].flags = 0;
            rows[i].publisher = ""; rows[i].year = 0;
        }
        start(rows, 30u);

        /* C-up cycles three ways round, not two. */
        assert(ui.view == SM_VIEW_LIST);
        frame(PRESS(toggle_view)); assert(ui.view == SM_VIEW_GRID);
        frame(PRESS(toggle_view)); assert(ui.view == SM_VIEW_COVERFLOW);
        frame(PRESS(toggle_view)); assert(ui.view == SM_VIEW_LIST);
        frame(PRESS(toggle_view)); frame(PRESS(toggle_view));
        assert(ui.view == SM_VIEW_COVERFLOW);

        /* The selection sits in the middle slot, so the window starts four
           before it -- three on screen plus the off-screen rung the animation
           slides from. At the top of the list that is before the list, and
           those slots hold nothing rather than wrapping to the end. */
        settle();
        assert(ui.selected == 0u);
        assert(ui.slot_base == -SM_UI_FLOW_OUTER);
        assert(ui.slot_count == SM_UI_FLOW_SLOTS);
        for (int slot = 0; slot < SM_UI_FLOW_OUTER; slot++)
            assert(ui.slot_indices[slot] == UINT32_MAX);
        assert(ui.slot_indices[SM_UI_FLOW_OUTER] == ui.items[0]);
        draw();                               /* and it draws in that state */

        /* Right walks the shelf and the window follows it. */
        frame(PRESS(right));
        assert(ui.selected == 1u);
        assert(ui.slot_base == 1 - SM_UI_FLOW_OUTER);

        /* One step costs one cover, not seven: the six that stay on screen
           are carried across rather than freed and read back. */
        settle();
        sm_test_reset();
        frame(PRESS(right));
        settle();
        assert(sm_test_sprite_loads == 1);

        /* L and R jump by initial. Five games per letter, so this is the
           difference between one press and five. */
        {
            uint32_t before = ui.selected;
            frame(PRESS(page_down));
            assert(ui.selected > before);
            assert(ui.selected == 5u);        /* first of the B group */
            frame(PRESS(page_down));
            assert(ui.selected == 10u);       /* first of the C group */
            /* Backwards lands on the *start* of the previous group, not its
               end: pressing L twice from the middle of C must reach A, and
               reach its first game. */
            frame(PRESS(page_up));
            assert(ui.selected == 5u);
            frame(PRESS(page_up));
            assert(ui.selected == 0u);
            /* And it stops at the ends rather than wrapping. */
            frame(PRESS(page_up));
            assert(ui.selected == 0u);
        }

        /* Up and down do the same as left and right: a d-pad in a hand does
           not know which axis this view thinks it is. */
        frame(PRESS(down));
        assert(ui.selected == 1u);
        frame(PRESS(up));
        assert(ui.selected == 0u);

        /* Leaving for the grid must release the seven and take twelve; coming
           back must release the twelve. The leak check below covers the
           balance, this covers the count. */
        frame(PRESS(toggle_view));
        assert(ui.view == SM_VIEW_LIST);
        frame(PRESS(toggle_view));
        assert(ui.view == SM_VIEW_GRID);
        settle();
        assert(ui.slot_count == SM_UI_GRID_VISIBLE);
        frame(PRESS(toggle_view));
        settle();
        assert(ui.slot_count == SM_UI_FLOW_SLOTS);
    }

    /* ---- the coverflow slide ---------------------------------------- */
    {
        static row_t rows[12];
        static char paths[12][16], titles[12][8];
        for (int i = 0; i < 12; i++) {
            snprintf(paths[i], sizeof(paths[i]), "g%02d.z64", i);
            snprintf(titles[i], sizeof(titles[i]), "G%02d", i);
            rows[i].path = paths[i]; rows[i].title = titles[i];
            rows[i].genre = "Racing"; rows[i].flags = 0;
            rows[i].publisher = ""; rows[i].year = 0;
        }
        start(rows, 12u);
        frame(PRESS(toggle_view)); frame(PRESS(toggle_view));
        assert(ui.view == SM_VIEW_COVERFLOW);
        settle();
        assert(ui.flow_frames == 0u);        /* settled */

        /* A step right starts the slide and says which way the shelf went.
           The countdown happens before the movement handler runs, so the
           press frame is started one short -- otherwise it would draw the
           shelf exactly where it already was and every step would open with a
           frame of stillness. */
        frame(PRESS(right));
        assert(ui.flow_dir == 1);
        assert(ui.flow_frames == SM_UI_FLOW_FRAMES - 1u);
        for (unsigned i = 0; i + 1u < SM_UI_FLOW_FRAMES; i++) {
            draw();
            assert(ui.flow_frames > 0u);     /* still moving */
            frame(NONE);
        }
        assert(ui.flow_frames == 0u);        /* and it finishes on its own */
        draw();                              /* settled, and still drawable */

        /* Left goes the other way. */
        frame(PRESS(left));
        assert(ui.flow_dir == -1);
        assert(ui.flow_frames > 0u);

        /* It keeps counting down while the cursor is settling. ui_update
           returns early during the settle delay, and a slide frozen half way
           because the controller stopped is worse than no slide. */
        {
            uint32_t before = ui.flow_frames;
            ui.settle = SM_UI_SETTLE_FRAMES;
            frame(NONE);
            assert(ui.flow_frames == before - 1u);
        }

        /* Changing view ends it: there is no shelf to have come from. */
        frame(PRESS(right));
        assert(ui.flow_frames > 0u);
        frame(PRESS(toggle_view));
        assert(ui.flow_frames == 0u);

        /* Nor does a slide survive the list changing underneath it. */
        frame(PRESS(toggle_view)); frame(PRESS(toggle_view));
        assert(ui.view == SM_VIEW_COVERFLOW);
        frame(PRESS(right));
        assert(ui.flow_frames > 0u);
        frame(PRESS(genre_next));            /* rebuilds onto favourites */
        assert(ui.flow_frames == 0u);

        /* Drawing mid-slide must be safe at both ends of the list, where a
           cover is sliding in from a rung that is off screen. */
        frame(PRESS(genre_prev));
        settle();
        frame(PRESS(right));
        draw();                              /* selection 1, near the start */
        for (int i = 0; i < 11; i++) { frame(PRESS(right)); draw(); }
        assert(ui.selected == 11u);          /* the end of the list */
        draw();
    }

    /* ---- a folder in coverflow looks like a folder ------------------ */
    {
        /* A folder used to get the same blank rectangle as a cover that had
           not streamed off the card yet, so on a shelf that is constantly
           loading you could not tell a folder from a picture about to appear.
           It is now a picture of its own, put through the same turning code. */
        static const row_t rows[] = {
            {"Racing/a.z64", "Alpha", "Racing", 0, "", 0, NULL},
            {"Racing/b.z64", "Beta",  "Racing", 0, "", 0, NULL},
            {"c.z64",        "Gamma", "Puzzle", 0, "", 0, NULL},
        };
        const uint16_t body = rgba16_of(78, 108, 150);
        const uint16_t tab = rgba16_of(245, 230, 160);
        start(rows, 3u);
        frame(PRESS(toggle_view)); frame(PRESS(toggle_view));
        assert(ui.view == SM_VIEW_COVERFLOW);
        settle();

        /* The folder sorts first, so it is the selection and sits face on. */
        assert(ui.items[0] & SM_UI_FOLDER_BIT);
        assert(ui.selected == 0u);
        draw_clean();
        assert(count_pixels(body) > 1000);   /* a 96x72 card, most of it body */
        assert(count_pixels(tab) > 100);     /* the tab and the lit lip */

        /* And it is drawn from the folder picture, not from a sprite: nothing
           has been loaded for it, and a cover with no sprite would be a plain
           box in the placeholder colour instead. */
        assert(ui.slot_sprites[SM_UI_FLOW_OUTER] == NULL);
        assert(count_pixels(rgba16_of(28, 36, 48)) == 0);

        /* Turned, it keeps both bands of contrast -- that is what survives
           being squeezed to a fifth of the width at the end of the shelf. */
        frame(PRESS(right));
        settle();
        assert(!(ui.items[ui.selected] & SM_UI_FOLDER_BIT));  /* on a game now */
        draw_clean();
        assert(count_pixels(body) > 100);    /* the folder, side on */
        assert(count_pixels(tab) > 10);
    }

    /* ---- coverflow on an empty shortlist ----------------------------- */
    {
        /* History starts empty on every card, and coverflow is one of the
           views it can be empty in. Drawing nothing must not read past the
           item list. */
        static const row_t rows[] = { {"a.z64", "Alpha", "Racing", 0, "", 0, NULL} };
        start(rows, 1u);
        frame(PRESS(toggle_view)); frame(PRESS(toggle_view));
        assert(ui.view == SM_VIEW_COVERFLOW);
        frame(PRESS(genre_next));            /* favourites: none set */
        frame(PRESS(genre_next));            /* history: nothing launched */
        assert(ui.item_count == 0u);
        settle();
        draw();
    }

    /* ---- the load bar ----------------------------------------------- */
    {
        static const row_t rows[] = { {"a.z64", "Alpha", "Racing", 0, "", 0, NULL} };
        start(rows, 1u);
        frame(PRESS(select));
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS);

        /* Nothing in flight: the card offers the decision. */
        assert(ui.load_total_kib == 0u);
        draw();
        assert(sm_test_drew("START"));

        /* Mid-transfer the bar replaces the prompts. Offering "START play"
           under a ROM that is already half loaded invites a second press. */
        ui.load_total_kib = 8192u;
        ui.load_done_kib = 2048u;
        ui.load_verifying = false;
        draw();
        assert(sm_test_drew("LOADING"));
        assert(sm_test_drew("25%"));
        assert(sm_test_drew("2/8 MB"));
        assert(!sm_test_drew("START   play"));

        /* The verify pass is named, because a bar that fills, empties and
           fills again with no explanation reads as a failure. */
        ui.load_verifying = true;
        ui.load_done_kib = 8192u;
        draw();
        assert(sm_test_drew("VERIFYING"));
        assert(sm_test_drew("100%"));

        /* A total of zero is "no load", not "divide by zero". */
        ui.load_total_kib = 0u;
        ui.load_done_kib = 0u;
        draw();
        assert(!sm_test_drew("LOADING"));
        assert(sm_test_drew("START"));

        /* And a done figure past the total clamps rather than overrunning the
           bar off the side of the screen. */
        ui.load_total_kib = 100u;
        ui.load_done_kib = 999u;
        draw();
        assert(sm_test_drew("100%"));
    }

    /* ---- nothing leaks ------------------------------------------- */
    {
        /* Counted from here rather than from the top of the run: the blocks
           above reset these counters for their own assertions, so a global
           total compares loads after the last reset against frees since
           before it and reads as a leak when there is none. What this has to
           prove is that a full cycle -- list cover, grid covers, close --
           gives every sprite back. */
        static const row_t rows[] = {{"a.z64", "A", "Racing", 0, "", 0, NULL}};
        start(rows, 1u);
        sm_test_reset();
        settle();
        frame(PRESS(toggle_view));
        idle(40);
        frame(PRESS(select));            /* the launch card takes one too */
        frame(PRESS(back));
        ui_close(&ui);
        assert(sm_test_sprite_loads > 0);
        assert(sm_test_sprite_frees == sm_test_sprite_loads);
    }

    /* ---- the description on the launch card ------------------------ */
    {
        /* A box back is a paragraph, and the card has a band of empty
           space under the cover. It goes there, wrapped on spaces to the
           safe width, cut with an ellipsis where it runs out of room --
           never clipped mid-word, never over the prompts. */
        static const row_t rows[] = {
            {"a.z64", "Alpha", "Racing", 0, "", 0,
             "Mario is super in a whole new way! Combining the finest 3-D graphics "
             "ever developed for a video game and an explosive sound track, Super "
             "Mario 64 becomes a new standard for video games. It's packed with "
             "bruising battles, daunting obstacle courses and underwater adventures. "
             "Retrieve the Power Stars from their hidden locations and confront your "
             "arch nemesis - Bowser, King of the Koopas! And then some more words "
             "so that it certainly does not fit on the card."},
            {"b.z64", "Beta", "Racing", 0, "", 0, NULL},
        };
        int lines, i;
        start(rows, 2u);
        frame(PRESS(select));
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS);
        draw();
        /* It is there, in pieces no wider than the safe area... */
        assert(sm_test_drew("Mario is super in a whole new way!"));
        lines = 0;
        for (i = 0; i < sm_test_text_count; i++) {
            const char *text = sm_test_text[i];
            if (strstr(text, "Mario is super") || strstr(text, "Koopas") ||
                strstr(text, "obstacle") || strstr(text, "standard") ||
                strstr(text, "Power Stars") || strstr(text, "explosive")) {
                assert((int)strlen(text) * SM_FONT_WIDTH <= layout.safe_right - layout.safe_left);
                /* ...never split inside a word: a line ends on a word or on
                   the ellipsis. */
                assert(text[strlen(text) - 1] != ' ');
                lines++;
            }
        }
        assert(lines >= 4);
        /* ...and it ends in an ellipsis, because it did not all fit. */
        assert(sm_test_drew("..."));
        assert(!sm_test_drew("certainly does not fit"));
        /* The prompts under it are untouched. */
        assert(sm_test_drew("START"));

        /* A game with nothing to say draws nothing extra. */
        frame(PRESS(back));
        frame(PRESS(down));
        frame(PRESS(select));
        draw();
        assert(!sm_test_drew("..."));
    }

    /* ---- the cheats page ---------------------------------------------- */
    {
        static const row_t rows[] = {
            {"a.z64", "Alpha", "Racing", 0, "", 0, NULL},
        };
        start(rows, 1u);
        settle();
        frame(PRESS(select));
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS);

        /* No file for the game: C-down says so and stays on the card --
           and says what the pack does have, when it has the game for
           another region. */
        fake_cheats_available = false;
        memset(&fake_cheats_source, 0, sizeof(fake_cheats_source));
        frame(PRESS(favorite));
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS);
        assert(ui.status && strstr(ui.status, "No cheat pack on the card"));
        fake_cheat_pack.count = 543;
        frame(PRESS(favorite));
        assert(ui.status && !strcmp(ui.status, "Not in the cheat pack (543 files) or sleekmenu/cheats"));
        fake_cheats_source.kind = SM_CHEAT_MATCH_OTHER_REGION;
        fake_cheats_source.found = SM_CART_REGION_EUROPE | SM_CART_REGION_JAPAN;
        fake_cheats_source.rom_region = SM_CART_REGION_USA;
        frame(PRESS(favorite));
        assert(ui.status && !strcmp(ui.status, "Cheat pack has this game for Europe, Japan; yours is USA"));
        draw();
        assert(!sm_test_drew("CHEATS"));

        /* A file with three entries, one of them without a value. */
        memset(&fake_cheats, 0, sizeof(fake_cheats));
        fake_cheats.count = 3;
        snprintf(fake_cheats.cheats[0].desc, SM_CHEAT_DESC_MAX, "Invincible");
        snprintf(fake_cheats.cheats[1].desc, SM_CHEAT_DESC_MAX, "Choose Level");
        fake_cheats.cheats[1].incomplete = true;
        snprintf(fake_cheats.cheats[2].desc, SM_CHEAT_DESC_MAX, "Infinite Time");
        fake_cheats.cheats[0].pairs = fake_cheats.cheats[2].pairs = 1;
        fake_cheats_available = true;
        memset(&fake_cheats_source, 0, sizeof(fake_cheats_source));
        snprintf(fake_cheats_source.path, sizeof(fake_cheats_source.path), "ED64/CHEATS/ALPHA.cht");
        fake_cheats_source.kind = SM_CHEAT_MATCH_UNVERIFIED;
        fake_cheat_saves = 0;
        draw();
        assert(sm_test_drew("CHEATS"));           /* the card names the page */
        assert(sm_test_drew("0 of 3 on"));

        frame(PRESS(favorite));
        assert(ui.screen == SM_SCREEN_CHEATS);
        draw();
        assert(sm_test_drew("[ ] Invincible"));
        assert(sm_test_drew("[?] Choose Level"));
        assert(sm_test_drew("A TOGGLE"));
        /* The page names the file, and says when the region is a guess. */
        assert(sm_test_drew("ED64/CHEATS/ALPHA.cht"));
        assert(sm_test_drew("No region tag: codes may be another region's"));
        assert(!sm_test_drew("can't hook"));
        fake_cheats_source.kind = SM_CHEAT_MATCH_PAL;
        fake_cheats_source.rom_region = SM_CART_REGION_GERMANY;
        draw();
        assert(sm_test_drew("Europe codes, cartridge is Germany"));
        fake_cheats_source.kind = SM_CHEAT_MATCH_UNVERIFIED;

        frame(PRESS(select));                     /* A on the first entry */
        assert(fake_cheats.cheats[0].enabled);
        draw();
        assert(sm_test_drew("[x] Invincible"));
        assert(sm_test_drew("1 of 3 on"));

        /* A boot code the engine cannot hook: the page says so in one line,
           the card says so in red next to the count, and a file matched by
           name carries no region tag. */
        fake_cheats_hook = SM_CHEATS_HOOK_NO_JUMP;
        fake_cheats_source.kind = SM_CHEAT_MATCH_REGION;
        draw();
        assert(sm_test_drew("Boot code can't be hooked: cheats won't run"));
        assert(!sm_test_drew("No region tag"));
        frame(PRESS(back));
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS);
        draw();
        assert(sm_test_drew("1 on, WILL NOT RUN"));
        fake_cheats_hook = SM_CHEATS_HOOK_OK;
        fake_cheats_possible = false;
        draw();
        assert(sm_test_drew("1 on, WILL NOT RUN"));
        frame(PRESS(favorite));
        assert(ui.screen == SM_SCREEN_CHEATS);
        draw();
        assert(sm_test_drew("No Expansion Pak: cheats need one"));
        frame(PRESS(back));
        fake_cheats_possible = true;
        draw();
        assert(sm_test_drew("1 of 3 on"));
        frame(PRESS(favorite));
        assert(ui.screen == SM_SCREEN_CHEATS);
        assert(ui.cheat_row == 0);
        assert(fake_cheat_saves == 2);            /* each leaving wrote once */
        fake_cheat_saves = 0;

        frame(PRESS(down));
        frame(PRESS(select));                     /* the incomplete one refuses */
        assert(!fake_cheats.cheats[1].enabled);
        assert(ui.status && strstr(ui.status, "needs a value"));

        frame(PRESS(down));
        assert(ui.cheat_row == 2);
        frame(PRESS(down));                       /* wraps */
        assert(ui.cheat_row == 0);
        frame(PRESS(up));
        assert(ui.cheat_row == 2);

        /* Leaving writes the record once, and lands back on the card. */
        frame(PRESS(back));
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS);
        assert(fake_cheat_saves == 1);
        draw();
        assert(sm_test_drew("1 of 3 on"));
        frame(PRESS(back));
        assert(ui.screen == SM_SCREEN_LIBRARY);
        fake_cheats_available = false;
    }

    /* ---- Start plays from the list, A shows the card ----------------- */
    {
        static const row_t rows[] = {
            {"Racing/Wave Race 64.z64", "Wave Race 64", "Racing", 0, "", 0, NULL},
            {"Zelda.z64", "Zelda", "Action", 0, "", 0, NULL},
        };
        start(rows, 2u);
        settle();
        draw();
        assert(sm_test_drew("START PLAY A INFO"));
        fake_launches = 0;

        /* Start on a folder: nothing to play, nothing happens. */
        assert(ui.items[0] & SM_UI_FOLDER_BIT);
        frame(PRESS(start));
        assert(ui.screen == SM_SCREEN_LIBRARY && fake_launches == 0);

        /* A on a game: the card, and no launch. */
        frame(PRESS(down));
        frame(PRESS(select));
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS && fake_launches == 0);
        frame(PRESS(back));
        assert(ui.screen == SM_SCREEN_LIBRARY);

        /* Start on a game: the card comes up as the progress screen and the
           launch is made in the same press. */
        frame(PRESS(start));
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS && fake_launches == 1);
        frame(PRESS(back));

        /* A refused file stops at the card, where the refusal is written. */
        fake_last_result = SM_LAUNCH_BAD_MAGIC;
        frame(PRESS(start));
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS && fake_launches == 1);
        frame(PRESS(back));
        fake_last_result = SM_LAUNCH_OK;

        /* Cheats on that will not run: the card stays up with its red line,
           and Start there is the second press that plays anyway. */
        memset(&fake_cheats, 0, sizeof(fake_cheats));
        fake_cheats.count = 1;
        fake_cheats.cheats[0].pairs = 1;
        fake_cheats.cheats[0].enabled = true;
        fake_cheats_available = true;
        fake_cheats_hook = SM_CHEATS_HOOK_NO_JUMP;
        frame(PRESS(start));
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS && fake_launches == 1);
        draw();
        assert(sm_test_drew("1 on, WILL NOT RUN"));
        frame(PRESS(start));
        assert(fake_launches == 2);
        frame(PRESS(back));
        /* The same cheats with a boot code they can hook: no warning, so
           Start plays straight away. */
        fake_cheats_hook = SM_CHEATS_HOOK_OK;
        frame(PRESS(start));
        assert(fake_launches == 3);
        frame(PRESS(back));
        /* And cheats present but all off never hold a launch. */
        fake_cheats.cheats[0].enabled = false;
        fake_cheats_hook = SM_CHEATS_HOOK_NO_JUMP;
        frame(PRESS(start));
        assert(fake_launches == 4);
        frame(PRESS(back));
        fake_cheats_available = false;
        fake_cheats_hook = SM_CHEATS_HOOK_OK;

        /* Coverflow and the grid answer Start the same way. */
        frame(PRESS(toggle_view));            /* grid */
        settle();
        frame(PRESS(start));
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS && fake_launches == 5);
        frame(PRESS(back));
        frame(PRESS(toggle_view));            /* coverflow */
        settle();
        draw();
        assert(sm_test_drew("START PLAY A INFO"));
        frame(PRESS(start));
        assert(ui.screen == SM_SCREEN_LAUNCH_DETAILS && fake_launches == 6);
        frame(PRESS(back));
    }

    remove(SM_FAVORITES_PATH);
    printf("ui host checks passed\n");
    return 0;
}
