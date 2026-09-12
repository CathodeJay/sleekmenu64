/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_DISPLAY_H
#define SLEEKMENU_DISPLAY_H

#include <libdragon.h>

typedef struct {
    int width;
    int height;
    int safe_left;
    int safe_top;
    int safe_right;
    int safe_bottom;
    int row_height;
    int visible_rows;
    /* The dense list divides the safe area into five bands: a title bar, the
       genre tabs, the list itself beside the detail panel, and a help bar. All
       of it is derived here rather than spelled out at each draw site, so PAL
       simply gets more rows instead of a second set of numbers. */
    int tabs_top;
    int list_top;
    int list_height;
    int list_width;
    int scrollbar_x;
    int panel_x;
    int footer_top;
} sm_layout_t;

enum {
    SM_HEADER_HEIGHT = 14,
    SM_TABS_HEIGHT = 11,
    SM_FOOTER_HEIGHT = 10,
    SM_ROW_HEIGHT = 10,
    SM_COVER_WIDTH = 96,
    SM_COVER_HEIGHT = 72,
    SM_FONT_WIDTH = 5,
    SM_FONT_HEIGHT = 8
};

void app_display_init(sm_layout_t *layout);
void app_display_load_font(void);
surface_t *app_display_begin(void);
void app_display_end(surface_t *surface);

#endif
