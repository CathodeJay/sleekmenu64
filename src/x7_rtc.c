/* SPDX-License-Identifier: AGPL-3.0-only */
#include "x7_rtc.h"
#include "save_type.h"

#ifdef __mips__
#include <libdragon.h>
#include <stdint.h>
#include <string.h>

/* Separate from libcart's SD controller and direction latch. OS 3.11 reads
   the DS1337, writes Joybus RTC blocks, then enables GAM_CFG bit 0x1000.
   See docs/X7_RTC.md and tools/trace_x7_rtc.py for the observed protocol. */
#define X7_I2C_CMD 0x1F800018u
#define X7_I2C_DAT 0x1F80001Cu
#define X7_I2C_POLL_LIMIT 10000u

static bool i2c_wait(void) {
    for (unsigned i = 0; i < X7_I2C_POLL_LIMIT; i++)
        if (!(io_read(X7_I2C_CMD) & 0x80u)) return true;
    return false;
}

static bool i2c_start(void) {
    uint32_t previous = io_read(X7_I2C_CMD);
    io_write(X7_I2C_CMD, 0x20u);
    io_write(X7_I2C_DAT, 0xFFu);
    if (!i2c_wait()) return false;
    io_write(X7_I2C_CMD, previous | 0x11u);
    return true;
}

static bool i2c_end(void) {
    io_write(X7_I2C_CMD, 0x30u);
    io_write(X7_I2C_DAT, 0xFFu);
    return i2c_wait();
}

static bool i2c_command(uint8_t value) {
    io_write(X7_I2C_DAT, value);
    return i2c_wait() && !(io_read(X7_I2C_CMD) & 1u);
}

static bool read_clock(uint8_t raw[16]) {
    bool ok = i2c_start() && i2c_command(0xD0u) && i2c_command(0u) &&
        i2c_start() && i2c_command(0xD1u);
    if (ok) {
        io_write(X7_I2C_CMD, io_read(X7_I2C_CMD) | 0x10u);
        for (unsigned i = 0; i < 16u; i++) {
            io_write(X7_I2C_DAT, 0xFFu);
            if (!i2c_wait()) { ok = false; break; }
            raw[i] = (uint8_t)io_read(X7_I2C_DAT);
        }
    }
    if (ok) {
        io_write(X7_I2C_CMD, io_read(X7_I2C_CMD) | 0x11u);
        /* Terminate the read with NACK, as the stock OS does. */
        io_write(X7_I2C_DAT, 0xFFu);
        ok = i2c_wait();
    }
    bool ended = i2c_end();
    return ok && ended;
}

static bool write_block(uint8_t block, const uint8_t data[8]) {
    uint64_t input_words[8] = {0}, output_words[8] = {0};
    uint8_t *input = (uint8_t *)input_words;
    uint8_t *output = (uint8_t *)output_words;
    /* Skip controller ports 0..3; send RTC write on cartridge port 4. */
    input[4] = 10u;
    input[5] = 1u;
    input[6] = 8u;
    input[7] = block;
    memcpy(input + 8, data, 8);
    input[16] = 0xFFu;
    input[17] = 0xFEu;
    input[63] = 1u;
    joybus_exec(input_words, output_words);
    /* The RTC status byte can report "stopped" during this sequence and
       some implementations leave it untouched. Like the stock launch path,
       do not treat it as an error code; only reject PIF transport errors. */
    return !(output[5] & 0xC0u);
}

bool sm_x7_rtc_prepare(unsigned config) {
    if (!(config & SM_SAVE_CFG_RTC)) return true;
    uint8_t raw[16], time[8];
    static const uint8_t stop[8] = {0, 4, 0, 0, 0, 0, 0, 0};
    static const uint8_t start[8] = {3, 0, 0, 0, 0, 0, 0, 0};
    if (!read_clock(raw)) return false;
    /* DS1337 -> Joybus: swap day-of-month and weekday, mask the same
       fields as OS 3.11, and use century 1 (2000..2099). */
    time[0] = raw[0];
    time[1] = raw[1];
    time[2] = raw[2] & 0x3Fu;
    time[3] = raw[4];
    time[4] = raw[3] & 7u;
    time[5] = raw[5] & 0x1Fu;
    time[6] = raw[6];
    time[7] = 1u;
    bool stopped = write_block(0u, stop);
    bool written = stopped && write_block(2u, time);
    /* Always try to restart the emulated clock, including after a failed
       stop/data command. No transaction here writes the physical DS1337. */
    bool started = write_block(0u, start);
    return stopped && written && started;
}
#endif
