/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_PICTURE_H
#define SLEEKMENU_PICTURE_H

#include <stdint.h>

/* A picture made smaller properly: each output pixel is the average of the
   source pixels it covers, each weighted by how much of it is covered. The
   alternative, the one source pixel nearest each output pixel, drops one
   column and one row in three going from 96 to 64 pixels wide, and a box
   shrunk that way reads as low resolution.

   RGBA16 in and out; strides in pixels. The output must be no larger than
   the source in either direction: this shrinks, it does not enlarge. A
   pixel is opaque when at least half of what it covers is. */
void sm_picture_shrink(const uint16_t *src, int src_w, int src_h, int src_stride,
    uint16_t *dst, int dst_w, int dst_h, int dst_stride);

#endif
