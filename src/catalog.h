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

typedef struct {
    void *data;
    size_t size;
    uint32_t count;
    sm_discovered_game_t *discovered;
    bool discovery_mode;
    bool discovery_capped;
} sm_catalog_t;

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
