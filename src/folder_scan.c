/* SPDX-License-Identifier: AGPL-3.0-only */
#include "card_paths.h"
#include "folder_scan.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

/* -- the name rules ------------------------------------------------------ */

/* Cartridge dumps and 64DD disk images alike: a disk is a game in the list,
   and whether it can be started is the launcher's call, per cartridge. */
bool sm_name_is_rom(const char *name) {
    size_t length = strlen(name);
    return length >= 4 && (!strcasecmp(name + length - 4, ".z64") ||
        !strcasecmp(name + length - 4, ".v64") || !strcasecmp(name + length - 4, ".n64") ||
        !strcasecmp(name + length - 4, ".ndd"));
}

/* Bookkeeping the operating systems leave on a card -- "._Game.z64"
   AppleDouble twins, ".Trashes", "$RECYCLE.BIN" -- by name shape. */
bool sm_name_is_hidden(const char *name) {
    return name[0] == '.' || name[0] == '$';
}

/* Folders known to hold no games, so a scan of the whole card need not walk
   them: the browser's own, the firmware's and any copy of it (ED64.bk2 holds
   the firmware's apps and 64DD IPLs, ROM-shaped files that are not games),
   the N64FlashcartMenu's (its menu ROM is a .n64 file), an unpacked art
   collection (thousands of entries), and the one Windows keeps on every
   removable disk. tools/card_layout.py has the same rule; the two must agree
   or the tool and the browser would disagree about what is on the card. */
bool sm_folder_excluded(const char *name) {
    return sm_name_is_hidden(name) || !strcasecmp(name, SM_FIRMWARE_FOLDER) ||
           !strncasecmp(name, SM_FIRMWARE_FOLDER ".", sizeof(SM_FIRMWARE_FOLDER)) ||
           !strcasecmp(name, SM_CARD_FOLDER) || !strcasecmp(name, "menu") ||
           !strcasecmp(name, "metadata") || !strcasecmp(name, "System Volume Information");
}

bool sm_file_excluded(const char *name) {
    return sm_name_is_hidden(name) || !strcasecmp(name, SM_BROWSER_ROM);
}

char *sm_title_from_name(const char *name) {
    size_t length = strlen(name), kept = 0;
    char *title;
    if (length >= 4 && sm_name_is_rom(name)) length -= 4;
    title = malloc(length + 2u);
    if (title == NULL) return NULL;
    memcpy(title, name, length);
    title[length] = '\0';
    length = sm_ascii_fold(title, title, length + 1u);
    /* Underscores and dashes read as spaces, and a run of spaces as one. */
    for (size_t i = 0; i < length; i++) {
        char c = (title[i] == '_' || title[i] == '-') ? ' ' : title[i];
        if (c == ' ' && (kept == 0 || title[kept - 1] == ' ')) continue;
        title[kept++] = c;
    }
    while (kept > 0 && title[kept - 1] == ' ') kept--;
    /* A name written wholly in letters the font lacks still names a game. */
    if (kept == 0) title[kept++] = '?';
    title[kept] = '\0';
    return title;
}

/* -- names in the font's letters ------------------------------------------ */

/* U+00A0..U+017F -- Latin-1 and Latin Extended-A, the letters of the
   European languages -- each as tools/build_catalog.py console_text()
   spells it. tests/test_build_catalog.py holds the two to the same answer
   for every one of them. */
