/* 
 * File:   n64.h
 * Author: Igor
 *
 * Created on May 1, 2026, 3:16 PM
 */

#ifndef N64_H
#define	N64_H

#define KSEG0           0x80000000
#define KSEG1           0xA0000000
//******************************************************************************

typedef struct {
    vu32 CR; /**< Control Register. */
    vu32 MADDR; /**< Memory Address. */
    vu32 H_WIDTH; /**< Horizontal Width. */
    vu32 V_INTR; /**< Vertical Interrupt. */
    vu32 CURR_LINE; /**< Current Line. */
    vu32 TIMING; /**< Timings. */
    vu32 V_SYNC; /**< Vertical Sync. */
    vu32 H_SYNC; /**< Horizontal Sync. */
    vu32 H_SYNC_LEAP; /**< Horizontal Sync Leap. */
    vu32 H_LIMITS; /**< Horizontal Limits. */
    vu32 V_LIMITS; /**< Vertical Limits. */
    vu32 COLOR_BURST; /**< Color Burst. */
    vu32 H_SCALE; /**< Horizontal Scale. */
    vu32 V_SCALE; /**< Vertical Scale. */
} vi_regs_t;

#define VI_BASE                     (KSEG1 | 0x04400000UL)
#define VI                          ((vi_regs_t *) VI_BASE)

#define VI_CR_TYPE_16               (2 << 0)
#define VI_CR_TYPE_32               (3 << 0)
#define VI_CR_GAMMA_DITHER_ON       (1 << 2)
#define VI_CR_GAMMA_ON              (1 << 3)
#define VI_CR_DIVOT_ON              (1 << 4)
#define VI_CR_SERRATE_ON            (1 << 6)
#define VI_CR_ANTIALIAS_0           (1 << 8)
#define VI_CR_ANTIALIAS_1           (1 << 9)
#define VI_CR_PIXEL_ADVANCE_0       (1 << 12)
#define VI_CR_PIXEL_ADVANCE_1       (1 << 13)
#define VI_CR_PIXEL_ADVANCE_2       (1 << 14)
#define VI_CR_PIXEL_ADVANCE_3       (1 << 15)
#define VI_CR_DITHER_FILTER_ON      (1 << 16)

#define VI_CURR_LINE_FIELD          (1 << 0)
//******************************************************************************
void pi_rd(void *dst, unsigned long pi_address, unsigned long len);
void pi_wr(void *src, unsigned long pi_address, unsigned long len);

#endif	/* N64_H */

