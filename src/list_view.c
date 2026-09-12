/* SPDX-License-Identifier: AGPL-3.0-only */
#include "list_view.h"

/* Never leave a gap at the bottom while there are rows above that could fill
   it: a window past the last full page is just blank space. */
static uint32_t clamp(uint32_t first, uint32_t visible, uint32_t count) {
    if (!visible || count <= visible) return 0u;
    return first > count - visible ? count - visible : first;
}

/* The grid, worked out in rows rather than items. Doing it in items and then
   rounding to a row boundary looks equivalent and is not: clamping to
   count - visible can land mid-row, and rounding that down scrolls the window
   back past the row the selection just moved onto. */
static uint32_t grid_window(uint32_t first_visible, uint32_t selected,
    uint32_t visible, uint32_t count, uint32_t columns) {
    uint32_t rows_visible = visible / columns;
    uint32_t total_rows = (count + columns - 1u) / columns;
    uint32_t first_row = first_visible / columns;
    uint32_t selected_row = selected / columns;
    uint32_t last_row;
    if (!rows_visible) return 0u;
    if (selected_row < first_row) first_row = selected_row;
    else if (selected_row >= first_row + rows_visible)
        first_row = selected_row - rows_visible + 1u;
    last_row = total_rows > rows_visible ? total_rows - rows_visible : 0u;
    if (first_row > last_row) first_row = last_row;
    return first_row * columns;
}

uint32_t sm_view_first_visible(uint32_t first_visible, uint32_t selected,
    uint32_t visible, uint32_t count, uint32_t columns) {
    if (!visible || !count) return 0u;
    if (selected >= count) selected = count - 1u;
    if (columns > 1u) return grid_window(first_visible, selected, visible, count, columns);
    if (selected < first_visible) return clamp(selected, visible, count);
    if (selected >= first_visible + visible) {
        /* selected >= visible here, so the subtraction cannot wrap. */
        return clamp(selected - visible + 1u, visible, count);
    }
    return clamp(first_visible, visible, count);
}

uint32_t sm_view_focus(uint32_t selected, uint32_t visible, uint32_t count, uint32_t columns) {
    if (!visible || !count) return 0u;
    if (selected >= count) selected = count - 1u;
    if (columns > 1u) {
        /* Centre by rows, then let the shared logic clamp both ends. */
        uint32_t rows_visible = visible / columns;
        uint32_t selected_row = selected / columns;
        uint32_t first_row = selected_row > rows_visible / 2u
            ? selected_row - rows_visible / 2u : 0u;
        return grid_window(first_row * columns, selected, visible, count, columns);
    }
    /* Roughly centred, so there is context on both sides of the landing spot. */
    if (selected < visible / 2u) return 0u;
    return clamp(selected - visible / 2u, visible, count);
}

int sm_flow_column_height(int near_height, int far_height, int width, int step) {
    if (width < 2) return near_height;
    if (step < 0) step = 0;
    if (step > width - 1) step = width - 1;
    return near_height + (far_height - near_height) * step / (width - 1);
}

int sm_flow_source_column(int source_width, int width, int far_height,
    int step, int height) {
    long column;
    if (source_width < 1) return 0;
    if (width < 2 || height < 1) return 0;
    if (step < 0) step = 0;
    if (step > width - 1) step = width - 1;
    column = (long)source_width * far_height * step /
             ((long)(width - 1) * height);
    if (column < 0) return 0;
    return column < source_width ? (int)column : source_width - 1;
}

void sm_flow_positions(int centre_x, const sm_flow_step_t *steps, int half,
    int *x_out) {
    int depth, left_edge, right_edge;
    if (!steps || !x_out || half < 0) return;

    /* The selection sits centred; everything else hangs off its two edges. */
    x_out[half] = centre_x - steps[0].width / 2;
    left_edge = x_out[half];
    right_edge = x_out[half] + steps[0].width;

    for (depth = 1; depth <= half; depth++) {
        /* Rightwards, each cover starts just inside the previous one's right
           edge -- gap is negative, so it overlaps. */
        x_out[half + depth] = right_edge + steps[depth].gap;
        right_edge = x_out[half + depth] + steps[depth].width;

        /* Leftwards is the mirror: the new cover's RIGHT edge sits just inside
           the previous cover's left edge, so its left edge is that minus its
           own width. Getting this by accumulating widths in the same direction
           as the right-hand walk is what put the left covers on top of the
           centre one. */
        left_edge = left_edge - steps[depth].gap - steps[depth].width;
        x_out[half - depth] = left_edge;
    }
}
