/* SPDX-License-Identifier: AGPL-3.0-only */
#include "save_sync.h"
#include "ed64_registry.h"
#include <stdio.h>
#include <string.h>

#ifdef __mips__

/* The ROM header fields the firmware copies into its record. */
#define SM_ROM_CRC_AT 0x10u
#define SM_ROM_CRC_LEN 8u

static void report_reset(sm_save_sync_report_t *report) {
    if (!report) return;
    memset(report, 0, sizeof(*report));
    report->type = SM_SAVE_OFF;
    snprintf(report->detail, sizeof(report->detail), "no pending save");
}

/* "/ROMS/a/Super Mario 64 (USA).z64" -> "Super Mario 64 (USA)", for the
   status line only. */
static void short_name(const char *path, char *out, size_t out_size) {
    const char *stem = strrchr(path, '/');
    const char *dot;
    size_t length;
    stem = stem ? stem + 1 : path;
    dot = strrchr(stem, '.');
    length = (dot && dot != stem) ? (size_t)(dot - stem) : strlen(stem);
    if (length >= out_size) length = out_size - 1u;
    memcpy(out, stem, length);
    out[length] = '\0';
}

void sm_save_sync_flush(sm_save_sync_report_t *report) {
    sm_registry_record_t record;
    sm_save_io_result_t result;
    char name[48];

    report_reset(report);
    if (!sm_registry_load(&record)) {
        if (report) snprintf(report->detail, sizeof(report->detail),
            "no ED64 registry; saves not synced");
        return;
    }
    if (record.save_type == SM_SAVE_OFF || !record.path[0]) return;

    short_name(record.path, name, sizeof(name));
    result = sm_save_backup(record.path, record.save_type);
    if (!report) return;
    report->ran = true;
    report->type = record.save_type;
    report->changed = result == SM_SAVE_IO_OK;
    if (result == SM_SAVE_IO_OK)
        snprintf(report->detail, sizeof(report->detail), "Saved %s (%s)",
            name, sm_save_type_name(record.save_type));
    else if (result == SM_SAVE_IO_BLANK_REFUSED)
        snprintf(report->detail, sizeof(report->detail),
            "%s save on cart was empty; card copy kept", name);
    else
        snprintf(report->detail, sizeof(report->detail), "%s: %s",
            name, sm_save_io_message(result));
}

bool sm_save_sync_arm(const char *rom_path, const uint8_t *header,
    sm_save_type_t type, sm_save_sync_report_t *report) {
    sm_registry_record_t record;
    sm_save_io_result_t result;
    char name[48];

    report_reset(report);
    if (!rom_path || !header) return false;
    if (report) report->type = type;
    short_name(rom_path, name, sizeof(name));

    /* Record first. If the console loses power between the record and the
       restore, the worst case is a writeback of the save we were about to
       replace -- the same bytes that are already on the card. The other
       ordering would leave the cartridge holding a save nothing points at. */
    memset(&record, 0, sizeof(record));
    if (sm_registry_path_for_launch(rom_path, record.path, sizeof(record.path))) {
        sm_save_full_id(header, SM_SAVE_MIN_HEADER, record.rom_id);
        memcpy(record.rom_crc, header + SM_ROM_CRC_AT, SM_ROM_CRC_LEN);
        record.save_type = type;
        if (!sm_registry_store(&record) && report)
            snprintf(report->detail, sizeof(report->detail),
                "%s: registry not updated; save may not write back", name);
    }

    if (sm_save_bytes(type) == 0u) {
        if (report) snprintf(report->detail, sizeof(report->detail),
            "%s: no save hardware", name);
        return true;
    }

    result = sm_save_restore(rom_path, type);
    if (report) {
        report->ran = true;
        report->changed = result == SM_SAVE_IO_OK;
        if (result == SM_SAVE_IO_OK)
            snprintf(report->detail, sizeof(report->detail), "Loaded save for %s (%s)",
                name, sm_save_type_name(type));
        else if (result == SM_SAVE_IO_NO_FILE)
            snprintf(report->detail, sizeof(report->detail), "%s: new save (%s)",
                name, sm_save_type_name(type));
        else
            snprintf(report->detail, sizeof(report->detail), "%s: %s",
                name, sm_save_io_message(result));
    }
    return result == SM_SAVE_IO_OK || result == SM_SAVE_IO_NO_FILE;
}
#endif