static const char *const LATIN[0x180 - 0xA0] = {
    /* 00A0 */ " ", "", "", "", "", "", "", "",
    /* 00A8 */ " ", "", "a", "", "", "", "", " ",
    /* 00B0 */ "", "", "2", "3", " ", "", "", "-",
    /* 00B8 */ " ", "1", "o", "", "14", "12", "34", "",
    /* 00C0 */ "A", "A", "A", "A", "A", "A", "AE", "C",
    /* 00C8 */ "E", "E", "E", "E", "I", "I", "I", "I",
    /* 00D0 */ "D", "N", "O", "O", "O", "O", "O", "x",
    /* 00D8 */ "O", "U", "U", "U", "U", "Y", "Th", "ss",
    /* 00E0 */ "a", "a", "a", "a", "a", "a", "ae", "c",
    /* 00E8 */ "e", "e", "e", "e", "i", "i", "i", "i",
    /* 00F0 */ "d", "n", "o", "o", "o", "o", "o", "",
    /* 00F8 */ "o", "u", "u", "u", "u", "y", "th", "y",
    /* 0100 */ "A", "a", "A", "a", "A", "a", "C", "c",
    /* 0108 */ "C", "c", "C", "c", "C", "c", "D", "d",
    /* 0110 */ "D", "d", "E", "e", "E", "e", "E", "e",
    /* 0118 */ "E", "e", "E", "e", "G", "g", "G", "g",
    /* 0120 */ "G", "g", "G", "g", "H", "h", "H", "h",
    /* 0128 */ "I", "i", "I", "i", "I", "i", "I", "i",
    /* 0130 */ "I", "i", "IJ", "ij", "J", "j", "K", "k",
    /* 0138 */ "k", "L", "l", "L", "l", "L", "l", "L",
    /* 0140 */ "l", "L", "l", "N", "n", "N", "n", "N",
    /* 0148 */ "n", "n", "N", "n", "O", "o", "O", "o",
    /* 0150 */ "O", "o", "OE", "oe", "R", "r", "R", "r",
    /* 0158 */ "R", "r", "S", "s", "S", "s", "S", "s",
    /* 0160 */ "S", "s", "T", "t", "T", "t", "T", "t",
    /* 0168 */ "U", "u", "U", "u", "U", "u", "U", "u",
    /* 0170 */ "U", "u", "U", "u", "W", "w", "Y", "y",
    /* 0178 */ "Y", "Z", "z", "Z", "z", "Z", "z", "s",
};

/* The code point at `*at`, which is stepped past it. A malformed sequence
   is one byte that spells nothing, so a name in some other encoding loses
   the odd letter rather than the rest of itself. */
static uint32_t next_code_point(const unsigned char **at) {
    const unsigned char *s = *at;
    uint32_t point;
    unsigned extra;
    if (s[0] < 0x80u) { *at = s + 1; return s[0]; }
    if ((s[0] & 0xE0u) == 0xC0u) { point = s[0] & 0x1Fu; extra = 1; }
    else if ((s[0] & 0xF0u) == 0xE0u) { point = s[0] & 0x0Fu; extra = 2; }
    else if ((s[0] & 0xF8u) == 0xF0u) { point = s[0] & 0x07u; extra = 3; }
    else { *at = s + 1; return 0; }
    for (unsigned i = 1; i <= extra; i++) {
        /* A NUL is not a continuation byte, so this never reads past one. */
        if ((s[i] & 0xC0u) != 0x80u) { *at = s + 1; return 0; }
        point = (point << 6) | (s[i] & 0x3Fu);
    }
    *at = s + 1 + extra;
    return point;
}

static const char *spelling(uint32_t point, char *one) {
    if (point >= 0x20u && point < 0x7Fu) { one[0] = (char)point; return one; }
    if (point >= 0xA0u && point < 0x180u) return LATIN[point - 0xA0u];
    /* Full-width ASCII, which Japanese file names use for Latin letters. */
    if (point >= 0xFF01u && point <= 0xFF5Eu) { one[0] = (char)(point - 0xFEE0u); return one; }
    switch (point) {
    case 0x2000: case 0x2001: case 0x2002: case 0x2003: case 0x2004: case 0x2005:
    case 0x2006: case 0x2007: case 0x2008: case 0x2009: case 0x200A: case 0x2017:
    case 0x202F: case 0x203E: case 0x205F: case 0x3000: return " ";
    case 0x2013: case 0x2014: case 0x2015: case 0x2022: case 0x2212: return "-";
    case 0x2018: case 0x2019: case 0x201A: return "'";
    case 0x201C: case 0x201D: case 0x201E: return "\"";
    case 0x2024: return ".";
    case 0x2025: return "..";
    case 0x2026: return "...";
    case 0x203C: return "!!";
    case 0x2047: return "??";
    case 0x2048: return "?!";
    case 0x2049: return "!?";
    /* Combining accents -- the second half of a decomposed letter -- and
       every script the font has no letters for. */
    default: return "";
    }
}

