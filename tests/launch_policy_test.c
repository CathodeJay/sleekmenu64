/* SPDX-License-Identifier: AGPL-3.0-only */
#include "launch.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct { const char *name; uint32_t crc; sm_cic_t cic; } ipl3_fixture_t;

/* Build a full-size, instruction-shaped IPL3 fixture and CRC-forge only its final
 * word. This exercises the real 0xFC0-byte fingerprint window rather than
 * passing signature constants directly to the classifier. */
static void make_ipl3_fixture(uint8_t out[0xFC0], uint32_t target, uint32_t salt) {
    static const uint32_t mips[] = {
        0x3C08A400u, 0x25080040u, 0x3C09A460u, 0xAD200010u,
        0x8D2A0010u, 0x314A0003u, 0x1540FFFDu, 0x00000000u
    };
    for (size_t i = 0; i < 0xFC0 / 4 - 1; i++) {
        uint32_t word = mips[(i + salt) % (sizeof(mips) / sizeof(mips[0]))] ^
            (salt * 0x01010101u + (uint32_t)i * 0x00010001u);
        out[i * 4] = (uint8_t)(word >> 24); out[i * 4 + 1] = (uint8_t)(word >> 16);
        out[i * 4 + 2] = (uint8_t)(word >> 8); out[i * 4 + 3] = (uint8_t)word;
    }
    memset(out + 0xFC0 - 4, 0, 4);
    uint32_t base = launch_crc32(out, 0xFC0), columns[32];
    for (unsigned bit = 0; bit < 32; bit++) {
        out[0xFC0 - 4 + bit / 8] = (uint8_t)(1u << (bit % 8));
        columns[bit] = launch_crc32(out, 0xFC0) ^ base;
        out[0xFC0 - 4 + bit / 8] = 0;
    }
    uint64_t rows[32];
    for (unsigned row = 0; row < 32; row++) {
        rows[row] = (uint64_t)(((target ^ base) >> row) & 1u) << 32;
        for (unsigned col = 0; col < 32; col++) rows[row] |= (uint64_t)((columns[col] >> row) & 1u) << col;
    }
    for (unsigned col = 0, pivot = 0; col < 32; col++, pivot++) {
        unsigned found = pivot; while (found < 32 && !(rows[found] & ((uint64_t)1 << col))) found++;
        assert(found < 32); uint64_t swap = rows[pivot]; rows[pivot] = rows[found]; rows[found] = swap;
        for (unsigned row = 0; row < 32; row++) if (row != pivot && (rows[row] & ((uint64_t)1 << col))) rows[row] ^= rows[pivot];
    }
    uint32_t solution = 0;
    for (unsigned bit = 0; bit < 32; bit++) solution |= (uint32_t)((rows[bit] >> 32) & 1u) << bit;
    for (unsigned bit = 0; bit < 32; bit++) if (solution & (1u << bit)) out[0xFC0 - 4 + bit / 8] |= (uint8_t)(1u << (bit % 8));
    assert(launch_crc32(out, 0xFC0) == target);
}

