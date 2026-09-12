/* SPDX-License-Identifier: AGPL-3.0-only */
#include "save_type.h"
#include "rom_db.h"
#include <ctype.h>
#include <string.h>

const char *sm_save_type_name(sm_save_type_t type) {
    switch (type) {
        case SM_SAVE_OFF: return "OFF";
        case SM_SAVE_EEP4K: return "EEP4K";
        case SM_SAVE_EEP16K: return "EEP16K";
        case SM_SAVE_SRM32K: return "SRAM";
        case SM_SAVE_SRM96K: return "SRAM768K";
        case SM_SAVE_FLASH: return "FLASHRAM";
        case SM_SAVE_SRM128K: return "SRAM128K";
        default: return "?";
    }
}

const char *sm_save_source_name(sm_save_source_t source) {
    switch (source) {
        case SM_SAVE_FROM_HEADER: return "header";
        case SM_SAVE_FROM_DB_CRC: return "db:crc";
        case SM_SAVE_FROM_DB_ID: return "db:id";
        case SM_SAVE_FROM_BUILTIN: return "builtin";
        default: return "default";
    }
}

void sm_save_full_id(const uint8_t *header, size_t length,
    char out[SM_SAVE_FULL_ID_LEN + 1u]) {
    static const char HEX[] = "0123456789ABCDEF";
    if (!out) return;
    out[0] = '\0';
    if (!header || length < SM_SAVE_MIN_HEADER) return;
    for (unsigned i = 0; i < 4u; i++) {
        unsigned char c = header[0x3Bu + i];
        /* Unprintable identifier bytes are common in homebrew; keep the slot
           so the field stays six wide and positional matching still works. */
        out[i] = (c >= 32u && c < 127u) ? (char)c : '?';
    }
    out[4] = HEX[(header[SM_ROM_OFFSET_OVERRIDE] >> 4) & 0x0Fu];
    out[5] = HEX[header[SM_ROM_OFFSET_OVERRIDE] & 0x0Fu];
    out[6] = '\0';
}

