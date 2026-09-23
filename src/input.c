/* SPDX-License-Identifier: AGPL-3.0-only */
#include "input.h"
#include "list_view.h"
#include <libdragon.h>

void app_input_init(void) {
    joypad_init();
}

/* How far the stick has to lean to count as a direction: past its dead zone
   and past the drift a worn stick rests at, well short of the rim. */
enum { STICK_LEAN = 50 };

sm_actions_t app_input_poll(void) {
    /* One per direction, the d-pad and the stick counting as the same hand. */
    static sm_repeat_t up, down, left, right;
    joypad_poll();
    joypad_buttons_t pressed = joypad_get_buttons_pressed(JOYPAD_PORT_1);
    joypad_buttons_t held = joypad_get_buttons_held(JOYPAD_PORT_1);
    joypad_inputs_t inputs = joypad_get_inputs(JOYPAD_PORT_1);
    uint32_t now = (uint32_t)get_ticks_ms();
    sm_actions_t actions = {
        .up = sm_repeat_fire(&up, held.d_up || inputs.stick_y > STICK_LEAN, now),
        .down = sm_repeat_fire(&down, held.d_down || inputs.stick_y < -STICK_LEAN, now),
        .left = sm_repeat_fire(&left, held.d_left || inputs.stick_x < -STICK_LEAN, now),
        .right = sm_repeat_fire(&right, held.d_right || inputs.stick_x > STICK_LEAN, now),
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
    return actions;
}
