/* SPDX-License-Identifier: AGPL-3.0-only */
#include "card_paths.h"
#include "catalog.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <libdragon.h>

/* Format 2: tools/build_catalog.py. A record is six string offsets, the
   year, and three bytes; format 1 had no description and 28-byte records,
   and is refused rather than misread -- a card built by an older tool
   simply gets rebuilt. */
#define SM_HEADER_SIZE 32u
#define SM_FORMAT_VERSION 2u
#define SM_RECORD_SIZE 32u

static uint16_t read_u16(const uint8_t *p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static uint32_t read_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void set_error(char *error, size_t size, const char *message) {
    if (error != NULL && size > 0) {
        snprintf(error, size, "%s", message);
    }
}

static uint32_t crc32_bytes(const uint8_t *data, size_t size) {
    uint32_t crc = 0xffffffffu;
    for (size_t i = 0; i < size; i++) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; bit++) {
            crc = (crc >> 1) ^ (0xedb88320u & (uint32_t)-(int32_t)(crc & 1u));
        }
    }
    return ~crc;
}

bool catalog_load(sm_catalog_t *catalog, const char *path, char *error, size_t error_size) {
    memset(catalog, 0, sizeof(*catalog));
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        set_error(error, error_size, "Catalog not found on SD card");
        return false;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        set_error(error, error_size, "Could not size catalog");
        return false;
    }
    long length = ftell(file);
    if (length < (long)SM_HEADER_SIZE || fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        set_error(error, error_size, "Catalog is truncated");
        return false;
    }
    uint8_t *data = malloc((size_t)length);
    if (data == NULL || fread(data, 1, (size_t)length, file) != (size_t)length) {
        free(data);
        fclose(file);
        set_error(error, error_size, "Could not read catalog");
        return false;
    }
    fclose(file);

    uint32_t count = read_u32(data + 8);
    uint32_t records_at = read_u32(data + 12);
    uint32_t strings_at = read_u32(data + 16);
    uint32_t strings_size = read_u32(data + 20);
    bool bad = memcmp(data, "EBC1", 4) != 0 || read_u16(data + 4) != SM_FORMAT_VERSION ||
        read_u16(data + 6) != SM_HEADER_SIZE || records_at != SM_HEADER_SIZE ||
        count > (UINT32_MAX - records_at) / SM_RECORD_SIZE ||
        strings_at != records_at + count * SM_RECORD_SIZE ||
        strings_size > (uint32_t)length || strings_at > (uint32_t)length - strings_size ||
        strings_at + strings_size != (uint32_t)length ||
        read_u32(data + 24) != crc32_bytes(data + SM_HEADER_SIZE, (size_t)length - SM_HEADER_SIZE);
    if (bad) {
        bool older = memcmp(data, "EBC1", 4) == 0 && read_u16(data + 4) < SM_FORMAT_VERSION;
        free(data);
        set_error(error, error_size, older
            ? "Catalog is from an older prep tool - run sleekmenu-prep again"
            : "Catalog format or checksum is invalid");
        return false;
    }
    catalog->data = data;
    catalog->size = (size_t)length;
    catalog->count = count;
    return true;
}

static const char *catalog_string(const sm_catalog_t *catalog, uint32_t offset) {
    const uint8_t *data = catalog->data;
    uint32_t strings_at = read_u32(data + 16);
    uint32_t strings_size = read_u32(data + 20);
    if (offset >= strings_size) return NULL;
    const char *value = (const char *)data + strings_at + offset;
    size_t available = strings_size - offset;
    return memchr(value, '\0', available) == NULL ? NULL : value;
}

bool catalog_get(const sm_catalog_t *catalog, uint32_t index, sm_game_t *game) {
    if (catalog == NULL || game == NULL || index >= catalog->count) return false;
    if (catalog->discovery_mode) {
        game->title = catalog->discovered[index].title;
        game->path = catalog->discovered[index].path;
        game->cover = "";
        game->publisher = "";
        game->genre = "";
        game->description = "";
        game->year = 0;
        game->players = 0;
        game->regions = 0;
        game->flags = 0;
        return game->title != NULL && game->path != NULL;
    }
    if (catalog->data == NULL) return false;
    const uint8_t *record = (const uint8_t *)catalog->data + SM_HEADER_SIZE + index * SM_RECORD_SIZE;
    game->title = catalog_string(catalog, read_u32(record));
    game->path = catalog_string(catalog, read_u32(record + 4));
    game->cover = catalog_string(catalog, read_u32(record + 8));
    game->publisher = catalog_string(catalog, read_u32(record + 12));
    game->genre = catalog_string(catalog, read_u32(record + 16));
    game->description = catalog_string(catalog, read_u32(record + 20));
    game->year = read_u16(record + 24);
    game->players = record[26];
    game->regions = record[27];
    game->flags = record[28];
    return game->title && game->path && game->cover && game->publisher && game->genre &&
        game->description;
}

/* Keep discovery memory predictable on the console. Paths waiting to be scanned
   are the only directory-tree state retained between directory enumerations. */
