/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_LIST_VIEW_H
#define SLEEKMENU_LIST_VIEW_H

/* Where a scrolling window should start.

   This is two lines of arithmetic that lived inline in ui.c and got one of
   them wrong: a single formula was used for both directions, so moving the
   selection up past the top of the window computed `selected - visible + 1` on
   unsigned values and wrapped to about four billion. Every row then failed its
   bounds check and the list drew empty. Unsigned underflow is invisible to a
   source scan and needs a real test, so the arithmetic lives here where the
   host can run it. */

#include <stdbool.h>
#include <stdint.h>

/* Adjust an existing window so `selected` is inside it, moving as little as
   possible. It follows the selection, pinning it to the top when it leaves
   upward and to the bottom when it leaves downward.

   `columns` is 1 for a list and the grid's width for a grid, where the window
   still moves a row at a time but always starts on a row boundary. A row at
   a time, not a page: snapping to whole pages would replace all twelve
   covers on screen for a move that changes four tiles -- twelve reads off
   the card instead of four. */
uint32_t sm_view_first_visible(uint32_t first_visible, uint32_t selected,
    uint32_t visible, uint32_t count, uint32_t columns);

/* Build a window around `selected` from scratch, for a jump that did not come
   from the arrow keys and where the old window means nothing. */
uint32_t sm_view_focus(uint32_t selected, uint32_t visible, uint32_t count, uint32_t columns);

/* Coverflow: one column of a cover turned about its vertical axis.

   `step` counts columns from the card's near edge (the one facing the middle
   of the screen) to its far edge, so both sides use the same arithmetic and
   the drawing code only has to decide which way round to walk.

   Height falls linearly from near to far, which is what a rectangle rotated
   about a vertical axis does on screen. */
int sm_flow_column_height(int near_height, int far_height, int width, int step);

/* Which source column that screen column samples.

   Sampling the source evenly would be an affine stretch, and reads as a cover
   squashed rather than turned. Screen height is proportional to 1/w, so with
   height interpolating linearly, u/w and 1/w do too and the perspective-correct
   source column is their ratio:

       u = far_height * step / ((width - 1) * height(step))

   Three integer operations, and the difference between a flat trapezoid and a
   card standing at an angle. Kept here, out of the drawing code, because it is
   arithmetic a host can check and a television cannot. */
int sm_flow_source_column(int source_width, int width, int far_height,
    int step, int height);

/* One rung of the coverflow shelf: how wide a cover at this depth is drawn,
   the heights of its near and far edges, and how far it overlaps the cover
   nearer the middle (negative overlaps, positive leaves a gap). */
typedef struct {
    int width, near_height, far_height, gap;
} sm_flow_step_t;

/* Left edge of every cover on the shelf, indexed by slot: slot `half` is the
   selection in the middle, lower slots run left and higher ones right.
   `steps` is indexed by depth, 0 being the centre cover, and must hold
   `half + 1` entries. `x_out` must hold `2 * half + 1`.

   Written out here because the first version of it was wrong in a way no unit
   test on the drawing could catch: the left-hand covers accumulated their
   widths in the wrong direction and were laid out on top of the centre one,
   marching right instead of left. Positions are arithmetic; arithmetic gets
   checked. */
void sm_flow_positions(int centre_x, const sm_flow_step_t *steps, int half,
    int *x_out);

/* The coverflow shelf's position, in items: the index of the cover in the
   middle, a fraction while the shelf is moving. It glides towards the
   selection rather than stepping to it, so a press in the middle of a move
   turns the move instead of restarting it, and a held direction reads as one
   continuous slide rather than a series of hops.

   The glide is a critically damped spring: it starts from rest, eases in and
   out, and never overshoots. It is stepped by elapsed time, not by frames,
   so a frame that runs late moves the shelf further rather than slowing it
   down. */
typedef struct {
    float pos;
    float vel;      /* items per second */
} sm_glide_t;

/* Move `seconds` towards `target`. `smooth` is roughly the time the glide
   takes to cover most of a step; a single step settles in about three times
   that. Returns true while the shelf is still moving. */
bool sm_glide_step(sm_glide_t *glide, float target, float seconds, float smooth);
/* At `target`, at rest: a list that changed underneath the shelf has
   nothing to glide from. */
void sm_glide_snap(sm_glide_t *glide, float target);
/* No further than `lag` items from `target`, keeping the speed: a jump of
   fifty covers glides the last `lag` of them rather than flying past fifty
   pictures nobody can see. */
void sm_glide_limit(sm_glide_t *glide, float target, float lag);
bool sm_glide_moving(const sm_glide_t *glide, float target);

/* A held direction repeats: once on the press, then after a pause, then
   faster the longer it is held, so a short list is walked one step at a
   time and a long one can be crossed without pressing three thousand
   times. `now_ms` is any clock in milliseconds. Returns true on the polls
   that should move the cursor. */
typedef struct {
    bool down;
    uint32_t since_ms;   /* when the press started */
    uint32_t next_ms;    /* when it next repeats */
} sm_repeat_t;

enum { SM_REPEAT_DELAY_MS = 300 };
bool sm_repeat_fire(sm_repeat_t *repeat, bool down, uint32_t now_ms);

#endif