size_t sm_ascii_fold(const char *text, char *out, size_t out_size) {
    const unsigned char *at = (const unsigned char *)text;
    char one[2] = {0, 0};
    size_t length = 0;
    if (out == NULL || out_size == 0) return 0;
    while (at != NULL && *at && length + 1u < out_size) {
        /* Read before written: no spelling is longer than the bytes it
           replaces, so `out` may be `text` itself. */
        const char *spelled = spelling(next_code_point(&at), one);
        while (*spelled && length + 1u < out_size) out[length++] = *spelled++;
    }
    out[length] = '\0';
    return length;
}

/* -- extras --------------------------------------------------------------- */

static char *copy_string(const char *text) {
    size_t length = strlen(text);
    char *copy = malloc(length + 1u);
    if (copy != NULL) memcpy(copy, text, length + 1u);
    return copy;
}

static void extras_clear(sm_extras_t *extras) {
    for (uint32_t i = 0; i < extras->count; i++) {
        free(extras->entries[i].title);
        free(extras->entries[i].path);
    }
    free(extras->entries);
    memset(extras, 0, sizeof(*extras));
}

/* "ROMS/New Game.z64" for a file, "ROMS/New/" for a folder; the root has
   no prefix at all. */
static char *extra_path(const char *folder, const char *name, bool is_folder) {
    size_t folder_length = strlen(folder);
    size_t name_length = strlen(name);
    size_t length = folder_length + (folder_length ? 1u : 0u) + name_length + (is_folder ? 1u : 0u);
    char *path = malloc(length + 1u);
    if (path == NULL) return NULL;
    snprintf(path, length + 1u, "%s%s%s%s", folder, folder_length ? "/" : "", name,
        is_folder ? "/" : "");
    return path;
}

static bool extras_add(sm_extras_t *extras, const char *folder, const char *name, bool is_folder) {
    sm_extra_t *entry;
    if (extras->count == SM_SCAN_MAX_EXTRAS) { extras->capped = true; return true; }
    if (extras->count == extras->capacity) {
        uint32_t capacity = extras->capacity ? extras->capacity * 2u : 32u;
        sm_extra_t *grown = realloc(extras->entries, capacity * sizeof(*grown));
        if (grown == NULL) return false;
        extras->entries = grown;
        extras->capacity = capacity;
    }
    entry = &extras->entries[extras->count];
    entry->folder = is_folder;
    entry->title = is_folder ? copy_string(name) : sm_title_from_name(name);
    entry->path = extra_path(folder, name, is_folder);
    if (entry->title == NULL || entry->path == NULL) {
        free(entry->title);
        free(entry->path);
        return false;
    }
    extras->count++;
    return true;
}

static int compare_extras(const void *left, const void *right) {
    const sm_extra_t *a = left;
    const sm_extra_t *b = right;
    return strcasecmp(a->path, b->path);
}

/* -- the catalog's names in this folder ----------------------------------- */

static const char *relative_part(const char *path, const char *folder) {
    size_t length = strlen(folder);
    if (!length) return path;
    return !strncmp(path, folder, length) && path[length] == '/' ? path + length + 1 : NULL;
}

/* FNV-1a over the name with ASCII case folded, which is the case the card's
   filesystem ignores and the comparison below ignores too. */
static uint32_t name_hash(const char *name, size_t length) {
    uint32_t hash = 2166136261u;
    for (size_t i = 0; i < length; i++) {
        unsigned char c = (unsigned char)name[i];
        if (c >= 'A' && c <= 'Z') c = (unsigned char)(c + ('a' - 'A'));
        hash = (hash ^ c) * 16777619u;
    }
    return hash;
}

enum { KNOWN_EMPTY = UINT32_MAX, KNOWN_FOLDER_BIT = 0x80000000u };

