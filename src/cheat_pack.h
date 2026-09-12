/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_CHEAT_PACK_H
#define SLEEKMENU_CHEAT_PACK_H

/* Finding a game's file in the EverDrive-64 Pro's cheat pack.

   The pack under ED64/CHEATS is the older half of libretro's Nintendo 64
   cheat database, 543 files named the GoodN64 way: "F-Zero X (U).cht",
   "Super Mario 64 (J).cht", with (E) (F) (G) (I) (S) (A) and (V1.1) tags.
   A library is usually named the No-Intro way -- "F-Zero X (USA).z64" --
   so a file named exactly like the ROM is the exception, and a lookup by
   exact name finds next to nothing. What does work is comparing the names
   with their tags stripped and the region taken from the tag on one side
   and from the ROM's game code on the other: NSME is the American Super
   Mario 64, NSMP the European one, and the fourth letter says so.

   Fifty-nine files carry no tag at all, most of them named after the
   twenty-character title in the ROM header ("SUPER MARIO 64.cht",
   "GOLDENEYE.cht"), which is the same on every region's cartridge. Their
   region was worked out once by matching their codes against libretro's
   region-named files and is a table here; the ones that could not be
   settled are handed over marked unverified.

   Pure: the pack is a list of names the launcher feeds in from the folder
   listing, and the match is a decision, not a read. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Cartridge regions, as a bit set: a file may serve more than one. (The
   catalog has its own three-region enum for the filter; this is the
   cartridge's, finer.) */
enum {
    SM_CART_REGION_USA = 1u << 0,
    SM_CART_REGION_EUROPE = 1u << 1,
    SM_CART_REGION_JAPAN = 1u << 2,
    SM_CART_REGION_FRANCE = 1u << 3,
    SM_CART_REGION_GERMANY = 1u << 4,
    SM_CART_REGION_ITALY = 1u << 5,
    SM_CART_REGION_SPAIN = 1u << 6,
    SM_CART_REGION_AUSTRALIA = 1u << 7,
    SM_CART_REGION_PAL = SM_CART_REGION_EUROPE | SM_CART_REGION_FRANCE | SM_CART_REGION_GERMANY |
        SM_CART_REGION_ITALY | SM_CART_REGION_SPAIN | SM_CART_REGION_AUSTRALIA
};

/* The fourth letter of the game code (header byte 0x3E) as a region, or 0. */
uint16_t sm_region_from_code(char letter);
/* "USA", "Europe", ... for one bit; a set is written as "Europe, Japan". */
const char *sm_region_name(uint16_t one);
size_t sm_region_list(uint16_t set, char *out, size_t out_size);

#define SM_CHEAT_PACK_MAX 1024u
#define SM_CHEAT_PACK_POOL (64u * 1024u)

typedef struct {
    char pool[SM_CHEAT_PACK_POOL];   /* name, base, per entry */
    uint16_t name_at[SM_CHEAT_PACK_MAX];
    uint16_t base_at[SM_CHEAT_PACK_MAX];
    uint16_t regions[SM_CHEAT_PACK_MAX];  /* from the tag, or the table; 0 unknown */
    uint8_t version[SM_CHEAT_PACK_MAX];   /* (V1.1) -> 1; 0xFF when untagged */
    uint32_t used;
    uint32_t count;
    uint32_t dropped;    /* names that did not fit */
    bool read;           /* the folder was listed, whatever it held */
} sm_cheat_pack_t;

void sm_cheat_pack_reset(sm_cheat_pack_t *pack);
/* One name from the folder; anything but a .cht is ignored. */
bool sm_cheat_pack_add(sm_cheat_pack_t *pack, const char *name);
const char *sm_cheat_pack_name(const sm_cheat_pack_t *pack, uint32_t index);

typedef enum {
    SM_CHEAT_MATCH_NONE = 0,
    SM_CHEAT_MATCH_EXACT,         /* named exactly like the ROM file */
    SM_CHEAT_MATCH_REGION,        /* same game, tag and game code agree */
    SM_CHEAT_MATCH_PAL,           /* a French, German... cartridge given the Europe file */
    SM_CHEAT_MATCH_UNVERIFIED,    /* same game, file without a region anyone could settle */
    SM_CHEAT_MATCH_OTHER_REGION   /* the pack has the game for other regions only */
} sm_cheat_match_kind_t;

typedef struct {
    sm_cheat_match_kind_t kind;
    const char *name;         /* the file, in the pack's pool; NULL for NONE and OTHER_REGION */
    uint16_t rom_region;      /* what the game code said, 0 when unreadable */
    uint16_t found;           /* regions the pack has the game for */
} sm_cheat_match_t;

/* `rom_path` is the ROM's file name or path; `header` its normalised
   header, at least 0x40 bytes, or NULL. */
sm_cheat_match_t sm_cheat_pack_find(const sm_cheat_pack_t *pack, const char *rom_path,
    const uint8_t *header, size_t header_length);

/* Exposed for the tests: a name with its tags dropped, folded to the
   letters and digits that survive. Returns the length. */
size_t sm_cheat_pack_normalise(const char *text, char *out, size_t out_size);

#endif
