/* SPDX-License-Identifier: AGPL-3.0-only */
#include "buttons.h"
#include <stdint.h>
#include <string.h>

/* Nine rows of nine pixels, the leftmost in bit 8. */
typedef uint16_t mask_t[SM_BUTTON_SIZE];

#define ROW(a, b, c, d, e, f, g, h, i) \
    (uint16_t)((a) << 8 | (b) << 7 | (c) << 6 | (d) << 5 | (e) << 4 | (f) << 3 | (g) << 2 | (h) << 1 | (i))

/* A face button: round. */
static const mask_t DISC = {
    ROW(0,0,1,1,1,1,1,0,0),
    ROW(0,1,1,1,1,1,1,1,0),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(0,1,1,1,1,1,1,1,0),
    ROW(0,0,1,1,1,1,1,0,0),
};
/* A shoulder button or the trigger: a key with its corners off. */
static const mask_t KEY = {
    ROW(0,1,1,1,1,1,1,1,0),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(0,1,1,1,1,1,1,1,0),
};
static const mask_t CROSS = {
    ROW(0,0,0,1,1,1,0,0,0),
    ROW(0,0,0,1,1,1,0,0,0),
    ROW(0,0,0,1,1,1,0,0,0),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(1,1,1,1,1,1,1,1,1),
    ROW(0,0,0,1,1,1,0,0,0),
    ROW(0,0,0,1,1,1,0,0,0),
    ROW(0,0,0,1,1,1,0,0,0),
};
/* The D-pad's arms, for the two pictures that mean one axis of it. */
static const mask_t ARMS_VERTICAL = {
    ROW(0,0,0,1,1,1,0,0,0),
    ROW(0,0,0,1,1,1,0,0,0),
    ROW(0,0,0,1,1,1,0,0,0),
    0, 0, 0,
    ROW(0,0,0,1,1,1,0,0,0),
    ROW(0,0,0,1,1,1,0,0,0),
    ROW(0,0,0,1,1,1,0,0,0),
};
static const mask_t ARMS_HORIZONTAL = {
    0, 0, 0,
    ROW(1,1,1,0,0,0,1,1,1),
    ROW(1,1,1,0,0,0,1,1,1),
    ROW(1,1,1,0,0,0,1,1,1),
    0, 0, 0,
};