/* The component of a catalog entry's path that sits directly in the folder,
   and whether it is a subfolder. */
static const char *known_component(const sm_catalog_t *catalog, uint32_t index,
    const char *folder, size_t *length, bool *is_folder) {
    sm_game_t game;
    const char *part, *slash;
    if (!catalog_get(catalog, index, &game)) return NULL;
    part = relative_part(game.path, folder);
    if (part == NULL || !part[0]) return NULL;
    slash = strchr(part, '/');
    *is_folder = slash != NULL;
    *length = slash ? (size_t)(slash - part) : strlen(part);
    return part;
}

static bool known_lookup(const sm_folder_scan_t *scan, const sm_catalog_t *catalog,
    const char *name, size_t length, bool is_folder) {
    uint32_t at;
    if (scan->known == NULL) return false;
    at = name_hash(name, length) & scan->known_mask;
    for (;;) {
        uint32_t slot = scan->known[at];
        size_t other_length;
        bool other_folder;
        const char *other;
        if (slot == KNOWN_EMPTY) return false;
        other = known_component(catalog, slot & ~KNOWN_FOLDER_BIT, scan->wanted,
            &other_length, &other_folder);
        if (other != NULL && other_folder == is_folder && other_length == length &&
            !strncasecmp(other, name, length)) return true;
        at = (at + 1u) & scan->known_mask;
    }
}

static void known_insert(sm_folder_scan_t *scan, uint32_t index, const char *name, size_t length,
    bool is_folder) {
    uint32_t at = name_hash(name, length) & scan->known_mask;
    while (scan->known[at] != KNOWN_EMPTY) at = (at + 1u) & scan->known_mask;
    scan->known[at] = index | (is_folder ? KNOWN_FOLDER_BIT : 0u);
}

/* One walk of the catalog. Sized for every entry with room to spare, so the
   probes stay short; a subfolder is entered once however many games it
   holds. */
static bool known_build(sm_folder_scan_t *scan, const sm_catalog_t *catalog) {
    uint32_t size = 64u;
    free(scan->known);
    scan->known = NULL;
    while (size < catalog->count * 2u + 2u) size *= 2u;
    scan->known = malloc(size * sizeof(*scan->known));
    if (scan->known == NULL) return false;
    scan->known_mask = size - 1u;
    memset(scan->known, 0xff, size * sizeof(*scan->known));
    for (uint32_t i = 0; i < catalog->count; i++) {
        size_t length;
        bool is_folder;
        const char *part = known_component(catalog, i, scan->wanted, &length, &is_folder);
        if (part == NULL) continue;
        if (is_folder && known_lookup(scan, catalog, part, length, true)) continue;
        known_insert(scan, i, part, length, is_folder);
    }
    return true;
}

/* -- the scan ------------------------------------------------------------- */

void sm_folder_scan_init(sm_folder_scan_t *scan) {
    memset(scan, 0, sizeof(*scan));
    /* Nothing has been wanted yet, and "" is a folder (the root). */
    scan->wanted[0] = '\x01';
}

static void publish(sm_folder_scan_t *scan, sm_catalog_t *catalog, unsigned slot) {
    if (slot != 0) {
        sm_extras_t front = scan->slots[slot];
        memmove(&scan->slots[1], &scan->slots[0], slot * sizeof(scan->slots[0]));
        scan->slots[0] = front;
    }
    catalog->extras = scan->slots[0];
}

static void drop_cursor(sm_folder_scan_t *scan) {
    scan->entry_pending = false;
    extras_clear(&scan->found);
}

bool sm_folder_scan_select(sm_folder_scan_t *scan, sm_catalog_t *catalog, const char *folder) {
    drop_cursor(scan);
    free(scan->known);
    scan->known = NULL;
    scan->failed = false;
    memset(&catalog->extras, 0, sizeof(catalog->extras));
    snprintf(scan->wanted, sizeof(scan->wanted), "%s", folder);
    for (unsigned i = 0; i < scan->slot_count; i++) {
        if (strcmp(scan->slots[i].folder, folder)) continue;
        publish(scan, catalog, i);
        scan->state = SM_SCAN_IDLE;
        return true;
    }
    snprintf(scan->sd_path, sizeof(scan->sd_path), SM_SD_ROOT "%s", folder);
    snprintf(scan->found.folder, sizeof(scan->found.folder), "%s", folder);
    scan->state = SM_SCAN_WANTED;
    return false;
}

