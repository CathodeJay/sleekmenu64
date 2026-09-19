/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef TEST_X7_LIBDRAGON_H
#define TEST_X7_LIBDRAGON_H
#include <stdbool.h>
#include <stdint.h>
uint32_t io_read(uint32_t address);
void io_write(uint32_t address, uint32_t value);
void joybus_exec(const void *input, void *output);
bool debug_init_sdfs(const char *prefix, int partition);
#endif