enum {
    SM_DISCOVERY_MAX_PATH = 1024,
    SM_DISCOVERY_MAX_PENDING_DIRS = 1024,
};

/* Cartridge dumps and 64DD disk images alike: a disk is a game in the list,
   and whether it can be started is the launcher's call, per cartridge. */
static bool rom_suffix(const char *path) {
    size_t length = strlen(path);
    return length >= 4 && (!strcasecmp(path + length - 4, ".z64") ||
        !strcasecmp(path + length - 4, ".v64") || !strcasecmp(path + length - 4, ".n64") ||
        !strcasecmp(path + length - 4, ".ndd"));
}

static const char *path_basename(const char *path) {
    const char *slash = strrchr(path, '/');
    return slash == NULL ? path : slash + 1;
}

/* Bookkeeping the operating systems leave on a card -- "._Game.z64"
   AppleDouble twins, ".Trashes", "$RECYCLE.BIN" -- by name shape. */
static bool hidden_name(const char *name) {
    return name[0] == '.' || name[0] == '$';
}

/* Folders known to hold no games, so a scan of the whole card need not walk
   them: the browser's own, the firmware's and any copy of it (ED64.bk2 holds
   the firmware's apps and 64DD IPLs, ROM-shaped files that are not games),
   the N64FlashcartMenu's (its menu ROM is a .n64 file), an unpacked art
   collection (thousands of entries), and the one Windows keeps on every
   removable disk. tools/card_layout.py has the same rule; the two must agree
   or the tool and the browser would disagree about what is on the card. */
static bool excluded_directory(const char *path) {
    const char *name = path_basename(path);
    return hidden_name(name) || !strcasecmp(name, SM_FIRMWARE_FOLDER) ||
           !strncasecmp(name, SM_FIRMWARE_FOLDER ".", sizeof(SM_FIRMWARE_FOLDER)) ||
           !strcasecmp(name, SM_CARD_FOLDER) || !strcasecmp(name, "menu") ||
           !strcasecmp(name, "metadata") || !strcasecmp(name, "System Volume Information");
}

static bool excluded_file(const char *name) {
    return hidden_name(name) || !strcasecmp(name, SM_BROWSER_ROM);
}

static char *copy_title(const char *path) {
    const char *name = path_basename(path);
    size_t length = strlen(name);
    if (length >= 4) length -= 4;
    char *title = malloc(length + 1);
    if (title == NULL) return NULL;
    for (size_t i = 0; i < length; i++)
        title[i] = (name[i] == '_' || name[i] == '-') ? ' ' : name[i];
    title[length] = '\0';
    return title;
}

static char *join_path(const char *directory, const char *name) {
    size_t directory_length = strlen(directory);
    size_t name_length = strlen(name);
    bool needs_slash = directory_length > 0 && directory[directory_length - 1] != '/';
    size_t length = directory_length + (needs_slash ? 1u : 0u) + name_length;
    if (length >= SM_DISCOVERY_MAX_PATH) return NULL;
    char *path = malloc(length + 1);
    if (path == NULL) return NULL;
    memcpy(path, directory, directory_length);
    if (needs_slash) path[directory_length++] = '/';
    memcpy(path + directory_length, name, name_length + 1);
    return path;
}

static const char *root_relative(const char *path, const char *root, size_t root_length) {
    const char *relative = path;
    if (!strncmp(path, root, root_length)) {
        relative += root_length;
        while (*relative == '/') relative++;
    }
    return relative;
}

static void free_pending_directories(char **pending, size_t count) {
    while (count > 0) free(pending[--count]);
}

static int compare_discovered(const void *left, const void *right) {
    const sm_discovered_game_t *a = left;
    const sm_discovered_game_t *b = right;
    return strcasecmp(a->path, b->path);
}

static uint32_t count_one(uint32_t value) {
    return value == UINT32_MAX ? value : value + 1;
}

static void report_progress(sm_discovery_progress_cb callback, void *context,
    const char *directory, uint32_t directories, uint32_t entries, uint32_t roms) {
    if (callback == NULL) return;
    const sm_discovery_progress_t progress = {
        .current_directory = directory,
        .directories_scanned = directories,
        .entries_inspected = entries,
        .roms_found = roms,
    };
    callback(&progress, context);
}

