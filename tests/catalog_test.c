/* SPDX-License-Identifier: AGPL-3.0-only */
/* The catalog contract, against a real file written by tools/build_catalog.py.

   Two languages have to agree on this byte for byte: an offset the reader
   computes differently from the builder is every title on the card being
   somebody else's, or a description that is a path. So the fixture is not
   hand-made here; it is whatever the builder wrote. */
#include "catalog.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    sm_catalog_t catalog;
    sm_game_t game;
    char error[96];

    assert(argc > 2);

    /* The good one loads, and every field lands where the builder put it. */
    assert(catalog_load(&catalog, argv[1], error, sizeof(error)));
    assert(catalog.count == 3u);
    assert(catalog_get(&catalog, 0, &game));
    assert(!strcmp(game.path, "ROMS/GoldenEye 007 (USA).z64"));
    assert(!strcmp(game.title, "GoldenEye 007 (USA)"));
    assert(!strcmp(game.cover, "NGEE.sprite"));
    assert(!strcmp(game.publisher, "Nintendo"));
    assert(!strcmp(game.genre, "Shooters"));
    assert(!strcmp(game.description, "You are Bond. James Bond."));
    assert(game.year == 1997);
    assert(game.players == 4);
    assert(game.regions == SM_REGION_USA);
    assert(game.flags == SM_FLAG_FAVORITE);

    /* A game with nothing to say has an empty description, not a NULL one:
       the launch card tests description[0] and nothing else. */
    assert(catalog_get(&catalog, 1, &game));
    assert(!strcmp(game.path, "ROMS/Homebrew.z64"));
    assert(game.description != NULL && game.description[0] == '\0');
    assert(game.cover[0] == '\0');
    assert(game.year == 0 && game.regions == 0);
    /* What the tool set aside travels as a record the browser knows and
       never lists: its name, its path, and the flag that says so. */
    assert(catalog_get(&catalog, 2, &game));
    assert(!strcmp(game.path, "ROMS/Tools/IPL.z64"));
    assert(!strcmp(game.title, "IPL"));
    assert(game.flags == SM_FLAG_SET_ASIDE);
    assert(!catalog_get(&catalog, 3, &game));
    catalog_close(&catalog);

    /* A format-1 catalog -- from a prep tool older than descriptions -- is
       refused with a message that says what to do, not misread as garbage. */
    assert(!catalog_load(&catalog, argv[2], error, sizeof(error)));
    assert(strstr(error, "older") != NULL);

    /* And a file that is not a catalog at all. */
    assert(!catalog_load(&catalog, argv[3], error, sizeof(error)));

    printf("catalog checks passed\n");
    return 0;
}
