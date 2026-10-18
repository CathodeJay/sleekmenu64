/* SPDX-License-Identifier: AGPL-3.0-only */
/* src/pro/pro_pi.c against a fake PI bus: cartridge memory, and a FIFO
   data register where every word read takes one byte out, as on the Pro.

   The rule under test is the one the console depends on: a DMA into the
   caller's memory only ever writes whole cache lines that are the caller's,
   so no other data in a shared line -- the tick count an interrupt updates,
   say -- can be loaded into the cache while the DMA runs. And the library's
   own transfers reach the bus exactly as before: one DMA, same address,
   same length. */
#include "pro/pro_pi.h"
#include <libdragon.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define MEM_PI 0x10000000u
#define MEM_SIZE 0x10000u
#define FIFO_PI 0x1F800000u
#define FIFO_WINDOW 0x800u

static uint8_t memory[MEM_SIZE];
static uint8_t fifo[4096];
static unsigned fifo_next;

typedef struct {
    bool read;
    uintptr_t ram;
    uint32_t pi;
    uint32_t len;
} dma_t;

static dma_t log_[8192];
static unsigned logged;
static bool pending;
static uintptr_t invalidated_at, written_back_at;
static unsigned long invalidated_len, written_back_len;

void data_cache_hit_writeback(volatile const void *addr, unsigned long length) {
    written_back_at = (uintptr_t)addr;
    written_back_len = length;
}

void data_cache_hit_writeback_invalidate(volatile void *addr, unsigned long length) {
    invalidated_at = (uintptr_t)addr;
    invalidated_len = length;
}

static bool covered(uintptr_t at, unsigned long length, uintptr_t ram, unsigned long len) {
    return ram >= at && ram + len <= at + length;
}

void dma_read_raw_async(void *ram_address, unsigned long pi_address, unsigned long len) {
    uintptr_t ram = (uintptr_t)ram_address;
    uint8_t *out = ram_address;
    assert(!pending && len > 0);
    /* The destination's lines were let go of before the DMA started. */
    assert(covered(invalidated_at, invalidated_len, ram, len));
    assert(logged < sizeof(log_) / sizeof(log_[0]));
    log_[logged++] = (dma_t){ true, ram, (uint32_t)pi_address, (uint32_t)len };
    if (pi_address >= FIFO_PI && pi_address < FIFO_PI + FIFO_WINDOW) {
        assert(len % 4u == 0);
        for (unsigned long i = 0; i < len; i += 4u) {
            uint32_t word = fifo[fifo_next++];
            memcpy(out + i, &word, 4);
        }
    } else {
        assert(pi_address >= MEM_PI && pi_address + len <= MEM_PI + MEM_SIZE);
        memcpy(out, memory + (pi_address - MEM_PI), len);
    }
    pending = true;
}

void dma_write_raw_async(const void *ram_address, unsigned long pi_address, unsigned long len) {
    uintptr_t ram = (uintptr_t)ram_address;
    assert(!pending && len > 0);
    assert(covered(written_back_at, written_back_len, ram, len));
    assert(pi_address >= MEM_PI && pi_address + len <= MEM_PI + MEM_SIZE);
    log_[logged++] = (dma_t){ false, ram, (uint32_t)pi_address, (uint32_t)len };
    memcpy(memory + (pi_address - MEM_PI), ram_address, len);
    pending = true;
}

void dma_wait(void) { pending = false; }

static uint8_t arena[40000] __attribute__((aligned(16)));

static void check_read(unsigned offset, uint32_t len, uint32_t pi_offset) {
    uint8_t *dst = arena + 64 + offset;
    uintptr_t from = (uintptr_t)dst, to = from + len;
    memset(arena, 0xA5, sizeof(arena));
    logged = 0;
    pi_rd(dst, 0xB0000000u + pi_offset, len);
    assert(!pending);
    assert(!memcmp(dst, memory + pi_offset, len));
    for (size_t i = 0; i < sizeof(arena); i++)
        if (arena + i < dst || arena + i >= dst + len) assert(arena[i] == 0xA5);
    for (unsigned i = 0; i < logged; i++) {
        const dma_t *d = &log_[i];
        bool in_arena = d->ram < (uintptr_t)(arena + sizeof(arena)) && d->ram + d->len > (uintptr_t)arena;
        assert(d->read && d->ram % SM_PRO_PI_LINE == 0);
        if (in_arena) {
            /* Straight into the caller's memory: whole lines, all of them
               the caller's. */
            assert(d->len % SM_PRO_PI_LINE == 0);
            assert(d->ram >= from && d->ram + d->len <= to);
        } else {
            assert(d->len <= SM_PRO_PI_BOUNCE);
        }
    }
    if (len <= SM_PRO_PI_BOUNCE) {
        /* On the bus, one DMA as before. */
        assert(logged == 1);
        assert(log_[0].pi == MEM_PI + pi_offset && log_[0].len == ((len + 3u) & ~3u));
    }
}

