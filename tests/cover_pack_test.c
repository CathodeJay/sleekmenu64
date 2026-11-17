/* SPDX-License-Identifier: AGPL-3.0-only */
/* The pack contract, against a real file written by tools/cover_pack.py.

   Two languages have to agree on this byte for byte: if Python writes an
   offset the C reader computes differently, every cover on the card is either
   missing or somebody else's picture. Testing the C side against a fixture it
   generated itself would prove nothing, so the fixture comes from the packer. */
#define _POSIX_C_SOURCE 200809L
#include "cover_pack.h"
#include <assert.h>
#include <fcntl.h>
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

/* How many files this process has open. */
static int open_files(void) {
    int count = 0;
    for (int fd = 3; fd < 256; fd++)
        if (fcntl(fd, F_GETFD) != -1) count++;
    return count;
}

/* A copy of the pack under another name, so that each pack below has a
   file of its own to take away. */
static void copy_pack(const char *from, char *to, size_t size, const char *suffix) {
    FILE *in = fopen(from, "rb"), *out;
    char buffer[4096];
    size_t got;
    snprintf(to, size, "%s.%s", from, suffix);
    out = fopen(to, "wb");
    assert(in && out);
    while ((got = fread(buffer, 1, sizeof(buffer), in)) > 0) assert(fwrite(buffer, 1, got, out) == got);
    fclose(in);
    fclose(out);
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

    /* A second pack: reading from it closes the first one's file, and
       reading from the first again opens it again. One file at a time. */
    {
        sm_cover_pack_t other;
        int files;
        sm_cover_pack_let_go();
        files = open_files();
        assert(sm_cover_pack_open(&other, argv[1]));
        assert(sm_cover_pack_holding());
        expect_found(&other, "Wave Race 64 (USA).sprite", 64u, 48u);
        expect_found(&pack, "Zelda (Japan).sprite", 96u, 72u);
        expect_found(&other, "Zelda (Japan).sprite", 96u, 72u);
        assert(open_files() == files + 1);
        /* Let go, and the next read opens it again. */
        sm_cover_pack_let_go();
        assert(!sm_cover_pack_holding() && sm_cover_pack_ready(&pack));
        expect_found(&pack, "Super Mario 64 (USA).sprite", 96u, 72u);
        assert(sm_cover_pack_holding());
        /* Closing the pack whose file is open closes the file. */
        sm_cover_pack_close(&pack);
        assert(!sm_cover_pack_holding());
        expect_found(&other, "Wave Race 64 (USA).sprite", 64u, 48u);
        sm_cover_pack_close(&other);
        assert(!sm_cover_pack_holding());
        assert(sm_cover_pack_open(&pack, argv[1]));
    }

    sm_cover_pack_close(&pack);
    assert(!sm_cover_pack_ready(&pack));
    sm_cover_pack_close(&pack);      /* twice must be harmless */

    /* Room for two, as the Pro has room for four: two packs keep their
       file, a third closes the one read from longest ago, and letting go
       closes them all. A file taken away from under a pack shows which
       ones are still open: an open one still reads, a closed one cannot
       open again. */
    {
        sm_cover_pack_t a, b, c;
        char path_a[300], path_b[300], path_c[300];
        int files;
        copy_pack(argv[1], path_a, sizeof(path_a), "a");
        copy_pack(argv[1], path_b, sizeof(path_b), "b");
        copy_pack(argv[1], path_c, sizeof(path_c), "c");
        sm_cover_pack_let_go();
        files = open_files();
        sm_cover_pack_set_open_limit(2u);
        assert(sm_cover_pack_open(&a, path_a) && sm_cover_pack_open(&b, path_b));
        assert(open_files() == files + 2);
        expect_found(&b, "Wave Race 64 (USA).sprite", 64u, 48u);
        expect_found(&a, "Zelda (Japan).sprite", 96u, 72u);
        assert(open_files() == files + 2);
        /* b was read from longest ago. */
        assert(sm_cover_pack_open(&c, path_c));
        assert(open_files() == files + 2);
        assert(remove(path_a) == 0 && remove(path_b) == 0);
        expect_found(&a, "Super Mario 64 (USA).sprite", 96u, 72u);
        expect_found(&c, "Zelda (Japan).sprite", 96u, 72u);
        /* b's file is gone. Room was made for it first, as on the X7, so
           a, read from longest ago, is closed too. */
        assert(sm_cover_pack_read(&b, "Zelda (Japan).sprite", &length) == NULL);
        assert(open_files() == files + 1);
        assert(sm_cover_pack_read(&a, "Zelda (Japan).sprite", &length) == NULL);
        /* Back to one, with two open: the one read from longest ago, c, is
           closed, and a keeps its file. */
        copy_pack(argv[1], path_a, sizeof(path_a), "a");
        expect_found(&a, "Zelda (Japan).sprite", 96u, 72u);
        assert(open_files() == files + 2);
        sm_cover_pack_set_open_limit(1u);
        assert(open_files() == files + 1);
        assert(remove(path_a) == 0);
        expect_found(&a, "Wave Race 64 (USA).sprite", 64u, 48u);
        sm_cover_pack_set_open_limit(2u);
        expect_found(&c, "Wave Race 64 (USA).sprite", 64u, 48u);
        assert(open_files() == files + 2);
        sm_cover_pack_let_go();
        assert(!sm_cover_pack_holding() && open_files() == files);
        /* Out of range is held to 1 and to SM_COVER_PACK_OPEN_MAX. */
        sm_cover_pack_set_open_limit(0u);
        expect_found(&c, "Wave Race 64 (USA).sprite", 64u, 48u);
        assert(open_files() == files + 1);
        sm_cover_pack_close(&a);
        sm_cover_pack_close(&b);
        sm_cover_pack_close(&c);
        assert(!sm_cover_pack_holding() && open_files() == files);
        remove(path_c);
        sm_cover_pack_set_open_limit(1u);
    }

    /* A truncated or corrupted pack must be refused, not half-read. */
    if (argc > 2) {
        assert(!sm_cover_pack_open(&pack, argv[2]));
        assert(!sm_cover_pack_ready(&pack));
    }

    printf("cover_pack host checks passed\n");
    return 0;
}
