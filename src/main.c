/* SPDX-License-Identifier: AGPL-3.0-only */
#include "card_paths.h"
#include "catalog.h"
#include "display.h"
#include "flashcart.h"
#include "input.h"
#include "launch.h"
#include "ui.h"
#include "save_sync.h"
#include <libdragon.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    const sm_layout_t *layout;
    const char *phase;
    const char *note;
    uint64_t last_redraw_ms;
    unsigned indicator_frame;
} scan_display_t;

static void draw_scan_now(scan_display_t *display, const sm_discovery_progress_t *progress) {
    surface_t *surface = app_display_begin();
    ui_draw_loading(surface, display->layout, display->phase, display->note, progress,
        display->indicator_frame++);
    app_display_end(surface);
    display->last_redraw_ms = get_ticks_ms();
}

static void scan_progress(const sm_discovery_progress_t *progress, void *context) {
    scan_display_t *display = context;
    uint64_t now = get_ticks_ms();
    /* Drawing is intentionally caller-side and rate-limited. The catalog
       callback exposes no dir_t or pending-stack state. */
    if (now - display->last_redraw_ms >= 100) draw_scan_now(display, progress);
}

#ifdef SM_SHOW_FRAME_TIME
/* A build for measuring (make perf): how long the browser works on each
   frame, the worst of the last half second, and how many frames reached the
   screen, over the right of the title bar. Work is ui_update and ui_draw,
   not the wait for a free framebuffer, so it says how much of the 16.7 ms a
   frame has at 60 Hz is used. */
typedef struct {
    uint64_t window_start_us, last_frame_us;
    uint32_t frames, work_sum_us, work_max_us;
    char line[48];
} frame_meter_t;

static void frame_meter(surface_t *surface, const sm_layout_t *layout, frame_meter_t *meter,
    uint32_t work_us, uint64_t now_us) {
    if (!meter->window_start_us) meter->window_start_us = now_us;
    meter->frames++;
    meter->work_sum_us += work_us;
    if (work_us > meter->work_max_us) meter->work_max_us = work_us;
    if (now_us - meter->window_start_us >= 500000u) {
        uint32_t span = (uint32_t)(now_us - meter->window_start_us);
        uint32_t average = meter->work_sum_us / meter->frames;
        snprintf(meter->line, sizeof(meter->line), "%lu.%lums MAX %lu.%lu %luFPS",
            (unsigned long)(average / 1000u), (unsigned long)(average % 1000u / 100u),
            (unsigned long)(meter->work_max_us / 1000u),
            (unsigned long)(meter->work_max_us % 1000u / 100u),
            (unsigned long)((meter->frames * 1000000u + span / 2u) / span));
        meter->window_start_us = now_us;
        meter->frames = meter->work_sum_us = meter->work_max_us = 0;
    }
    if (meter->line[0]) {
        int width = (int)strlen(meter->line) * SM_FONT_WIDTH;
        int x = layout->safe_right - 3 - width;
        graphics_draw_box(surface, x - 2, layout->safe_top, width + 4, SM_HEADER_HEIGHT,
            graphics_make_color(90, 20, 20, 255));
        graphics_set_color(graphics_make_color(255, 255, 255, 255), 0);
        graphics_draw_text(surface, x, layout->safe_top + 3, meter->line);
    }
}
#endif

int main(void) {
    static sm_ui_t ui;
    sm_layout_t layout;
    sm_catalog_t catalog = {0};
    char error[96];
    char loaded_status[64];
    static sm_save_sync_report_t save_sync;
    app_display_init(&layout);
    app_input_init();
    dfs_init(DFS_DEFAULT_LOCATION);
    app_display_load_font();
    scan_display_t scan_display = { .layout = &layout, .phase = "Finding the cartridge",
        .note = "EverDrive-64 X7 or Pro" };
    draw_scan_now(&scan_display, NULL);
    /* Which EverDrive this is decides how every byte reaches the console;
       nothing else in the browser needs to know. */
    const sm_flashcart_t *cart = sm_flashcart_detect();
    scan_display.phase = "Loading catalog";
    scan_display.note = cart->name;
    draw_scan_now(&scan_display, NULL);
    if (!cart->init(error, sizeof(error))) {
        ui.status = error;
    } else {
        bool catalog_loaded = false;
        /* Before anything else touches the card: whatever the last game left
           in the cartridge's save memory belongs in ED64/gamedata/. The stock
           firmware does this on every menu boot and reads the same record, so
           a save survives whichever menu the console comes back to. On the
           Pro the stock OS has already done it before launching the browser,
           and the backend says so. */
        scan_display.phase = "Syncing saves";
        scan_display.note = "Moving the last game's save to ED64/gamedata";
        draw_scan_now(&scan_display, NULL);
        cart->save_sync_flush(&save_sync);
        /* The catalog is the only source of genre, publisher, year and cover
           art: a bare SD scan can read headers, and headers do not carry any
           of them. Without it the browser still works, just plainly. */
        catalog_loaded = catalog_load(&catalog, SM_CATALOG_PATH, error, sizeof(error));
        if (!catalog_loaded) {
            /* The games can be anywhere on the card. The scan skips the
               folders known to hold none (the firmware's, this browser's,
               an unpacked art collection), which is what kept a ROMS-first
               scan cheap; ROMS itself is just another folder now. */
            scan_display.phase = "Scanning the card";
            scan_display.note = "Scanning SD; large cards take time";
            draw_scan_now(&scan_display, NULL);
            catalog_discover_sd(&catalog, SM_SD_ROOT, error, sizeof(error), scan_progress, &scan_display);
            if (catalog.count > 0) {
                ui.status = catalog.discovery_capped
                    ? "ROM scan reached 8192-item cap; metadata can be added later"
                    : "ROMs discovered; metadata can be added later";
            } else {
                ui.status = error;
            }
        } else {
            snprintf(loaded_status, sizeof(loaded_status), "Catalog loaded: %lu games",
                (unsigned long)catalog.count);
            ui.status = loaded_status;
        }
        /* The firmware's cheat pack, if the card has one: 543 names, read
           once here rather than at the first launch card, where the second
           it takes on the Pro's MCU would be felt. */
        scan_display.phase = "Reading cheat pack";
        scan_display.note = SM_FIRMWARE_FOLDER "/CHEATS";
        draw_scan_now(&scan_display, NULL);
        launch_read_cheat_pack();
        /* A save that just moved is more worth saying than a catalog count. */
        if (save_sync.ran) ui.status = save_sync.detail;
    }
#ifdef SM_SHOW_FRAME_TIME
    static frame_meter_t meter;
#endif
    while (1) {
#ifdef SM_SHOW_FRAME_TIME
        uint64_t began = get_ticks_us();
        ui_update(&ui, &catalog, app_input_poll(), &layout);
        uint64_t updated = get_ticks_us();
        surface_t *surface = app_display_begin();
        uint64_t drawing = get_ticks_us();
        ui_draw(surface, &layout, &catalog, &ui);
        uint64_t drawn = get_ticks_us();
        frame_meter(surface, &layout, &meter,
            (uint32_t)((updated - began) + (drawn - drawing)), drawing);
#else
        ui_update(&ui, &catalog, app_input_poll(), &layout);
        surface_t *surface = app_display_begin();
        ui_draw(surface, &layout, &catalog, &ui);
#endif
        app_display_end(surface);
    }
}
