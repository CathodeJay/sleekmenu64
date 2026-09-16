/* SPDX-License-Identifier: AGPL-3.0-only */
#include "x7_rtc.h"
#include "x7_save_reg.h"
#include "save_type.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CMD 0x1F800018u
#define DAT 0x1F80001Cu
static struct { uint32_t address, value; } writes[128];
static unsigned write_count, read_count, data_at, packet_count, command_at;
static uint8_t packets[4][64];
static uint8_t raw[16];
static uint32_t mode, last_data;
static uint32_t game_config;
static int nack_command, fail_packet, fail_busy_at;
static bool timeout;
static uint8_t rtc_status;

static void reset(void) {
    write_count = read_count = data_at = packet_count = command_at = 0;
    mode = last_data = 0;
    game_config = 0;
    nack_command = fail_packet = fail_busy_at = -1;
    timeout = false;
    rtc_status = 0;
    memset(raw, 0, sizeof(raw));
    /* Same synthetic DS1337 sample used in the stock OS trace. */
    const uint8_t sample[] = {0x58, 0x59, 0x23, 4, 0x31, 0x12, 0x26};
    memcpy(raw, sample, sizeof(sample));
}

uint32_t io_read(uint32_t address) {
    read_count++;
    if (address == CMD) {
        if (timeout || (int)write_count == fail_busy_at) return 0x80u;
        if (mode == 0x11u && (int)command_at == nack_command) return 1u;
        return 0;
    }
    assert(address == DAT && data_at < 16u);
    return raw[data_at++];
}

void io_write(uint32_t address, uint32_t value) {
    assert(write_count < 128u);
    writes[write_count].address = address;
    writes[write_count++].value = value;
    if (address == CMD) mode = value;
    else if (address == DAT) {
        last_data = value;
        if (mode == 0x11u) command_at++;
    } else {
        assert(address == SM_X7_REG_GAM_CFG);
        game_config = value;
    }
}

void joybus_exec(const void *input, void *output) {
    assert(packet_count < 4u);
    memcpy(packets[packet_count], input, 64);
    memset(output, 0, 64);
    ((uint8_t *)output)[16] = rtc_status;
    /* An RTC-disabled cartridge does not answer the RTC commands. This
       models SleekMenu's entry state, which the old stub omitted. */
    if (!(game_config & SM_X7_GAM_CFG_RTC) || (int)packet_count == fail_packet)
        ((uint8_t *)output)[5] = 0x80;
    packet_count++;
}

static void assert_packet(unsigned n, unsigned block, const uint8_t data[8]) {
    uint8_t expected[64] = {0};
    expected[4] = 10;
    expected[5] = 1;
    expected[6] = 8;
    expected[7] = block;
    memcpy(expected + 8, data, 8);
    expected[16] = 0xFF;
    expected[17] = 0xFE;
    expected[63] = 1;
    assert(!memcmp(expected, packets[n], sizeof(expected)));
}

