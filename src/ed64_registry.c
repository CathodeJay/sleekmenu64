/* SPDX-License-Identifier: AGPL-3.0-only */
#include "ed64_registry.h"
#include "launch.h"
#include <string.h>

/* Field offsets. tools/ed64_registry.py carries the full annotated map and the
   evidence behind each one; these are only the fields SleekMenu writes. */
#define SM_REG_PATH_A 0u
#define SM_REG_PATH_A_MAX 1024u
#define SM_REG_ROM_CRC 1028u
#define SM_REG_ID 1040u
#define SM_REG_SAVE_TYPE 1048u /* big endian u16 */
#define SM_REG_PATH_B 1196u
#define SM_REG_PATH_B_MAX 256u
#define SM_REG_CRC 2252u

static uint32_t read_be32(const uint8_t *at) {
    return ((uint32_t)at[0] << 24) | ((uint32_t)at[1] << 16) |
           ((uint32_t)at[2] << 8) | (uint32_t)at[3];
}

static void write_be32(uint8_t *at, uint32_t value) {
    at[0] = (uint8_t)(value >> 24); at[1] = (uint8_t)(value >> 16);
    at[2] = (uint8_t)(value >> 8);  at[3] = (uint8_t)value;
}

bool sm_registry_verify(const uint8_t *blob, size_t size) {
    if (!blob || size != SM_REGISTRY_SIZE) return false;
    return read_be32(blob + SM_REG_CRC) == launch_crc32(blob, SM_REG_CRC);
}

static void copy_field(const uint8_t *blob, size_t at, size_t cap,
    char *out, size_t out_size) {
    size_t length = 0;
    while (length < cap && length + 1u < out_size && blob[at + length])
        length++;
    memcpy(out, blob + at, length);
    out[length] = '\0';
}

bool sm_registry_read(const uint8_t *blob, size_t size, sm_registry_record_t *out) {
    uint16_t type;
    if (!out || !sm_registry_verify(blob, size)) return false;
    memset(out, 0, sizeof(*out));
    copy_field(blob, SM_REG_PATH_A, SM_REG_PATH_A_MAX, out->path, sizeof(out->path));
    memcpy(out->rom_id, blob + SM_REG_ID, SM_SAVE_FULL_ID_LEN);
    out->rom_id[SM_SAVE_FULL_ID_LEN] = '\0';
    memcpy(out->rom_crc, blob + SM_REG_ROM_CRC, sizeof(out->rom_crc));
    type = (uint16_t)((blob[SM_REG_SAVE_TYPE] << 8) | blob[SM_REG_SAVE_TYPE + 1u]);
    /* An id outside krikzz's set is read as OFF rather than passed on: it
       would otherwise reach REG_GAM_CFG, and inventing a save mode is worse
       than declining to write a save. */
    out->save_type = type <= SM_SAVE_TYPE_MAX ? (sm_save_type_t)type : SM_SAVE_OFF;
    return true;
}

bool sm_registry_write(uint8_t *blob, size_t size, const sm_registry_record_t *record) {
    size_t length;
    if (!record || !sm_registry_verify(blob, size)) return false;
    if ((unsigned)record->save_type > SM_SAVE_TYPE_MAX) return false;
    length = strlen(record->path);
    if (!length || length >= SM_REG_PATH_B_MAX) return false;
    if (strlen(record->rom_id) != SM_SAVE_FULL_ID_LEN) return false;

    /* Only the field at offset 0 is the writeback record. The one at 1196 is
       the stock browser's CURRENT SELECTION, and the cursor stack just above it
       records how deep in the tree that selection sits.

       Writing the launched path there without also writing a matching cursor
       stack is what left the stock menu inside a subfolder it could not climb
       out of after a reset: it restored the path but had no stack to pop. The
       stack's encoding is not decoded, so the honest move is to leave both
       alone -- they belong to the other menu's browser, not to this record.
       sample-04 settles that it costs nothing: the firmware flushed a save
       from a record whose field at 1196 was empty. */
    memset(blob + SM_REG_PATH_A, 0, SM_REG_PATH_A_MAX);
    memcpy(blob + SM_REG_PATH_A, record->path, length);
    memcpy(blob + SM_REG_ID, record->rom_id, SM_SAVE_FULL_ID_LEN);
    memcpy(blob + SM_REG_ROM_CRC, record->rom_crc, sizeof(record->rom_crc));
    blob[SM_REG_SAVE_TYPE] = (uint8_t)((unsigned)record->save_type >> 8);
    blob[SM_REG_SAVE_TYPE + 1u] = (uint8_t)((unsigned)record->save_type & 0xFFu);
    write_be32(blob + SM_REG_CRC, launch_crc32(blob, SM_REG_CRC));
    return true;
}

bool sm_registry_normalise_path(const char *path, char *out, size_t out_size) {
    const char *relative;
    size_t length;
    if (!path || !out || out_size < 2u) return false;
    relative = path;
    if (!strncmp(relative, "sd:/", 4)) relative += 4;
    while (*relative == '/') relative++;
    length = strlen(relative);
    if (!length || length + 2u > out_size) return false;
    out[0] = '/';
    memcpy(out + 1, relative, length + 1u);
    return true;
}

/* The one to call at launch. A catalog stores paths relative to the ROMS root,
   so the loader resolves "1 US - N-Z/x.z64" to "sd:/ROMS/1 US - N-Z/x.z64"
   before opening it -- and the record has to name the file the loader actually
   opened, not the catalog's shorthand. Normalising the shorthand directly
   wrote "/1 US - N-Z/x.z64" into the firmware's own state file, a path that
   does not exist on the card. There is one resolver; this uses it. */
bool sm_registry_path_for_launch(const char *resolved_sd_path, char *out, size_t out_size) {
    const char *without_volume;
    size_t length;
    if (!resolved_sd_path || !out || out_size < 2u) return false;
    if (strncmp(resolved_sd_path, "sd:/", 4)) return sm_registry_normalise_path(resolved_sd_path, out, out_size);
    without_volume = resolved_sd_path + 3;   /* keeps the leading slash */
    length = strlen(without_volume);
    if (length < 2u || length + 1u > out_size) return false;
    memcpy(out, without_volume, length + 1u);
    return true;
}

#ifdef __mips__
#include <stdio.h>

static uint8_t registry_blob[SM_REGISTRY_SIZE] __attribute__((aligned(8)));

static bool registry_read_blob(void) {
    FILE *file = fopen(SM_REGISTRY_PATH, "rb");
    size_t read;
    if (!file) return false;
    read = fread(registry_blob, 1, sizeof(registry_blob), file);
    fclose(file);
    return read == sizeof(registry_blob) &&
        sm_registry_verify(registry_blob, sizeof(registry_blob));
}

bool sm_registry_load(sm_registry_record_t *out) {
    if (!registry_read_blob()) return false;
    return sm_registry_read(registry_blob, sizeof(registry_blob), out);
}

bool sm_registry_store(const sm_registry_record_t *record) {
    FILE *file;
    size_t written;
    /* Always re-read before patching. The stock menu may have rewritten the
       file since we last looked, and its settings and cursor live in the bytes
       we are carrying through. */
    if (!registry_read_blob()) return false;
    if (!sm_registry_write(registry_blob, sizeof(registry_blob), record)) return false;
    file = fopen(SM_REGISTRY_PATH, "wb");
    if (!file) return false;
    written = fwrite(registry_blob, 1, sizeof(registry_blob), file);
    if (fclose(file) || written != sizeof(registry_blob)) return false;
    return true;
}
#endif