int main(void) {
    uint8_t header[SM_N64_HEADER_SIZE] = {0x80, 0x37, 0x12, 0x40};
    uint32_t crc = 0;
    sm_cic_t cic = SM_CIC_UNKNOWN;
    sm_launch_paths_t paths;
    /* Card-relative first, which is what every catalog and the card scan
       record; ROMS/ second, for a catalog built against the ROM folder. */
    assert(launch_resolve_paths("Action/Game.z64", &paths));
    assert(paths.count == 2);
    assert(!strcmp(paths.primary, "sd:/Action/Game.z64"));
    assert(!strcmp(paths.fallback, "sd:/ROMS/Action/Game.z64"));
    assert(launch_resolve_paths("ROMS/Action/Game.z64", &paths));
    assert(paths.count == 1 && !strcmp(paths.primary, "sd:/ROMS/Action/Game.z64"));
    assert(launch_resolve_paths("/ROMS/Action/Game.z64", &paths));
    assert(paths.count == 1 && !strcmp(paths.primary, "sd:/ROMS/Action/Game.z64"));
    assert(launch_resolve_paths("sd:/ROMS/Action/Game.z64", &paths));
    assert(paths.count == 1 && !strcmp(paths.primary, "sd:/ROMS/Action/Game.z64"));
    assert(launch_resolve_paths("/Action/Game.z64", &paths));
    assert(paths.count == 1 && !strcmp(paths.primary, "sd:/Action/Game.z64"));
    assert(launch_validate("x.z64", SM_N64_HEADER_SIZE - 1, SM_LAUNCH_MAX_ROM, header, &crc, &cic) == SM_LAUNCH_BAD_SIZE);
    assert(launch_validate("x.z64", SM_LAUNCH_MAX_ROM + 2u, SM_LAUNCH_MAX_ROM, header, &crc, &cic) == SM_LAUNCH_BAD_SIZE);
    assert(launch_validate("x.z64", SM_N64_HEADER_SIZE + 1, SM_LAUNCH_MAX_ROM, header, &crc, &cic) == SM_LAUNCH_BAD_SIZE);
    header[0] = 0x37;
    assert(launch_validate("x.z64", SM_N64_HEADER_SIZE, SM_LAUNCH_MAX_ROM, header, &crc, &cic) == SM_LAUNCH_BAD_MAGIC);
    header[0] = 0x80;
    /* --- format is judged by the header, never by the filename --- */
    {
        uint8_t z[16], v[16], n[16];
        static const uint8_t Z[8] = {0x80,0x37,0x12,0x40, 0xDE,0xAD,0xBE,0xEF};
        static const uint8_t V[8] = {0x37,0x80,0x40,0x12, 0xAD,0xDE,0xEF,0xBE};
        static const uint8_t N[8] = {0x40,0x12,0x37,0x80, 0xEF,0xBE,0xAD,0xDE};
        memcpy(z, Z, 8); memcpy(v, V, 8); memcpy(n, N, 8);
        assert(sm_rom_format_detect(z, 8) == SM_ROM_FORMAT_Z64);
        assert(sm_rom_format_detect(v, 8) == SM_ROM_FORMAT_V64);
        assert(sm_rom_format_detect(n, 8) == SM_ROM_FORMAT_N64);
        assert(sm_rom_format_detect(z, 3) == SM_ROM_FORMAT_UNKNOWN);
        assert(sm_rom_format_detect(NULL, 8) == SM_ROM_FORMAT_UNKNOWN);
        /* normalising either swapped form must reproduce the z64 bytes */
        sm_rom_header_normalise(v, 8, SM_ROM_FORMAT_V64);
        assert(!memcmp(v, Z, 8));
        sm_rom_header_normalise(n, 8, SM_ROM_FORMAT_N64);
        assert(!memcmp(n, Z, 8));
        sm_rom_header_normalise(z, 8, SM_ROM_FORMAT_Z64);
        assert(!memcmp(z, Z, 8));   /* z64 is left alone */
        assert(!strcmp(sm_rom_format_name(SM_ROM_FORMAT_V64), "v64"));
    }
    /* every ROM extension is accepted; content decides */
    assert(launch_suffix_is_rom("g.z64") && launch_suffix_is_rom("g.V64") &&
           launch_suffix_is_rom("g.n64") && !launch_suffix_is_rom("g.txt"));

    /* The five-entry table is display only: the seed handed to IPL3 is
       fingerprinted from the target's own IPL3 at boot, so an unrecognised
       boot CRC is reported and no longer blocks the launch. */
    assert(launch_validate("x.z64", SM_N64_HEADER_SIZE, SM_LAUNCH_MAX_ROM, header, &crc, &cic) == SM_LAUNCH_OK);
    assert(cic == SM_CIC_UNKNOWN);
    static const ipl3_fixture_t fixtures[] = {
        {"standard 6101", 0x6170A4A1u, SM_CIC_6101},
        {"standard 6102", 0x90BB6CB5u, SM_CIC_6102},
        {"standard 6103", 0x0B050EE0u, SM_CIC_6103},
        {"standard 6105", 0x98BC2C86u, SM_CIC_6105},
        {"standard 6106", 0xACC8580Au, SM_CIC_6106},
    };
    for (size_t i = 0; i < sizeof(fixtures) / sizeof(fixtures[0]); i++) {
        (void)fixtures[i].name;
        make_ipl3_fixture(header + 0x40, fixtures[i].crc, (uint32_t)i + 1);
        assert(launch_validate("fixture.z64", SM_N64_HEADER_SIZE, SM_LAUNCH_MAX_ROM, header, &crc, &cic) == SM_LAUNCH_OK);
        assert(crc == fixtures[i].crc && cic == fixtures[i].cic);
    }

    /* 64DD disk images: a suffix of their own, never a ROM, and the IPL is
       chosen by the system area's first word. */
    {
        static const uint8_t japan[4] = { 0xE8, 0x48, 0xD3, 0x16 };
        static const uint8_t usa[4] = { 0x22, 0x63, 0xEE, 0x56 };
        static const uint8_t other[4] = { 0x00, 0x00, 0x00, 0x00 };
        assert(launch_suffix_is_disk("g.ndd") && launch_suffix_is_disk("G.NDD"));
        assert(!launch_suffix_is_disk("g.z64") && !launch_suffix_is_disk("ndd"));
        assert(!launch_suffix_is_rom("g.ndd"));
        assert(launch_validate("g.ndd", 64458560u, SM_LAUNCH_MAX_ROM, header, &crc, &cic) == SM_LAUNCH_BAD_SUFFIX);
        assert(launch_disk_region(japan, 4) == SM_DISK_REGION_JAPAN);
        assert(launch_disk_region(usa, 4) == SM_DISK_REGION_USA);
        assert(launch_disk_region(other, 4) == SM_DISK_REGION_DEVELOPMENT);
        assert(launch_disk_region(japan, 3) == SM_DISK_REGION_UNKNOWN);
        assert(launch_disk_region(NULL, 4) == SM_DISK_REGION_UNKNOWN);
        assert(!strcmp(launch_disk_ipl_name(SM_DISK_REGION_JAPAN), "NDDJ2.n64"));
        assert(!strcmp(launch_disk_ipl_name(SM_DISK_REGION_USA), "NDDE0.n64"));
        assert(!strcmp(launch_disk_ipl_name(SM_DISK_REGION_DEVELOPMENT), "NDXJ0.n64"));
        assert(launch_disk_ipl_name(SM_DISK_REGION_UNKNOWN) == NULL);
        assert(!strcmp(launch_disk_region_name(SM_DISK_REGION_JAPAN), "JPN"));
        assert(strstr(launch_result_message(SM_LAUNCH_NO_64DD), "Pro"));
        assert(strstr(launch_result_message(SM_LAUNCH_NO_IPL), "64ddipl"));
        assert(!strcmp(SM_DISK_IPL_DIR, "sd:/ED64/64ddipl"));
    }
    puts("launch policy tests passed");
    return 0;
}
