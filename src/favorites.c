/* SPDX-License-Identifier: AGPL-3.0-only */
#include "favorites.h"
#include <stdio.h>
#include <string.h>

static char lower(char c) { return (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; }

/* Case-insensitive, because nothing else in the pipeline treats a ROM path as
   case-sensitive and a card formatted exFAT does not either. */
static uint64_t sm_favorites_key(const char *path) {
    uint64_t hash = 1469598103934665603ull;   /* FNV-1a, 64-bit */
    if (!path) return 0u;
    for (; *path; path++) {
        hash ^= (uint64_t)(unsigned char)lower(*path);
        hash *= 1099511628211ull;
    }
    /* 0 marks an empty slot, so a path that hashes there is nudged. */
    return hash ? hash : 1u;
}

void sm_favorites_reset(sm_favorites_t *favorites) {
    if (!favorites) return;
    memset(favorites, 0, sizeof(*favorites));
    favorites->text[0] = '\0';
}

static bool find_key(const sm_favorites_t *favorites, uint64_t key, uint32_t *at) {
    uint32_t i;
    for (i = 0; i < favorites->count; i++)
        if (favorites->keys[i] == key) { if (at) *at = i; return true; }
    return false;
}

bool sm_favorites_contains(const sm_favorites_t *favorites, const char *path) {
    if (!favorites || !path || !path[0]) return false;
    return find_key(favorites, sm_favorites_key(path), NULL);
}

/* The line in the text that holds this path, or NULL. Comparison is on whole
   lines so that "A/Game.z64" never matches inside "B/A/Game.z64". */
static char *find_line(sm_favorites_t *favorites, const char *path, size_t *length) {
    size_t want = strlen(path);
    char *at = favorites->text;
    while (*at) {
        char *end = strchr(at, '\n');
        size_t line = end ? (size_t)(end - at) : strlen(at);
        if (line == want) {
            size_t i = 0;
            while (i < line && lower(at[i]) == lower(path[i])) i++;
            if (i == line) { if (length) *length = line + (end ? 1u : 0u); return at; }
        }
        if (!end) break;
        at = end + 1;
    }
    return NULL;
}

bool sm_favorites_add(sm_favorites_t *favorites, const char *path) {
    size_t length;
    uint64_t key;
    if (!favorites || !path || !path[0] || strchr(path, '\n')) return false;
    key = sm_favorites_key(path);
    if (find_key(favorites, key, NULL)) return true;
    length = strlen(path);
    if (favorites->count >= SM_FAVORITES_MAX ||
        favorites->used + length + 2u > SM_FAVORITES_TEXT) {
        favorites->full = true;
        return false;
    }
    memcpy(favorites->text + favorites->used, path, length);
    favorites->used += length;
    favorites->text[favorites->used++] = '\n';
    favorites->text[favorites->used] = '\0';
    favorites->keys[favorites->count++] = key;
    return true;
}

bool sm_favorites_remove(sm_favorites_t *favorites, const char *path) {
    uint32_t at;
    char *line;
    size_t length;
    if (!favorites || !path || !path[0]) return false;
    if (!find_key(favorites, sm_favorites_key(path), &at)) return false;
    line = find_line(favorites, path, &length);
    if (line) {
        size_t offset = (size_t)(line - favorites->text);
        memmove(line, line + length, favorites->used - offset - length + 1u);
        favorites->used -= length;
    }
    favorites->keys[at] = favorites->keys[--favorites->count];
    favorites->full = false;
    return true;
}

bool sm_favorites_toggle(sm_favorites_t *favorites, const char *path) {
    if (!favorites || !path || !path[0]) return false;
    if (sm_favorites_contains(favorites, path)) {
        sm_favorites_remove(favorites, path);
        return false;
    }
    return sm_favorites_add(favorites, path);
}

void sm_favorites_parse(sm_favorites_t *favorites, const char *text, size_t length) {
    char line[512];
    size_t at = 0;
    if (!favorites) return;
    sm_favorites_reset(favorites);
    if (!text) return;
    while (at < length) {
        size_t end = at;
        size_t size;
        while (end < length && text[end] != '\n' && text[end] != '\r') end++;
        size = end - at;
        if (size && size < sizeof(line)) {
            memcpy(line, text + at, size);
            line[size] = '\0';
            sm_favorites_add(favorites, line);
        }
        at = end;
        while (at < length && (text[at] == '\n' || text[at] == '\r')) at++;
    }
}

void sm_favorites_load(sm_favorites_t *favorites, const char *path) {
    char buffer[SM_FAVORITES_TEXT];
    size_t read;
    FILE *file;
    if (!favorites) return;
    sm_favorites_reset(favorites);
    favorites->loaded = true;
    if (!path) return;
    file = fopen(path, "rb");
    if (!file) return;                       /* nothing favourited yet */
    read = fread(buffer, 1, sizeof(buffer) - 1u, file);
    fclose(file);
    buffer[read] = '\0';
    sm_favorites_parse(favorites, buffer, read);
    favorites->loaded = true;
    favorites->present = true;
}

bool sm_favorites_save(const sm_favorites_t *favorites, const char *path) {
    FILE *file;
    size_t written;
    if (!favorites || !path) return false;
    file = fopen(path, "wb");
    if (!file) return false;
    written = favorites->used ? fwrite(favorites->text, 1, favorites->used, file) : 0u;
    if (fclose(file)) return false;
    return written == favorites->used;
}
