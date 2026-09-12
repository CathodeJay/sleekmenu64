/* SPDX-License-Identifier: AGPL-3.0-only */
#include <libdragon.h>

char sm_test_text[SM_TEST_TEXT_MAX][96];
int sm_test_text_count;
int sm_test_box_count;
int sm_test_sprite_loads;
int sm_test_sprite_frees;
const char *sm_test_present_cover;

void sm_test_reset(void) {
    sm_test_text_count = 0;
    sm_test_box_count = 0;
    sm_test_sprite_loads = 0;
    sm_test_sprite_frees = 0;
}

void graphics_draw_box(surface_t *s, int x, int y, int w, int h, uint32_t c) {
    (void)s; (void)x; (void)y; (void)w; (void)h; (void)c;
    sm_test_box_count++;
}

void graphics_draw_text(surface_t *s, int x, int y, const char *text) {
    (void)s; (void)x; (void)y;
    if (sm_test_text_count < SM_TEST_TEXT_MAX && text)
        snprintf(sm_test_text[sm_test_text_count++], 96, "%s", text);
}

bool sm_test_drew(const char *needle) {
    for (int i = 0; i < sm_test_text_count; i++)
        if (strstr(sm_test_text[i], needle)) return true;
    return false;
}

sprite_t *sprite_load(const char *path) {
    sprite_t *sprite;
    (void)path;
    sm_test_sprite_loads++;
    sprite = calloc(1, sizeof(*sprite));
    if (!sprite) return NULL;
    sprite->width = 96;
    sprite->height = 72;
    sprite->pixels = calloc((size_t)sprite->width * sprite->height, 2u);
    return sprite;
}

/* Reads the real sprite container the pack holds, so the test exercises the
   actual bytes tools/cover_pack.py wrote: a wrong offset or a byte-order slip
   in the reader shows up here as the wrong dimensions rather than as nothing
   at all. */
sprite_t *sprite_load_buf(void *buffer, int size) {
    const uint8_t *bytes = buffer;
    sprite_t *sprite;
    if (!buffer || size < 8) return NULL;
    sm_test_sprite_loads++;
    sprite = calloc(1, sizeof(*sprite));
    if (!sprite) return NULL;
    sprite->width = (uint16_t)((bytes[0] << 8) | bytes[1]);
    sprite->height = (uint16_t)((bytes[2] << 8) | bytes[3]);
    sprite->hslices = bytes[6];
    sprite->vslices = bytes[7];
    sprite->pixels = calloc((size_t)sprite->width * sprite->height, 2u);
    sprite->owned = buffer;
    return sprite;
}

void sprite_free(sprite_t *sprite) {
    if (!sprite) return;
    sm_test_sprite_frees++;
    if (sprite->flags & SPRITE_FLAGS_OWNEDBUFFER) free(sprite->owned);
    free(sprite->pixels);
    free(sprite);
}

surface_t sprite_get_pixels(sprite_t *sprite) {
    surface_t out;
    memset(&out, 0, sizeof(out));
    out.flags = FMT_RGBA16;
    out.width = sprite->width;
    out.height = sprite->height;
    out.stride = (uint16_t)(sprite->width * 2);
    out.buffer = sprite->pixels;
    return out;
}

int dir_findfirst(const char *path, dir_t *entry) {
    (void)path; (void)entry;
    return -1;
}

int dir_findnext(const char *path, dir_t *entry) {
    (void)path; (void)entry;
    return -1;
}