static void remember(sm_folder_scan_t *scan, sm_catalog_t *catalog) {
    if (scan->slot_count == SM_SCAN_MEMO) extras_clear(&scan->slots[SM_SCAN_MEMO - 1u]);
    else scan->slot_count++;
    memmove(&scan->slots[1], &scan->slots[0], (scan->slot_count - 1u) * sizeof(scan->slots[0]));
    scan->slots[0] = scan->found;
    memset(&scan->found, 0, sizeof(scan->found));
    catalog->extras = scan->slots[0];
}

bool sm_folder_scan_step(sm_folder_scan_t *scan, sm_catalog_t *catalog) {
    int result;
    unsigned read = 0;
    if (scan->state == SM_SCAN_IDLE) return false;
    if (scan->state == SM_SCAN_WANTED) {
        if (scan->known == NULL && !known_build(scan, catalog)) {
            scan->failed = true;
            scan->state = SM_SCAN_IDLE;
            return false;
        }
        snprintf(scan->found.folder, sizeof(scan->found.folder), "%s", scan->wanted);
        result = dir_findfirst(scan->sd_path, &scan->entry);
        if (result != 0) {
            /* An empty folder and an unreadable one look the same here, and
               both mean the same thing: nothing to add. */
            scan->failed = result < -1;
            scan->state = SM_SCAN_IDLE;
            remember(scan, catalog);
            return true;
        }
        scan->entry_pending = true;
        scan->state = SM_SCAN_RUNNING;
    }
    while (read < SM_SCAN_ENTRIES_PER_STEP) {
        const dir_t *entry = &scan->entry;
        if (!scan->entry_pending) {
            result = dir_findnext(scan->sd_path, &scan->entry);
            if (result != 0) {
                scan->failed = result < -1;
                if (scan->failed) extras_clear(&scan->found);
                if (scan->found.count)
                    qsort(scan->found.entries, scan->found.count, sizeof(*scan->found.entries),
                        compare_extras);
                scan->entry_pending = false;
                scan->state = SM_SCAN_IDLE;
                free(scan->known);
                scan->known = NULL;
                remember(scan, catalog);
                return true;
            }
        }
        scan->entry_pending = false;
        read++;
        if (entry->d_type == DT_DIR) {
            if (sm_folder_excluded(entry->d_name)) continue;
            if (known_lookup(scan, catalog, entry->d_name, strlen(entry->d_name), true)) continue;
            if (!extras_add(&scan->found, scan->wanted, entry->d_name, true)) scan->found.capped = true;
        } else if (entry->d_type == DT_REG) {
            if (!sm_name_is_rom(entry->d_name) || sm_file_excluded(entry->d_name)) continue;
            if (known_lookup(scan, catalog, entry->d_name, strlen(entry->d_name), false)) continue;
            if (!extras_add(&scan->found, scan->wanted, entry->d_name, false)) scan->found.capped = true;
        }
    }
    return false;
}

void sm_folder_scan_yield(sm_folder_scan_t *scan) {
    if (scan->state != SM_SCAN_RUNNING) return;
    drop_cursor(scan);
    scan->state = SM_SCAN_WANTED;
}

bool sm_folder_scan_busy(const sm_folder_scan_t *scan) {
    return scan->state == SM_SCAN_RUNNING;
}

void sm_folder_scan_close(sm_folder_scan_t *scan, sm_catalog_t *catalog) {
    for (unsigned i = 0; i < scan->slot_count; i++) extras_clear(&scan->slots[i]);
    extras_clear(&scan->found);
    free(scan->known);
    if (catalog != NULL) memset(&catalog->extras, 0, sizeof(catalog->extras));
    memset(scan, 0, sizeof(*scan));
}
