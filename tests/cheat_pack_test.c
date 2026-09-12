/* SPDX-License-Identifier: AGPL-3.0-only */
/* Finding a game's file in the Pro's cheat pack: names as the pack really
   spells them, ROMs as a No-Intro library spells them, and the region
   from the game code deciding between them. */
#include "cheat_pack.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

/* Verbatim names from ED64/CHEATS, chosen to cover every kind of tag. */
static const char *const NAMES[] = {
    "F-Zero X (U).cht", "F-Zero X (E).cht", "F-Zero X (J).cht",
    "Super Mario 64 (J).cht", "Super Mario 64 Shindou Edition (J).cht", "SUPER MARIO 64.cht",
    "GOLDENEYE.cht",
    "007 The World is Not Enough (E).cht",
    "Legend of Zelda, The - Ocarina of Time (U) (V1.0).cht",
    "Legend of Zelda, The - Ocarina of Time (U) (V1.1).cht",
    "Legend of Zelda, The - Ocarina of Time (U) (V1.2).cht",
    "Legend of Zelda, The - Ocarina of Time (E) (M3) (V1.1).cht",
    "Pokemon Stadium (E).cht", "Pokemon Stadium (U).cht",
    "Banjo-Kazooie.cht", "Diddy Kong Racing.cht",
    "WCW  nWo  REVENGE.cht", "HYBRID HEAVEN PAL.cht", "Kirby64.cht",
    "Madden 2000 (U).cht", "1080 SNOWBOARDING.cht",
    "Star Wars - Rogue Squadron (U) (M3) (V1.1).cht",
    "Mario Party (U) (V1.0) [f1].cht",
    "readme.txt", "._007 The World is Not Enough (E).cht",
};

static sm_cheat_pack_t pack;

/* A header with the title and the game code the cartridge would carry. */
static void header_for(uint8_t *header, const char *title, const char *code) {
    memset(header, 0, 0x40);
    memset(header + 0x20, ' ', 20);
    memcpy(header + 0x20, title, strlen(title));
    memcpy(header + 0x3B, code, 4);
}

static sm_cheat_match_t find(const char *rom, const char *title, const char *code) {
    uint8_t header[0x40];
    header_for(header, title, code);
    return sm_cheat_pack_find(&pack, rom, header, sizeof(header));
}

