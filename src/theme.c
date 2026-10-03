/* SPDX-License-Identifier: AGPL-3.0-only */
#define SM_THEME_TABLE_DEFINE
#include "theme.h"
#include <libdragon.h>
#include <stdio.h>

static int current;

static char lower(char c) { return (c >= 'A' && c <= 'Z') ? (char)(c - 'A' + 'a') : c; }

static bool same_word(const char *id, const char *word, size_t length) {
    size_t i;
    for (i = 0; i < length; i++)
        if (!id[i] || lower(id[i]) != lower(word[i])) return false;
    return id[length] == '\0';
}

static int find_word(const char *word, size_t length) {
    unsigned i;
    if (!word || !length || length > SM_THEME_ID_MAX) return -1;
    for (i = 0; i < SM_THEME_COUNT; i++)
        if (same_word(SM_THEME_TABLE[i].id, word, length)) return (int)i;
    return -1;
}

int sm_theme_find(const char *id) {
    size_t length = 0;
    if (!id) return -1;
    while (id[length]) length++;
    return find_word(id, length);
}

static bool blank(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }

int sm_theme_from_text(const char *text, size_t length) {
    size_t start = 0, end;
    if (!text) return -1;
    /* A byte order mark, should an editor have left one. */
    if (length >= 3 && (unsigned char)text[0] == 0xEF && (unsigned char)text[1] == 0xBB &&
        (unsigned char)text[2] == 0xBF) start = 3;
    while (start < length && blank(text[start])) start++;
    end = start;
    while (end < length && text[end] && !blank(text[end])) end++;
    return find_word(text + start, end - start);
}

void sm_theme_use(int index) {
    current = (index >= 0 && (unsigned)index < SM_THEME_COUNT) ? index : 0;
}

int sm_theme_current(void) { return current; }

static unsigned in_range(int index) {
    return (index >= 0 && (unsigned)index < SM_THEME_COUNT) ? (unsigned)index : 0u;
}

const char *sm_theme_id(int index) { return SM_THEME_TABLE[in_range(index)].id; }
const char *sm_theme_name(int index) { return SM_THEME_TABLE[in_range(index)].name; }

const unsigned char *sm_colour_rgb(sm_colour_role_t role) {
    return SM_THEME_TABLE[current].rgb[(unsigned)role < SM_C_COUNT ? role : SM_C_TEXT];
}

uint32_t sm_colour(sm_colour_role_t role) {
    const unsigned char *rgb = sm_colour_rgb(role);
    return graphics_make_color(rgb[0], rgb[1], rgb[2], 255);
}

bool sm_theme_load(const char *path) {
    char text[64];
    size_t read;
    int index;
    FILE *file = fopen(path, "rb");
    if (!file) return false;
    read = fread(text, 1, sizeof(text), file);
    fclose(file);
    index = sm_theme_from_text(text, read);
    if (index < 0) return false;
    sm_theme_use(index);
    return true;
}

bool sm_theme_save(const char *path) {
    bool written;
    FILE *file = fopen(path, "wb");
    if (!file) return false;
    written = fprintf(file, "%s\n", sm_theme_id(current)) > 0;
    return fclose(file) == 0 && written;
}