int main(void) {
    static const uint32_t lengths[] = {
        1, 2, 3, 4, 5, 8, 12, 15, 16, 17, 31, 32, 33, 64, 100, 508, 511, 512,
        513, 516, 1000, 1024, 4096, 4108, 16380, 16384,
    };
    for (size_t i = 0; i < sizeof(memory); i++) memory[i] = (uint8_t)(i * 7u + (i >> 8));

    /* Every alignment against every length, from memory. */
    for (unsigned offset = 0; offset < 32u; offset++)
        for (size_t l = 0; l < sizeof(lengths) / sizeof(lengths[0]); l++)
            check_read(offset, lengths[l], 0x40u + (offset & ~1u));

    /* Whole lines of the caller's own go straight in, in one DMA. */
    logged = 0;
    pi_rd(arena, MEM_PI, 4096);
    assert(logged == 1 && log_[0].ram == (uintptr_t)arena && log_[0].len == 4096);

    /* A register read into a four-byte static that shares its line: the
       value arrives, the DMA never touches that line, and its neighbours
       are as they were. */
    {
        static struct { uint32_t before[2]; uint32_t rx; uint32_t after; } line
            __attribute__((aligned(16))) = { { 0x11111111u, 0x22222222u }, 0, 0x33333333u };
        uint32_t value = 0x00000C0Bu;
        memcpy(memory + 0x200, &value, 4);
        logged = 0;
        pi_rd(&line.rx, 0xB0000000u + 0x200u, 4);
        assert(line.rx == value);
        assert(line.before[0] == 0x11111111u && line.before[1] == 0x22222222u && line.after == 0x33333333u);
        assert(logged == 1 && log_[0].len == 4 && log_[0].pi == MEM_PI + 0x200u);
        assert(log_[0].ram + 4 <= (uintptr_t)&line || log_[0].ram >= (uintptr_t)(&line + 1));
    }

    /* The FIFO: the library reads it 1 to 128 words at a time into a buffer
       aligned to 512. Each read is one DMA from the register, of exactly
       those words, and takes exactly that many bytes out, in order. */
    {
        static uint32_t buff[128] __attribute__((aligned(512)));
        unsigned expected = 0;
        for (size_t i = 0; i < sizeof(fifo); i++) fifo[i] = (uint8_t)(i * 13u + 5u);
        fifo_next = 0;
        for (uint32_t block = 1; block <= 128u && fifo_next + block <= sizeof(fifo); block++) {
            logged = 0;
            pi_rd(buff, 0xBF800000u, block * 4u);
            assert(logged == 1 && log_[0].pi == FIFO_PI && log_[0].len == block * 4u);
            assert(fifo_next == expected + block);
            for (uint32_t i = 0; i < block; i++) assert(buff[i] == fifo[expected + i]);
            expected += block;
        }
    }

    /* Nothing asked, nothing on the bus. */
    logged = 0;
    pi_rd(arena + 3, MEM_PI, 0);
    pi_wr(arena + 3, MEM_PI, 0);
    assert(logged == 0);

    /* Writes: an aligned source goes as it is, written back first. */
    {
        uint8_t *src = arena + 8;
        for (unsigned i = 0; i < 40u; i++) src[i] = (uint8_t)(200u - i);
        logged = 0;
        pi_wr(src, 0xB0000000u + 0x1000u, 40);
        assert(logged == 1 && !log_[0].read && log_[0].ram == (uintptr_t)src && log_[0].len == 40);
        assert(!memcmp(memory + 0x1000, src, 40));
    }
    /* One that is not 8-byte aligned is copied through the buffer. */
    {
        uint8_t *src = arena + 1;
        for (unsigned i = 0; i < 600u; i++) src[i] = (uint8_t)(i ^ 0x5Au);
        logged = 0;
        pi_wr(src, MEM_PI + 0x2000u, 600);
        assert(logged == 2 && log_[0].len == 512 && log_[1].len == 88);
        assert(log_[0].ram % 8u == 0 && log_[1].pi == MEM_PI + 0x2000u + 512u);
        assert(!memcmp(memory + 0x2000, src, 600));
    }

    puts("pro_pi checks passed");
    return 0;
}
