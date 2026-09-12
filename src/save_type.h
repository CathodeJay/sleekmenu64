/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_SAVE_TYPE_H
#define SLEEKMENU_SAVE_TYPE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Save-type IDs are krikzz's, from ed64-x-pub docs/rom_config_database.md and
   ED64-XIO/inc/bios.h (SAVE_OFF..SAVE_SRM128K). The ID is written verbatim to
   REG_GAM_CFG, so these values are a hardware contract, not a local enum. */
typedef enum {
    SM_SAVE_OFF = 0,
    SM_SAVE_EEP4K = 1,
    SM_SAVE_EEP16K = 2,
    SM_SAVE_SRM32K = 3,
    SM_SAVE_SRM96K = 4,
    SM_SAVE_FLASH = 5,
    SM_SAVE_SRM128K = 6
} sm_save_type_t;

#define SM_SAVE_TYPE_MAX 6u

/* Config nibble. Additive, per the same document. Neither bit belongs to
   REG_GAM_CFG: RTC is a separate register and region affects the boot
   handoff, so both are carried for later and applied by neither yet. */
#define SM_SAVE_CFG_RTC 1u
#define SM_SAVE_CFG_REGION_FREE 2u
#define SM_SAVE_CFG_MAX 3u

typedef enum {
    SM_SAVE_FROM_DEFAULT = 0, /* nothing matched; save hardware stays off */
    SM_SAVE_FROM_HEADER,      /* "ED" developer override in the ROM header */
    SM_SAVE_FROM_DB_CRC,      /* save_db.txt 0xCRCHI record */
    SM_SAVE_FROM_DB_ID,       /* save_db.txt ROM ID record */
    SM_SAVE_FROM_BUILTIN      /* the built-in database, like the stock firmware */
} sm_save_source_t;

/* The stock firmware's full ROM identifier: header 0x3B..0x3E as characters
   followed by the version byte at 0x3F as two uppercase hex digits. This is
   the form ED64/sysdata/registry.dat stores, and the form save_db.txt's
   longer records are written against ("NK4J02" = Kirby 64 (J) rev 2). */
#define SM_SAVE_FULL_ID_LEN 6u

typedef struct {
    sm_save_type_t type;
    unsigned config;
    sm_save_source_t source;
    char rom_id[3];  /* header 0x3C..0x3D, NUL terminated */
    char full_id[SM_SAVE_FULL_ID_LEN + 1u]; /* the stock firmware's 6-symbol form */
    unsigned features; /* SM_FEAT_* from the built-in database, 0 if unknown */
    uint32_t crc_hi; /* header 0x10, big endian (the menu's "CRC HI") */
} sm_save_decision_t;

/* Header offsets this module reads. */
#define SM_ROM_OFFSET_CRC_HI 0x10u
#define SM_ROM_OFFSET_ID 0x3Cu
#define SM_ROM_OFFSET_OVERRIDE 0x3Fu
#define SM_SAVE_MIN_HEADER 0x40u

void sm_save_full_id(const uint8_t *header, size_t length,
    char out[SM_SAVE_FULL_ID_LEN + 1u]);

const char *sm_save_type_name(sm_save_type_t type);
const char *sm_save_source_name(sm_save_source_t source);

/* Parse one save_db.txt record: "<ROMID|0xCRCHI>=<type><config>" followed by
   optional whitespace and a description. Returns false for blank lines,
   separators and anything else that is not a record. */
/* rom_id_out receives up to SM_SAVE_FULL_ID_LEN characters: since OS 3.07 the
   file supports 2-6 symbol identifiers, not just the original two. */
bool sm_save_parse_db_line(const char *line, size_t length, bool *by_crc,
    char rom_id_out[SM_SAVE_FULL_ID_LEN + 1u], uint32_t *crc_hi,
    sm_save_type_t *type, unsigned *config);

/* Resolution order: the "ED" header override wins outright, then the first
   matching save_db.txt record (upper records have priority), then off.
   db_text may be NULL when the card carries no database. */
void sm_save_resolve(const uint8_t *header, size_t header_length,
    const char *db_text, sm_save_decision_t *out);

#endif