/* What is written on a button: a letter three pixels by five, or an arrow. */
static const mask_t INK[SM_BUTTON_COUNT] = {
    [SM_BUTTON_A] = { 0, 0,
        ROW(0,0,0,0,1,0,0,0,0),
        ROW(0,0,0,1,0,1,0,0,0),
        ROW(0,0,0,1,1,1,0,0,0),
        ROW(0,0,0,1,0,1,0,0,0),
        ROW(0,0,0,1,0,1,0,0,0), 0, 0 },
    [SM_BUTTON_B] = { 0, 0,
        ROW(0,0,0,1,1,0,0,0,0),
        ROW(0,0,0,1,0,1,0,0,0),
        ROW(0,0,0,1,1,0,0,0,0),
        ROW(0,0,0,1,0,1,0,0,0),
        ROW(0,0,0,1,1,0,0,0,0), 0, 0 },
    [SM_BUTTON_START] = { 0, 0,
        ROW(0,0,0,0,1,1,0,0,0),
        ROW(0,0,0,1,0,0,0,0,0),
        ROW(0,0,0,0,1,0,0,0,0),
        ROW(0,0,0,0,0,1,0,0,0),
        ROW(0,0,0,1,1,0,0,0,0), 0, 0 },
    [SM_BUTTON_C_UP] = { 0, 0, 0,
        ROW(0,0,0,0,1,0,0,0,0),
        ROW(0,0,0,1,1,1,0,0,0),
        ROW(0,0,1,1,1,1,1,0,0), 0, 0, 0 },
    [SM_BUTTON_C_DOWN] = { 0, 0, 0,
        ROW(0,0,1,1,1,1,1,0,0),
        ROW(0,0,0,1,1,1,0,0,0),
        ROW(0,0,0,0,1,0,0,0,0), 0, 0, 0 },
    [SM_BUTTON_C_LEFT] = { 0, 0,
        ROW(0,0,0,0,0,1,0,0,0),
        ROW(0,0,0,0,1,1,0,0,0),
        ROW(0,0,0,1,1,1,0,0,0),
        ROW(0,0,0,0,1,1,0,0,0),
        ROW(0,0,0,0,0,1,0,0,0), 0, 0 },
    [SM_BUTTON_C_RIGHT] = { 0, 0,
        ROW(0,0,0,1,0,0,0,0,0),
        ROW(0,0,0,1,1,0,0,0,0),
        ROW(0,0,0,1,1,1,0,0,0),
        ROW(0,0,0,1,1,0,0,0,0),
        ROW(0,0,0,1,0,0,0,0,0), 0, 0 },
    [SM_BUTTON_Z] = { 0, 0,
        ROW(0,0,0,1,1,1,0,0,0),
        ROW(0,0,0,0,0,1,0,0,0),
        ROW(0,0,0,0,1,0,0,0,0),
        ROW(0,0,0,1,0,0,0,0,0),
        ROW(0,0,0,1,1,1,0,0,0), 0, 0 },
    [SM_BUTTON_L] = { 0, 0,
        ROW(0,0,0,1,0,0,0,0,0),
        ROW(0,0,0,1,0,0,0,0,0),
        ROW(0,0,0,1,0,0,0,0,0),
        ROW(0,0,0,1,0,0,0,0,0),
        ROW(0,0,0,1,1,1,0,0,0), 0, 0 },
    [SM_BUTTON_R] = { 0, 0,
        ROW(0,0,0,1,1,0,0,0,0),
        ROW(0,0,0,1,0,1,0,0,0),
        ROW(0,0,0,1,1,0,0,0,0),
        ROW(0,0,0,1,0,1,0,0,0),
        ROW(0,0,0,1,0,1,0,0,0), 0, 0 },
};

typedef struct {
    const mask_t *body;
    unsigned char body_rgb[3];
    const mask_t *ink;          /* over the body; NULL for none */
    unsigned char ink_rgb[3];
} look_t;

#define WHITE {255, 255, 255}
#define BLUE {36, 104, 228}
#define GREEN {34, 160, 70}
#define RED {214, 44, 44}
#define YELLOW {246, 206, 48}
#define YELLOW_INK {48, 36, 0}
#define GREY {176, 182, 194}
#define GREY_INK {24, 28, 36}
#define PAD {112, 118, 130}
#define PAD_LIT {236, 238, 242}

static const look_t LOOKS[SM_BUTTON_COUNT] = {
    [SM_BUTTON_A] = { &DISC, BLUE, &INK[SM_BUTTON_A], WHITE },
    [SM_BUTTON_B] = { &DISC, GREEN, &INK[SM_BUTTON_B], WHITE },
    [SM_BUTTON_START] = { &DISC, RED, &INK[SM_BUTTON_START], WHITE },
    [SM_BUTTON_C_UP] = { &DISC, YELLOW, &INK[SM_BUTTON_C_UP], YELLOW_INK },
    [SM_BUTTON_C_DOWN] = { &DISC, YELLOW, &INK[SM_BUTTON_C_DOWN], YELLOW_INK },
    [SM_BUTTON_C_LEFT] = { &DISC, YELLOW, &INK[SM_BUTTON_C_LEFT], YELLOW_INK },
    [SM_BUTTON_C_RIGHT] = { &DISC, YELLOW, &INK[SM_BUTTON_C_RIGHT], YELLOW_INK },
    [SM_BUTTON_Z] = { &KEY, GREY, &INK[SM_BUTTON_Z], GREY_INK },
    [SM_BUTTON_L] = { &KEY, GREY, &INK[SM_BUTTON_L], GREY_INK },
    [SM_BUTTON_R] = { &KEY, GREY, &INK[SM_BUTTON_R], GREY_INK },
    [SM_BUTTON_DPAD] = { &CROSS, PAD_LIT, NULL, WHITE },
    [SM_BUTTON_DPAD_VERTICAL] = { &CROSS, PAD, &ARMS_VERTICAL, PAD_LIT },
    [SM_BUTTON_DPAD_HORIZONTAL] = { &CROSS, PAD, &ARMS_HORIZONTAL, PAD_LIT },
};

