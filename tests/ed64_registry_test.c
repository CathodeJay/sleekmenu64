/* SPDX-License-Identifier: AGPL-3.0-only */
/* Host-side checks for registry.dat handling, run against the real files the
   firmware wrote, which are checked into docs/sd-forensics/. Anything this
   module gets wrong is a file the stock menu will reject or, worse, accept and
   act on -- so the samples are the test fixtures, not synthetic bytes. */
#include "ed64_registry.h"
#include "launch.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

#define SAMPLE_03 "docs/sd-forensics/sample-03-armed-sm64/registry.dat"
#define SAMPLE_02 "docs/sd-forensics/sample-02-after-majora/registry.dat"
#define SAMPLE_01 "docs/sd-forensics/sample-01-after-sleekmenu-probe/registry.dat"

static size_t slurp(const char *path, uint8_t *out, size_t cap) {
    FILE *file = fopen(path, "rb");
    size_t read;
    if (!file) { fprintf(stderr, "missing fixture %s\n", path); assert(0); }
    read = fread(out, 1, cap, file);
    fclose(file);
    return read;
}

static void expect_normalised(const char *in, const char *want) {
    char out[SM_REGISTRY_PATH_MAX];
    bool ok = sm_registry_normalise_path(in, out, sizeof(out));
    if (!want) { assert(!ok); return; }
    assert(ok);
    if (strcmp(out, want)) {
        fprintf(stderr, "normalise %s\n  got  %s\n  want %s\n", in, out, want);
        assert(0);
    }
}

