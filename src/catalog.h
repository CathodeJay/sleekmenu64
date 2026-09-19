/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_CATALOG_H
#define SLEEKMENU_CATALOG_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum { SM_REGION_USA = 1, SM_REGION_JAPAN = 2, SM_REGION_EUROPE = 4 };
enum { SM_FLAG_FAVORITE = 1 };
/* 8,192 comfortably exceeds known multi-region N64 sets while bounding RAM use. */
enum { SM_DISCOVERY_MAX_GAMES = 8192 };

typedef struct {
    char *title;
    char *path;
} sm_discovered_game_t;

typedef struct {
    const char *title;
    const char *path;
    const char *cover;
    const char *publisher;
    const char *genre;
    /* From the metadata collection's box back; "" when there is none. Plain
       ASCII, already reduced to what the font can draw; the browser wraps it. */
    const char *description;
    uint16_t year;
    uint8_t players;
    uint8_t regions;
    uint8_t flags;
} sm_game_t;

/* A file or folder the card has in the folder being browsed that the
   catalog does not (src/folder_scan.c). A folder's path ends in '/', so
   that everything reading "the first game inside this folder" off a folder
   item finds a component followed by a slash, as it would in the catalog. */
typedef struct {
    char *title;
    char *path;
    bool folder;
} sm_extra_t;

typedef struct {
    sm_extra_t *entries;
    uint32_t count;
    uint32_t capacity;
    /* The folder these were found in: catalog form, "" for the card root. */
    char folder[256];
    bool capped;   /* the folder had more than would be kept */
} sm_extras_t;

/* The launch card's text for a game the catalog does not know. */
#define SM_EXTRA_DESCRIPTION \
    "This file was added after the card was last prepared, so the catalog " \
    "has no box or facts for it yet. Run sleekmenu-prep on a computer to add " \
    "them. It launches like any other."

typedef struct {
    void *data;
    size_t size;
    uint32_t count;
    sm_discovered_game_t *discovered;
    bool discovery_mode;
    bool discovery_capped;
    /* What the folder being browsed has beyond the catalog, reached through
       the indices past `count`. A view: the browser's folder scan owns the
       entries and swaps them as the folder changes. */
    sm_extras_t extras;
} sm_catalog_t;

static inline uint32_t catalog_total(const sm_catalog_t *catalog) {
    return catalog->count + catalog->extras.count;
}

/* An extra as a game: its name for a title, nothing else known. */
static inline bool sm_extras_get(const sm_extras_t *extras, uint32_t index, sm_game_t *game) {
    const sm_extra_t *extra;
    if (extras == NULL || game == NULL || index >= extras->count) return false;
    extra = &extras->entries[index];
    game->title = extra->title;
    game->path = extra->path;
    game->cover = "";
    game->publisher = "";
    game->genre = "";
    game->description = extra->folder ? "" : SM_EXTRA_DESCRIPTION;
    game->year = 0;
    game->players = 0;
    game->regions = 0;
    game->flags = 0;
    return game->title != NULL && game->path != NULL;
}

typedef struct {
    const char *folder_prefix;
    const char *genre;
    const char *publisher;
    uint16_t year;
    uint8_t players;
    uint8_t regions;
    bool favorites_only;
} sm_filter_t;

typedef struct {
    const char *current_directory;
    uint32_t directories_scanned;
    uint32_t entries_inspected;
    uint32_t roms_found;
} sm_discovery_progress_t;

/* Progress callbacks are observational: the snapshot contains no mutable
   traversal objects and is valid only for the duration of the call. */
typedef void (*sm_discovery_progress_cb)(const sm_discovery_progress_t *progress, void *context);

bool catalog_load(sm_catalog_t *catalog, const char *path, char *error, size_t error_size);
bool catalog_discover_sd(sm_catalog_t *catalog, const char *root, char *error, size_t error_size,
    sm_discovery_progress_cb progress_cb, void *progress_context);
bool catalog_get(const sm_catalog_t *catalog, uint32_t index, sm_game_t *game);
bool catalog_matches(const sm_game_t *game, const sm_filter_t *filter);
void catalog_close(sm_catalog_t *catalog);

#endif
