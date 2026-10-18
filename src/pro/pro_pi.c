/* SPDX-License-Identifier: AGPL-3.0-only */
/* PI reads that never share a cache line.

   A PI read is a DMA: it writes RDRAM behind the CPU's data cache. The
   usual way to do it is to write back and invalidate the destination's
   lines, start the DMA and wait for it, then read. That is only right if
   nothing loads those lines again before the DMA is done. A line that
   holds the destination and some other data can be loaded at any moment by
   whatever uses the other data -- an interrupt included -- and the CPU then
   reads the destination's old bytes from the cache.

   The krikzz library reads every cartridge register into a four-byte
   static, and libdragon updates its 64-bit tick count on every interrupt.
   When the linker puts the two in one line, a register read now and then
   returns the value before. If that register is the FIFO's fill level, the
   console reads a reply the MCU has not sent yet, every reply after it is
   out of step, and every card access fails until the console is turned
   off. Where the linker puts things changes with every build, so the rule
   is kept here, for every read: the DMA only ever writes whole lines that
   belong to the destination. A part line at either end goes through a
   line-aligned buffer of its own and is copied over by the CPU.

   On the bus side nothing changes for the library's own transfers: a read
   of up to SM_PRO_PI_BOUNCE bytes is still one DMA of the same length from
   the same address, which matters for the FIFO, where every word read
   takes a byte out. Only longer reads into cartridge memory, which can be
   read twice without harm, may be split.

   Writes need none of this: the source is written back first and the DMA
   only reads RDRAM, so a line loaded meanwhile changes nothing. pi_wr is
   the library's own, with the same buffer for a source that is not
   8-byte aligned. */
#include "pro_pi.h"
#include <libdragon.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#define LINE SM_PRO_PI_LINE
#define BOUNCE SM_PRO_PI_BOUNCE

_Static_assert((LINE & (LINE - 1u)) == 0, "a line is a power of two");
_Static_assert(BOUNCE % LINE == 0, "the buffer is whole lines");

static uint8_t bounce[BOUNCE] __attribute__((aligned(LINE)));

static bool owns_lines(const void *at, uint32_t len) {
    return ((uintptr_t)at & (LINE - 1u)) == 0 && (len & (LINE - 1u)) == 0;
}

static uint32_t words(uint32_t len) { return (len + 3u) & ~3u; }

/* Whole lines, straight into the destination. */
static void read_lines(uint8_t *dst, uint32_t pi, uint32_t len) {
    data_cache_hit_writeback_invalidate(dst, len);
    dma_read_raw_async(dst, pi, len);
    dma_wait();
}

/* Up to BOUNCE bytes through the buffer. Nothing else is in its lines, so
   nothing can load them while the DMA runs. */
static void read_bounced(uint8_t *dst, uint32_t pi, uint32_t len) {
    uint32_t bus = words(len);
    data_cache_hit_writeback_invalidate(bounce, bus);
    dma_read_raw_async(bounce, pi, bus);
    dma_wait();
    memcpy(dst, bounce, len);
}

void pi_rd(void *dst, unsigned long pi_address, unsigned long len) {
    uint8_t *out = dst;
    uint32_t pi = (uint32_t)pi_address & 0x1FFFFFFFu;
    uint32_t left = (uint32_t)len;
    uint32_t head, whole;

    if (!left) return;
    if (owns_lines(out, left)) {
        read_lines(out, pi, left);
        return;
    }
    if (left <= BOUNCE) {
        read_bounced(out, pi, left);
        return;
    }
    /* Longer than the buffer and not whole lines: only cartridge memory is
       read this way. The part line before the first boundary, the lines,
       then the part line after the last. */
    head = (LINE - ((uintptr_t)out & (LINE - 1u))) & (LINE - 1u);
    if (head) {
        read_bounced(out, pi, head);
        out += head; pi += head; left -= head;
    }
    whole = left & ~(LINE - 1u);
    if (whole) {
        read_lines(out, pi, whole);
        out += whole; pi += whole; left -= whole;
    }
    if (left) read_bounced(out, pi, left);
}

static void write_raw(const void *src, uint32_t pi, uint32_t len) {
    data_cache_hit_writeback(src, len);
    dma_write_raw_async(src, pi, len);
    dma_wait();
}

void pi_wr(void *src, unsigned long pi_address, unsigned long len) {
    const uint8_t *in = src;
    uint32_t pi = (uint32_t)pi_address & 0x1FFFFFFFu;
    uint32_t left = (uint32_t)len;

    if (!left) return;
    if (((uintptr_t)in & 7u) == 0) {
        write_raw(in, pi, left);
        return;
    }
    while (left) {
        uint32_t block = left < BOUNCE ? left : BOUNCE;
        memcpy(bounce, in, block);
        write_raw(bounce, pi, block);
        in += block; pi += block; left -= block;
    }
}
