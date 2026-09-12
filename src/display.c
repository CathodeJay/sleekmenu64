/* SPDX-License-Identifier: AGPL-3.0-only */
#include "display.h"

void app_display_init(sm_layout_t *layout) {
    bool pal = get_tv_type() == TV_PAL;
    layout->width = 320;
    layout->height = pal ? 288 : 240;
    layout->safe_left = 24;
    layout->safe_top = 20;
    layout->safe_right = 296;
    layout->safe_bottom = layout->height - 20;
    layout->row_height = SM_ROW_HEIGHT;
    layout->tabs_top = layout->safe_top + SM_HEADER_HEIGHT + 2;
    layout->list_top = layout->tabs_top + SM_TABS_HEIGHT + 2;
    layout->footer_top = layout->safe_bottom - SM_FOOTER_HEIGHT;
    /* Four pixels of air above the help bar, so a highlighted last row does
       not touch it. */
    layout->list_height = layout->footer_top - 4 - layout->list_top;
    /* The panel takes the cover's width plus a two-pixel gutter; the list gets
       what is left, minus the scrollbar column between them. */
    layout->panel_x = layout->safe_right - SM_COVER_WIDTH - 2;
    layout->scrollbar_x = layout->panel_x - 6;
    layout->list_width = layout->scrollbar_x - layout->safe_left;
    layout->visible_rows = layout->list_height / layout->row_height;
    resolution_t resolution = { .width = 320, .height = pal ? 288 : 240, .interlaced = false };
    /* The VI's resampling blends each pixel with its neighbour on the way
       out, which softens 5-pixel glyphs. Turning it off (FILTERS_DISABLED)
       is not an option here: at 16 bits per pixel and 320 across, the
       hardware misbehaves on NTSC consoles (libdragon issue #66) and
       libdragon refuses with an assert at startup -- which it did. A crisp
       picture at this width needs a 32-bit framebuffer, or 640 across. */
    display_init(resolution, DEPTH_16_BPP, 2, GAMMA_NONE, FILTERS_RESAMPLE);
}

void app_display_load_font(void) {
    int handle = dfs_open("/sleekmenu-font.sprite");
    if (handle < 0) return;
    dfs_close(handle);
    sprite_t *font = sprite_load("rom:/sleekmenu-font.sprite");
    if (font && font->width == 16 * SM_FONT_WIDTH && font->height == 8 * SM_FONT_HEIGHT &&
        font->hslices == 16 && font->vslices == 8) {
        graphics_set_font_sprite(font);
    } else if (font) {
        sprite_free(font);
    }
}

surface_t *app_display_begin(void) {
    return display_get();
}

void app_display_end(surface_t *surface) {
    display_show(surface);
}
