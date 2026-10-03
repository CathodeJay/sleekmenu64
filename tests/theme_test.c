/* SPDX-License-Identifier: AGPL-3.0-only */
/* The themes: finding one by the name a card gives, and what a role's
   colour is in each. */
#include "theme.h"
#include <assert.h>
#include <libdragon.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int from(const char *text) { return sm_theme_from_text(text, strlen(text)); }

int main(int argc, char **argv) {
    /* The first theme is the default, and it is the look the browser has
       always had: navy, with a pale gold accent. */
    assert(SM_THEME_COUNT >= 2u);
    assert(sm_theme_current() == 0);
    assert(!strcmp(sm_theme_id(0), "midnight") && !strcmp(sm_theme_name(0), "Midnight"));
    assert(!memcmp(sm_colour_rgb(SM_C_BG), (unsigned char[]){8, 12, 20}, 3));
    assert(!memcmp(sm_colour_rgb(SM_C_ACCENT), (unsigned char[]){245, 230, 160}, 3));
    assert(sm_colour(SM_C_ACCENT) == graphics_make_color(245, 230, 160, 255));

    /* A name is found whatever its case, whole, and only whole. */
    assert(sm_theme_find("midnight") == 0 && sm_theme_find("MIDNIGHT") == 0);
    assert(sm_theme_find("jungle") > 0 && sm_theme_find("Jungle") == sm_theme_find("jungle"));
    assert(sm_theme_find("jung") == -1 && sm_theme_find("jungles") == -1);
    assert(sm_theme_find("") == -1 && sm_theme_find(NULL) == -1);
    assert(sm_theme_find("a-name-far-too-long-to-be-a-theme") == -1);

    /* The card's file: its first word, whatever surrounds it. */
    assert(from("jungle\n") == sm_theme_find("jungle"));
    assert(from("  Grape\r\n") == sm_theme_find("grape"));
    assert(from("\xef\xbb\xbf" "fire") == sm_theme_find("fire"));
    assert(from("ice and nothing else matters\n") == sm_theme_find("ice"));
    assert(from("") == -1 && from("\n\n") == -1 && from("nothing-known\n") == -1);
    assert(sm_theme_from_text(NULL, 0) == -1);
    /* Only the bytes it was given: no terminator is needed, or read past. */
    assert(sm_theme_from_text("jungleXXXX", 6) == sm_theme_find("jungle"));

    /* Using one changes every role at once; an index nobody has is the
       default. */
    sm_theme_use(sm_theme_find("jungle"));
    assert(sm_theme_current() == sm_theme_find("jungle"));
    assert(memcmp(sm_colour_rgb(SM_C_BG), (unsigned char[]){8, 12, 20}, 3));
    assert(!memcmp(sm_colour_rgb(SM_C_ERROR), (unsigned char[]){255, 96, 80}, 3));   /* a meaning, not a mood */
    sm_theme_use(99);
    assert(sm_theme_current() == 0);
    sm_theme_use(-1);
    assert(sm_theme_current() == 0);

    /* Every theme has an id that fits the reader's buffer, a name, and is
       found by its own id. */
    for (unsigned i = 0; i < SM_THEME_COUNT; i++) {
        assert(strlen(sm_theme_id((int)i)) > 0 && strlen(sm_theme_id((int)i)) <= SM_THEME_ID_MAX);
        assert(strlen(sm_theme_name((int)i)) > 0);
        assert(sm_theme_find(sm_theme_id((int)i)) == (int)i);
    }

    /* The file on the card: read, and used; a file that is not there, or
       names nothing, leaves the theme alone. */
    if (argc > 1) {
        char path[512];
        FILE *file;
        snprintf(path, sizeof(path), "%s/theme.txt", argv[1]);
        assert(!sm_theme_load(path) && sm_theme_current() == 0);
        file = fopen(path, "wb"); fputs("grape\n", file); fclose(file);
        assert(sm_theme_load(path) && sm_theme_current() == sm_theme_find("grape"));
        file = fopen(path, "wb"); fputs("no-such-theme\n", file); fclose(file);
        assert(!sm_theme_load(path) && sm_theme_current() == sm_theme_find("grape"));
    }
    puts("theme checks passed");
    return 0;
}