int main(void) {
    uint8_t blob[SM_REGISTRY_SIZE + 16];
    uint8_t original[SM_REGISTRY_SIZE];
    sm_registry_record_t record;

    /* Every sample the firmware wrote must verify. If this breaks, the CRC
       reading is wrong and nothing else in this module can be trusted. */
    assert(slurp(SAMPLE_01, blob, sizeof(blob)) == SM_REGISTRY_SIZE);
    assert(sm_registry_verify(blob, SM_REGISTRY_SIZE));
    assert(slurp(SAMPLE_02, blob, sizeof(blob)) == SM_REGISTRY_SIZE);
    assert(sm_registry_verify(blob, SM_REGISTRY_SIZE));
    assert(slurp(SAMPLE_03, blob, sizeof(blob)) == SM_REGISTRY_SIZE);
    assert(sm_registry_verify(blob, SM_REGISTRY_SIZE));
    memcpy(original, blob, sizeof(original));

    /* Wrong length is refused outright, and so is a single flipped bit. */
    assert(!sm_registry_verify(blob, SM_REGISTRY_SIZE - 1u));
    assert(!sm_registry_verify(NULL, SM_REGISTRY_SIZE));
    blob[7] ^= 0x01u;
    assert(!sm_registry_verify(blob, SM_REGISTRY_SIZE));
    assert(!sm_registry_read(blob, SM_REGISTRY_SIZE, &record));
    assert(!sm_registry_write(blob, SM_REGISTRY_SIZE, &record));
    blob[7] ^= 0x01u;

    /* What sample-03 says. This is the record the firmware wrote for itself
       after launching Super Mario 64, so it is ground truth for the decode. */
    assert(sm_registry_read(blob, SM_REGISTRY_SIZE, &record));
    assert(!strcmp(record.path, "/ROMS/1 US - N-Z/Super Mario 64 (USA).z64"));
    assert(!strcmp(record.rom_id, "NSME00"));
    assert(record.save_type == SM_SAVE_EEP4K);
    assert(!memcmp(record.rom_crc, "\x63\x5A\x2B\xFF\x8B\x02\x23\x26", 8));

    /* Writing back exactly what was read must reproduce the file, apart from
       the stale tail the firmware leaves after a shortened path. */
    assert(sm_registry_write(blob, SM_REGISTRY_SIZE, &record));
    assert(sm_registry_verify(blob, SM_REGISTRY_SIZE));
    {
        sm_registry_record_t again;
        assert(sm_registry_read(blob, SM_REGISTRY_SIZE, &again));
        assert(!strcmp(again.path, record.path));
        assert(!strcmp(again.rom_id, record.rom_id));
        assert(again.save_type == record.save_type);
        assert(!memcmp(again.rom_crc, record.rom_crc, 8));
    }
    /* Everything we did not decode must survive untouched: the settings block
       and the browser cursor belong to the user, not to us. */
    assert(!memcmp(blob + 1050, original + 1050, 1196 - 1050));
    assert(!memcmp(blob + 2223, original + 2223, 2252 - 2223));

    /* Retargeting the record at another ROM. */
    {
        sm_registry_record_t majora;
        memset(&majora, 0, sizeof(majora));
        snprintf(majora.path, sizeof(majora.path),
            "/ROMS/1 US - A-M/Legend of Zelda, The - Majora's Mask (USA).z64");
        memcpy(majora.rom_id, "NZSE00", 7);
        majora.save_type = SM_SAVE_SRM32K;
        assert(sm_registry_write(blob, SM_REGISTRY_SIZE, &majora));
        assert(sm_registry_read(blob, SM_REGISTRY_SIZE, &record));
        assert(!strcmp(record.path, majora.path));
        assert(record.save_type == SM_SAVE_SRM32K);
        /* The record's own field carries it and the old tail is gone. */
        assert(!memchr(blob + strlen(majora.path) + 1u, 'j', 1024u - strlen(majora.path) - 1u));
        /* The stock browser's selection and cursor stack are NOT touched:
           writing a path there without a matching stack strands the other
           menu inside a folder it cannot climb out of. */
        assert(!memcmp(blob + 1064, original + 1064, 8u));
        assert(!memcmp(blob + 1196, original + 1196, 256u));
    }

    /* Refusals: an id of the wrong length, an empty or oversized path, and a
       save type outside krikzz's set. Each of these would reach the firmware
       or REG_GAM_CFG as a value we made up. */
    {
        sm_registry_record_t bad;
        assert(sm_registry_read(blob, SM_REGISTRY_SIZE, &bad));
        char keep[SM_REGISTRY_PATH_MAX];
        snprintf(keep, sizeof(keep), "%s", bad.path);
        memcpy(bad.rom_id, "NSME", 5);
        assert(!sm_registry_write(blob, SM_REGISTRY_SIZE, &bad));
        memcpy(bad.rom_id, "NSME00", 7);
        bad.path[0] = '\0';
        assert(!sm_registry_write(blob, SM_REGISTRY_SIZE, &bad));
        snprintf(bad.path, sizeof(bad.path), "%s", keep);
        bad.save_type = (sm_save_type_t)(SM_SAVE_TYPE_MAX + 1u);
        assert(!sm_registry_write(blob, SM_REGISTRY_SIZE, &bad));
    }

    /* The longest path the record can hold still leaves room for its
       terminator inside the shorter of the two path fields. */
    {
        sm_registry_record_t longest;
        memset(&longest, 0, sizeof(longest));
        memset(longest.path, 'x', sizeof(longest.path) - 1u);
        longest.path[0] = '/';
        memcpy(longest.rom_id, "NSME00", 7);
        longest.save_type = SM_SAVE_SRM32K;
        assert(strlen(longest.path) == sizeof(longest.path) - 1u);
        assert(sm_registry_write(blob, SM_REGISTRY_SIZE, &longest));
        assert(sm_registry_read(blob, SM_REGISTRY_SIZE, &record));
        assert(!strcmp(record.path, longest.path));
        /* Both fields are terminated; nothing ran past the end of either. */
        assert(blob[strlen(longest.path)] == 0u);
        assert(!memcmp(blob + 2223, original + 2223, 2252 - 2223));
    }

    /* A save type the firmware never writes is read as OFF, not passed on:
       this value would otherwise reach REG_GAM_CFG. */
    {
        uint8_t forged[SM_REGISTRY_SIZE];
        uint32_t crc;
        memcpy(forged, original, sizeof(forged));
        forged[1049] = 0x40u;
        crc = launch_crc32(forged, 2252);
        forged[2252] = (uint8_t)(crc >> 24); forged[2253] = (uint8_t)(crc >> 16);
        forged[2254] = (uint8_t)(crc >> 8);  forged[2255] = (uint8_t)crc;
        assert(sm_registry_verify(forged, SM_REGISTRY_SIZE));
        assert(sm_registry_read(forged, SM_REGISTRY_SIZE, &record));
        assert(record.save_type == SM_SAVE_OFF);
    }

    /* Path forms the catalog can produce all reduce to the firmware's form. */
    expect_normalised("sd:/ROMS/a/b.z64", "/ROMS/a/b.z64");
    expect_normalised("/ROMS/a/b.z64", "/ROMS/a/b.z64");
    expect_normalised("ROMS/a/b.z64", "/ROMS/a/b.z64");
    expect_normalised("sd://ROMS/a/b.z64", "/ROMS/a/b.z64");
    expect_normalised("", NULL);
    expect_normalised("/", NULL);
    expect_normalised(NULL, NULL);
    {
        char small[4];
        assert(!sm_registry_normalise_path("ROMS/a.z64", small, sizeof(small)));
    }

    /* The bug this test exists for. A catalog stores paths relative to the
       ROMS root, so the browser hands the loader "1 US - N-Z/x.z64"; the
       loader resolves that to "sd:/ROMS/1 US - N-Z/x.z64" and opens it. What
       goes into the firmware's record has to name the file on the CARD. The
       shorthand normalised directly gives "/1 US - N-Z/x.z64" -- a path that
       does not exist, written into the state file the stock menu reads at
       boot. Resolve first, then strip the volume. */
    {
        static const char *catalog_paths[] = {
            "1 US - N-Z/Super Mario 64 (USA).z64",
            "ROMS/1 US - N-Z/Super Mario 64 (USA).z64",
            "/ROMS/1 US - N-Z/Super Mario 64 (USA).z64",
            "sd:/ROMS/1 US - N-Z/Super Mario 64 (USA).z64",
        };
        for (size_t i = 0; i < sizeof(catalog_paths) / sizeof(*catalog_paths); i++) {
            sm_launch_paths_t resolved;
            char card[SM_REGISTRY_PATH_MAX];
            assert(launch_resolve_paths(catalog_paths[i], &resolved));
            assert(sm_registry_path_for_launch(resolved.primary, card, sizeof(card)));
            if (strcmp(card, "/ROMS/1 US - N-Z/Super Mario 64 (USA).z64")) {
                fprintf(stderr, "%s\n  resolved %s\n  card     %s\n",
                    catalog_paths[i], resolved.primary, card);
                assert(0);
            }
        }
        /* A ROM sitting at the card root keeps its own place. */
        {
            sm_launch_paths_t resolved;
            char card[SM_REGISTRY_PATH_MAX];
            assert(launch_resolve_paths("/sleekmenu.z64", &resolved));
            assert(sm_registry_path_for_launch(resolved.primary, card, sizeof(card)));
            assert(!strcmp(card, "/sleekmenu.z64"));
        }
        /* The two functions are not interchangeable, and this is the
           difference that broke a card: handed the catalog's shorthand,
           normalise answers with a path that does not exist. */
        {
            char card[SM_REGISTRY_PATH_MAX];
            assert(sm_registry_normalise_path("1 US - N-Z/Super Mario 64 (USA).z64",
                card, sizeof(card)));
            assert(!strcmp(card, "/1 US - N-Z/Super Mario 64 (USA).z64"));
            assert(strcmp(card, "/ROMS/1 US - N-Z/Super Mario 64 (USA).z64"));
        }

        /* Refusals: nothing to name, and no room to name it. */
        {
            char card[SM_REGISTRY_PATH_MAX], tiny[3];
            assert(!sm_registry_path_for_launch(NULL, card, sizeof(card)));
            assert(!sm_registry_path_for_launch("sd:/", card, sizeof(card)));
            assert(!sm_registry_path_for_launch("sd:/ROMS/x.z64", tiny, sizeof(tiny)));
        }
    }

    printf("ed64_registry host checks passed\n");
    return 0;
}
