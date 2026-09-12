/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_INPUT_H
#define SLEEKMENU_INPUT_H

#include <stdbool.h>

typedef struct {
    bool up, down, left, right, page_up, page_down, select, back, filter, favorite, toggle_view, start;
    /* Genre lives on the C pad because the D-pad has to keep moving the
       cursor in the grid, where left and right are how you get across a row. */
    bool genre_prev, genre_next;
} sm_actions_t;

void app_input_init(void);
sm_actions_t app_input_poll(void);

#endif
