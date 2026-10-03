/* SPDX-License-Identifier: AGPL-3.0-only */
/* Written by tools/themes.py -- change the themes there, then run
   python3 -m tools.themes --header src/theme_table.h */
#ifndef SLEEKMENU_THEME_TABLE_H
#define SLEEKMENU_THEME_TABLE_H

typedef enum {
    SM_C_BG,
    SM_C_BAR,
    SM_C_WELL,
    SM_C_BAND,
    SM_C_TAB,
    SM_C_STRIPE,
    SM_C_SELECT,
    SM_C_SELECT_HI,
    SM_C_THUMB,
    SM_C_FOLDER,
    SM_C_TEXT,
    SM_C_TEXT_BRIGHT,
    SM_C_TEXT_BODY,
    SM_C_TEXT_SOFT,
    SM_C_TEXT_MUTED,
    SM_C_TEXT_DIM,
    SM_C_TEXT_FAINT,
    SM_C_ACCENT,
    SM_C_ACCENT_INK,
    SM_C_STAR,
    SM_C_WARN,
    SM_C_ERROR,
    SM_C_PROGRESS,
    SM_C_PROGRESS_VERIFY,
    SM_C_PROGRESS_HEAD,
    SM_C_COUNT
} sm_colour_role_t;

#define SM_THEME_COUNT 6u
#define SM_THEME_ID_MAX 15u

