/* SPDX-License-Identifier: AGPL-3.0-only */
/* The help bar's buttons: which code names which, how wide a line is, and
   that a line is never drawn past where it was told to stop.

   Given arguments, each is a line of help taken from src/ui.c, and each
   must fit the bar. */
#include "buttons.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

/* The bar: the safe area's 272 pixels, less three at each end. */
#define BAR_WIDTH 266

int main(int argc, char **argv) {
    surface_t screen;
    memset(&screen, 0, sizeof(screen));

    assert(sm_button_from_code('A') == SM_BUTTON_A && sm_button_from_code('S') == SM_BUTTON_START);
    assert(sm_button_from_code('^') == SM_BUTTON_C_UP && sm_button_from_code('v') == SM_BUTTON_C_DOWN);
    assert(sm_button_from_code('|') == SM_BUTTON_DPAD_VERTICAL);
    assert(sm_button_from_code('x') == -1 && sm_button_from_code('a') == -1);

    /* Words are five pixels a letter; a button is nine and two after it;
       one that follows a space stands three further off. */
    assert(sm_hints_width("") == 0 && sm_hints_width(NULL) == 0);
    assert(sm_hints_width("PLAY") == 20);
    assert(sm_hints_width("{A}") == 11);
    assert(sm_hints_width("{A}BOX") == 26);
    assert(sm_hints_width("{<}{>}TABS") == 42);
    assert(sm_hints_width("{S}PLAY {A}INFO") == 11 + 25 + 3 + 11 + 20);
    /* Braces that name no button are words. */
    assert(sm_hints_width("{x}") == 15 && sm_hints_width("{A") == 10 && sm_hints_width("a{}b") == 20);

    /* Drawing: the words go out as text, each button as boxes in its own
       colour, and it ends where the measure said. */
    {
        const unsigned char *blue = sm_button_rgb(SM_BUTTON_A);
        const unsigned char *red = sm_button_rgb(SM_BUTTON_START);
        sm_test_reset();
        assert(sm_hints_draw(&screen, 10, 50, 300, "{S}PLAY {A}INFO") == 10 + sm_hints_width("{S}PLAY {A}INFO"));
        assert(sm_test_drew("PLAY ") && sm_test_drew("INFO") && !sm_test_drew("{"));
        assert(sm_test_boxes_of(graphics_make_color(red[0], red[1], red[2], 255)) > 0);
        assert(sm_test_boxes_of(graphics_make_color(blue[0], blue[1], blue[2], 255)) > 0);
        assert(memcmp(blue, red, 3));

        /* Stopped at the edge: a button that would cross it is not drawn,
           nor anything after it. */
        sm_test_reset();
        assert(sm_hints_draw(&screen, 0, 0, 40, "{S}PLAY {A}INFO") <= 40);
        assert(sm_test_drew("PLAY") && !sm_test_drew("INFO"));
        assert(sm_test_boxes_of(graphics_make_color(blue[0], blue[1], blue[2], 255)) == 0);
        sm_test_reset();
        assert(sm_hints_draw(&screen, 0, 0, 22, "ABCDEFGH") == 20);
        assert(sm_test_drew("ABCD") && !sm_test_drew("ABCDE"));
    }

    /* Every button has a picture: something is drawn for each. */
    for (int button = 0; button < SM_BUTTON_COUNT; button++) {
        sm_test_reset();
        sm_button_draw(&screen, 0, 0, (sm_button_t)button);
        assert(sm_test_box_count >= 3);
    }

    for (int i = 1; i < argc; i++) {
        int width = sm_hints_width(argv[i]);
        if (width > BAR_WIDTH) {
            fprintf(stderr, "%d pixels, the bar has %d: %s\n", width, BAR_WIDTH, argv[i]);
            return 1;
        }
    }
    printf("button checks passed (%d lines of help fit)\n", argc - 1);
    return 0;
}
