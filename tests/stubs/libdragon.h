/* SPDX-License-Identifier: AGPL-3.0-only */
/* Enough of libdragon to compile src/ui.c on a desktop.

   The UI had four bugs in a row that source inspection could not see -- a
   folder drawn as the game inside it, a genre that existed and could not be
   selected, a button that did nothing, and a cover read on every keypress.
   All four are behaviour, so the browser needs somewhere it can actually be
   run. This is that somewhere: the drawing calls record what they were asked
   to draw, and sprite_load counts how often the card was touched.

   It is a stand-in, not a second implementation. Anything that drifts from
   the real header breaks the ROM build, which is the check that matters. */
#ifndef SLEEKMENU_TEST_LIBDRAGON_H
#define SLEEKMENU_TEST_LIBDRAGON_H

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef enum { FMT_NONE = 0, FMT_RGBA16 = 2, FMT_RGBA32 = 3 } tex_format_t;

typedef struct {
    uint32_t flags;
    uint16_t width;
    uint16_t height;
    uint16_t stride;
    void *buffer;
} surface_t;

typedef struct {
    uint16_t width;
    uint16_t height;
    uint8_t bitdepth;
    uint8_t format;
    uint8_t hslices;
    uint8_t vslices;
    uint8_t flags;
    void *pixels;
    /* sprite_load_buf works in place in real libdragon: the buffer IS the
       sprite, and sprite_free releases it only when the caller has claimed
       ownership. The stub cannot alias its own sprite_t onto the file bytes,
       so it remembers the buffer instead and honours the same flag -- which
       keeps the browser to one code path rather than one per build. */
    void *owned;
} sprite_t;

#define SPRITE_FLAGS_OWNEDBUFFER 0x20

static inline tex_format_t surface_get_format(const surface_t *s) {
    return (tex_format_t)(s->flags & 0x1F);
}

/* --- what the test observes ------------------------------------------- */
#define SM_TEST_TEXT_MAX 256
extern char sm_test_text[SM_TEST_TEXT_MAX][96];
extern int sm_test_text_count;
extern int sm_test_box_count;
extern int sm_test_sprite_loads;
extern int sm_test_sprite_frees;
/* Paths sprite_load will answer for; anything else returns NULL. */
extern const char *sm_test_present_cover;

void sm_test_reset(void);
bool sm_test_drew(const char *needle);

/* --- the stubbed surface ----------------------------------------------- */
static inline uint32_t graphics_make_color(int r, int g, int b, int a) {
    return (uint32_t)((r << 24) | (g << 16) | (b << 8) | a);
}
static inline void graphics_set_color(uint32_t f, uint32_t b) { (void)f; (void)b; }
static inline void graphics_fill_screen(surface_t *s, uint32_t c) { (void)s; (void)c; }
void graphics_draw_box(surface_t *s, int x, int y, int w, int h, uint32_t c);
void graphics_draw_text(surface_t *s, int x, int y, const char *text);
static inline void graphics_draw_sprite_trans(surface_t *s, int x, int y, sprite_t *sprite) {
    (void)s; (void)x; (void)y; (void)sprite;
}

sprite_t *sprite_load(const char *path);
sprite_t *sprite_load_buf(void *buffer, int size);
void sprite_free(sprite_t *sprite);
surface_t sprite_get_pixels(sprite_t *sprite);

#define assertf(expr, ...) do { if (!(expr)) { fprintf(stderr, __VA_ARGS__); abort(); } } while (0)

/* --- the card's directory walk, for src/catalog.c ----------------------
   The host never has a card; discovery is not exercised here, only refused
   politely. What is exercised is catalog_load against a real file the Python
   builder wrote. */
#include "dir.h"

#endif