int main(void) {
    /* Every non-RTC config leaves the clock untouched, including after a
       preceding RTC launch and when EEPROM is selected. */
    for (unsigned type = 0; type <= SM_SAVE_TYPE_MAX; type++) {
        for (unsigned config = 0; config <= SM_SAVE_CFG_MAX; config++) {
            reset();
            assert(sm_x7_rtc_prepare(config));
            assert(game_config == 0);
            if (!(config & SM_SAVE_CFG_RTC))
                assert(write_count == 0 && read_count == 0 && packet_count == 0);
            sm_x7_apply_launch_config((sm_save_type_t)type, config);
            assert(writes[write_count - 1].address == SM_X7_REG_GAM_CFG);
            assert(writes[write_count - 1].value ==
                   (type | ((config & SM_SAVE_CFG_RTC) ? 0x1000u : 0u)));
            sm_x7_apply_save_type((sm_save_type_t)type);
            assert(writes[write_count - 1].value == type);
        }
    }

    reset();
    assert(sm_x7_rtc_prepare(SM_SAVE_CFG_RTC));
    assert(data_at == 16 && packet_count == 3);
    /* These three packets are the output of OS 3.11's real launch routine
       under tools/trace_x7_rtc.py, not values inferred from this driver. */
    const uint8_t stop[] = {0, 4, 0, 0, 0, 0, 0, 0};
    const uint8_t time[] = {0x58, 0x59, 0x23, 0x31, 4, 0x12, 0x26, 1};
    const uint8_t start[] = {3, 0, 0, 0, 0, 0, 0, 0};
    assert_packet(0, 0, stop);
    assert_packet(1, 2, time);
    assert_packet(2, 0, start);
    /* Start/address/pointer, repeated start/read address, read mode, 16
       bytes, write mode/NACK, stop. No writes to the physical clock. */
    const uint32_t prefix[][2] = {
        {CMD,0x20}, {DAT,0xFF}, {CMD,0x11}, {DAT,0xD0}, {DAT,0},
        {CMD,0x20}, {DAT,0xFF}, {CMD,0x11}, {DAT,0xD1}, {CMD,0x10}
    };
    assert(write_count == 32);
    for (unsigned i = 0; i < 10; i++) {
        assert(writes[i].address == prefix[i][0]);
        assert(writes[i].value == prefix[i][1]);
    }
    for (unsigned i = 10; i < 26; i++)
        assert(writes[i].address == DAT && writes[i].value == 0xFF);
    assert(writes[26].address == CMD && writes[26].value == 0x11);
    assert(writes[27].address == DAT && writes[27].value == 0xFF);
    assert(writes[28].address == CMD && writes[28].value == 0x30);
    assert(writes[29].address == DAT && writes[29].value == 0xFF);
    assert(writes[30].address == SM_X7_REG_GAM_CFG && writes[30].value == 0x1000);
    assert(writes[31].address == SM_X7_REG_GAM_CFG && writes[31].value == 0);

    /* A stopped clock (or an untouched status response) is not a failed
       write. PIF transport error flags are checked separately below. */
    reset();
    rtc_status = 0x80;
    assert(sm_x7_rtc_prepare(SM_SAVE_CFG_RTC));
    reset();
    rtc_status = 0xFF;
    assert(sm_x7_rtc_prepare(SM_SAVE_CFG_RTC));

    for (int command = 1; command <= 3; command++) {
        reset();
        nack_command = command;
        assert(!sm_x7_rtc_prepare(SM_SAVE_CFG_RTC));
        assert(strstr(sm_x7_rtc_error(), "NACK"));
        assert(game_config == 0);
        assert(packet_count == 0);
        assert(writes[write_count - 2].address == CMD);
        assert(writes[write_count - 2].value == 0x30);
    }
    reset();
    timeout = true;
    assert(!sm_x7_rtc_prepare(SM_SAVE_CFG_RTC));
    assert(strstr(sm_x7_rtc_error(), "timeout"));
    assert(read_count <= 20002 && packet_count == 0);
    const int polled[] = {2, 4, 5, 7, 9, 11, 12, 13, 14, 15, 16, 17,
                          18, 19, 20, 21, 22, 23, 24, 25, 26, 28, 30};
    for (unsigned i = 0; i < sizeof(polled) / sizeof(polled[0]); i++) {
        reset();
        fail_busy_at = polled[i];
        assert(!sm_x7_rtc_prepare(SM_SAVE_CFG_RTC));
        assert(packet_count == 0 && read_count < 21000);
    }
    for (int packet = 0; packet < 3; packet++) {
        reset();
        fail_packet = packet;
        assert(!sm_x7_rtc_prepare(SM_SAVE_CFG_RTC));
        assert_packet(packet_count - 1, 0, start);
        assert(game_config == 0);
        const char *step[] = {"stop", "time write", "start"};
        assert(strstr(sm_x7_rtc_error(), step[packet]));
    }
    puts("X7 RTC: stock OS protocol, per-game flags, and failure paths passed");
    return 0;
}
