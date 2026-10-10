/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_INPUT_H
#define SLEEKMENU_INPUT_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool up, down, left, right, page_up, page_down, select, back, filter, favorite, toggle_view, start;
    /* Genre lives on the C pad because the D-pad has to keep moving the
       cursor in the grid, where left and right are how you get across a row. */
    bool genre_prev, genre_next;
    /* How many games a held direction moves this time: one, or more once
       a long hold is crossing a big library (sm_repeat_stride). Zero is
       read as one. Last, so the flags above stay a run of bools. */
    uint16_t step;
} sm_actions_t;

void app_input_init(void);
sm_actions_t app_input_poll(void);

#endif
