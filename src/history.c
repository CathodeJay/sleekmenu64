/* SPDX-License-Identifier: AGPL-3.0-only */
#include "history.h"
#include <stdio.h>
#include <string.h>

static char lower(char c) { return (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; }

/* Case-insensitive whole-path comparison, matching favourites: the card is
   exFAT and nothing else in the pipeline treats a ROM path as case-sensitive
   either. */
static bool same_path(const char *a, const char *b) {
    for (; *a && *b; a++, b++)
        if (lower(*a) != lower(*b)) return false;
    return !*a && !*b;
}

void sm_history_reset(sm_history_t *history) {
    if (!history) return;
    memset(history, 0, sizeof(*history));
}

uint32_t sm_history_count(const sm_history_t *history) {
    return history ? history->count : 0u;
}

int32_t sm_history_position(const sm_history_t *history, const char *path) {
    uint32_t i;
    if (!history || !path || !path[0]) return -1;
    for (i = 0; i < history->count; i++)
        if (same_path(history->paths[i], path)) return (int32_t)i;
    return -1;
}

bool sm_history_record(sm_history_t *history, const char *path) {
    int32_t found;
    uint32_t i, last;
    if (!history || !path || !path[0]) return false;
    if (strlen(path) >= SM_HISTORY_PATH_MAX) return false;

    found = sm_history_position(history, path);
    if (found == 0) return true;             /* already the most recent */

    if (found > 0) {
        /* Move to front: shuffle everything above it down by one. Replaying
           one game must not cost the other fourteen their places. */
        last = (uint32_t)found;
    } else {
        /* New entry. Full means the oldest falls off the end. */
        if (history->count < SM_HISTORY_MAX) history->count++;
        last = history->count - 1u;
    }
    for (i = last; i > 0u; i--)
        memcpy(history->paths[i], history->paths[i - 1u], SM_HISTORY_PATH_MAX);
    snprintf(history->paths[0], SM_HISTORY_PATH_MAX, "%s", path);
    return true;
}

/* The file is written most-recent-first, so parsing has to append rather than
   record: sm_history_record() moves to front, which would reverse the list. */
void sm_history_parse(sm_history_t *history, const char *text, size_t length) {
    size_t at = 0;
    bool loaded, present;
    if (!history) return;
    loaded = history->loaded;
    present = history->present;
    sm_history_reset(history);
    history->loaded = loaded;
    history->present = present;
    if (!text) return;
    while (at < length && history->count < SM_HISTORY_MAX) {
        size_t end = at;
        size_t size;
        while (end < length && text[end] != '\n' && text[end] != '\r') end++;
        size = end - at;
        if (size && size < SM_HISTORY_PATH_MAX) {
            char line[SM_HISTORY_PATH_MAX];
            memcpy(line, text + at, size);
            line[size] = '\0';
            /* A file edited by hand can hold the same path twice; keep the
               first, which is the more recent. */
            if (sm_history_position(history, line) < 0) {
                memcpy(history->paths[history->count], line, size + 1u);
                history->count++;
            }
        }
        at = end;
        while (at < length && (text[at] == '\n' || text[at] == '\r')) at++;
    }
}

size_t sm_history_format(const sm_history_t *history, char *out, size_t size) {
    size_t used = 0;
    uint32_t i;
    if (!history) return 0u;
    for (i = 0; i < history->count; i++) {
        size_t length = strlen(history->paths[i]);
        if (out && used + length + 1u < size) {
            memcpy(out + used, history->paths[i], length);
            out[used + length] = '\n';
        }
        used += length + 1u;
    }
    if (out && size) out[used < size ? used : size - 1u] = '\0';
    return used;
}

void sm_history_load(sm_history_t *history, const char *path) {
    char buffer[SM_HISTORY_MAX * SM_HISTORY_PATH_MAX];
    size_t read;
    FILE *file;
    if (!history) return;
    sm_history_reset(history);
    history->loaded = true;
    if (!path) return;
    file = fopen(path, "rb");
    if (!file) return;                       /* nothing launched yet */
    read = fread(buffer, 1, sizeof(buffer) - 1u, file);
    fclose(file);
    buffer[read] = '\0';
    history->present = true;
    sm_history_parse(history, buffer, read);
    history->loaded = true;
    history->present = true;
}

bool sm_history_save(const sm_history_t *history, const char *path) {
    char buffer[SM_HISTORY_MAX * SM_HISTORY_PATH_MAX];
    size_t used;
    FILE *file;
    if (!history || !path) return false;
    used = sm_history_format(history, buffer, sizeof(buffer));
    if (used >= sizeof(buffer)) return false;
    file = fopen(path, "wb");
    if (!file) return false;
    if (used && fwrite(buffer, 1, used, file) != used) { fclose(file); return false; }
    return fclose(file) == 0;
}
