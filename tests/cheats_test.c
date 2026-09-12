/* SPDX-License-Identifier: AGPL-3.0-only */
/* The cheat module against the shape of the real database: the first file
   of the EverDrive-64 Pro's ED64/CHEATS folder, entries with placeholders,
   conditionals, repeaters, and the browser's own state file. */
#include "cheats.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Verbatim from the Pro's ED64/CHEATS/007 The World is Not Enough (E).cht,
   with two entries added: one with the database's "XXXX" placeholder and
   one with a code the file gets wrong. */
static const char SAMPLE[] =
    "cheats = 13\n"
    "cheat0_desc = \"Invincible\"\n"
    "cheat0_enable = false\n"
    "cheat0_code = \"811147D8 0101\"\n"
    "cheat1_desc = \"Access Levels & Difficulties\"\n"
    "cheat1_enable = false\n"
    "cheat1_code = \"81103B66 0021;50000D01 0000;80118F38 0001\"\n"
    "cheat2_desc = \"Infinite Time\"\n"
    "cheat2_enable = true\n"
    "cheat2_code = \"81103B82 0000\"\n"
    "cheat3_desc = \"Multi Player\\Access All Arenas\"\n"
    "cheat3_enable = false\n"
    "cheat3_code = \"801147EB 0001;811147EC 0101;801147EE 0001\"\n"
    "cheat4_desc = \"Choose Level\"\n"
    "cheat4_enable = false\n"
    "cheat4_code = \"81127640 XXXX\"\n"
    "cheat5_desc = \"Button Activated\"\n"
    "cheat5_code = \"D01147EB 0001;801147EC 0001\"\n"
    "cheat6_desc = \"Broken\"\n"
    "cheat6_code = \"not a code at all\"\n"
    "cheat7_desc = \"No code, only a name\"\n"
    "cheat7_enable = false\n";

static sm_cheat_set_t set;

/* The hook check against a real ROM, when the runner names one: the test
   suite cannot carry a retail IPL3, so this part runs only where a cartridge
   image is at hand (SLEEKMENU_TEST_ROM=/path/to/game.z64, big-endian). */
static void check_real_rom(const char *path) {
    static uint8_t header[0x1000];
    FILE *file = fopen(path, "rb");
    size_t read;
    assert(file);
    read = fread(header, 1, sizeof(header), file);
    fclose(file);
    assert(read == sizeof(header));
    assert(header[0] == 0x80 && header[1] == 0x37);
    assert(sm_cheats_hook_check(header, sizeof(header)) == SM_CHEATS_HOOK_OK);
    /* Break the one instruction the engine overwrites and the check sees it. */
    header[475 * 4 + 3] ^= 1;
    header[472 * 4 + 3] ^= 1;
    header[466 * 4 + 3] ^= 1;
    header[499 * 4 + 3] ^= 1;
    header[488 * 4 + 3] ^= 1;
    if (sm_cheats_hook_check(header, sizeof(header)) == SM_CHEATS_HOOK_OK) assert(0);
    printf("hook check passed against %s\n", path);
}

