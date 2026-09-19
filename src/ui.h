/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_UI_H
#define SLEEKMENU_UI_H

#include "catalog.h"
#include "cover_pack.h"
#include "display.h"
#include "input.h"
#include "favorites.h"
#include "folder_scan.h"
#include "history.h"
#include "genre.h"
#include "save_type.h"

/* Shown on the diagnostics screen. SleekMenu 64 is AGPL-3.0-only: this is the
   one place the running program says so and points at the source, which is
   what a copyleft licence is for. */
#define SM_ABOUT "github.com/CathodeJay/sleekmenu64  AGPL-3.0"

enum { SM_UI_MAX_ITEMS = SM_DISCOVERY_MAX_GAMES, SM_UI_FOLDER_BIT = 0x80000000u };
/* Four across, three down. The covers are drawn at two thirds size, which is
   what makes twelve fit where four full-size ones did; the grid also gives up
   the tab strip, showing the active genre in the title bar instead, and that
   thirteen pixels is the third row. */
enum { SM_UI_GRID_COLUMNS = 4, SM_UI_GRID_VISIBLE = 12,
       SM_UI_TILE_WIDTH = 64, SM_UI_TILE_HEIGHT = 48 };
/* Coverflow shows the selection full size with three receding covers either
   side. Seven is what fits across 320 pixels once the side ones overlap, and
   it is also about as many as read as one row rather than a crowd. */
enum { SM_UI_FLOW_HALF = 3 };
/* One rung further out than the shelf shows, placed off the side of the
   screen. Two things need it. A cover entering has to come from somewhere and
   a cover leaving has to go somewhere -- and both have to be real covers, held
   in real slots, or they blink instead of moving. The first attempt kept only
   the seven that are on screen, so the departing one was simply gone from the
   array by the time the slide started and popped out of existence. */
enum { SM_UI_FLOW_OUTER = SM_UI_FLOW_HALF + 1 };
/* Slots held: the seven on screen plus the two off it. The centre is at
   SM_UI_FLOW_OUTER, so a slot's depth is its distance from there. */
enum { SM_UI_FLOW_SLOTS = 2 * SM_UI_FLOW_OUTER + 1 };
/* Frames a step takes. Six is about a tenth of a second on NTSC -- long enough
   to read as movement, short enough that holding a direction still feels like
   the shelf is keeping up rather than catching up. */
enum { SM_UI_FLOW_FRAMES = 6 };
/* The grid and coverflow share one set of loaded sprites, because they want
   the same thing: a handful of covers held across a scroll so that moving one
   step costs one card read rather than a whole window of them. Sized for
   whichever view wants more. */
/* Written out rather than computed: comparing two anonymous enums is a
   -Wenum-compare error, so the assertions cast to int to say plainly that
   these are counts and not two different kinds of thing. */
enum { SM_UI_SLOTS_MAX = 12 };
_Static_assert((int)SM_UI_SLOTS_MAX >= (int)SM_UI_FLOW_SLOTS,
    "coverflow needs a slot per cover, including the two off screen");
_Static_assert((int)SM_UI_SLOTS_MAX >= (int)SM_UI_GRID_VISIBLE,
    "the grid needs a slot per tile");

/* Frames the selection must sit still before the card is touched. Cover art
   comes off the card, and opening a file in a 3,400-entry exFAT tree is slow
   enough that loading one per keypress would make scrolling crawl. Holding
   a direction costs nothing at all, and a cover appears a tenth of a second
   after you stop. */
enum { SM_UI_SETTLE_FRAMES = 6 };

typedef enum { SM_SCREEN_LIBRARY, SM_SCREEN_FILTERS, SM_SCREEN_LAUNCH_DETAILS, SM_SCREEN_CHEATS,
               SM_SCREEN_BOX } sm_screen_t;
typedef enum { SM_VIEW_LIST, SM_VIEW_GRID, SM_VIEW_COVERFLOW } sm_view_t;

