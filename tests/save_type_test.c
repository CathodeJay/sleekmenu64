/* SPDX-License-Identifier: AGPL-3.0-only */
#include "save_type.h"
#include "rom_db.h"
#include <assert.h>
#include <string.h>

/* Verbatim from krikzz/ed64-x-pub docs/rom_config_database.md. */
static const char SAMPLE_DB[] =
"------------------------ CRC detection ------------------------------ \n"
"0xCE84793D=30 \tDonkey Kong [f2]. CRC detection. SRAM\n"
"0x4CBC3B56=31\t64DD DMTJ SRAM+RTC\n"
"0xABA51D09=12\t40 Winks EEP4K+region-free\n"
"0xFA5A3DFF=02\tClay Fighter\n"
"0xbcb1f89f=10\tkirby-1.3\n"
"0x46039FB4=20\tkirby-U\n"
"0x0D93BA11=20\tkirby-U\n"
"------------------------ ID detection ------------------------------ \n"
"N6=10\t\tDr. Mario. ROM ID detection EEP4K\n"
"AF=51\t\tDoubutsu no Mori FLASHRAM+RTC\n"
"DD=31\t\tAll 64DD games SRAM+RTC\n";

static void header_init(uint8_t h[0x40], const char *id, uint32_t crc_hi, uint8_t override) {
    memset(h, 0, 0x40);
    h[0] = 0x80; h[1] = 0x37; h[2] = 0x12; h[3] = 0x40;
    h[0x10] = (uint8_t)(crc_hi >> 24); h[0x11] = (uint8_t)(crc_hi >> 16);
    h[0x12] = (uint8_t)(crc_hi >> 8);  h[0x13] = (uint8_t)crc_hi;
    h[0x3C] = (uint8_t)id[0]; h[0x3D] = (uint8_t)id[1];
    h[0x3F] = override;
}

