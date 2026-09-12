/* SPDX-License-Identifier: AGPL-3.0-only */
/* Favourites have to survive a rebuilt catalog and a power cycle, which is the
   whole reason they live on the card rather than in the catalog. */
#include "favorites.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static sm_favorites_t fav;

static const char *TEMP = "/tmp/eb-favorites-test.txt";

int main(void) {
    /* Toggling is what the button does: on, then off, then on again. */
    sm_favorites_reset(&fav);
    assert(!sm_favorites_contains(&fav, "ROMS/A/Game.z64"));
    assert(sm_favorites_toggle(&fav, "ROMS/A/Game.z64"));
    assert(sm_favorites_contains(&fav, "ROMS/A/Game.z64"));
    assert(!sm_favorites_toggle(&fav, "ROMS/A/Game.z64"));
    assert(!sm_favorites_contains(&fav, "ROMS/A/Game.z64"));
    assert(fav.count == 0u && fav.used == 0u);
    assert(sm_favorites_toggle(&fav, "ROMS/A/Game.z64"));

    /* A card is exFAT and nothing else in the pipeline is case-sensitive
       about a ROM path either. */
    assert(sm_favorites_contains(&fav, "roms/a/GAME.Z64"));

    /* A path must match a whole line. "A/Game.z64" living inside
       "B/A/Game.z64" would otherwise unfavourite the wrong game. */
    sm_favorites_reset(&fav);
    sm_favorites_add(&fav, "B/A/Game.z64");
    assert(!sm_favorites_contains(&fav, "A/Game.z64"));
    assert(sm_favorites_remove(&fav, "B/A/Game.z64"));
    assert(fav.used == 0u);

    /* Removing from the middle keeps everything else intact -- the failure
       this guards is a memmove that eats the following line. */
    sm_favorites_reset(&fav);
    sm_favorites_add(&fav, "one.z64");
    sm_favorites_add(&fav, "two.z64");
    sm_favorites_add(&fav, "three.z64");
    assert(sm_favorites_remove(&fav, "two.z64"));
    assert(fav.count == 2u);
    assert(!strcmp(fav.text, "one.z64\nthree.z64\n"));
    assert(fav.used == strlen(fav.text));
    assert(sm_favorites_contains(&fav, "one.z64"));
    assert(sm_favorites_contains(&fav, "three.z64"));

    /* Adding the same path twice is a no-op, not a duplicate line. */
    assert(sm_favorites_add(&fav, "one.z64"));
    assert(fav.count == 2u);
    assert(!strcmp(fav.text, "one.z64\nthree.z64\n"));

    /* A path carrying a newline would corrupt the file; refuse it. */
    assert(!sm_favorites_add(&fav, "bad\nname.z64"));

    /* Round trip through the file, which is what a power cycle does. */
    assert(sm_favorites_save(&fav, TEMP));
    sm_favorites_reset(&fav);
    sm_favorites_load(&fav, TEMP);
    assert(fav.count == 2u);
    assert(sm_favorites_contains(&fav, "one.z64"));
    assert(sm_favorites_contains(&fav, "three.z64"));

    /* "Never had a file" and "had one, emptied it" are different states: only
       the first lets the catalog's own flags seed the set, or a card built
       with favourites would resurrect every one you deleted. */
    assert(fav.present);
    remove(TEMP);
    sm_favorites_load(&fav, TEMP);
    assert(fav.loaded && !fav.present && fav.count == 0u);
    sm_favorites_reset(&fav);
    assert(sm_favorites_save(&fav, TEMP));
    sm_favorites_load(&fav, TEMP);
    assert(fav.present && fav.count == 0u);

    /* Files written elsewhere: CRLF, blank lines, a trailing line with no
       newline. All should read back as three favourites. */
    {
        static const char text[] = "a.z64\r\n\r\nb.z64\nc.z64";
        sm_favorites_parse(&fav, text, sizeof(text) - 1u);
        assert(fav.count == 3u);
        assert(sm_favorites_contains(&fav, "b.z64"));
        assert(sm_favorites_contains(&fav, "c.z64"));
    }

    /* Filling up is reported rather than silently dropping the press. */
    {
        char path[64];
        uint32_t i;
        sm_favorites_reset(&fav);
        for (i = 0; i < SM_FAVORITES_MAX; i++) {
            snprintf(path, sizeof(path), "ROMS/filler/%06u.z64", i);
            assert(sm_favorites_add(&fav, path));
        }
        assert(!fav.full);
        assert(!sm_favorites_add(&fav, "ROMS/one-too-many.z64"));
        assert(fav.full);
        /* Making room clears the warning. */
        assert(sm_favorites_remove(&fav, "ROMS/filler/000000.z64"));
        assert(!fav.full);
        assert(sm_favorites_add(&fav, "ROMS/one-too-many.z64"));
    }

    /* Nothing dereferences a null. */
    assert(!sm_favorites_contains(NULL, "x"));
    assert(!sm_favorites_add(NULL, "x"));
    assert(!sm_favorites_remove(NULL, "x"));
    assert(!sm_favorites_contains(&fav, NULL));
    assert(!sm_favorites_save(&fav, NULL));
    sm_favorites_load(NULL, TEMP);
    sm_favorites_parse(NULL, "x", 1u);

    printf("favorites host checks passed\n");
    return 0;
}