bool catalog_discover_sd(sm_catalog_t *catalog, const char *root, char *error, size_t error_size,
    sm_discovery_progress_cb progress_cb, void *progress_context) {
    catalog_close(catalog);
    catalog->discovered = calloc(SM_DISCOVERY_MAX_GAMES, sizeof(*catalog->discovered));
    if (catalog->discovered == NULL) {
        set_error(error, error_size, "Not enough memory to discover ROMs");
        return false;
    }
    catalog->discovery_mode = true;

    char *pending[SM_DISCOVERY_MAX_PENDING_DIRS];
    size_t pending_count = 0;
    size_t root_length = strlen(root);
    uint32_t directories_scanned = 0;
    uint32_t entries_inspected = 0;
    pending[pending_count++] = strdup(root);
    if (pending[0] == NULL) {
        catalog_close(catalog);
        set_error(error, error_size, "ROM scan stopped: not enough memory for directory paths");
        return false;
    }

    while (pending_count > 0) {
        char *directory = pending[--pending_count];
        size_t children_begin = pending_count;
        dir_t entry;
        directories_scanned = count_one(directories_scanned);
        report_progress(progress_cb, progress_context, directory, directories_scanned,
            entries_inspected, catalog->count);
        int result = dir_findfirst(directory, &entry);

        while (result == 0) {
            entries_inspected = count_one(entries_inspected);
            if (entry.d_type == DT_DIR && !excluded_directory(entry.d_name)) {
                if (pending_count == SM_DISCOVERY_MAX_PENDING_DIRS) {
                    free(directory);
                    free_pending_directories(pending, pending_count);
                    catalog_close(catalog);
                    set_error(error, error_size, "ROM scan stopped: too many pending directories");
                    return false;
                }
                char *child = join_path(directory, entry.d_name);
                if (child == NULL) {
                    free(directory);
                    free_pending_directories(pending, pending_count);
                    catalog_close(catalog);
                    set_error(error, error_size, "ROM scan stopped: directory path is too long or memory is low");
                    return false;
                }
                pending[pending_count++] = child;
            } else if (entry.d_type == DT_REG && rom_suffix(entry.d_name) && !excluded_file(entry.d_name)) {
                if (catalog->count == SM_DISCOVERY_MAX_GAMES) {
                    catalog->discovery_capped = true;
                } else {
                    char *full_path = join_path(directory, entry.d_name);
                    if (full_path == NULL) {
                        free(directory);
                        free_pending_directories(pending, pending_count);
                        catalog_close(catalog);
                        set_error(error, error_size, "ROM scan stopped: ROM path is too long or memory is low");
                        return false;
                    }
                    const char *relative = root_relative(full_path, root, root_length);
                    char *path = strdup(relative);
                    char *title = copy_title(relative);
                    free(full_path);
                    if (path == NULL || title == NULL) {
                        free(path);
                        free(title);
                        free(directory);
                        free_pending_directories(pending, pending_count);
                        catalog_close(catalog);
                        set_error(error, error_size, "ROM scan stopped: not enough memory for ROM entries");
                        return false;
                    }
                    catalog->discovered[catalog->count].path = path;
                    catalog->discovered[catalog->count].title = title;
                    catalog->count++;
                }
            }
            report_progress(progress_cb, progress_context, directory, directories_scanned,
                entries_inspected, catalog->count);
            result = dir_findnext(directory, &entry);
        }

        free(directory);
        if (result < -1) {
            free_pending_directories(pending, pending_count);
            catalog_close(catalog);
            set_error(error, error_size, "Could not finish reading an SD card directory");
            return false;
        }
        if (catalog->discovery_capped) {
            while (pending_count > children_begin) free(pending[--pending_count]);
            free_pending_directories(pending, pending_count);
            break;
        }
    }
    qsort(catalog->discovered, catalog->count, sizeof(*catalog->discovered), compare_discovered);
    if (catalog->count == 0) set_error(error, error_size, "No N64 ROMs found on SD card");
    return catalog->count > 0;
}

bool catalog_matches(const sm_game_t *game, const sm_filter_t *filter) {
    if (game == NULL || filter == NULL) return false;
    if (filter->folder_prefix != NULL && filter->folder_prefix[0] != '\0') {
        size_t length = strlen(filter->folder_prefix);
        if (strncmp(game->path, filter->folder_prefix, length) != 0 ||
            (game->path[length] != '/' && game->path[length] != '\0')) return false;
    }
    if (filter->genre != NULL && filter->genre[0] != '\0' && strcmp(game->genre, filter->genre) != 0) return false;
    if (filter->publisher != NULL && filter->publisher[0] != '\0' && strcmp(game->publisher, filter->publisher) != 0) return false;
    if (filter->year != 0 && game->year != filter->year) return false;
    /* "at least this many", not "exactly": someone looking for a two-player
       game wants the four-player ones too. Games that seat more people than
       the console has ports (Micro Machines 64 Turbo shares pads for eight)
       stay findable instead of matching nothing at all. */
    if (filter->players != 0 && game->players < filter->players) return false;
    if (filter->regions != 0 && (game->regions & filter->regions) == 0) return false;
    if (filter->favorites_only && (game->flags & SM_FLAG_FAVORITE) == 0) return false;
    return true;
}

void catalog_close(sm_catalog_t *catalog) {
    if (catalog != NULL) {
        if (catalog->discovered != NULL) {
            for (uint32_t i = 0; i < catalog->count; i++) {
                free(catalog->discovered[i].title);
                free(catalog->discovered[i].path);
            }
            free(catalog->discovered);
        }
        free(catalog->data);
        memset(catalog, 0, sizeof(*catalog));
    }
}