int sm_button_from_code(char code) {
    switch (code) {
    case 'A': return SM_BUTTON_A;
    case 'B': return SM_BUTTON_B;
    case 'S': return SM_BUTTON_START;
    case '^': return SM_BUTTON_C_UP;
    case 'v': return SM_BUTTON_C_DOWN;
    case '<': return SM_BUTTON_C_LEFT;
    case '>': return SM_BUTTON_C_RIGHT;
    case 'Z': return SM_BUTTON_Z;
    case 'L': return SM_BUTTON_L;
    case 'R': return SM_BUTTON_R;
    case '+': return SM_BUTTON_DPAD;
    case '|': return SM_BUTTON_DPAD_VERTICAL;
    case '-': return SM_BUTTON_DPAD_HORIZONTAL;
    default: return -1;
    }
}

const unsigned char *sm_button_rgb(sm_button_t button) {
    return LOOKS[(unsigned)button < SM_BUTTON_COUNT ? button : SM_BUTTON_A].body_rgb;
}

/* A mask in one colour, a box per run of set pixels. */
static void draw_mask(surface_t *surface, int x, int y, const mask_t *mask, const unsigned char *rgb) {
    uint32_t colour = graphics_make_color(rgb[0], rgb[1], rgb[2], 255);
    int row, column;
    for (row = 0; row < SM_BUTTON_SIZE; row++) {
        uint16_t bits = (*mask)[row];
        for (column = 0; column < SM_BUTTON_SIZE; column++) {
            int start = column;
            while (column < SM_BUTTON_SIZE && (bits & (1u << (SM_BUTTON_SIZE - 1 - column)))) column++;
            if (column > start) graphics_draw_box(surface, x + start, y + row, column - start, 1, colour);
        }
    }
}

void sm_button_draw(surface_t *surface, int x, int y, sm_button_t button) {
    const look_t *look;
    if ((unsigned)button >= SM_BUTTON_COUNT) return;
    look = &LOOKS[button];
    draw_mask(surface, x, y, look->body, look->body_rgb);
    if (look->ink) draw_mask(surface, x, y, look->ink, look->ink_rgb);
}

/* One walk for both: with no surface it only measures. */
static int walk(surface_t *surface, int x, int y, int max_x, const char *text) {
    char run[64];
    size_t used = 0;
    int run_x = x;
    bool after_space = false;
    if (!text) return x;
    while (*text) {
        int button = (text[0] == '{' && text[1] && text[2] == '}') ? sm_button_from_code(text[1]) : -1;
        if (button >= 0) {
            int lead = after_space ? SM_BUTTON_LEAD : 0;
            if (x + lead + SM_BUTTON_SIZE > max_x) break;
            if (used) {
                run[used] = '\0';
                if (surface) graphics_draw_text(surface, run_x, y, run);
                used = 0;
            }
            x += lead;
            if (surface) sm_button_draw(surface, x, y - 1, (sm_button_t)button);
            x += SM_BUTTON_SIZE + SM_BUTTON_GAP;
            run_x = x;
            after_space = false;
            text += 3;
            continue;
        }
        if (x + SM_HINT_CHAR_WIDTH > max_x || used + 1 >= sizeof(run)) break;
        run[used++] = *text;
        after_space = *text == ' ';
        x += SM_HINT_CHAR_WIDTH;
        text++;
    }
    if (used) {
        run[used] = '\0';
        if (surface) graphics_draw_text(surface, run_x, y, run);
    }
    return x;
}

int sm_hints_width(const char *text) {
    return walk(NULL, 0, 0, 1 << 20, text);
}

int sm_hints_draw(surface_t *surface, int x, int y, int max_x, const char *text) {
    return walk(surface, x, y, max_x, text);
}
