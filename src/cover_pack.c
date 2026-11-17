/* SPDX-License-Identifier: AGPL-3.0-only */
#include "cover_pack.h"
#include <stdlib.h>
#include <string.h>

#define FNV_OFFSET 0xCBF29CE484222325ull
#define FNV_PRIME 0x100000001B3ull

static uint32_t be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

static uint64_t be64(const uint8_t *p) {
    return ((uint64_t)be32(p) << 32) | (uint64_t)be32(p + 4);
}

uint64_t sm_cover_hash(const char *name) {
    uint64_t digest = FNV_OFFSET;
    if (!name) return digest;
    for (; *name; name++) {
        unsigned char c = (unsigned char)*name;
        if (c >= 'A' && c <= 'Z') c = (unsigned char)(c - 'A' + 'a');
        digest = (digest ^ (uint64_t)c) * FNV_PRIME;
    }
    return digest;
}

bool sm_cover_pack_parse_header(const uint8_t *header, size_t length,
    uint32_t *count, uint32_t *index_offset, uint32_t *payload_offset) {
    uint32_t entries, index, payload;
    if (!header || length < SM_COVER_PACK_HEADER) return false;
    if (memcmp(header, SM_COVER_PACK_MAGIC, 4)) return false;
    if (be32(header + 4) != SM_COVER_PACK_VERSION) return false;
    entries = be32(header + 8);
    index = be32(header + 12);
    payload = be32(header + 24);
    if (!entries || entries > SM_COVER_PACK_MAX) return false;
    if (index < SM_COVER_PACK_HEADER) return false;
    /* The index has to fit between where it starts and where the pictures do,
       or the two overlap and every offset in it is suspect. */
    if (payload < index || payload - index < entries * SM_COVER_PACK_ENTRY) return false;
    if (count) *count = entries;
    if (index_offset) *index_offset = index;
    if (payload_offset) *payload_offset = payload;
    return true;
}

int32_t sm_cover_pack_find(const sm_cover_entry_t *entries, uint32_t count, uint64_t hash) {
    uint32_t low = 0u, high = count;
    if (!entries) return -1;
    while (low < high) {
        uint32_t middle = low + (high - low) / 2u;
        if (entries[middle].hash == hash) return (int32_t)middle;
        if (entries[middle].hash < hash) low = middle + 1u; else high = middle;
    }
    return -1;
}

/* The packs whose file is open, each with when it was last read from, and
   how many may be open at once. */
static struct {
    const sm_cover_pack_t *pack;
    FILE *file;
    uint32_t used;
} held[SM_COVER_PACK_OPEN_MAX];
static unsigned open_limit = 1u;
static uint32_t use_clock;

static void let_go_of(unsigned slot) {
    if (held[slot].file) fclose(held[slot].file);
    held[slot].file = NULL;
    held[slot].pack = NULL;
}

/* Close the file read from longest ago until fewer than `room` are open. */
static void make_room(unsigned room) {
    for (;;) {
        unsigned slot, open = 0u, oldest = SM_COVER_PACK_OPEN_MAX;
        for (slot = 0u; slot < SM_COVER_PACK_OPEN_MAX; slot++) {
            if (!held[slot].file) continue;
            open++;
            if (oldest == SM_COVER_PACK_OPEN_MAX || held[slot].used < held[oldest].used) oldest = slot;
        }
        if (open < room) return;
        let_go_of(oldest);
    }
}

void sm_cover_pack_set_open_limit(unsigned limit) {
    if (limit < 1u) limit = 1u;
    if (limit > SM_COVER_PACK_OPEN_MAX) limit = SM_COVER_PACK_OPEN_MAX;
    open_limit = limit;
    make_room(open_limit + 1u);
}

void sm_cover_pack_let_go(void) {
    unsigned slot;
    for (slot = 0u; slot < SM_COVER_PACK_OPEN_MAX; slot++) let_go_of(slot);
}

bool sm_cover_pack_holding(void) {
    unsigned slot;
    for (slot = 0u; slot < SM_COVER_PACK_OPEN_MAX; slot++)
        if (held[slot].file) return true;
    return false;
}

/* Close this pack's file, if it is open. */
static void let_go_of_pack(const sm_cover_pack_t *pack) {
    unsigned slot;
    for (slot = 0u; slot < SM_COVER_PACK_OPEN_MAX; slot++)
        if (held[slot].pack == pack) let_go_of(slot);
}

