/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_PRO_PI_H
#define SLEEKMENU_PRO_PI_H

/* The two PI transfers the vendored krikzz library is built on, declared
   exactly as its n64.h declares them. They are defined in pro_pi.c, which
   is compiled in place of the library's own n64.c (see pro_pi.c for why).

   pi_rd copies `len` bytes from the PI bus at `pi_address` into `dst`;
   pi_wr copies `len` bytes from `src` to the PI bus. A length that is not
   a multiple of four is rounded up on the bus side, as the library's own
   version does: every caller in the library passes whole words. */

void pi_rd(void *dst, unsigned long pi_address, unsigned long len);
void pi_wr(void *src, unsigned long pi_address, unsigned long len);

/* The size of a data cache line, and of the buffer the ends of a read go
   through. Every transfer the library makes over the FIFO is at most this
   long, so each still reaches the bus as the one DMA it always was. */
#define SM_PRO_PI_LINE 16u
#define SM_PRO_PI_BOUNCE 512u

#endif