typedef struct {
    uint32_t selected;
    uint32_t first_visible;
    uint32_t item_count;
    uint32_t items[SM_UI_MAX_ITEMS];
    char folder[256];
    /* Where browsing starts and where B stops: the folder every game on the
       card is under, when there is one. A card whose whole library sits in
       ROMS/ opens inside ROMS/ rather than on a list with one entry in it;
       a card with games in two folders, or loose at the root, opens at the
       root. Catalog paths and everything written to the card keep the full
       form; only the tree and its header are relative to this. */
    char root[256];
    /* The favourites view is flat: no folders, every starred game wherever it
       lives. The folder being browsed is put aside so that stepping back off
       the tab returns to it. */
    char folder_before_flat[256];
    bool flat;
    sm_filter_t filter;
    sm_screen_t screen;
    sm_view_t view;
    uint8_t filter_row;
    /* The genre tab strip, rebuilt whenever the item list is. tab 0 is "all". */
    sm_genre_tabs_t genres;
    uint32_t genre_tab;
    /* Read from the highlighted ROM's own header rather than the catalog: the
       save type and the accessories it wants are in the cartridge, and asking
       it costs one 64-byte read per selection change. */
    sm_save_type_t selected_save;
    unsigned selected_features;
    /* Bytes on the card. Taken from the file that is already open for the
       header read, so it costs a seek rather than another directory walk --
       and it works on a card whose catalog predates this, which a new catalog
       field would not. */
    uint32_t selected_size;
    bool selected_details_loaded;
    bool selected_disk;        /* the highlighted item is a 64DD disk image */
    /* Horizontal offset for a selected title too long for the row, advanced
       one pixel per frame and wrapped by the drawing code. */
    unsigned marquee;
    /* The launch screen shows a game card; the numbers that were on it are a
       keypress away, where someone diagnosing a card can still reach them. */
    bool diagnostics;
    /* The cheats page, reached from the launch card: which entry the cursor
       is on and which is at the top of the window. */
    uint32_t cheat_row;
    uint32_t cheat_first;
    const char *status;
    sprite_t *cover_sprite;
    uint32_t cover_index;
    bool cover_loaded;
    /* The box view's sprite, read from covers-large.pak when the view opens
       and freed when it closes: one 92 KB read, held for as long as it is on
       screen and no longer. NULL with the view open means the card has no
       large cover for this game, and the view doubles the thumbnail. */
    sprite_t *box_sprite;
    sprite_t *slot_sprites[SM_UI_SLOTS_MAX];
    uint32_t slot_indices[SM_UI_SLOTS_MAX];
    /* Which slots have not been looked up yet. A scroll keeps the sprites for
       tiles still on screen and fills the rest one per frame, rather than
       throwing all twelve away and reading them back. */
    bool slot_pending[SM_UI_SLOTS_MAX];
    /* The item index the first slot holds. Signed and biased, because
       coverflow centres the selection: near the start of the list the leftmost
       slots sit before item zero and hold nothing. INT32_MIN means the slots
       describe nothing yet. */
    int32_t slot_base;
    /* How many slots the current view uses. The arrays are sized for the
       larger view, so a stale count would free sprites the other view still
       holds. */
    uint32_t slot_count;
    /* Coverflow's slide. `flow_frames` counts down to zero; while it is
       running every cover is drawn between where it was and where it is going,
       and `flow_dir` says which way the shelf moved (+1 for a step right).
       Zero means settled, and the covers are drawn at their table positions. */
    uint32_t flow_frames;
    int32_t flow_dir;
    /* The ROM load, for the bar on the launch card. `load_total` of zero means
       no load is in flight, which is also the state before the first chunk
       arrives -- so the bar appears with the first progress callback rather
       than as an empty frame waiting for one. */
    uint32_t load_done_kib;
    uint32_t load_total_kib;
    bool load_verifying;
    unsigned settle;
    /* The box back on the launch card, rendered whole into its own surface
       when the card opens, and shown through a window that moves a pixel
       at a time: on its own after a pause, or by hand with up and down.
       The software renderer has no clipping, so the window is a row copy. */
    surface_t desc_surface;
    int desc_lines;           /* wrapped lines rendered; 0 means nothing to show */
    int desc_offset;          /* the pixel row at the top of the window */
    unsigned desc_idle;       /* frames since the card opened or the last press */
    bool desc_manual;         /* up or down was pressed: no automatic scroll this visit */
    /* Favourites live on the card, not in the catalog, so C-down can set one
       and it survives both a power cycle and a rebuilt catalog. */
    sm_favorites_t favorites;
    /* The last fifteen launches, most recent first. Unlike every other
       view this one is not in catalog order, so rebuild() walks the
       history list rather than the catalog when its tab is up. */
    sm_history_t history;
    /* All the box art in one indexed file, opened once. The loose directory
       still works when there is no pack, which is what lets an existing card
       keep running, but it pays a FatFs directory walk per cover and that is
       the pause between moving the cursor and the picture arriving. */
    sm_cover_pack_t covers;
    /* The box view's pack, opened beside the first; its index is 16 bytes a
       cover. A card without it is a card without the view's large art, not
       an error. */
    sm_cover_pack_t covers_large;
    /* The folder being browsed, read off the card for what the catalog
       does not know: a game copied on since the card was prepared is
       listed and playable, with its box and facts to follow once
       sleekmenu-prep has run. What it finds becomes the catalog's extras;
       the status line under the list says how many. */
    sm_folder_scan_t scan;
    char scan_status[64];
    bool initialized;
} sm_ui_t;

/* The catalog is not const because browsing a folder adds to it: see
   sm_ui_t.scan. */
void ui_update(sm_ui_t *ui, sm_catalog_t *catalog, sm_actions_t actions, const sm_layout_t *layout);
void ui_draw(surface_t *surface, const sm_layout_t *layout, const sm_catalog_t *catalog, const sm_ui_t *ui);
/* `note` is the line along the bottom. It is a parameter rather than a
   constant because the startup sequence has more than one phase now: telling
   someone the card is being scanned while their save is being written back is
   worse than saying nothing. */
void ui_draw_loading(surface_t *surface, const sm_layout_t *layout, const char *phase,
    const char *note, const sm_discovery_progress_t *progress, unsigned indicator_frame);
void ui_close(sm_ui_t *ui);

/* "8 MB", "12.6 MB", "512 KB", "-" for nothing. Cartridge sizes are powers of
   two and read better whole; a trimmed or homebrew image gets one decimal so
   it is not rounded into looking like a retail cart. */
void sm_format_rom_size(uint32_t bytes, char *out, size_t size);

#endif