static FILE *pack_file(const sm_cover_pack_t *pack) {
    unsigned slot;
    for (slot = 0u; slot < SM_COVER_PACK_OPEN_MAX; slot++) {
        if (held[slot].pack != pack || !held[slot].file) continue;
        held[slot].used = ++use_clock;
        return held[slot].file;
    }
    /* At the limit, the file read from longest ago is closed before this
       one is opened: on the X7 that is the one pack file there is. */
    make_room(open_limit);
    for (slot = 0u; held[slot].file; slot++) {}
    held[slot].file = fopen(pack->path, "rb");
    if (!held[slot].file) return NULL;
    held[slot].pack = pack;
    held[slot].used = ++use_clock;
    return held[slot].file;
}

bool sm_cover_pack_open(sm_cover_pack_t *pack, const char *path) {
    uint8_t header[SM_COVER_PACK_HEADER];
    uint8_t *raw = NULL;
    uint32_t count = 0u, index_offset = 0u, payload_offset = 0u, i;
    FILE *file;
    if (!pack) return false;
    let_go_of_pack(pack);
    memset(pack, 0, sizeof(*pack));
    if (!path || strlen(path) >= sizeof(pack->path)) return false;
    memcpy(pack->path, path, strlen(path) + 1u);
    file = pack_file(pack);
    if (!file) return false;
    if (fread(header, 1, sizeof(header), file) != sizeof(header) ||
        !sm_cover_pack_parse_header(header, sizeof(header), &count, &index_offset, &payload_offset))
        goto fail;

    raw = (uint8_t *)malloc((size_t)count * SM_COVER_PACK_ENTRY);
    pack->entries = (sm_cover_entry_t *)malloc((size_t)count * sizeof(sm_cover_entry_t));
    if (!raw || !pack->entries) goto fail;
    if (fseek(file, (long)index_offset, SEEK_SET) ||
        fread(raw, 1, (size_t)count * SM_COVER_PACK_ENTRY, file) !=
            (size_t)count * SM_COVER_PACK_ENTRY)
        goto fail;
    for (i = 0u; i < count; i++) {
        const uint8_t *at = raw + (size_t)i * SM_COVER_PACK_ENTRY;
        pack->entries[i].hash = be64(at);
        pack->entries[i].offset = be32(at + 8);
        pack->entries[i].length = be32(at + 12);
        /* Sorted is not a nicety: the lookup binary-searches. An index that
           arrived out of order would silently fail to find covers that are
           right there, which is far worse than refusing the file. */
        if (i && pack->entries[i].hash <= pack->entries[i - 1u].hash) goto fail;
        if (pack->entries[i].offset < payload_offset) goto fail;
    }
    free(raw);
    pack->count = count;
    pack->payload_offset = payload_offset;
    return true;

fail:
    free(raw);
    sm_cover_pack_close(pack);
    return false;
}

void sm_cover_pack_close(sm_cover_pack_t *pack) {
    if (!pack) return;
    let_go_of_pack(pack);
    free(pack->entries);
    memset(pack, 0, sizeof(*pack));
}

void *sm_cover_pack_read(sm_cover_pack_t *pack, const char *name, uint32_t *length) {
    int32_t at;
    void *buffer;
    uint32_t size;
    FILE *file;
    if (length) *length = 0u;
    if (!sm_cover_pack_ready(pack) || !name || !name[0]) return NULL;
    at = sm_cover_pack_find(pack->entries, pack->count, sm_cover_hash(name));
    if (at < 0) return NULL;
    size = pack->entries[at].length;
    /* A sprite smaller than its own header is not a sprite, and a cover the
       size of a ROM is a corrupt offset. Both are cheaper to refuse here than
       to hand to the decoder. */
    if (size < 16u || size > (1u << 20)) return NULL;
    file = pack_file(pack);
    if (!file) return NULL;
    buffer = malloc(size);
    if (!buffer) return NULL;
    if (fseek(file, (long)pack->entries[at].offset, SEEK_SET) ||
        fread(buffer, 1, size, file) != size) {
        free(buffer);
        return NULL;
    }
    if (length) *length = size;
    return buffer;
}
