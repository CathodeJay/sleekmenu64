/* SPDX-License-Identifier: AGPL-3.0-only */
#include "cheats.h"
#include "cic.h"      /* the vendored boot code's CIC detector, pure C */
#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

void sm_cheats_reset(sm_cheat_set_t *set) {
    if (set) memset(set, 0, sizeof(*set));
}

/* -- codes ----------------------------------------------------------------- */

static int hex_value(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static bool parse_hex(const char *text, size_t digits, uint32_t *out) {
    uint32_t value = 0;
    size_t i;
    for (i = 0; i < digits; i++) {
        int digit = hex_value(text[i]);
        if (digit < 0) return false;
        value = (value << 4) | (uint32_t)digit;
    }
    *out = value;
    return true;
}

bool sm_cheats_parse_code(const char *text, size_t length, uint32_t *code, uint32_t *value) {
    /* "811147D8 0101": eight hex digits, one separator, four hex digits.
       Padding either side is tolerated; anything else is not a code. */
    size_t start = 0, end = length;
    while (start < end && isspace((unsigned char)text[start])) start++;
    while (end > start && isspace((unsigned char)text[end - 1])) end--;
    if (end - start != 13u) return false;
    if (text[start + 8] != ' ' && text[start + 8] != '\t') return false;
    if (!parse_hex(text + start, 8, code)) return false;
    if (!parse_hex(text + start + 9, 4, value)) return false;
    return true;
}

/* A cheat's code field into words. Codes are separated by ';' (the Pro's
   files) or '+' (other libretro dumps). A token that is not a code -- the
   database's "XXXX" placeholders -- makes the whole entry incomplete. */
static bool parse_codes(const char *text, size_t length, uint32_t *words, size_t max_words,
    uint32_t *pairs) {
    size_t at = 0;
    *pairs = 0;
    while (at < length) {
        size_t end = at;
        uint32_t code, value;
        while (end < length && text[end] != ';' && text[end] != '+') end++;
        if (end > at) {
            bool blank = true;
            size_t i;
            for (i = at; i < end; i++) if (!isspace((unsigned char)text[i])) { blank = false; break; }
            if (!blank) {
                if (!sm_cheats_parse_code(text + at, end - at, &code, &value)) return false;
                if ((size_t)(*pairs) * 2u + 2u > max_words) return false;
                words[*pairs * 2u] = code;
                words[*pairs * 2u + 1u] = value;
                (*pairs)++;
            }
        }
        at = end + 1;
    }
    return *pairs > 0;
}

/* -- the .cht file --------------------------------------------------------- */

typedef struct {
    const char *key;
    size_t key_length;
    const char *value;
    size_t value_length;
} kv_t;

/* One "key = value" line. Quotes around the value are stripped; a line
   without '=' is not a pair. */
static bool split_line(const char *line, size_t length, kv_t *kv) {
    size_t eq = 0, key_end, value_start, value_end;
    while (eq < length && line[eq] != '=') eq++;
    if (eq == length) return false;
    key_end = eq;
    while (key_end > 0 && isspace((unsigned char)line[key_end - 1])) key_end--;
    value_start = eq + 1;
    while (value_start < length && isspace((unsigned char)line[value_start])) value_start++;
    value_end = length;
    while (value_end > value_start && isspace((unsigned char)line[value_end - 1])) value_end--;
    if (value_end > value_start && line[value_start] == '"' && line[value_end - 1] == '"') {
        value_start++;
        if (value_end > value_start) value_end--;
    }
    kv->key = line;
    kv->key_length = key_end;
    kv->value = line + value_start;
    kv->value_length = value_end - value_start;
    return true;
}

/* "cheat12_code" -> 12, "code"; false for any other key. */
static bool cheat_key(const kv_t *kv, uint32_t *index, const char **field, size_t *field_length) {
    size_t at = 5;
    uint32_t number = 0;
    bool digits = false;
    if (kv->key_length < 7u || strncmp(kv->key, "cheat", 5) != 0) return false;
    while (at < kv->key_length && kv->key[at] >= '0' && kv->key[at] <= '9') {
        number = number * 10u + (uint32_t)(kv->key[at] - '0');
        if (number > 100000u) return false;
        at++;
        digits = true;
    }
    if (!digits || at >= kv->key_length || kv->key[at] != '_') return false;
    *index = number;
    *field = kv->key + at + 1;
    *field_length = kv->key_length - at - 1;
    return true;
}

static void copy_desc(char *out, size_t out_size, const char *text, size_t length) {
    size_t i, n = 0;
    for (i = 0; i < length && n + 1 < out_size; i++) {
        unsigned char c = (unsigned char)text[i];
        /* The database nests with backslashes ("Multi Player\Invincible");
           the console font has no backslash, so it reads as a separator. */
        if (c == '\\') { if (n + 3 < out_size) { out[n++] = ' '; out[n++] = '/'; out[n++] = ' '; } continue; }
        if (c < 32 || c > 126) c = '?';
        out[n++] = (char)c;
    }
    out[n] = '\0';
    /* Trim what the separator may have left at either end. */
    while (n > 0 && out[n - 1] == ' ') out[--n] = '\0';
}

uint32_t sm_cheats_parse(sm_cheat_set_t *set, const char *text, size_t length) {
    size_t at = 0;
    uint32_t highest = 0;
    bool seen[SM_CHEATS_MAX];
    uint32_t i, kept = 0;

    if (!set) return 0;
    sm_cheats_reset(set);
    if (!text) return 0;
    memset(seen, 0, sizeof(seen));

    while (at < length) {
        size_t end = at;
        kv_t kv;
        uint32_t index;
        const char *field;
        size_t field_length;
        while (end < length && text[end] != '\n' && text[end] != '\r') end++;
        if (end > at && split_line(text + at, end - at, &kv) &&
            cheat_key(&kv, &index, &field, &field_length)) {
            if (index >= SM_CHEATS_MAX) {
                if (field_length == 4 && !strncmp(field, "code", 4)) set->skipped++;
            } else {
                sm_cheat_t *cheat = &set->cheats[index];
                seen[index] = true;
                if (index + 1u > highest) highest = index + 1u;
                if (field_length == 4 && !strncmp(field, "desc", 4)) {
                    copy_desc(cheat->desc, sizeof(cheat->desc), kv.value, kv.value_length);
                } else if (field_length == 6 && !strncmp(field, "enable", 6)) {
                    cheat->enabled = kv.value_length == 4 && !strncasecmp(kv.value, "true", 4);
                } else if (field_length == 4 && !strncmp(field, "code", 4)) {
                    uint32_t pairs = 0;
                    size_t room = SM_CHEAT_WORDS_MAX - set->word_count;
                    if (parse_codes(kv.value, kv.value_length, set->words + set->word_count,
                            room, &pairs)) {
                        cheat->first = (uint16_t)set->word_count;
                        cheat->pairs = (uint16_t)pairs;
                        cheat->incomplete = false;
                        set->word_count += pairs * 2u;
                    } else {
                        cheat->pairs = 0;
                        cheat->incomplete = true;
                    }
                }
            }
        }
        at = end;
        while (at < length && (text[at] == '\n' || text[at] == '\r')) at++;
    }

    /* Keep entries in file order, dropping index gaps and anything that never
       had a code line (a description on its own is not a cheat). An entry
       whose code could not be read stays, marked, so the player sees why it
       cannot be turned on. */
    for (i = 0; i < highest; i++) {
        sm_cheat_t *cheat = &set->cheats[i];
        if (!seen[i] || (cheat->pairs == 0 && !cheat->incomplete)) { if (seen[i]) set->skipped++; continue; }
        if (cheat->incomplete) cheat->enabled = false;
        if (kept != i) set->cheats[kept] = *cheat;
        kept++;
    }
    set->count = kept;
    for (i = kept; i < SM_CHEATS_MAX; i++) memset(&set->cheats[i], 0, sizeof(set->cheats[i]));
    return kept;
}

/* -- names ------------------------------------------------------------------ */

bool sm_cheats_file_from_rom_path(const char *rom_path, char *out, size_t out_size) {
    const char *slash, *name, *dot;
    size_t stem;
    if (!rom_path || !out || !out_size) return false;
    slash = strrchr(rom_path, '/');
    name = slash ? slash + 1 : rom_path;
    dot = strrchr(name, '.');
    stem = dot ? (size_t)(dot - name) : strlen(name);
    if (stem == 0 || stem + 5u > out_size) return false;
    memcpy(out, name, stem);
    memcpy(out + stem, ".cht", 5);
    return true;
}

/* -- the engine's list ------------------------------------------------------ */

uint32_t sm_cheats_enabled_count(const sm_cheat_set_t *set) {
    uint32_t i, n = 0;
    if (!set) return 0;
    for (i = 0; i < set->count; i++) if (set->cheats[i].enabled && !set->cheats[i].incomplete) n++;
    return n;
}

uint32_t sm_cheats_build_list(const sm_cheat_set_t *set, uint32_t *out, size_t out_words) {
    uint32_t i, n = 0;
    if (!set || !out || out_words < 2u) return 0;
    if (sm_cheats_enabled_count(set) == 0) return 0;
    for (i = 0; i < set->count; i++) {
        const sm_cheat_t *cheat = &set->cheats[i];
        uint32_t words = (uint32_t)cheat->pairs * 2u;
        if (!cheat->enabled || cheat->incomplete) continue;
        if (n + words + 2u > out_words) return 0;
        memcpy(out + n, set->words + cheat->first, words * sizeof(uint32_t));
        n += words;
    }
    out[n++] = 0;
    out[n++] = 0;
    return n;
}

/* -- the hook --------------------------------------------------------------- */

/* The boot code's own numbers (third_party/n64flashcartmenu/boot/cheats.c):
   the word of the IPL3 -- counted from the start of the ROM, as the boot code
   counts it after copying the first 4 KiB into DMEM -- that holds `jr $t1`,
   and for the 6106, whose IPL3 is scrambled from word 0x13C on, the stream
   it is scrambled with. The check is the one the boot code makes, byte for
   byte; the numbers are pinned by tests/cheats_test.c against the vendored
   source so a bump of the boot code cannot leave them behind. */
#define HOOK_JR_T1 0x01200008u
#define HOOK_X106_XOR_CONSTANT 0x0260BCD5u
#define HOOK_X106_ENC_START 0x13Cu
#define HOOK_X106_SEED 0x85u

static uint32_t x106_xor(uint32_t offset) {
    uint32_t val = HOOK_X106_XOR_CONSTANT * HOOK_X106_SEED + 1u, i;
    for (i = 0; i < offset; i++) val *= HOOK_X106_XOR_CONSTANT;
    return val;
}

sm_cheats_hook_t sm_cheats_hook_check(const uint8_t *header, size_t header_length) {
    uint32_t offset, word;
    cic_type_t cic;
    if (!header || header_length < 0x40u + IPL3_LENGTH) return SM_CHEATS_HOOK_UNKNOWN_CIC;
    cic = cic_detect((uint8_t *)header + 0x40u);
    switch (cic) {
    case CIC_5101: offset = 476; break;
    case CIC_6101:
    case CIC_7102: offset = 466; break;
    case CIC_x102: offset = 475; break;
    case CIC_x103: offset = 472; break;
    case CIC_x105: offset = 499; break;
    case CIC_x106: offset = 488; break;
    default: return SM_CHEATS_HOOK_UNKNOWN_CIC;
    }
    word = ((uint32_t)header[offset * 4u] << 24) | ((uint32_t)header[offset * 4u + 1u] << 16) |
           ((uint32_t)header[offset * 4u + 2u] << 8) | (uint32_t)header[offset * 4u + 3u];
    if (cic == CIC_x106) word ^= x106_xor(offset - HOOK_X106_ENC_START);
    return word == HOOK_JR_T1 ? SM_CHEATS_HOOK_OK : SM_CHEATS_HOOK_NO_JUMP;
}

/* -- the state file --------------------------------------------------------- */

size_t sm_cheats_format_code(const sm_cheat_set_t *set, uint32_t index, char *out, size_t out_size) {
    const sm_cheat_t *cheat;
    size_t n = 0;
    uint32_t w;
    if (!set || index >= set->count || !out || !out_size) { if (out && out_size) out[0] = '\0'; return 0; }
    cheat = &set->cheats[index];
    out[0] = '\0';
    for (w = 0; w < cheat->pairs; w++) {
        int written = snprintf(out + n, out_size - n, "%s%08lX %04lX", w ? ";" : "",
            (unsigned long)set->words[cheat->first + w * 2u],
            (unsigned long)(set->words[cheat->first + w * 2u + 1u] & 0xFFFFu));
        if (written < 0 || (size_t)written >= out_size - n) { out[0] = '\0'; return 0; }
        n += (size_t)written;
    }
    return n;
}

/* Whether a line of the state file names this entry: same codes, in order. */
static bool line_matches(const sm_cheat_set_t *set, const sm_cheat_t *cheat, const char *line, size_t length) {
    uint32_t words[64];
    uint32_t pairs = 0, w;
    if (cheat->pairs > 32u) {
        /* Long entries are compared as text instead of through the small
           scratch above. */
        char text[SM_CHEAT_CODE_TEXT_MAX];
        size_t n = sm_cheats_format_code(set, (uint32_t)(cheat - set->cheats), text, sizeof(text));
        size_t start = 0, end = length;
        while (start < end && isspace((unsigned char)line[start])) start++;
        while (end > start && isspace((unsigned char)line[end - 1])) end--;
        return n > 0 && n == end - start && !strncasecmp(text, line + start, n);
    }
    if (!parse_codes(line, length, words, sizeof(words) / sizeof(words[0]), &pairs)) return false;
    if (pairs != cheat->pairs) return false;
    for (w = 0; w < pairs * 2u; w++)
        if (words[w] != set->words[cheat->first + w]) return false;
    return true;
}

static bool section_is(const char *line, size_t length, const char *rom_path) {
    size_t path_length = strlen(rom_path);
    if (length < 2u || line[0] != '[' || line[length - 1] != ']') return false;
    return length - 2u == path_length && !strncasecmp(line + 1, rom_path, path_length);
}

static bool is_section(const char *line, size_t length) {
    return length >= 2u && line[0] == '[' && line[length - 1] == ']';
}

void sm_cheats_state_apply(sm_cheat_set_t *set, const char *state, size_t state_length,
    const char *rom_path) {
    size_t at = 0;
    bool inside = false, found = false;
    uint32_t i;
    if (!set || !state || !rom_path) return;
    /* A section for the game is the whole truth about it: entries it does
       not list are off, whatever the database's own flags said. */
    while (at < state_length) {
        size_t end = at;
        while (end < state_length && state[end] != '\n' && state[end] != '\r') end++;
        if (end > at) {
            if (is_section(state + at, end - at)) {
                inside = section_is(state + at, end - at, rom_path);
                if (inside && !found) {
                    found = true;
                    for (i = 0; i < set->count; i++) set->cheats[i].enabled = false;
                }
            } else if (inside && state[at] != '#') {
                for (i = 0; i < set->count; i++) {
                    if (!set->cheats[i].incomplete && line_matches(set, &set->cheats[i], state + at, end - at))
                        set->cheats[i].enabled = true;
                }
            }
        }
        at = end;
        while (at < state_length && (state[at] == '\n' || state[at] == '\r')) at++;
    }
}

static bool append(char *out, size_t out_size, size_t *n, const char *text, size_t length) {
    if (*n + length + 1u > out_size) return false;
    memcpy(out + *n, text, length);
    *n += length;
    out[*n] = '\0';
    return true;
}

size_t sm_cheats_state_update(const char *state, size_t state_length, const char *rom_path,
    const sm_cheat_set_t *set, char *out, size_t out_size) {
    size_t at = 0, n = 0;
    bool skipping = false;
    uint32_t i;
    if (!out || !out_size) return 0;
    out[0] = '\0';
    if (!rom_path || !set) return 0;
    /* Every other game's section is copied through as it was. */
    while (state && at < state_length) {
        size_t end = at, next;
        while (end < state_length && state[end] != '\n' && state[end] != '\r') end++;
        next = end;
        while (next < state_length && (state[next] == '\n' || state[next] == '\r')) next++;
        if (end > at) {
            if (is_section(state + at, end - at)) skipping = section_is(state + at, end - at, rom_path);
            if (!skipping) {
                if (!append(out, out_size, &n, state + at, end - at) || !append(out, out_size, &n, "\n", 1)) {
                    out[0] = '\0'; return 0;
                }
            }
        }
        at = next;
    }
    if (sm_cheats_enabled_count(set) == 0) return n;
    if (n > 0 && !append(out, out_size, &n, "\n", 1)) { out[0] = '\0'; return 0; }
    if (!append(out, out_size, &n, "[", 1) || !append(out, out_size, &n, rom_path, strlen(rom_path)) ||
        !append(out, out_size, &n, "]\n", 2)) { out[0] = '\0'; return 0; }
    for (i = 0; i < set->count; i++) {
        char code[SM_CHEAT_CODE_TEXT_MAX];
        size_t length;
        if (!set->cheats[i].enabled || set->cheats[i].incomplete) continue;
        length = sm_cheats_format_code(set, i, code, sizeof(code));
        if (!length || !append(out, out_size, &n, code, length) || !append(out, out_size, &n, "\n", 1)) {
            out[0] = '\0'; return 0;
        }
    }
    return n;
}
