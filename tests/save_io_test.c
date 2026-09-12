/* SPDX-License-Identifier: AGPL-3.0-only */
/* Host-side checks for the parts of save_io that decide a filename and a
   length. Those two decisions are what makes a save written by SleekMenu the
   same file the stock firmware would have written, so they are worth pinning
   down away from hardware. */
#include "save_io.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void expect_path(const char *rom, sm_save_type_t type, const char *want) {
    char out[320];
    bool ok = sm_save_file_path(rom, type, "sd:/" SM_GAMEDATA_DIR, out, sizeof(out));
    if (!want) { assert(!ok); return; }
    assert(ok);
    if (strcmp(out, want)) {
        fprintf(stderr, "path for %s\n  got  %s\n  want %s\n", rom, out, want);
        assert(0);
    }
}

int main(void) {
    /* The sizes are a hardware contract: the stock firmware writes exactly
       these lengths, and a file of the wrong length is a file the firmware
       will not read back correctly. */
    assert(sm_save_bytes(SM_SAVE_OFF) == 0u);
    assert(sm_save_bytes(SM_SAVE_EEP4K) == 512u);
    assert(sm_save_bytes(SM_SAVE_EEP16K) == 2048u);
    assert(sm_save_bytes(SM_SAVE_SRM32K) == 32768u);
    assert(sm_save_bytes(SM_SAVE_SRM96K) == 98304u);
    assert(sm_save_bytes(SM_SAVE_FLASH) == 131072u);
    assert(sm_save_bytes(SM_SAVE_SRM128K) == 131072u);
    assert(sm_save_bytes((sm_save_type_t)99) == 0u);
    /* Nothing may exceed the one static buffer callers are told to size to. */
    for (int type = 0; type <= (int)SM_SAVE_TYPE_MAX; type++)
        assert(sm_save_bytes((sm_save_type_t)type) <= SM_SAVE_MAX_BYTES);

    assert(!sm_save_extension(SM_SAVE_OFF));
    assert(!strcmp(sm_save_extension(SM_SAVE_EEP4K), ".eep"));
    assert(!strcmp(sm_save_extension(SM_SAVE_EEP16K), ".eep"));
    assert(!strcmp(sm_save_extension(SM_SAVE_SRM32K), ".srm"));
    assert(!strcmp(sm_save_extension(SM_SAVE_SRM96K), ".srm"));
    assert(!strcmp(sm_save_extension(SM_SAVE_SRM128K), ".srm"));
    assert(!strcmp(sm_save_extension(SM_SAVE_FLASH), ".fla"));

    /* EEPROM is a serial device on the joybus; everything else is the
       cartridge's battery window. The two need different transfers. */
    assert(!sm_save_is_battery_backed(SM_SAVE_OFF));
    assert(!sm_save_is_battery_backed(SM_SAVE_EEP4K));
    assert(!sm_save_is_battery_backed(SM_SAVE_EEP16K));
    assert(sm_save_is_battery_backed(SM_SAVE_SRM32K));
    assert(sm_save_is_battery_backed(SM_SAVE_FLASH));

    /* The case the card proves: this exact file was written by the firmware
       and is checked into docs/sd-forensics/sample-03-armed-sm64/. */
    expect_path("/ROMS/1 US - N-Z/Super Mario 64 (USA).z64", SM_SAVE_EEP4K,
        "sd:/ED64/gamedata/Super Mario 64 (USA).eep");
    /* Every path form the catalog can hand us must reduce to the same name. */
    expect_path("sd:/ROMS/1 US - N-Z/Super Mario 64 (USA).z64", SM_SAVE_EEP4K,
        "sd:/ED64/gamedata/Super Mario 64 (USA).eep");
    expect_path("ROMS/1 US - N-Z/Super Mario 64 (USA).z64", SM_SAVE_EEP4K,
        "sd:/ED64/gamedata/Super Mario 64 (USA).eep");
    expect_path("Super Mario 64 (USA).z64", SM_SAVE_EEP4K,
        "sd:/ED64/gamedata/Super Mario 64 (USA).eep");

    /* Dots inside the name are not extension separators; only the last is. */
    expect_path("/ROMS/Mario Kart 64 (USA) v1.1.z64", SM_SAVE_SRM32K,
        "sd:/ED64/gamedata/Mario Kart 64 (USA) v1.1.srm");
    expect_path("/ROMS/Paper Mario (USA).n64", SM_SAVE_FLASH,
        "sd:/ED64/gamedata/Paper Mario (USA).fla");
    /* A browse-only format keeps its own stem: the save belongs to the file on
       the card, whatever the dump format is called. */
    expect_path("/ROMS/Body Harvest (USA).v64", SM_SAVE_SRM32K,
        "sd:/ED64/gamedata/Body Harvest (USA).srm");
    /* No extension at all is still a valid stem. */
    expect_path("/ROMS/nameless", SM_SAVE_SRM32K, "sd:/ED64/gamedata/nameless.srm");
    /* A leading dot is part of the name, not a separator. */
    expect_path("/ROMS/.hidden", SM_SAVE_SRM32K, "sd:/ED64/gamedata/.hidden.srm");

    /* Refusals. A type with no file has no path, and neither does a directory
       or an empty name. */
    expect_path("/ROMS/Whatever.z64", SM_SAVE_OFF, NULL);
    expect_path("/ROMS/", SM_SAVE_SRM32K, NULL);
    expect_path("", SM_SAVE_SRM32K, NULL);
    {
        char small[8];
        assert(!sm_save_file_path("/ROMS/Super Mario 64 (USA).z64", SM_SAVE_EEP4K,
            "sd:/" SM_GAMEDATA_DIR, small, sizeof(small)));
        assert(!sm_save_file_path(NULL, SM_SAVE_EEP4K, "sd:/", small, sizeof(small)));
    }

    /* The fill the EverDrive leaves in unused save RAM is 0xAA, not 0x00 or
       0xFF -- see docs/sd-forensics/sample-04-flushed-srm/. Whatever the byte,
       a uniform buffer is not a save. */
    {
        static const uint8_t fills[] = {0x00u, 0xFFu, 0xAAu, 0x55u, 0x01u};
        uint8_t probe[64];
        for (size_t f = 0; f < sizeof(fills); f++) {
            memset(probe, fills[f], sizeof(probe));
            assert(sm_save_buffer_is_blank(probe, sizeof(probe)));
            probe[sizeof(probe) - 1u] ^= 0x01u;
            assert(!sm_save_buffer_is_blank(probe, sizeof(probe)));
        }
    }

    /* Every result code has a message; a silent failure is a lost save the
       user is never told about. */
    for (int code = 0; code <= (int)SM_SAVE_IO_BLANK_REFUSED; code++) {
        const char *message = sm_save_io_message((sm_save_io_result_t)code);
        assert(message && message[0]);
    }

    printf("save_io host checks passed\n");
    return 0;
}