static int hex_digit(unsigned char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

bool sm_save_parse_db_line(const char *line, size_t length, bool *by_crc,
    char rom_id_out[SM_SAVE_FULL_ID_LEN + 1u], uint32_t *crc_hi,
    sm_save_type_t *type, unsigned *config) {
    size_t start = 0, end, equals, key_end;
    unsigned parsed_type, parsed_config = 0u;

    if (!line || !by_crc || !rom_id_out || !crc_hi || !type || !config) return false;
    while (start < length && (line[start] == ' ' || line[start] == '\t')) start++;
    /* Separator banners and comments are the bulk of a real save_db.txt. */
    if (start >= length || line[start] == '-' || line[start] == '#' ||
        line[start] == ';' || line[start] == '\r' || line[start] == '\n')
        return false;

    end = length;
    while (end > start && (line[end - 1] == '\r' || line[end - 1] == '\n')) end--;
    equals = start;
    while (equals < end && line[equals] != '=') equals++;
    if (equals >= end) return false;
    key_end = equals;
    while (key_end > start && (line[key_end - 1] == ' ' || line[key_end - 1] == '\t')) key_end--;

    /* Value: save type digit, then an optional config digit. */
    {
        size_t at = equals + 1;
        int digit;
        while (at < end && (line[at] == ' ' || line[at] == '\t')) at++;
        if (at >= end) return false;
        digit = hex_digit((unsigned char)line[at]);
        if (digit < 0 || (unsigned)digit > SM_SAVE_TYPE_MAX) return false;
        parsed_type = (unsigned)digit;
        at++;
        if (at < end) {
            digit = hex_digit((unsigned char)line[at]);
            if (digit >= 0) {
                if ((unsigned)digit > SM_SAVE_CFG_MAX) return false;
                parsed_config = (unsigned)digit;
                at++;
            }
        }
        /* Anything after the value must be separated from it. */
        if (at < end && line[at] != ' ' && line[at] != '\t') return false;
    }

    if (key_end - start == 10u && line[start] == '0' &&
        (line[start + 1] == 'x' || line[start + 1] == 'X')) {
        uint32_t value = 0u;
        for (size_t i = start + 2u; i < key_end; i++) {
            int digit = hex_digit((unsigned char)line[i]);
            if (digit < 0) return false;
            value = (value << 4) | (uint32_t)digit;
        }
        *by_crc = true;
        *crc_hi = value;
        rom_id_out[0] = '\0';
    } else if (key_end - start >= 2u && key_end - start <= SM_SAVE_FULL_ID_LEN) {
        /* OS 3.07 and later accept 2 to 6 symbol identifiers, not just the two
           the original documentation described. The card's own save_db.txt
           carries "NK4J02=2", which a two-character parser silently drops. */
        size_t n = key_end - start, i;
        for (i = 0; i < n; i++)
            if (!isalnum((unsigned char)line[start + i])) return false;
        for (i = 0; i < n; i++) rom_id_out[i] = line[start + i];
        rom_id_out[n] = '\0';
        *by_crc = false;
        *crc_hi = 0u;
    } else {
        return false;
    }

    *type = (sm_save_type_t)parsed_type;
    *config = parsed_config;
    return true;
}

/* Where a save_db.txt identifier sits inside the six-symbol form.
   Two symbols is the original documented case and means the game code at
   0x3C..0x3D, i.e. offset 1. Six symbols is the whole string, offset 0. The
   three-to-five cases are undocumented; both alignments are tried, offset 0
   first, which is the only inference in this file. */
static bool sm_save_id_matches(const char *key, const char *full_id) {
    size_t n = strlen(key);
    if (n < 2u || n > SM_SAVE_FULL_ID_LEN || strlen(full_id) != SM_SAVE_FULL_ID_LEN)
        return false;
    if (n >= 3u && !strncmp(key, full_id, n)) return true;
    if (n <= 5u && !strncmp(key, full_id + 1, n)) return true;
    return false;
}

void sm_save_resolve(const uint8_t *header, size_t header_length,
    const char *db_text, sm_save_decision_t *out) {
    if (!out) return;
    memset(out, 0, sizeof(*out));
    out->type = SM_SAVE_OFF;
    out->source = SM_SAVE_FROM_DEFAULT;
    if (!header || header_length < SM_SAVE_MIN_HEADER) return;

    out->rom_id[0] = (char)header[SM_ROM_OFFSET_ID];
    out->rom_id[1] = (char)header[SM_ROM_OFFSET_ID + 1u];
    out->rom_id[2] = '\0';
    sm_save_full_id(header, header_length, out->full_id);
    out->crc_hi = ((uint32_t)header[SM_ROM_OFFSET_CRC_HI] << 24) |
                  ((uint32_t)header[SM_ROM_OFFSET_CRC_HI + 1u] << 16) |
                  ((uint32_t)header[SM_ROM_OFFSET_CRC_HI + 2u] << 8) |
                  (uint32_t)header[SM_ROM_OFFSET_CRC_HI + 3u];

    /* Developer override: ROM ID "ED", packed byte at 0x3F (type high nibble,
       config low nibble). This beats the database by design. */
    if (out->rom_id[0] == 'E' && out->rom_id[1] == 'D') {
        unsigned packed = header[SM_ROM_OFFSET_OVERRIDE];
        unsigned type = packed >> 4;
        unsigned config = packed & 0x0Fu;
        if (type <= SM_SAVE_TYPE_MAX && config <= SM_SAVE_CFG_MAX) {
            out->type = (sm_save_type_t)type;
            out->config = config;
            out->source = SM_SAVE_FROM_HEADER;
            return;
        }
    }

    if (db_text) for (const char *line = db_text; *line;) {
        const char *stop = strchr(line, '\n');
        size_t length = stop ? (size_t)(stop - line) : strlen(line);
        bool by_crc = false;
        char id[SM_SAVE_FULL_ID_LEN + 1u] = {0};
        uint32_t crc = 0u;
        sm_save_type_t type = SM_SAVE_OFF;
        unsigned config = 0u;
        if (sm_save_parse_db_line(line, length, &by_crc, id, &crc, &type, &config)) {
            bool hit = by_crc ? (crc == out->crc_hi)
                              : sm_save_id_matches(id, out->full_id);
            if (hit) {
                /* Upper records win, so the first hit is final. */
                out->type = type;
                out->config = config;
                out->source = by_crc ? SM_SAVE_FROM_DB_CRC : SM_SAVE_FROM_DB_ID;
                return;
            }
        }
        if (!stop) break;
        line = stop + 1;
    }

    /* Last resort, and the one that covers the retail library: the built-in
       database, exactly as the stock firmware falls back to its own. */
    {
        const sm_rom_db_entry_t *entry = sm_rom_db_lookup(header, header_length);
        /* Peripheral flags are recorded whatever the save type: roughly a third
           of the retail library has no cartridge save at all and keeps its
           progress on a Controller Pak instead, which the cartridge cannot
           emulate. Saying so is more useful than showing a bare "OFF". */
        if (entry) out->features = entry->feat;
        if (entry && entry->save != (uint8_t)SM_SAVE_OFF) {
            out->type = (sm_save_type_t)entry->save;
            out->config = (entry->feat & SM_FEAT_RTC) ? SM_SAVE_CFG_RTC : 0u;
            out->source = SM_SAVE_FROM_BUILTIN;
        }
    }
}
