/* SPDX-License-Identifier: AGPL-3.0-only */
/* sm_picture_shrink: the grid's tiles are averages, not samples. */
#include "picture.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint16_t rgba(unsigned r, unsigned g, unsigned b, unsigned a) {
    return (uint16_t)((r << 11) | (g << 6) | (b << 1) | a);
}
static unsigned red_of(uint16_t p) { return (p >> 11) & 31u; }
static unsigned green_of(uint16_t p) { return (p >> 6) & 31u; }
static unsigned blue_of(uint16_t p) { return (p >> 1) & 31u; }

int main(void) {
    static uint16_t cover[72][96], tile[48][64];

    /* One colour in is the same colour out, every pixel. */
    for (int y = 0; y < 72; y++)
        for (int x = 0; x < 96; x++) cover[y][x] = rgba(20, 10, 5, 1);
    sm_picture_shrink(&cover[0][0], 96, 72, 96, &tile[0][0], 64, 48, 64);
    for (int y = 0; y < 48; y++)
        for (int x = 0; x < 64; x++) assert(tile[y][x] == rgba(20, 10, 5, 1));

    /* Every source column counts. A one-pixel white line on black, in any
       column, leaves a trace in the tile; sampling drops a third of them. */
    for (int column = 0; column < 96; column++) {
        int lit = 0;
        for (int y = 0; y < 72; y++)
            for (int x = 0; x < 96; x++) cover[y][x] = rgba(x == column ? 31 : 0, 0, 0, 1);
        sm_picture_shrink(&cover[0][0], 96, 72, 96, &tile[0][0], 64, 48, 64);
        for (int x = 0; x < 64; x++) lit += red_of(tile[10][x]) > 0;
        assert(lit >= 1 && lit <= 2);
    }

    /* Three to two: the middle source pixel is shared half and half, the
       outer ones belong whole to their side. 0, 30, 30 -> 10 and 30. */
    {
        uint16_t row[3] = { rgba(0, 0, 0, 1), rgba(30, 0, 0, 1), rgba(30, 0, 0, 1) };
        uint16_t out[2];
        sm_picture_shrink(row, 3, 1, 3, out, 2, 1, 2);
        assert(red_of(out[0]) == 10u && red_of(out[1]) == 30u);
    }

    /* Each channel on its own, with rounding to nearest. */
    {
        uint16_t pair[2] = { rgba(31, 0, 7, 1), rgba(0, 31, 8, 1) };
        uint16_t out[1];
        sm_picture_shrink(pair, 2, 1, 2, out, 1, 1, 1);
        assert(red_of(out[0]) == 16u && green_of(out[0]) == 16u && blue_of(out[0]) == 8u);
    }

    /* Opaque when at least half of what a pixel covers is. */
    {
        uint16_t quad[4] = { rgba(31, 31, 31, 1), rgba(31, 31, 31, 1),
                             rgba(0, 0, 0, 0), rgba(0, 0, 0, 0) };
        uint16_t out[1];
        sm_picture_shrink(quad, 2, 2, 2, out, 1, 1, 1);
        assert((out[0] & 1u) == 1u);
        quad[1] = rgba(0, 0, 0, 0);
        sm_picture_shrink(quad, 2, 2, 2, out, 1, 1, 1);
        assert((out[0] & 1u) == 0u);
    }

    /* Strides are honoured: a source wider than the picture in it. */
    {
        uint16_t wide[2][4] = { { rgba(31, 0, 0, 1), rgba(31, 0, 0, 1), 0xFFFF, 0xFFFF },
                                { rgba(31, 0, 0, 1), rgba(31, 0, 0, 1), 0xFFFF, 0xFFFF } };
        uint16_t out[1];
        sm_picture_shrink(&wide[0][0], 2, 2, 4, out, 1, 1, 1);
        assert(out[0] == rgba(31, 0, 0, 1));
    }

    /* Growing is not shrinking, and nonsense is refused: nothing written. */
    {
        uint16_t one[1] = { rgba(1, 1, 1, 1) }, out[4];
        memset(out, 0xAB, sizeof(out));
        sm_picture_shrink(one, 1, 1, 1, out, 2, 2, 2);
        sm_picture_shrink(NULL, 1, 1, 1, out, 1, 1, 1);
        sm_picture_shrink(one, 1, 1, 0, out, 1, 1, 1);
        for (int i = 0; i < 4; i++) assert(out[i] == 0xABABu);
    }

    printf("picture host checks passed\n");
    return 0;
}
