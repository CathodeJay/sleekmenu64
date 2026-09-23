/* SPDX-License-Identifier: AGPL-3.0-only */
/* The window arithmetic, exercised where unsigned wraparound shows up. */
#include "list_view.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    const uint32_t rows = 8u, n = 100u;

    /* The bug this module exists for: the selection leaves the top of the
       window. The old inline formula computed selected - visible + 1 here and
       wrapped, which drew an empty list. */
    for (uint32_t selected = 0; selected < rows; selected++) {
        uint32_t first = sm_view_first_visible(rows, selected, rows, n, 1u);
        assert(first == selected);
        assert(first <= selected && selected < first + rows);
    }
    assert(sm_view_first_visible(1u, 0u, rows, n, 1u) == 0u);
    assert(sm_view_first_visible(50u, 0u, rows, n, 1u) == 0u);

    /* Leaving the bottom pins the selection to the last row. */
    assert(sm_view_first_visible(0u, rows, rows, n, 1u) == 1u);
    assert(sm_view_first_visible(0u, rows + 4u, rows, n, 1u) == 5u);

    /* Staying inside the window moves nothing. */
    for (uint32_t selected = 3u; selected < 3u + rows; selected++)
        assert(sm_view_first_visible(3u, selected, rows, n, 1u) == 3u);

    /* Never a blank gap at the bottom, however the window got there. */
    assert(sm_view_first_visible(0u, n - 1u, rows, n, 1u) == n - rows);
    assert(sm_view_first_visible(n, n - 1u, rows, n, 1u) == n - rows);
    assert(sm_view_first_visible(0u, 500u, rows, n, 1u) == n - rows);

    /* Fewer items than rows: everything fits, so the window never moves. */
    for (uint32_t selected = 0; selected < 3u; selected++)
        assert(sm_view_first_visible(0u, selected, rows, 3u, 1u) == 0u);

    /* Degenerate inputs answer 0 instead of wrapping. */
    assert(sm_view_first_visible(0u, 0u, 0u, n, 1u) == 0u);
    assert(sm_view_first_visible(9u, 4u, rows, 0u, 1u) == 0u);
    assert(sm_view_focus(0u, 0u, n, 1u) == 0u);
    assert(sm_view_focus(4u, rows, 0u, 1u) == 0u);

    /* The grid snaps to whole pages, so a page is never split across two. */
    const uint32_t page = 4u;
    for (uint32_t selected = 0; selected < 40u; selected++) {
        /* The grid scrolls a row at a time and always starts on a row
           boundary. It used to snap to whole pages, which replaced all twelve
           covers on screen for a move that changed four tiles. */
        const uint32_t columns = 4u;
        uint32_t first = sm_view_first_visible(0u, selected, page, 40u, columns);
        assert(first % columns == 0u);
        assert(first <= selected && selected < first + page);
    }

    /* Focus lands the selection on screen with room on both sides. */
    for (uint32_t selected = 0; selected < n; selected++) {
        uint32_t first = sm_view_focus(selected, rows, n, 1u);
        assert(first <= selected && selected < first + rows);
        assert(first + rows <= n);
    }
    assert(sm_view_focus(0u, rows, n, 1u) == 0u);
    assert(sm_view_focus(2u, rows, n, 1u) == 0u);
    assert(sm_view_focus(50u, rows, n, 1u) == 46u);

    /* Every result is a window that can actually be drawn. */
    for (uint32_t count = 1u; count <= 20u; count++)
        for (uint32_t selected = 0; selected < count; selected++)
            for (uint32_t first = 0; first <= count + 2u; first++)
                for (uint32_t columns = 1u; columns <= 4u; columns += 3u) {
                    uint32_t out = sm_view_first_visible(first, selected, rows, count, columns);
                    assert(out <= selected);
                    assert(selected < out + rows);
                    /* A list must never leave blank rows above the end. A grid
                       may: its last row is usually short, and refusing to show
                       a half-full row would make the last few games
                       unreachable. */
                    if (columns == 1u) assert(out == 0u || out + rows <= count);
                    else assert(out == 0u || out + rows < count + columns);
                }

    /* A grid keeps the selection on screen at every position, always starts
       on a row boundary, and never scrolls past the last row. The bug this
       replaces: clamping in item units and rounding down could put the window
       one row above the row the cursor had just moved onto. */
    for (uint32_t columns = 2u; columns <= 5u; columns++) {
        for (uint32_t visible = columns; visible <= columns * 4u; visible += columns) {
            for (uint32_t count = 1u; count <= 40u; count++) {
                uint32_t first = 0u;
                for (uint32_t selected = 0; selected < count; selected++) {
                    first = sm_view_first_visible(first, selected, visible, count, columns);
                    assert(first % columns == 0u);
                    assert(first <= selected && selected < first + visible);
                    assert(first == 0u || first + visible <= count + columns - 1u);
                    assert(sm_view_focus(selected, visible, count, columns) % columns == 0u);
                }
                /* and walking back up stays put rather than jumping a page */
                for (uint32_t step = count; step-- > 0;) {
                    first = sm_view_first_visible(first, step, visible, count, columns);
                    assert(first <= step && step < first + visible);
                }
            }
        }
    }

    /* ---- coverflow: a turned card, not a squashed one ---------------- */
    {
        const int W = 34, NEAR = 68, FAR = 54, SRC = 96;

        /* Height falls from the near edge to the far one, and the ends are
           exactly the two heights asked for -- an off-by-one here shows up as
           a one-pixel step where two covers meet. */
        assert(sm_flow_column_height(NEAR, FAR, W, 0) == NEAR);
        assert(sm_flow_column_height(NEAR, FAR, W, W - 1) == FAR);
        for (int step = 1; step < W; step++)
            assert(sm_flow_column_height(NEAR, FAR, W, step) <=
                   sm_flow_column_height(NEAR, FAR, W, step - 1));

        /* The centre cover is face on: both edges the same height, so every
           column is the same height too. */
        for (int step = 0; step < 96; step++)
            assert(sm_flow_column_height(72, 72, 96, step) == 72);

        /* Sampling spans the whole source and never runs off it. */
        assert(sm_flow_source_column(SRC, W, FAR, 0, NEAR) == 0);
        assert(sm_flow_source_column(SRC, W, FAR, W - 1, FAR) == SRC - 1);
        for (int step = 0; step < W; step++) {
            int h = sm_flow_column_height(NEAR, FAR, W, step);
            int u = sm_flow_source_column(SRC, W, FAR, step, h);
            assert(u >= 0 && u < SRC);
        }

        /* Monotonic: a card never doubles back on itself. */
        for (int step = 1; step < W; step++) {
            int a = sm_flow_source_column(SRC, W, FAR, step - 1,
                        sm_flow_column_height(NEAR, FAR, W, step - 1));
            int b = sm_flow_source_column(SRC, W, FAR, step,
                        sm_flow_column_height(NEAR, FAR, W, step));
            assert(b >= a);
        }

        /* And the point of the whole thing: the sampling is NOT even. The far
           half of the card, which is further away, must cover more of the
           source than the near half -- that foreshortening is what reads as a
           turn rather than a squash. An affine stretch would split it evenly.
        */
        {
            int mid = W / 2;
            int at_mid = sm_flow_source_column(SRC, W, FAR, mid,
                             sm_flow_column_height(NEAR, FAR, W, mid));
            assert(at_mid < SRC / 2);
        }

        /* A face-on card has nothing to foreshorten, so it samples evenly.
           This is the control: if it failed, the test above would be
           measuring rounding rather than perspective. */
        {
            int mid = 96 / 2;
            int at_mid = sm_flow_source_column(96, 96, 72, mid, 72);
            assert(at_mid == mid);
        }

        /* Degenerate inputs return something drawable rather than dividing by
           zero: a cover one pixel wide, or a slot with no height, happens at
           the ends of the shelf. */
        assert(sm_flow_column_height(NEAR, FAR, 1, 0) == NEAR);
        assert(sm_flow_source_column(SRC, 1, FAR, 0, NEAR) == 0);
        assert(sm_flow_source_column(SRC, W, FAR, 5, 0) == 0);
        assert(sm_flow_source_column(0, W, FAR, 5, NEAR) == 0);
        /* Out-of-range steps clamp instead of walking off the source. */
        assert(sm_flow_source_column(SRC, W, FAR, -3, NEAR) == 0);
        assert(sm_flow_source_column(SRC, W, FAR, W + 99, FAR) == SRC - 1);
    }

    /* ---- the shelf is laid out either side of the selection --------- */
    {
        /* The real table. If these numbers change, the assertions below say
           what about the shape has to stay true, not what the numbers are. */
        static const sm_flow_step_t STEPS[] = {
            { 96, 72, 72, 0 }, { 34, 68, 54, -7 }, { 27, 60, 45, -4 },
            { 21, 52, 38, -3 },
        };
        const int HALF = 3, CENTRE = 160;
        int x[7];
        sm_flow_positions(CENTRE, STEPS, HALF, x);

        /* The selection is centred. */
        assert(x[HALF] == CENTRE - STEPS[0].width / 2);

        /* The first version of this walked the left-hand covers in the same
           direction as the right-hand ones, which laid all three on top of the
           centre cover and marching rightwards. Every left cover must end at
           or before the centre cover starts. */
        for (int depth = 1; depth <= HALF; depth++) {
            int slot = HALF - depth;
            assert(x[slot] + STEPS[depth].width <= x[HALF] + STEPS[0].width);
            assert(x[slot] < x[HALF]);
        }

        /* Left to right, strictly increasing, with no cover swallowed by its
           neighbour. */
        for (int slot = 1; slot < 2 * HALF + 1; slot++)
            assert(x[slot] > x[slot - 1]);

        /* Symmetric about the centre: the shelf leans neither way. */
        {
            int left_extent = CENTRE - x[0];
            int right_extent = (x[2 * HALF] + STEPS[HALF].width) - CENTRE;
            assert(left_extent == right_extent);
        }

        /* Each cover overlaps its inner neighbour by exactly the gap it asks
           for -- that overlap is what makes the row read as a shelf rather
           than a line of separate pictures. */
        for (int depth = 1; depth <= HALF; depth++) {
            int inner_right = x[HALF + depth - 1] + STEPS[depth - 1].width;
            assert(x[HALF + depth] == inner_right + STEPS[depth].gap);
            {
                int inner_left = x[HALF - depth + 1];
                assert(x[HALF - depth] + STEPS[depth].width
                       == inner_left - STEPS[depth].gap);
            }
        }

        /* And the whole shelf fits inside a 320-pixel safe area. */
        assert(x[0] >= 8);
        assert(x[2 * HALF] + STEPS[HALF].width <= 312);

        /* Degenerate: a shelf of one is just the selection. */
        {
            int only[1];
            sm_flow_positions(CENTRE, STEPS, 0, only);
            assert(only[0] == CENTRE - STEPS[0].width / 2);
        }
        sm_flow_positions(CENTRE, NULL, HALF, x);      /* must not crash */
        sm_flow_positions(CENTRE, STEPS, HALF, NULL);
    }

    /* ---- the shelf's glide ------------------------------------------ */
    {
        const float frame = 1.0f / 60.0f, smooth = 0.06f;
        sm_glide_t glide = {0.0f, 0.0f};
        float last = 0.0f;
        int frames = 0;

        /* One step: it starts at once, moves forward every frame, never
           passes the cover, and comes to rest on it within a fifth of a
           second or so. */
        assert(!sm_glide_moving(&glide, 0.0f));
        while (sm_glide_step(&glide, 1.0f, frame, smooth)) {
            assert(glide.pos > last || (frames == 0 && glide.pos > 0.0f));
            assert(glide.pos <= 1.0f);
            last = glide.pos;
            frames++;
            assert(frames < 40);
        }
        assert(glide.pos == 1.0f && glide.vel == 0.0f);
        assert(frames >= 6 && frames <= 20);

        /* It eases: the first frame moves less than the middle ones. */
        {
            sm_glide_t g = {0.0f, 0.0f};
            float first, second, third;
            sm_glide_step(&g, 1.0f, frame, smooth); first = g.pos;
            sm_glide_step(&g, 1.0f, frame, smooth); second = g.pos - first;
            sm_glide_step(&g, 1.0f, frame, smooth); third = g.pos - first - second;
            assert(first > 0.0f && second > first && third > 0.0f);
        }

        /* A second press mid-glide turns it, never sends it backwards. */
        {
            sm_glide_t g = {0.0f, 0.0f};
            float before;
            for (int i = 0; i < 3; i++) sm_glide_step(&g, 1.0f, frame, smooth);
            before = g.pos;
            sm_glide_step(&g, 2.0f, frame, smooth);
            assert(g.pos > before);
            while (sm_glide_step(&g, 2.0f, frame, smooth)) {}
            assert(g.pos == 2.0f);
        }

        /* Left is the mirror of right. */
        {
            sm_glide_t g = {5.0f, 0.0f};
            sm_glide_step(&g, 4.0f, frame, smooth);
            assert(g.pos < 5.0f && g.vel < 0.0f);
        }

        /* Time, not frames: two half frames land where one frame does, near
           enough, so a late frame moves the shelf further rather than slower. */
        {
            sm_glide_t a = {0.0f, 0.0f}, b = {0.0f, 0.0f};
            sm_glide_step(&a, 1.0f, frame, smooth);
            sm_glide_step(&b, 1.0f, frame / 2.0f, smooth);
            sm_glide_step(&b, 1.0f, frame / 2.0f, smooth);
            assert(a.pos - b.pos < 0.01f && b.pos - a.pos < 0.01f);
            sm_glide_t c = {0.0f, 0.0f};
            sm_glide_step(&c, 1.0f, frame * 2.0f, smooth);
            assert(c.pos > a.pos);
        }

        /* A long jump glides only its last stretch. */
        {
            sm_glide_t g = {0.0f, 0.0f};
            sm_glide_limit(&g, 50.0f, 2.0f);
            assert(g.pos == 48.0f);
            sm_glide_limit(&g, 10.0f, 2.0f);
            assert(g.pos == 12.0f);
            sm_glide_snap(&g, 7.0f);
            assert(g.pos == 7.0f && g.vel == 0.0f && !sm_glide_moving(&g, 7.0f));
        }

        /* Nothing to do is not a crash. */
        assert(!sm_glide_step(NULL, 1.0f, frame, smooth));
        sm_glide_snap(NULL, 0.0f);
        sm_glide_limit(NULL, 0.0f, 1.0f);
    }

    /* ---- held directions ------------------------------------------- */
    {
        sm_repeat_t r = {0};
        int fired = 0;
        /* The press itself moves once. */
        assert(sm_repeat_fire(&r, true, 1000u));
        /* Then nothing until the pause is over. */
        for (uint32_t t = 1016u; t < 1000u + SM_REPEAT_DELAY_MS; t += 16u)
            assert(!sm_repeat_fire(&r, true, t));
        assert(sm_repeat_fire(&r, true, 1000u + SM_REPEAT_DELAY_MS));
        /* Then steadily, and faster the longer it is held. */
        for (uint32_t t = 1316u; t < 2300u; t += 16u) fired += sm_repeat_fire(&r, true, t);
        assert(fired >= 6 && fired <= 10);          /* about eight a second */
        fired = 0;
        for (uint32_t t = 4000u; t < 5000u; t += 16u) fired += sm_repeat_fire(&r, true, t);
        assert(fired >= 18);                        /* a lot more */
        /* Letting go resets it: the next press is a fresh one. */
        assert(!sm_repeat_fire(&r, false, 5010u));
        assert(sm_repeat_fire(&r, true, 5026u));
        assert(!sm_repeat_fire(&r, true, 5042u));
        /* A clock that wraps keeps its order. */
        {
            sm_repeat_t w = {0};
            assert(sm_repeat_fire(&w, true, 0xFFFFFF00u));
            assert(!sm_repeat_fire(&w, true, 0xFFFFFF10u));
            assert(sm_repeat_fire(&w, true, 0xFFFFFF00u + SM_REPEAT_DELAY_MS));
        }
        assert(!sm_repeat_fire(NULL, true, 0u));
    }

    printf("list_view host checks passed\n");
    return 0;
}