int main(void) {
    char text[64];
    size_t i;

    /* --- names ------------------------------------------------------------- */
    assert(sm_cheat_pack_normalise("Legend of Zelda, The - Ocarina of Time (U) (V1.0)", text, sizeof(text)) == 29);
    assert(!strcmp(text, "legendofzeldatheocarinaoftime"));
    sm_cheat_pack_normalise("WCW  nWo  REVENGE", text, sizeof(text));
    assert(!strcmp(text, "wcwnworevenge"));
    sm_cheat_pack_normalise("WCW / nWo  REVENGE", text, sizeof(text));
    assert(!strcmp(text, "wcwnworevenge"));
    sm_cheat_pack_normalise("Command & Conquer (USA)", text, sizeof(text));
    assert(!strcmp(text, "commandandconquer"));
    sm_cheat_pack_normalise("Bug's Life, A (E) [f1] (NTSC)", text, sizeof(text));
    assert(!strcmp(text, "bugslifea"));
    assert(sm_cheat_pack_normalise("(only tags)", text, sizeof(text)) == 0);
    assert(sm_cheat_pack_normalise(NULL, text, sizeof(text)) == 0 && text[0] == '\0');

    /* --- regions ----------------------------------------------------------- */
    assert(sm_region_from_code('E') == SM_CART_REGION_USA);
    assert(sm_region_from_code('P') == SM_CART_REGION_EUROPE);
    assert(sm_region_from_code('J') == SM_CART_REGION_JAPAN);
    assert(sm_region_from_code('D') == SM_CART_REGION_GERMANY);
    assert(sm_region_from_code('A') == (SM_CART_REGION_USA | SM_CART_REGION_JAPAN));
    assert(sm_region_from_code('?') == 0);
    sm_region_list(SM_CART_REGION_EUROPE | SM_CART_REGION_JAPAN, text, sizeof(text));
    assert(!strcmp(text, "Europe, Japan"));
    sm_region_list(0, text, sizeof(text));
    assert(text[0] == '\0');
    assert(!strcmp(sm_region_name(SM_CART_REGION_AUSTRALIA), "Australia"));

    /* --- the pack ---------------------------------------------------------- */
    sm_cheat_pack_reset(&pack);
    for (i = 0; i < sizeof(NAMES) / sizeof(NAMES[0]); i++) sm_cheat_pack_add(&pack, NAMES[i]);
    /* readme.txt is not a .cht, and the "._" twin is macOS bookkeeping */
    assert(pack.count == sizeof(NAMES) / sizeof(NAMES[0]) - 2u);
    assert(!strcmp(sm_cheat_pack_name(&pack, 0), "F-Zero X (U).cht"));
    assert(sm_cheat_pack_name(&pack, pack.count) == NULL);
    assert(pack.regions[0] == SM_CART_REGION_USA && pack.regions[1] == SM_CART_REGION_EUROPE);
    assert(pack.regions[5] == SM_CART_REGION_EUROPE);          /* SUPER MARIO 64: the table */
    assert(pack.regions[6] == SM_CART_REGION_USA);             /* GOLDENEYE */
    assert(pack.regions[11] == SM_CART_REGION_EUROPE && pack.version[11] == 1);
    assert(pack.version[8] == 0 && pack.version[10] == 2 && pack.version[0] == 0xFF);
    assert(pack.regions[16] == (SM_CART_REGION_USA | SM_CART_REGION_EUROPE));  /* WCW nWo Revenge */
    assert(pack.regions[18] == 0);                        /* Kirby64: not settled */
    assert(pack.regions[20] == 0);                        /* 1080: not settled */

    /* --- exact name -------------------------------------------------------- */
    {
        sm_cheat_match_t m = find("ROMS/F-Zero X (U).z64", "F-ZERO X", "CFZE");
        assert(m.kind == SM_CHEAT_MATCH_EXACT && !strcmp(m.name, "F-Zero X (U).cht"));
        m = find("ROMS/f-zero x (u).v64", "F-ZERO X", "CFZE");
        assert(m.kind == SM_CHEAT_MATCH_EXACT);
    }

    /* --- No-Intro name, region from the game code --------------------------- */
    {
        sm_cheat_match_t m = find("ROMS/1 US/F-Zero X (USA).z64", "F-ZERO X", "CFZE");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "F-Zero X (U).cht"));
        m = find("F-Zero X (Europe).z64", "F-ZERO X", "CFZP");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "F-Zero X (E).cht"));
        m = find("F-Zero X (Japan).z64", "F-ZERO X", "CFZJ");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "F-Zero X (J).cht"));
        assert(m.rom_region == SM_CART_REGION_JAPAN);
        assert(m.found == (SM_CART_REGION_USA | SM_CART_REGION_EUROPE | SM_CART_REGION_JAPAN));
        /* An oddly named file still finds its game through the header. */
        m = find("fzx.z64", "F-ZERO X", "CFZE");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "F-Zero X (U).cht"));
    }

    /* --- the title-named files and their settled regions -------------------- */
    {
        /* A European Super Mario 64 gets the file; an American one is told
           the pack has the game for Europe and Japan only. */
        sm_cheat_match_t m = find("Super Mario 64 (Europe) (En,Fr,De).z64", "SUPER MARIO 64", "NSMP");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "SUPER MARIO 64.cht"));
        m = find("Super Mario 64 (USA).z64", "SUPER MARIO 64", "NSME");
        assert(m.kind == SM_CHEAT_MATCH_OTHER_REGION && m.name == NULL);
        assert(m.found == (SM_CART_REGION_EUROPE | SM_CART_REGION_JAPAN));
        assert(m.rom_region == SM_CART_REGION_USA);
        m = find("SuperMario 64.z64", "SUPER MARIO 64", "NSMJ");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "Super Mario 64 (J).cht"));
        /* GoldenEye: the title-named file is the American one. */
        m = find("GoldenEye 007 (USA).z64", "GOLDENEYE", "NGEE");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "GOLDENEYE.cht"));
        m = find("007 - GoldenEye (Japan).z64", "GOLDENEYE", "NGEJ");
        assert(m.kind == SM_CHEAT_MATCH_OTHER_REGION && m.found == SM_CART_REGION_USA);
        /* A file serving two regions. */
        m = find("WCW-nWo Revenge (USA).z64", "WCW / nWo  REVENGE", "NW2E");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "WCW  nWo  REVENGE.cht"));
        m = find("WCW-nWo Revenge (Europe).z64", "WCW / nWo  REVENGE", "NW2P");
        assert(m.kind == SM_CHEAT_MATCH_REGION);
        /* An alias: the pack's name is neither the file's nor the title's. */
        m = find("Hybrid Heaven (Europe) (En,Fr,De).z64", "HYBRID HEAVEN", "NHYP");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "HYBRID HEAVEN PAL.cht"));
        m = find("Hybrid Heaven (USA).z64", "HYBRID HEAVEN", "NHYE");
        assert(m.kind == SM_CHEAT_MATCH_OTHER_REGION && m.found == SM_CART_REGION_EUROPE);
        m = find("Kirby 64 - The Crystal Shards (USA).z64", "KIRBY64", "NK4E");
        assert(m.kind == SM_CHEAT_MATCH_UNVERIFIED && !strcmp(m.name, "Kirby64.cht"));
    }

    /* --- a file the pack never gave a region ------------------------------- */
    {
        sm_cheat_match_t m = find("1080 Snowboarding (Japan, USA) (En,Ja).z64", "1080 SNOWBOARDING", "NTEA");
        assert(m.kind == SM_CHEAT_MATCH_UNVERIFIED && !strcmp(m.name, "1080 SNOWBOARDING.cht"));
        assert(m.rom_region == (SM_CART_REGION_USA | SM_CART_REGION_JAPAN));
        m = find("Diddy Kong Racing (USA) (En,Fr) (Rev 1).z64", "Diddy Kong Racing", "NDYE");
        assert(m.kind == SM_CHEAT_MATCH_UNVERIFIED && !strcmp(m.name, "Diddy Kong Racing.cht"));
    }

    /* --- PAL cousins ------------------------------------------------------- */
    {
        sm_cheat_match_t m = find("Pokemon Stadium (France).z64", "POKEMON STADIUM", "NPOF");
        assert(m.kind == SM_CHEAT_MATCH_PAL && !strcmp(m.name, "Pokemon Stadium (E).cht"));
        assert(m.rom_region == SM_CART_REGION_FRANCE);
        /* An American cartridge is not given the Europe file. */
        m = find("007 - The World Is Not Enough (USA).z64", "007 TWINE", "NO7E");
        assert(m.kind == SM_CHEAT_MATCH_OTHER_REGION && m.found == SM_CART_REGION_EUROPE);
        /* Nor a Japanese one. */
        m = find("007 - The World Is Not Enough (Japan).z64", "007 TWINE", "NO7J");
        assert(m.kind == SM_CHEAT_MATCH_OTHER_REGION);
        /* And the European one gets the file, never its "._" twin. */
        m = find("007 - The World Is Not Enough (Europe).z64", "007 TWINE", "NO7P");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "007 The World is Not Enough (E).cht"));
    }

    /* --- revisions --------------------------------------------------------- */
    {
        sm_cheat_match_t m = find("Legend of Zelda, The - Ocarina of Time (USA) (Rev 2).z64", "THE LEGEND OF ZELDA", "CZLE");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "Legend of Zelda, The - Ocarina of Time (U) (V1.2).cht"));
        m = find("Legend of Zelda, The - Ocarina of Time (USA) (Rev A).z64", "THE LEGEND OF ZELDA", "CZLE");
        assert(!strcmp(m.name, "Legend of Zelda, The - Ocarina of Time (U) (V1.1).cht"));
        m = find("Legend of Zelda, The - Ocarina of Time (USA).z64", "THE LEGEND OF ZELDA", "CZLE");
        assert(!strcmp(m.name, "Legend of Zelda, The - Ocarina of Time (U) (V1.0).cht"));
        /* No matching version: the untagged one, else the lowest. */
        m = find("Star Wars - Rogue Squadron (USA) (Rev 2).z64", "Rogue Squadron", "NRSE");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "Star Wars - Rogue Squadron (U) (M3) (V1.1).cht"));
        m = find("Mario Party (USA).z64", "MARIO PARTY", "NLBE");
        assert(m.kind == SM_CHEAT_MATCH_REGION && !strcmp(m.name, "Mario Party (U) (V1.0) [f1].cht"));
    }

    /* --- nothing ----------------------------------------------------------- */
    {
        sm_cheat_match_t m = find("Carmageddon 64 (USA).z64", "CARMAGEDDON 64", "NCDE");
        assert(m.kind == SM_CHEAT_MATCH_NONE && m.name == NULL && m.found == 0);
        assert(m.rom_region == SM_CART_REGION_USA);
        m = sm_cheat_pack_find(&pack, "Carmageddon 64 (USA).z64", NULL, 0);
        assert(m.kind == SM_CHEAT_MATCH_NONE);
        m = sm_cheat_pack_find(&pack, NULL, NULL, 0);
        assert(m.kind == SM_CHEAT_MATCH_NONE);
        m = sm_cheat_pack_find(NULL, "x.z64", NULL, 0);
        assert(m.kind == SM_CHEAT_MATCH_NONE);
        /* Without a header there is no region: a tagged file is another
           region's, an untagged one a guess. */
        m = sm_cheat_pack_find(&pack, "F-Zero X (USA).z64", NULL, 0);
        assert(m.kind == SM_CHEAT_MATCH_OTHER_REGION);
        m = sm_cheat_pack_find(&pack, "Diddy Kong Racing (USA).z64", NULL, 0);
        assert(m.kind == SM_CHEAT_MATCH_UNVERIFIED);
    }

    /* --- limits ------------------------------------------------------------ */
    {
        static char name[300];
        uint32_t before = pack.count;
        memset(name, 'a', sizeof(name) - 1);
        memcpy(name + sizeof(name) - 5, ".cht", 5);
        assert(!sm_cheat_pack_add(&pack, name));         /* longer than a name can be */
        assert(pack.count == before && pack.dropped == 1);
        assert(!sm_cheat_pack_add(&pack, "(E).cht"));     /* no name under the tag */
        assert(!sm_cheat_pack_add(&pack, NULL));
        sm_cheat_pack_reset(&pack);
        assert(pack.count == 0 && !pack.read);
        /* A full pack: every slot, then refusals counted. */
        for (i = 0; i < SM_CHEAT_PACK_MAX + 5u; i++) {
            snprintf(name, sizeof(name), "Game %u (U).cht", (unsigned)i);
            sm_cheat_pack_add(&pack, name);
        }
        assert(pack.count == SM_CHEAT_PACK_MAX && pack.dropped == 5);
    }

    puts("cheat pack tests passed");
    return 0;
}
