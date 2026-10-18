/* SPDX-License-Identifier: AGPL-3.0-only */
#include <libdragon.h>

char sm_test_text[SM_TEST_TEXT_MAX][96];
int sm_test_text_y[SM_TEST_TEXT_MAX];
int sm_test_text_count;
int sm_test_box_count;
int sm_test_sprite_loads;
int sm_test_sprite_frees;
const char *sm_test_present_cover;
#define SM_TEST_BOX_MAX 4096
static uint32_t box_colours[SM_TEST_BOX_MAX];

void sm_test_reset(void) {
    sm_test_text_count = 0;
    sm_test_box_count = 0;
    sm_test_sprite_loads = 0;
    sm_test_sprite_frees = 0;
}

void graphics_draw_box(surface_t *s, int x, int y, int w, int h, uint32_t c) {
    (void)s; (void)x; (void)y; (void)w; (void)h;
    if (sm_test_box_count < SM_TEST_BOX_MAX) box_colours[sm_test_box_count] = c;
    sm_test_box_count++;
}

int sm_test_boxes_of(uint32_t colour) {
    int found = 0;
    for (int i = 0; i < sm_test_box_count && i < SM_TEST_BOX_MAX; i++)
        if (box_colours[i] == colour) found++;
    return found;
}

void graphics_draw_text(surface_t *s, int x, int y, const char *text) {
    (void)s; (void)x;
    if (sm_test_text_count < SM_TEST_TEXT_MAX && text) {
        sm_test_text_y[sm_test_text_count] = y;
        snprintf(sm_test_text[sm_test_text_count++], 96, "%s", text);
    }
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

/* The folders the card lists, each with its entries, served to whoever
   lists that path; every other path is empty. The browser reads the folder
   it is in for files the catalog does not know, and looks into the new
   subfolders it finds; these are those folders. One listing at a time, as
   on the cartridges. */
enum { DIR_FOLDERS = 16 };
static struct { char path[272]; const sm_test_dir_entry_t *entries; int count; } dir_folders[DIR_FOLDERS];
static int dir_folder_count;
static int dir_current = -1;
static int dir_position;
int sm_test_dir_opens;

void sm_test_dir_set(const char *path, const sm_test_dir_entry_t *entries, int count) {
    dir_folder_count = 0;
    dir_current = -1;
    dir_position = 0;
    if (path) sm_test_dir_add(path, entries, count);
}

void sm_test_dir_add(const char *path, const sm_test_dir_entry_t *entries, int count) {
    if (dir_folder_count == DIR_FOLDERS) return;
    snprintf(dir_folders[dir_folder_count].path, sizeof(dir_folders[0].path), "%s", path);
    dir_folders[dir_folder_count].entries = entries;
    dir_folders[dir_folder_count].count = count;
    dir_folder_count++;
}

int dir_findnext(const char *path, dir_t *entry) {
    (void)path;
    if (dir_current < 0 || dir_position >= dir_folders[dir_current].count) return -1;
    snprintf(entry->d_name, sizeof(entry->d_name), "%s", dir_folders[dir_current].entries[dir_position].name);
    entry->d_type = dir_folders[dir_current].entries[dir_position].folder ? DT_DIR : DT_REG;
    dir_position++;
    return 0;
}

int dir_findfirst(const char *path, dir_t *entry) {
    sm_test_dir_opens++;
    dir_current = -1;
    dir_position = 0;
    for (int i = 0; i < dir_folder_count; i++)
        if (dir_folders[i].entries && !strcmp(path, dir_folders[i].path)) dir_current = i;
    if (dir_current < 0) return -1;
    return dir_findnext(path, entry);
}

uint64_t sm_test_now_us;
uint64_t get_ticks_us(void) { return sm_test_now_us; }
uint64_t get_ticks_ms(void) { return sm_test_now_us / 1000u; }