int main(int argc, char **argv) {
    uint32_t code, value;
    char name[64];
    uint32_t list[64];
    char state[2048];
    char text[2048];

    /* --- one code --------------------------------------------------------- */
    assert(sm_cheats_parse_code("811147D8 0101", 13, &code, &value));
    assert(code == 0x811147D8u && value == 0x0101u);
    assert(sm_cheats_parse_code("  811147d8 0101  ", 17, &code, &value) && code == 0x811147D8u);
    assert(!sm_cheats_parse_code("811147D8 XXXX", 13, &code, &value));
    assert(!sm_cheats_parse_code("811147D80101", 12, &code, &value));
    assert(!sm_cheats_parse_code("811147D8 01010", 14, &code, &value));

    /* --- the file --------------------------------------------------------- */
    assert(sm_cheats_parse(&set, SAMPLE, strlen(SAMPLE)) == 7);
    assert(set.count == 7);
    assert(set.skipped == 1);                     /* the entry with no code */
    assert(!strcmp(set.cheats[0].desc, "Invincible"));
    assert(set.cheats[0].pairs == 1 && !set.cheats[0].enabled && !set.cheats[0].incomplete);
    assert(set.words[set.cheats[0].first] == 0x811147D8u && set.words[set.cheats[0].first + 1] == 0x0101u);
    assert(set.cheats[1].pairs == 3);
    assert(set.words[set.cheats[1].first + 2] == 0x50000D01u);  /* the repeater, in order */
    assert(set.cheats[2].enabled);                /* the file's own flag is honoured */
    assert(!strcmp(set.cheats[3].desc, "Multi Player / Access All Arenas"));
    assert(set.cheats[4].incomplete && set.cheats[4].pairs == 0 && !set.cheats[4].enabled);
    assert(!strcmp(set.cheats[4].desc, "Choose Level"));
    assert(set.cheats[5].pairs == 2 && (set.words[set.cheats[5].first] >> 24) == 0xD0u);
    assert(set.cheats[6].incomplete);
    assert(set.word_count == (1 + 3 + 1 + 3 + 2) * 2);

    /* --- names ------------------------------------------------------------ */
    assert(sm_cheats_file_from_rom_path("ROMS/1 US - A-M/F-Zero X (USA).z64", name, sizeof(name)));
    assert(!strcmp(name, "F-Zero X (USA).cht"));
    assert(sm_cheats_file_from_rom_path("sd:/ROMS/Game.v64", name, sizeof(name)) && !strcmp(name, "Game.cht"));
    assert(!sm_cheats_file_from_rom_path("ROMS/.z64", name, sizeof(name)));
    assert(!sm_cheats_file_from_rom_path("ROMS/Game.z64", name, 8));
    /* --- the engine's list ------------------------------------------------ */
    assert(sm_cheats_enabled_count(&set) == 1);
    {
        uint32_t n = sm_cheats_build_list(&set, list, 64);
        assert(n == 4);                            /* one pair and the terminator */
        assert(list[0] == 0x81103B82u && list[1] == 0 && list[2] == 0 && list[3] == 0);
    }
    set.cheats[0].enabled = true;
    set.cheats[1].enabled = true;
    set.cheats[4].enabled = true;                  /* incomplete: must not count */
    assert(sm_cheats_enabled_count(&set) == 3);
    {
        uint32_t n = sm_cheats_build_list(&set, list, 64);
        assert(n == (1 + 3 + 1) * 2 + 2);
        assert(list[0] == 0x811147D8u);            /* file order, not toggle order */
        assert(list[2] == 0x81103B66u && list[4] == 0x50000D01u && list[6] == 0x80118F38u);
        assert(list[8] == 0x81103B82u);
        assert(list[10] == 0 && list[11] == 0);
        /* too small a buffer is a refusal, not a truncated list */
        assert(sm_cheats_build_list(&set, list, 6) == 0);
    }
    /* nothing enabled: no list at all */
    set.cheats[0].enabled = set.cheats[1].enabled = set.cheats[2].enabled = set.cheats[4].enabled = false;
    assert(sm_cheats_build_list(&set, list, 64) == 0);

    /* --- the state file --------------------------------------------------- */
    {
        const char *existing =
            "[ROMS/Other Game.z64]\n"
            "80000000 0001\n"
            "\n"
            "[roms/007 The World is Not Enough (E).z64]\n"
            "81103B66 0021;50000D01 0000;80118F38 0001\n"
            "80000000 FFFF\n";                      /* not in this file: ignored */
        size_t n;
        sm_cheats_parse(&set, SAMPLE, strlen(SAMPLE));
        /* A section for the game replaces the file's own flags entirely. */
        sm_cheats_state_apply(&set, existing, strlen(existing), "ROMS/007 The World is Not Enough (E).z64");
        assert(!set.cheats[2].enabled && set.cheats[1].enabled && !set.cheats[0].enabled);
        assert(sm_cheats_enabled_count(&set) == 1);
        /* No section: the file's flags stand. */
        sm_cheats_parse(&set, SAMPLE, strlen(SAMPLE));
        sm_cheats_state_apply(&set, existing, strlen(existing), "ROMS/Nothing.z64");
        assert(set.cheats[2].enabled && !set.cheats[1].enabled);

        /* Rewriting keeps the other game and replaces ours. */
        set.cheats[0].enabled = true;
        n = sm_cheats_state_update(existing, strlen(existing), "ROMS/007 The World is Not Enough (E).z64",
            &set, state, sizeof(state));
        assert(n > 0);
        assert(!strcmp(state,
            "[ROMS/Other Game.z64]\n"
            "80000000 0001\n"
            "\n"
            "[ROMS/007 The World is Not Enough (E).z64]\n"
            "811147D8 0101\n"
            "81103B82 0000\n"));
        /* Round trip. */
        sm_cheats_parse(&set, SAMPLE, strlen(SAMPLE));
        sm_cheats_state_apply(&set, state, n, "ROMS/007 The World is Not Enough (E).z64");
        assert(set.cheats[0].enabled && set.cheats[2].enabled && !set.cheats[1].enabled);
        /* Turning everything off removes the section. */
        set.cheats[0].enabled = set.cheats[2].enabled = false;
        n = sm_cheats_state_update(state, n, "ROMS/007 The World is Not Enough (E).z64", &set, text, sizeof(text));
        assert(!strcmp(text, "[ROMS/Other Game.z64]\n80000000 0001\n"));
        /* From nothing. */
        set.cheats[3].enabled = true;
        n = sm_cheats_state_update(NULL, 0, "ROMS/x.z64", &set, text, sizeof(text));
        assert(!strcmp(text, "[ROMS/x.z64]\n801147EB 0001;811147EC 0101;801147EE 0001\n"));
        assert(sm_cheats_state_update(NULL, 0, "ROMS/x.z64", &set, text, 16) == 0 && text[0] == '\0');
        /* Formatting one entry. */
        assert(sm_cheats_format_code(&set, 1, text, sizeof(text)) == 41);
        assert(!strcmp(text, "81103B66 0021;50000D01 0000;80118F38 0001"));
    }

    /* --- limits ------------------------------------------------------------ */
    {
        /* More entries than the set holds: the extra are counted, not lost
           silently, and the first SM_CHEATS_MAX survive. */
        static char big[SM_CHEATS_MAX * 64 + 4096];
        size_t at = 0;
        unsigned i;
        for (i = 0; i < SM_CHEATS_MAX + 10u; i++)
            at += (size_t)snprintf(big + at, sizeof(big) - at, "cheat%u_code = \"80%06X 0001\"\n", i, i);
        assert(sm_cheats_parse(&set, big, at) == SM_CHEATS_MAX);
        assert(set.skipped == 10);
        /* An empty or absent file is an empty set. */
        assert(sm_cheats_parse(&set, "", 0) == 0 && set.count == 0);
        assert(sm_cheats_parse(&set, NULL, 0) == 0);
        assert(sm_cheats_parse(&set, "cheats = 0\n", 11) == 0);
    }

    /* --- the hook ----------------------------------------------------------- */
    {
        static uint8_t header[0x1000];
        memset(header, 0, sizeof(header));
        /* Nothing, or too little, or a boot code no CIC signs: no hook. */
        assert(sm_cheats_hook_check(NULL, sizeof(header)) == SM_CHEATS_HOOK_UNKNOWN_CIC);
        assert(sm_cheats_hook_check(header, 0x800) == SM_CHEATS_HOOK_UNKNOWN_CIC);
        assert(sm_cheats_hook_check(header, sizeof(header)) == SM_CHEATS_HOOK_UNKNOWN_CIC);
        memset(header, 0xA5, sizeof(header));
        assert(sm_cheats_hook_check(header, sizeof(header)) == SM_CHEATS_HOOK_UNKNOWN_CIC);
        if (argc > 1) check_real_rom(argv[1]);
    }

    puts("cheats tests passed");
    return 0;
}
