/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_COVER_PACK_H
#define SLEEKMENU_COVER_PACK_H

/* One file for all the box art, with an index read once at startup.

   745 loose sprites in one directory is slower than it sounds. FatFs has no
   directory index, so opening one by name walks the directory from the start,
   and long filenames cost four or five 32-byte entries each -- well over
   100 KB of directory read before the first byte of a picture, and it was
   being paid twice per cover because existence was probed before the load.
   That is the pause between moving the cursor and the art appearing.

   Here the index is 16 bytes per cover, held in RAM, and a lookup is a binary
   search over sorted 64-bit name hashes followed by one seek. The file stays
   open for the session, so after startup a cover costs no directory work at
   all.

   Written by tools/cover_pack.py, which documents the layout. Only the header
   is checked here: the pack is ten megabytes and verifying its CRC at startup
   would cost more than every lookup it will ever serve. The catalog, at half a
   megabyte, is checked in full. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define SM_COVER_PACK_MAGIC "EBCP"
#define SM_COVER_PACK_VERSION 1u
#define SM_COVER_PACK_HEADER 32u
#define SM_COVER_PACK_ENTRY 16u
/* The same ceiling the discovery scan uses. A corrupt header must not be able
   to ask for an arbitrary allocation. */
#define SM_COVER_PACK_MAX 8192u

typedef struct {
    uint64_t hash;
    uint32_t offset;
    uint32_t length;
} sm_cover_entry_t;

typedef struct {
    FILE *file;
    sm_cover_entry_t *entries;
    uint32_t count;
    uint32_t payload_offset;
} sm_cover_pack_t;

/* FNV-1a over the lowercased name: a card formatted exFAT is case-insensitive
   and nobody should have to care which case the catalog recorded. */
uint64_t sm_cover_hash(const char *name);

/* Pure header parse, so the format contract can be tested without a card. */
bool sm_cover_pack_parse_header(const uint8_t *header, size_t length,
    uint32_t *count, uint32_t *index_offset, uint32_t *payload_offset);

/* Index of the entry with this hash, or -1. The index is sorted, so this is a
   binary search -- linear would be 745 comparisons per keystroke. */
int32_t sm_cover_pack_find(const sm_cover_entry_t *entries, uint32_t count, uint64_t hash);

bool sm_cover_pack_open(sm_cover_pack_t *pack, const char *path);
void sm_cover_pack_close(sm_cover_pack_t *pack);
static inline bool sm_cover_pack_ready(const sm_cover_pack_t *pack) {
    return pack && pack->file && pack->entries && pack->count;
}

/* The sprite bytes for a cover, malloc'd, or NULL. The caller owns the buffer;
   on the console it is handed straight to sprite_load_buf, which works in
   place, so it must outlive the sprite. */
void *sm_cover_pack_read(sm_cover_pack_t *pack, const char *name, uint32_t *length);

#endif
