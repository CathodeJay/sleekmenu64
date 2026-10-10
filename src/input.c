/* SPDX-License-Identifier: AGPL-3.0-only */
#include "input.h"
#include "list_view.h"
#include <libdragon.h>

void app_input_init(void) {
    joypad_init();
}

/* How far the stick has to lean, on libdragon's scale: a new stick reaches
   about 80 at the rim, a worn or third-party one less. Past STICK_ON is a
   walk, past STICK_RUN a run; each lets go a little lower than it took
   hold, so a hand resting near either line does not flicker across it,
   and STICK_OFF stays above the drift a worn stick rests at. */
enum { STICK_OFF = 20, STICK_ON = 28, STICK_RUN = 50, STICK_RUN_OFF = 44 };

static sm_lean_t lean_of(bool dpad, int along, const sm_repeat_t *was) {
    bool running = was->down && !was->part;
    if (dpad || along > (running ? STICK_RUN_OFF : STICK_RUN)) return SM_LEAN_FULL;
    if (along > (was->down ? STICK_OFF : STICK_ON)) return SM_LEAN_PART;
    return SM_LEAN_NONE;
}

sm_actions_t app_input_poll(void) {
    /* One per direction, the d-pad and the stick counting as the same hand. */
    static sm_repeat_t up, down, left, right;
    joypad_poll();
    joypad_buttons_t pressed = joypad_get_buttons_pressed(JOYPAD_PORT_1);
    joypad_buttons_t held = joypad_get_buttons_held(JOYPAD_PORT_1);
    joypad_inputs_t inputs = joypad_get_inputs(JOYPAD_PORT_1);
    uint32_t now = (uint32_t)get_ticks_ms();
    sm_lean_t lean_up = lean_of(held.d_up, inputs.stick_y, &up);
    sm_lean_t lean_down = lean_of(held.d_down, -inputs.stick_y, &down);
    sm_lean_t lean_left = lean_of(held.d_left, -inputs.stick_x, &left);
    sm_lean_t lean_right = lean_of(held.d_right, inputs.stick_x, &right);
    uint32_t step = 1u;
    sm_actions_t actions = {
        .up = sm_repeat_lean(&up, lean_up, now),
        .down = sm_repeat_lean(&down, lean_down, now),
        .left = sm_repeat_lean(&left, lean_left, now),
        .right = sm_repeat_lean(&right, lean_right, now),
        .page_up = pressed.l,
        .page_down = pressed.r,
        .select = pressed.a,
        .back = pressed.b,
        .filter = pressed.z,
        .genre_prev = pressed.c_left,
        .genre_next = pressed.c_right,
        .toggle_view = pressed.c_up,
        .favorite = pressed.c_down,
        .start = pressed.start,
    };
    if (actions.up && sm_repeat_stride(&up, now) > step) step = sm_repeat_stride(&up, now);
    if (actions.down && sm_repeat_stride(&down, now) > step) step = sm_repeat_stride(&down, now);
    if (actions.left && sm_repeat_stride(&left, now) > step) step = sm_repeat_stride(&left, now);
    if (actions.right && sm_repeat_stride(&right, now) > step) step = sm_repeat_stride(&right, now);
    actions.step = (uint16_t)step;
    return actions;
}
