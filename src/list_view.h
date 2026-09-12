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

#endif