#ifdef SM_THEME_TABLE_DEFINE
static const struct {
    const char *id;
    const char *name;
    unsigned char rgb[SM_C_COUNT][3];
} SM_THEME_TABLE[SM_THEME_COUNT] = {
    { "midnight", "Midnight", {
        {  8,  12,  20},  /* bg */
        { 16,  22,  32},  /* bar */
        { 35,  42,  52},  /* well */
        { 24,  45,  72},  /* band */
        { 30,  44,  62},  /* tab */
        { 20,  32,  48},  /* stripe */
        { 45,  75, 110},  /* select */
        { 70,  95, 130},  /* select_hi */
        { 90, 120, 155},  /* thumb */
        { 78, 108, 150},  /* folder */
        {240, 240, 232},  /* text */
        {255, 255, 255},  /* text_bright */
        {200, 208, 220},  /* text_body */
        {180, 200, 220},  /* text_soft */
        {150, 165, 185},  /* text_muted */
        {110, 128, 150},  /* text_dim */
        { 55,  64,  78},  /* text_faint */
        {245, 230, 160},  /* accent */
        { 20,  24,  32},  /* accent_ink */
        {250, 210,  90},  /* star */
        {255, 190,  90},  /* warn */
        {255,  96,  80},  /* error */
        { 70, 140, 200},  /* progress */
        {200, 170,  70},  /* progress_verify */
        {235, 245, 255},  /* progress_head */
    } },
    { "charcoal", "Charcoal", {
        { 13,  14,  15},  /* bg */
        { 23,  24,  25},  /* bar */
        { 42,  43,  45},  /* well */
        { 45,  48,  51},  /* band */
        { 44,  46,  48},  /* tab */
        { 32,  34,  36},  /* stripe */
        { 74,  77,  81},  /* select */
        { 96,  99, 104},  /* select_hi */
        {119, 122, 126},  /* thumb */
        {110, 113, 118},  /* folder */
        {240, 240, 232},  /* text */
        {255, 255, 255},  /* text_bright */
        {209, 210, 211},  /* text_body */
        {198, 200, 202},  /* text_soft */
        {165, 167, 170},  /* text_muted */
        {128, 130, 132},  /* text_dim */
        { 65,  66,  68},  /* text_faint */
        {255, 176,  80},  /* accent */
        { 25,  26,  27},  /* accent_ink */
        {250, 210,  90},  /* star */
        {255, 190,  90},  /* warn */
        {255,  96,  80},  /* error */
        {127, 134, 143},  /* progress */
        {200, 170,  70},  /* progress_verify */
        {235, 245, 255},  /* progress_head */
    } },
    { "jungle", "Jungle", {
        {  8,  20,  14},  /* bg */
        { 16,  32,  24},  /* bar */
        { 35,  52,  44},  /* well */
        { 25,  71,  48},  /* band */
        { 31,  61,  46},  /* tab */
        { 21,  47,  34},  /* stripe */
        { 47, 108,  78},  /* select */
        { 72, 128, 100},  /* select_hi */
        { 92, 153, 122},  /* thumb */
        { 80, 148, 114},  /* folder */
        {240, 240, 232},  /* text */
        {255, 255, 255},  /* text_bright */
        {200, 219, 210},  /* text_body */
        {181, 219, 200},  /* text_soft */
        {151, 184, 168},  /* text_muted */
        {111, 149, 130},  /* text_dim */
        { 56,  77,  66},  /* text_faint */
        {214, 240, 130},  /* accent */
        { 20,  32,  26},  /* accent_ink */
        {250, 210,  90},  /* star */
        {255, 190,  90},  /* warn */
        {255,  96,  80},  /* error */
        { 73, 197, 135},  /* progress */
        {200, 170,  70},  /* progress_verify */
        {235, 245, 255},  /* progress_head */
    } },
    { "grape", "Grape", {
        { 15,   9,  21},  /* bg */
        { 26,  17,  33},  /* bar */
        { 46,  37,  54},  /* well */
        { 52,  26,  74},  /* band */
        { 49,  32,  64},  /* tab */
        { 37,  22,  50},  /* stripe */
        { 84,  49, 114},  /* select */
        {107,  75, 135},  /* select_hi */
        {131,  97, 160},  /* thumb */
        {122,  84, 156},  /* folder */
        {240, 240, 232},  /* text */
        {255, 255, 255},  /* text_bright */
        {221, 213, 228},  /* text_body */
        {211, 194, 226},  /* text_soft */
        {177, 161, 191},  /* text_muted */
        {138, 118, 155},  /* text_dim */
        { 71,  58,  81},  /* text_faint */
        {255, 178, 224},  /* accent */
        { 28,  21,  33},  /* accent_ink */
        {250, 210,  90},  /* star */
        {255, 190,  90},  /* warn */
        {255,  96,  80},  /* error */
        {146,  83, 200},  /* progress */
        {200, 170,  70},  /* progress_verify */
        {235, 245, 255},  /* progress_head */
    } },
    { "fire", "Fire", {
        { 20,   9,   8},  /* bg */
        { 32,  18,  16},  /* bar */
        { 52,  37,  35},  /* well */
        { 73,  30,  23},  /* band */
        { 63,  34,  29},  /* tab */
        { 49,  23,  19},  /* stripe */
        {112,  52,  43},  /* select */
        {132,  77,  69},  /* select_hi */
        {157,  97,  88},  /* thumb */
        {152,  86,  76},  /* folder */
        {240, 240, 232},  /* text */
        {255, 255, 255},  /* text_bright */
        {220, 202, 199},  /* text_body */
        {221, 185, 179},  /* text_soft */
        {186, 154, 149},  /* text_muted */
        {151, 115, 109},  /* text_dim */
        { 79,  58,  54},  /* text_faint */
        {255, 208,  96},  /* accent */
        { 32,  21,  20},  /* accent_ink */
        {250, 210,  90},  /* star */
        {255, 190,  90},  /* warn */
        {255,  96,  80},  /* error */
        {203,  85,  67},  /* progress */
        {200, 170,  70},  /* progress_verify */
        {235, 245, 255},  /* progress_head */
    } },
    { "ice", "Ice", {
        {  8,  20,  22},  /* bg */
        { 16,  32,  35},  /* bar */
        { 37,  54,  57},  /* well */
        { 23,  71,  80},  /* band */
        { 31,  62,  69},  /* tab */
        { 20,  48,  53},  /* stripe */
        { 45, 109, 122},  /* select */
        { 72, 132, 144},  /* select_hi */
        { 96, 156, 168},  /* thumb */
        { 80, 152, 166},  /* folder */
        {240, 240, 232},  /* text */
        {255, 255, 255},  /* text_bright */
        {220, 231, 234},  /* text_body */
        {200, 226, 232},  /* text_soft */
        {165, 192, 197},  /* text_muted */
        {120, 154, 161},  /* text_dim */
        { 58,  81,  85},  /* text_faint */
        {190, 240, 255},  /* accent */
        { 21,  33,  35},  /* accent_ink */
        {250, 210,  90},  /* star */
        {255, 190,  90},  /* warn */
        {255,  96,  80},  /* error */
        { 81, 189, 211},  /* progress */
        {200, 170,  70},  /* progress_verify */
        {235, 245, 255},  /* progress_head */
    } },
};
#endif

#endif
