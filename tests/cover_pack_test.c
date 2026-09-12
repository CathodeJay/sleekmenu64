/* SPDX-License-Identifier: AGPL-3.0-only */
/* The pack contract, against a real file written by tools/cover_pack.py.

   Two languages have to agree on this byte for byte: if Python writes an
   offset the C reader computes differently, every cover on the card is either
   missing or somebody else's picture. Testing the C side against a fixture it
   generated itself would prove nothing, so the fixture comes from the packer. */
#include "cover_pack.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void expect_found(sm_cover_pack_t *pack, const char *name,
    uint32_t width, uint32_t height) {
    uint32_t length = 0u;
    uint8_t *bytes = sm_cover_pack_read(pack, name, &length);
    if (!bytes) {
        fprintf(stderr, "cover not found in pack: %s\n", name);
        assert(0);
    }
    /* Big-endian, straight out of the sprite header. Getting this wrong is
       exactly the kind of slip a same-language test would miss. */
    assert(((bytes[0] << 8) | bytes[1]) == (int)width);
    assert(((bytes[2] << 8) | bytes[3]) == (int)height);
    assert(length >= 8u + width * height * 2u);
    free(bytes);
}

int main(int argc, char **argv) {
    sm_cover_pack_t pack;
    uint32_t length = 0u;

    assert(argc > 1);

    /* The hash has to match the packer's, or nothing is ever found. */
    assert(sm_cover_hash("Super Mario 64 (USA).sprite") ==
           sm_cover_hash("SUPER MARIO 64 (usa).SPRITE"));
    assert(sm_cover_hash("a") != sm_cover_hash("b"));

    /* A header the reader should refuse rather than trust. */
    {
        uint8_t header[SM_COVER_PACK_HEADER];
        uint32_t count, index, payload;
        memset(header, 0, sizeof(header));
        assert(!sm_cover_pack_parse_header(header, sizeof(header), &count, &index, &payload));
        memcpy(header, SM_COVER_PACK_MAGIC, 4);
        header[7] = 99;                       /* wrong version */
        assert(!sm_cover_pack_parse_header(header, sizeof(header), &count, &index, &payload));
        header[7] = (uint8_t)SM_COVER_PACK_VERSION;
        assert(!sm_cover_pack_parse_header(header, sizeof(header), &count, &index, &payload));
        header[11] = 1;                       /* count 1 */
        header[15] = (uint8_t)SM_COVER_PACK_HEADER;
        header[27] = (uint8_t)(SM_COVER_PACK_HEADER + SM_COVER_PACK_ENTRY);
        assert(sm_cover_pack_parse_header(header, sizeof(header), &count, &index, &payload));
        assert(count == 1u && index == SM_COVER_PACK_HEADER);
        /* An index that would overlap the pictures cannot be trusted. */
        header[27] = (uint8_t)(SM_COVER_PACK_HEADER + 4u);
        assert(!sm_cover_pack_parse_header(header, sizeof(header), &count, &index, &payload));
    }

    /* The search is binary, so a sorted index is load-bearing. */
    {
        const sm_cover_entry_t entries[] = {
            {1u, 0u, 0u}, {5u, 0u, 0u}, {9u, 0u, 0u}, {40u, 0u, 0u}, {41u, 0u, 0u},
        };
        assert(sm_cover_pack_find(entries, 5u, 1u) == 0);
        assert(sm_cover_pack_find(entries, 5u, 41u) == 4);
        assert(sm_cover_pack_find(entries, 5u, 9u) == 2);
        assert(sm_cover_pack_find(entries, 5u, 8u) == -1);
        assert(sm_cover_pack_find(entries, 5u, 0u) == -1);
        assert(sm_cover_pack_find(entries, 5u, 99u) == -1);
        assert(sm_cover_pack_find(entries, 0u, 1u) == -1);
        assert(sm_cover_pack_find(NULL, 5u, 1u) == -1);
    }

    assert(!sm_cover_pack_open(&pack, "/nonexistent/covers.pak"));
    assert(!sm_cover_pack_ready(&pack));
    assert(sm_cover_pack_read(&pack, "anything.sprite", &length) == NULL);

    assert(sm_cover_pack_open(&pack, argv[1]));
    assert(sm_cover_pack_ready(&pack));
    assert(pack.count == 3u);

    expect_found(&pack, "Super Mario 64 (USA).sprite", 96u, 72u);
    /* exFAT is case-insensitive; the catalog's spelling must not have to
       match the packer's. */
    expect_found(&pack, "super mario 64 (usa).SPRITE", 96u, 72u);
    expect_found(&pack, "Wave Race 64 (USA).sprite", 64u, 48u);
    expect_found(&pack, "Zelda (Japan).sprite", 96u, 72u);

    assert(sm_cover_pack_read(&pack, "Not On This Card.sprite", &length) == NULL);
    assert(length == 0u);
    assert(sm_cover_pack_read(&pack, "", &length) == NULL);
    assert(sm_cover_pack_read(&pack, NULL, &length) == NULL);

    sm_cover_pack_close(&pack);
    assert(!sm_cover_pack_ready(&pack));
    sm_cover_pack_close(&pack);      /* twice must be harmless */

    /* A truncated or corrupted pack must be refused, not half-read. */
    if (argc > 2) {
        assert(!sm_cover_pack_open(&pack, argv[2]));
        assert(!sm_cover_pack_ready(&pack));
    }

    printf("cover_pack host checks passed\n");
    return 0;
}
