/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_BUTTONS_H
#define SLEEKMENU_BUTTONS_H

/* The controller's buttons, drawn.

   The help bar used to spell a button out -- "C^ VIEW", "Cv STAR" -- which
   took reading, and room the bar does not have. A button is now a picture
   of itself, nine pixels square, in the colour it has on the controller: a
   blue A, a green B, a red Start, yellow C buttons with their arrow, grey
   Z, L and R, and the D-pad as a cross. Those colours are the buttons' own
   and belong to no theme.

   A line of help names a button in braces and the words go between:

       "{S}PLAY {A}INFO {<}{>}TABS {^}VIEW {v}STAR {Z}FILTER"

   {A} {B} {S}tart {Z} {L} {R}, the C buttons {^} {v} {<} {>}, and the
   D-pad whole {+}, up and down {|}, left and right {-}. Anything else in
   braces is drawn as it is written.

   Measuring is pure, and tested on the host; drawing is the same walk with
   a surface to draw on. */

#include <libdragon.h>
#include <stdbool.h>

typedef enum {
    SM_BUTTON_A, SM_BUTTON_B, SM_BUTTON_START,
    SM_BUTTON_C_UP, SM_BUTTON_C_DOWN, SM_BUTTON_C_LEFT, SM_BUTTON_C_RIGHT,
    SM_BUTTON_Z, SM_BUTTON_L, SM_BUTTON_R,
    SM_BUTTON_DPAD, SM_BUTTON_DPAD_VERTICAL, SM_BUTTON_DPAD_HORIZONTAL,
    SM_BUTTON_COUNT
} sm_button_t;

enum {
    SM_BUTTON_SIZE = 9,
    /* After a button, before what it does. */
    SM_BUTTON_GAP = 2,
    /* Added before a button that follows a space, so the bar reads as
       groups rather than as one run. */
    SM_BUTTON_LEAD = 3,
    SM_HINT_CHAR_WIDTH = 5
};

/* The button a brace code names, or -1. */
int sm_button_from_code(char code);
/* Its body colour: three bytes. */
const unsigned char *sm_button_rgb(sm_button_t button);

/* One button, its top left corner at x, y. */
void sm_button_draw(surface_t *surface, int x, int y, sm_button_t button);

/* How wide a line of help is, in pixels. */
int sm_hints_width(const char *text);
/* Draw a line of help: the words in the colour the caller set, each button
   as its picture. `y` is the top of the text; a button is one pixel taller
   and starts a pixel above. Nothing is drawn past `max_x`: the line stops
   before the first button or word that would cross it. Returns the x after
   the last thing drawn. */
int sm_hints_draw(surface_t *surface, int x, int y, int max_x, const char *text);

#endif
