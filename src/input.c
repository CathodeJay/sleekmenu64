/* SPDX-License-Identifier: AGPL-3.0-only */
#include "input.h"
#include <libdragon.h>

void app_input_init(void) {
    joypad_init();
}

sm_actions_t app_input_poll(void) {
    static bool stick_up_latched, stick_down_latched;
    joypad_poll();
    joypad_buttons_t pressed = joypad_get_buttons_pressed(JOYPAD_PORT_1);
    joypad_inputs_t inputs = joypad_get_inputs(JOYPAD_PORT_1);
    bool stick_up = inputs.stick_y > 50, stick_down = inputs.stick_y < -50;
    sm_actions_t actions = {
        .up = pressed.d_up || (stick_up && !stick_up_latched),
        .down = pressed.d_down || (stick_down && !stick_down_latched),
        .left = pressed.d_left,
        .right = pressed.d_right,
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
    stick_up_latched = stick_up;
    stick_down_latched = stick_down;
    return actions;
}