int main(void) {
    uint8_t h[0x40];
    sm_save_decision_t d;

    /* --- line parser, against the documented samples --- */
    {
        bool by_crc; char id[SM_SAVE_FULL_ID_LEN + 1u]; uint32_t crc; sm_save_type_t t; unsigned c;
        assert(sm_save_parse_db_line("0xABA51D09=12\t40 Winks", 22, &by_crc, id, &crc, &t, &c));
        assert(by_crc && crc == 0xABA51D09u && t == SM_SAVE_EEP4K && c == SM_SAVE_CFG_REGION_FREE);
        /* lowercase hex is used in krikzz's own sample */
        assert(sm_save_parse_db_line("0xbcb1f89f=10\tkirby", 19, &by_crc, id, &crc, &t, &c));
        assert(by_crc && crc == 0xBCB1F89Fu && t == SM_SAVE_EEP4K && c == 0u);
        assert(sm_save_parse_db_line("AF=51\t\tDoubutsu", 15, &by_crc, id, &crc, &t, &c));
        assert(!by_crc && !strcmp(id, "AF") && t == SM_SAVE_FLASH && c == SM_SAVE_CFG_RTC);
        /* "DD=31  All 64DD games SRAM+RTC": type 3 = SRAM, config 1 = RTC. */
        assert(sm_save_parse_db_line("DD=31", 5, &by_crc, id, &crc, &t, &c));
        assert(!by_crc && !strcmp(id, "DD") && t == SM_SAVE_SRM32K && c == SM_SAVE_CFG_RTC);
        /* config is additive: 3 is RTC and region-free together */
        assert(sm_save_parse_db_line("XY=33", 5, &by_crc, id, &crc, &t, &c));
        assert(c == (SM_SAVE_CFG_RTC | SM_SAVE_CFG_REGION_FREE));

        /* non-records */
        assert(!sm_save_parse_db_line("---------- CRC detection ----------", 34, &by_crc, id, &crc, &t, &c));
        assert(!sm_save_parse_db_line("", 0, &by_crc, id, &crc, &t, &c));
        assert(!sm_save_parse_db_line("   ", 3, &by_crc, id, &crc, &t, &c));
        assert(!sm_save_parse_db_line("# comment", 9, &by_crc, id, &crc, &t, &c));
        assert(!sm_save_parse_db_line("NOKEY", 5, &by_crc, id, &crc, &t, &c));
        assert(!sm_save_parse_db_line("N6=", 3, &by_crc, id, &crc, &t, &c));
        assert(!sm_save_parse_db_line("N6=9", 4, &by_crc, id, &crc, &t, &c));   /* type > 6 */
        assert(!sm_save_parse_db_line("N6=14", 5, &by_crc, id, &crc, &t, &c));  /* config > 3 */
        /* OS 3.07+ accepts 2-6 symbols; the card's own file has "NK4J02=2". */
        assert(sm_save_parse_db_line("NK4J02=2", 8, &by_crc, id, &crc, &t, &c));
        assert(!by_crc && !strcmp(id, "NK4J02") && t == SM_SAVE_EEP16K && c == 0u);
        assert(sm_save_parse_db_line("NDKJ=1", 6, &by_crc, id, &crc, &t, &c));
        assert(!by_crc && !strcmp(id, "NDKJ"));
        assert(!sm_save_parse_db_line("TOOLONGID=10", 12, &by_crc, id, &crc, &t, &c));
        assert(!sm_save_parse_db_line("N=10", 4, &by_crc, id, &crc, &t, &c));
        assert(!sm_save_parse_db_line("0xZZZZZZZZ=10", 13, &by_crc, id, &crc, &t, &c));
        assert(!sm_save_parse_db_line("N6=10x", 6, &by_crc, id, &crc, &t, &c)); /* value not delimited */
    }

    /* --- developer override beats the database --- */
    header_init(h, "ED", 0xABA51D09u, 0x31);
    sm_save_resolve(h, sizeof(h), SAMPLE_DB, &d);
    assert(d.source == SM_SAVE_FROM_HEADER);
    assert(d.type == SM_SAVE_SRM32K && d.config == SM_SAVE_CFG_RTC);
    assert(!strcmp(d.rom_id, "ED") && d.crc_hi == 0xABA51D09u);

    header_init(h, "ED", 0u, 0x12);
    sm_save_resolve(h, sizeof(h), NULL, &d);
    assert(d.source == SM_SAVE_FROM_HEADER && d.type == SM_SAVE_EEP4K &&
           d.config == SM_SAVE_CFG_REGION_FREE);

    /* An "ED" id with a nonsense override falls through rather than lying. */
    header_init(h, "ED", 0xFA5A3DFFu, 0xF9);
    sm_save_resolve(h, sizeof(h), SAMPLE_DB, &d);
    assert(d.source == SM_SAVE_FROM_DB_CRC && d.type == SM_SAVE_OFF && d.config == 2u);

    /* --- CRC record --- */
    header_init(h, "XX", 0xCE84793Du, 0);
    sm_save_resolve(h, sizeof(h), SAMPLE_DB, &d);
    assert(d.source == SM_SAVE_FROM_DB_CRC && d.type == SM_SAVE_SRM32K && d.config == 0u);

    /* lowercase record still matches an uppercase header value */
    header_init(h, "XX", 0xBCB1F89Fu, 0);
    sm_save_resolve(h, sizeof(h), SAMPLE_DB, &d);
    assert(d.source == SM_SAVE_FROM_DB_CRC && d.type == SM_SAVE_EEP4K);

    /* --- ID record --- */
    header_init(h, "N6", 0u, 0);
    sm_save_resolve(h, sizeof(h), SAMPLE_DB, &d);
    assert(d.source == SM_SAVE_FROM_DB_ID && d.type == SM_SAVE_EEP4K && d.config == 0u);

    header_init(h, "AF", 0u, 0);
    sm_save_resolve(h, sizeof(h), SAMPLE_DB, &d);
    assert(d.source == SM_SAVE_FROM_DB_ID && d.type == SM_SAVE_FLASH &&
           d.config == SM_SAVE_CFG_RTC);

    /* CRC is checked per record in file order, so a CRC line above an ID line wins */
    header_init(h, "DD", 0x4CBC3B56u, 0);
    sm_save_resolve(h, sizeof(h), SAMPLE_DB, &d);
    assert(d.source == SM_SAVE_FROM_DB_CRC);

    /* --- nothing matches --- */
    header_init(h, "ZZ", 0x11111111u, 0);
    sm_save_resolve(h, sizeof(h), SAMPLE_DB, &d);
    assert(d.source == SM_SAVE_FROM_DEFAULT && d.type == SM_SAVE_OFF && d.config == 0u);
    sm_save_resolve(h, sizeof(h), NULL, &d);
    assert(d.source == SM_SAVE_FROM_DEFAULT && d.type == SM_SAVE_OFF);

    /* --- upper records win --- */
    {
        static const char DUP[] = "N6=51\tfirst\nN6=10\tsecond\n";
        header_init(h, "N6", 0u, 0);
        sm_save_resolve(h, sizeof(h), DUP, &d);
        assert(d.type == SM_SAVE_FLASH && d.config == SM_SAVE_CFG_RTC);
    }

    /* --- defensive --- */
    sm_save_resolve(NULL, 0, SAMPLE_DB, &d);
    assert(d.source == SM_SAVE_FROM_DEFAULT && d.type == SM_SAVE_OFF);
    sm_save_resolve(h, 4u, SAMPLE_DB, &d);
    assert(d.source == SM_SAVE_FROM_DEFAULT);
    sm_save_resolve(h, sizeof(h), SAMPLE_DB, NULL);

    /* --- the stock firmware's six-symbol identifier --- */
    {
        char full[SM_SAVE_FULL_ID_LEN + 1u];
        memset(h, 0, sizeof(h));
        h[0x3B] = 'N'; h[0x3C] = 'K'; h[0x3D] = '4'; h[0x3E] = 'J'; h[0x3F] = 0x02;
        sm_save_full_id(h, sizeof(h), full);
        assert(!strcmp(full, "NK4J02"));
        h[0x3B] = 0; h[0x3F] = 0xAB;
        sm_save_full_id(h, sizeof(h), full);
        assert(!strcmp(full, "?K4JAB"));   /* unprintable keeps the slot */
        sm_save_full_id(NULL, 0, full);
        assert(full[0] == '\0');
    }

    /* --- a six-symbol save_db record must actually match --- */
    {
        static const char DB6[] = "NK4J02=2\tkirby-1.2 eep16 (6 symbols ID)\n";
        memset(h, 0, sizeof(h));
        h[0] = 0x80; h[1] = 0x37; h[2] = 0x12; h[3] = 0x40;
        h[0x3B] = 'N'; h[0x3C] = 'K'; h[0x3D] = '4'; h[0x3E] = 'J'; h[0x3F] = 0x02;
        sm_save_resolve(h, sizeof(h), DB6, &d);
        assert(d.source == SM_SAVE_FROM_DB_ID && d.type == SM_SAVE_EEP16K);
        assert(!strcmp(d.full_id, "NK4J02"));
        /* a different revision must not match that record, and falls through
           to the built-in database instead */
        h[0x3F] = 0x00;
        sm_save_resolve(h, sizeof(h), DB6, &d);
        assert(d.source == SM_SAVE_FROM_BUILTIN);
    }

    /* --- built-in database: the retail library the stock firmware knows --- */
    {
        memset(h, 0, sizeof(h));
        h[0] = 0x80; h[1] = 0x37; h[2] = 0x12; h[3] = 0x40;
        /* Super Mario 64 (USA) — the game that exposed the missing database */
        h[0x3B] = 'N'; h[0x3C] = 'S'; h[0x3D] = 'M'; h[0x3E] = 'E';
        sm_save_resolve(h, sizeof(h), NULL, &d);
        assert(d.source == SM_SAVE_FROM_BUILTIN && d.type == SM_SAVE_EEP4K);

        /* Kirby 64 (J) rev 0 is SRAM; every other revision is EEPROM 16k */
        h[0x3B] = 'N'; h[0x3C] = 'K'; h[0x3D] = '4'; h[0x3E] = 'J'; h[0x3F] = 0x00;
        sm_save_resolve(h, sizeof(h), NULL, &d);
        assert(d.source == SM_SAVE_FROM_BUILTIN && d.type == SM_SAVE_SRM32K);
        h[0x3F] = 0x02;
        sm_save_resolve(h, sizeof(h), NULL, &d);
        assert(d.source == SM_SAVE_FROM_BUILTIN && d.type == SM_SAVE_EEP16K);
        h[0x3E] = 'E'; h[0x3F] = 0x00;      /* non-Japanese takes the else branch */
        sm_save_resolve(h, sizeof(h), NULL, &d);
        assert(d.source == SM_SAVE_FROM_BUILTIN && d.type == SM_SAVE_EEP16K);

        /* Castlevania: EEPROM 16k in Japan, no save elsewhere */
        h[0x3B] = 'N'; h[0x3C] = 'D'; h[0x3D] = '3'; h[0x3E] = 'J'; h[0x3F] = 0;
        sm_save_resolve(h, sizeof(h), NULL, &d);
        assert(d.source == SM_SAVE_FROM_BUILTIN && d.type == SM_SAVE_EEP16K);
        h[0x3E] = 'E';
        sm_save_resolve(h, sizeof(h), NULL, &d);
        assert(d.source == SM_SAVE_FROM_DEFAULT && d.type == SM_SAVE_OFF);

        /* an override in save_db.txt still beats the built-in database */
        {
            static const char OVR[] = "SM=50\tforce flashram\n";
            h[0x3B] = 'N'; h[0x3C] = 'S'; h[0x3D] = 'M'; h[0x3E] = 'E'; h[0x3F] = 0;
            sm_save_resolve(h, sizeof(h), OVR, &d);
            assert(d.source == SM_SAVE_FROM_DB_ID && d.type == SM_SAVE_FLASH);
        }
        /* and the ED header override beats everything */
        h[0x3C] = 'E'; h[0x3D] = 'D'; h[0x3F] = 0x31;
        sm_save_resolve(h, sizeof(h), NULL, &d);
        assert(d.source == SM_SAVE_FROM_HEADER && d.type == SM_SAVE_SRM32K);
    }

    /* --- names --- */
    assert(!strcmp(sm_save_type_name(SM_SAVE_FLASH), "FLASHRAM"));
    assert(!strcmp(sm_save_source_name(SM_SAVE_FROM_DB_CRC), "db:crc"));
    return 0;
}
