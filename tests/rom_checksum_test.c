/* SPDX-License-Identifier: AGPL-3.0-only */
/* The console's checksum over a synthetic image, printed for the Python
   side to compare with tools/n64_checksum.py over the same bytes. The two
   were written apart, in two languages, from the same description; the
   Python one is checked against real cartridges, and this comparison
   carries that check over. The image is a linear congruential sequence, so
   both sides can make it without sharing a file. */
#include "rom_checksum.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define IMAGE (SM_CHECKSUM_START + SM_CHECKSUM_LENGTH)

static uint8_t *image;
static unsigned reads;

static bool read_image(uint32_t offset, void *dst, uint32_t bytes, void *context) {
    (void)context;
    assert(offset + bytes <= IMAGE);
    memcpy(dst, image + offset, bytes);
    reads++;
    return true;
}

static bool read_fails(uint32_t offset, void *dst, uint32_t bytes, void *context) {
    (void)offset; (void)dst; (void)bytes; (void)context;
    return false;
}

int main(int argc, char **argv) {
    uint32_t state = argc > 1 ? (uint32_t)strtoul(argv[1], NULL, 10) : 12345u;
    static const unsigned cics[] = {6101, 6102, 6103, 6105, 6106};
    image = malloc(IMAGE);
    assert(image);
    for (uint32_t i = 0; i < IMAGE; i++) {
        state = state * 1103515245u + 12345u;
        image[i] = (uint8_t)(state >> 16);
    }
    for (size_t c = 0; c < sizeof(cics) / sizeof(cics[0]); c++) {
        uint32_t words[2] = {0, 0};
        reads = 0;
        assert(sm_checksum_compute(cics[c], image + SM_CHECKSUM_BOOT_OFFSET, read_image, NULL, words));
        assert(reads == SM_CHECKSUM_LENGTH / 0x4000u);
        printf("%u %08lX %08lX\n", cics[c], (unsigned long)words[0], (unsigned long)words[1]);
    }
    {
        uint32_t words[2];
        uint8_t out[8];
        assert(!sm_checksum_compute(6104, image + SM_CHECKSUM_BOOT_OFFSET, read_image, NULL, words));
        assert(!sm_checksum_compute(6102, image + SM_CHECKSUM_BOOT_OFFSET, read_fails, NULL, words));
        image[0x10] = 0x12; image[0x11] = 0x34; image[0x12] = 0x56; image[0x13] = 0x78;
        image[0x14] = 0x9A; image[0x15] = 0xBC; image[0x16] = 0xDE; image[0x17] = 0xF0;
        sm_checksum_header_words(image, words);
        assert(words[0] == 0x12345678u && words[1] == 0x9ABCDEF0u);
        sm_checksum_encode(words, out);
        assert(!memcmp(out, image + 0x10, 8));
    }
    free(image);
    return 0;
}
