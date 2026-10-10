/* SPDX-License-Identifier: AGPL-3.0-only */
#include "picture.h"

#include <stddef.h>

/* Coordinates are kept as whole numbers by measuring both pictures in the
   same small unit: a source pixel is dst pixels long and an output pixel is
   src pixels long, so output pixel o covers [o * src, (o + 1) * src) and
   source pixel s covers [s * dst, (s + 1) * dst). The overlap of the two is
   the weight, and the weights of one output pixel add up to src along each
   axis. */
void sm_picture_shrink(const uint16_t *src, int src_w, int src_h, int src_stride,
    uint16_t *dst, int dst_w, int dst_h, int dst_stride) {
    uint32_t total;
    if (!src || !dst || src_w <= 0 || src_h <= 0 || dst_w <= 0 || dst_h <= 0 ||
        dst_w > src_w || dst_h > src_h || src_stride < src_w || dst_stride < dst_w)
        return;
    total = (uint32_t)src_w * (uint32_t)src_h;
    for (uint32_t oy = 0; oy < (uint32_t)dst_h; oy++) {
        uint32_t y0 = oy * (uint32_t)src_h, y1 = y0 + (uint32_t)src_h;
        uint16_t *out = dst + (size_t)oy * (size_t)dst_stride;
        for (uint32_t ox = 0; ox < (uint32_t)dst_w; ox++) {
            uint32_t x0 = ox * (uint32_t)src_w, x1 = x0 + (uint32_t)src_w;
            uint32_t r = 0, g = 0, b = 0, a = 0;
            for (uint32_t sy = y0 / (uint32_t)dst_h; sy * (uint32_t)dst_h < y1; sy++) {
                uint32_t top = sy * (uint32_t)dst_h, bottom = top + (uint32_t)dst_h;
                uint32_t wy = (bottom < y1 ? bottom : y1) - (top > y0 ? top : y0);
                const uint16_t *row = src + (size_t)sy * (size_t)src_stride;
                for (uint32_t sx = x0 / (uint32_t)dst_w; sx * (uint32_t)dst_w < x1; sx++) {
                    uint32_t left = sx * (uint32_t)dst_w, right = left + (uint32_t)dst_w;
                    uint32_t w = ((right < x1 ? right : x1) - (left > x0 ? left : x0)) * wy;
                    uint32_t pixel = row[sx];
                    r += w * ((pixel >> 11) & 31u);
                    g += w * ((pixel >> 6) & 31u);
                    b += w * ((pixel >> 1) & 31u);
                    a += w * (pixel & 1u);
                }
            }
            out[ox] = (uint16_t)((((r + total / 2u) / total) << 11) |
                                 (((g + total / 2u) / total) << 6) |
                                 (((b + total / 2u) / total) << 1) |
                                 (a * 2u >= total ? 1u : 0u));
        }
    }
}
