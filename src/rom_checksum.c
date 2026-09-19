/* SPDX-License-Identifier: AGPL-3.0-only */
#include "rom_checksum.h"
#include <string.h>

/* The sum reads the megabyte in pieces of this size. Large enough that the
   PI is not asked a thousand times, small enough not to matter next to the
   cover cache. */
#define CHUNK 0x4000u

static uint32_t rol(uint32_t value, unsigned bits) {
    bits &= 31u;
    return bits ? (value << bits) | (value >> (32u - bits)) : value;
}

static uint32_t word_at(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

static bool seed_for(unsigned cic, uint32_t *seed) {
    switch (cic) {
        case 6101: case 6102: *seed = 0xF8CA4DDCu; return true;
        case 6103: *seed = 0xA3886759u; return true;
        case 6105: *seed = 0xDF26F436u; return true;
        case 6106: *seed = 0x1FEA617Au; return true;
        default: return false;
    }
}

bool sm_checksum_compute(unsigned cic, const uint8_t *boot, sm_checksum_reader_t read,
    void *context, uint32_t words[2]) {
    static uint8_t chunk[CHUNK] __attribute__((aligned(16)));
    uint32_t seed, t1, t2, t3, t4, t5, t6;
    if (!boot || !read || !words || !seed_for(cic, &seed)) return false;
    t1 = t2 = t3 = t4 = t5 = t6 = seed;
    for (uint32_t offset = SM_CHECKSUM_START; offset < SM_CHECKSUM_START + SM_CHECKSUM_LENGTH; offset += CHUNK) {
        if (!read(offset, chunk, CHUNK, context)) return false;
        for (uint32_t i = 0; i < CHUNK; i += 4u) {
            uint32_t d = word_at(chunk + i);
            uint32_t summed = t6 + d;
            uint32_t r = rol(d, d & 0x1Fu);
            if (summed < t6) t4++;
            t6 = summed;
            t3 ^= d;
            t5 += r;
            if (t2 > d) t2 ^= r;
            else t2 ^= t6 ^ d;
            if (cic == 6105) {
                /* The 6105 mixes in its own boot code: the word at 0x0710 of
                   it, stepping through a 256-byte window as the position
                   advances. */
                t1 += word_at(boot + 0x0710u + ((offset + i) & 0xFFu)) ^ d;
            } else {
                t1 += t5 ^ d;
            }
        }
    }
    if (cic == 6103) {
        words[0] = (t6 ^ t4) + t3;
        words[1] = (t5 ^ t2) + t1;
    } else if (cic == 6106) {
        words[0] = t6 * t4 + t3;
        words[1] = t5 * t2 + t1;
    } else {
        words[0] = t6 ^ t4 ^ t3;
        words[1] = t5 ^ t2 ^ t1;
    }
    return true;
}

void sm_checksum_header_words(const uint8_t *header, uint32_t words[2]) {
    words[0] = word_at(header + SM_CHECKSUM_WORDS_OFFSET);
    words[1] = word_at(header + SM_CHECKSUM_WORDS_OFFSET + 4u);
}

void sm_checksum_encode(const uint32_t words[2], uint8_t out[8]) {
    for (unsigned w = 0; w < 2u; w++) {
        out[w * 4u] = (uint8_t)(words[w] >> 24);
        out[w * 4u + 1u] = (uint8_t)(words[w] >> 16);
        out[w * 4u + 2u] = (uint8_t)(words[w] >> 8);
        out[w * 4u + 3u] = (uint8_t)words[w];
    }
}
