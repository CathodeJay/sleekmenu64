/* SPDX-License-Identifier: AGPL-3.0-only */
/* The background music: which files are a track the browser can play, and
   the On/Off the card keeps. */
#include "music.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* A header as the Game Catalog Manager writes one: 22050 Hz, mono, 16-bit,
   raw, 44100 samples looped whole, samples right after the header. */
static void make(uint8_t h[24]) {
    static const uint8_t good[24] = {'W', 'V', '6', '4', 2, 0, 1, 16,
        0, 0, 0x56, 0x22, 0, 0, 0xAC, 0x44, 0, 0, 0xAC, 0x44, 0, 0, 0, 24};
    memcpy(h, good, 24);
}

static bool setting(const char *text) { return sm_music_setting_from_text(text, strlen(text)); }

int main(int argc, char **argv) {
    uint8_t h[24];
    sm_music_info_t info;
    const uint32_t whole = 24u + 44100u * 2u;
    char track[512], saved[512], text[16];
    FILE *file;
    size_t read;

    make(h);
    assert(sm_music_read_header(h, sizeof(h), whole, &info));
    assert(info.frequency == 22050u && info.samples == 44100u && info.data_offset == 24u);

    /* Too short to be a header, or nothing to fill. */
    assert(!sm_music_read_header(h, 23, whole, &info));
    assert(!sm_music_read_header(NULL, 24, whole, &info));
    assert(!sm_music_read_header(h, 24, whole, NULL));
    /* Something else than a WAV64 file. */
    make(h); memcpy(h, "RIFF", 4); assert(!sm_music_read_header(h, 24, whole, &info));
    /* What libdragon's own converter also writes, and this browser does not
       play: another version, compressed samples, stereo, 8 bits. */
    make(h); h[4] = 1; assert(!sm_music_read_header(h, 24, whole, &info));
    make(h); h[5] = 1; assert(!sm_music_read_header(h, 24, whole, &info));
    make(h); h[5] = 3; assert(!sm_music_read_header(h, 24, whole, &info));
    make(h); h[6] = 2; assert(!sm_music_read_header(h, 24, whole, &info));
    make(h); h[7] = 8; assert(!sm_music_read_header(h, 24, whole, &info));
    /* A rate the audio hardware does not take. */
    make(h); h[10] = 0x1F; h[11] = 0x3F; assert(!sm_music_read_header(h, 24, whole, &info));   /* 7999 */
    make(h); h[10] = 0x1F; h[11] = 0x40; assert(sm_music_read_header(h, 24, whole, &info));    /* 8000 */
    make(h); h[9] = 0x01; h[10] = 0x77; h[11] = 0x00; assert(!sm_music_read_header(h, 24, whole, &info));   /* 96000 */
    /* Samples that would start inside the header, or past the file. */
    make(h); h[23] = 20; assert(!sm_music_read_header(h, 24, whole, &info));
    make(h); assert(!sm_music_read_header(h, 24, 24, &info));
    /* A file cut short plays what it holds; one with hardly anything left
       is not a track. */
    make(h); assert(sm_music_read_header(h, 24, 24u + 30000u * 2u, &info) && info.samples == 30000u);
    make(h); assert(sm_music_read_header(h, 24, 24u + 2205u * 2u, &info) && info.samples == 2205u);
    make(h); assert(!sm_music_read_header(h, 24, 24u + 2204u * 2u, &info));

    /* The setting: only "off" is off, whatever its case or surroundings. */
    assert(!setting("off") && !setting("off\n") && !setting("  OFF\r\n") && !setting("\xef\xbb\xbfOff"));
    assert(setting("on\n") && setting("") && setting("offbeat") && setting("of") && setting("yes"));
    assert(sm_music_setting_from_text(NULL, 0));
    assert(!sm_music_setting_from_text("offXXXX", 3));

    /* On the card. No track: nothing to play, whatever the setting says. */
    assert(argc > 1);
    snprintf(track, sizeof(track), "%s/music.wav64", argv[1]);
    snprintf(saved, sizeof(saved), "%s/music.txt", argv[1]);
    sm_music_init(track, saved);
    assert(!sm_music_available() && sm_music_enabled() && !sm_music_playing());
    sm_music_set_enabled(true);
    assert(!sm_music_playing());

    /* A track: it plays, until it is turned off. */
    file = fopen(track, "wb");
    assert(file);
    make(h);
    fwrite(h, 1, sizeof(h), file);
    for (unsigned i = 0; i < 44100u * 2u; i++) fputc(0, file);
    fclose(file);
    sm_music_init(track, saved);
    assert(sm_music_available() && sm_music_playing());
    sm_music_set_enabled(false);
    assert(!sm_music_playing() && !sm_music_enabled());
    assert(sm_music_save_setting(saved));
    file = fopen(saved, "rb");
    assert(file);
    read = fread(text, 1, sizeof(text) - 1, file);
    fclose(file);
    text[read] = '\0';
    assert(!strcmp(text, "off\n"));
    sm_music_init(track, saved);
    assert(sm_music_available() && !sm_music_enabled() && !sm_music_playing());
    /* Coming back from a launch that did not boot changes nothing when the
       music is off. */
    sm_music_resume();
    assert(!sm_music_playing());

    /* On, then a launch: stopped for it, and back after it. */
    sm_music_set_enabled(true);
    assert(sm_music_save_setting(saved) && sm_music_playing());
    sm_music_fade_out();
    assert(!sm_music_playing());
    sm_music_resume();
    assert(sm_music_playing());
    sm_music_init(track, saved);
    assert(sm_music_enabled() && sm_music_playing());

    /* A track that is not one is not available, and the setting stays. */
    file = fopen(track, "wb");
    assert(file);
    fputs("RIFF and nothing else", file);
    fclose(file);
    sm_music_init(track, saved);
    assert(!sm_music_available() && sm_music_enabled() && !sm_music_playing());
    remove(track);
    remove(saved);
    puts("music ok");
    return 0;
}
