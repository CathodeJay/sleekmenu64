/* SPDX-License-Identifier: AGPL-3.0-only */
/* The background music: which files are a track the browser can play, and
   the On/Off the card keeps. */
#include "music.h"
#include <libdragon.h>
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

/* A track as the Game Catalog Manager writes one, two seconds long. */
static void write_track(const char *path) {
    uint8_t h[24];
    FILE *file = fopen(path, "wb");
    assert(file);
    make(h);
    fwrite(h, 1, sizeof(h), file);
    for (unsigned i = 0; i < 44100u * 2u; i++) fputc(0, file);
    fclose(file);
}

static bool path_is(unsigned number, const char *first, const char *expected) {
    char out[64];
    return sm_music_track_path(out, sizeof(out), first, number) && !strcmp(out, expected);
}

/* Over `seeds` seeds from `base`, `step` apart: every track is picked, and
   none more than twice as often as an even share. */
static void picks_evenly(unsigned count, uint64_t base, uint64_t step, unsigned seeds) {
    unsigned times[SM_MUSIC_MAX_TRACKS + 1] = {0};
    for (unsigned i = 0; i < seeds; i++) {
        unsigned picked = sm_music_pick(count, base + i * step);
        assert(picked >= 1u && picked <= count);
        times[picked]++;
    }
    for (unsigned n = 1; n <= count; n++)
        assert(times[n] > 0u && times[n] <= 2u * seeds / count);
}

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

    /* The path of each track: the first as it is, the others numbered
       before the extension, and nothing past eight. */
    assert(path_is(1, "sd:/sleekmenu/music.wav64", "sd:/sleekmenu/music.wav64"));
    assert(path_is(2, "sd:/sleekmenu/music.wav64", "sd:/sleekmenu/music-2.wav64"));
    assert(path_is(8, "sd:/sleekmenu/music.wav64", "sd:/sleekmenu/music-8.wav64"));
    assert(path_is(3, "card.d/music", "card.d/music-3"));
    assert(!path_is(0, "sd:/sleekmenu/music.wav64", ""));
    assert(!path_is(9, "sd:/sleekmenu/music.wav64", ""));
    {
        char small[12];
        assert(sm_music_track_path(small, sizeof(small), "a/music.wav", 1));
        assert(!sm_music_track_path(small, sizeof(small), "a/music.wav", 2));   /* a/music-2.wav */
        assert(!sm_music_track_path(small, sizeof(small), "a/music.wav64", 1));
    }

    /* The pick. Nothing to pick from, or one track. */
    assert(sm_music_pick(0, 12345u) == 0u);
    assert(sm_music_pick(1, 0u) == 1u && sm_music_pick(1, UINT64_MAX) == 1u);
    for (unsigned count = 2; count <= SM_MUSIC_MAX_TRACKS; count++) {
        /* Seeds that differ only in their lowest bits, as two power-ons of
           one console do, near zero and two seconds in. */
        picks_evenly(count, 0u, 1u, 64u * count);
        picks_evenly(count, 93750000u, 1u, 64u * count);
        /* and seeds whose lowest bits are all the same: the rest counts too */
        picks_evenly(count, 0u, 1u << 20, 64u * count);
        picks_evenly(count, 0u, (uint64_t)1 << 32, 64u * count);
    }

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

    assert(sm_music_track_count() == 1u && sm_music_track() == 1u);

    /* Three tracks: each start counts them and picks one by the ticks. */
    {
        char second[512], third[512], ninth[512];
        bool heard[4] = {false};
        assert(sm_music_track_path(second, sizeof(second), track, 2));
        assert(sm_music_track_path(third, sizeof(third), track, 3));
        write_track(second);
        write_track(third);
        for (uint64_t ticks = 0; ticks < 32u; ticks++) {
            sm_test_ticks = ticks;
            sm_music_init(track, saved);
            assert(sm_music_available() && sm_music_playing() && sm_music_track_count() == 3u);
            assert(sm_music_track() == sm_music_pick(3, ticks));
            heard[sm_music_track()] = true;
        }
        assert(heard[1] && heard[2] && heard[3]);

        /* Off and on, and a launch that comes back: the same track, though
           the ticks have moved on. */
        for (uint64_t ticks = 0; ticks < 32u; ticks++) {
            unsigned picked;
            sm_test_ticks = ticks;
            sm_music_init(track, saved);
            picked = sm_music_track();
            sm_test_ticks = ticks + 1u;
            sm_music_set_enabled(false);
            sm_music_set_enabled(true);
            assert(sm_music_playing() && sm_music_track() == picked);
            sm_music_fade_out();
            sm_music_resume();
            assert(sm_music_playing() && sm_music_track() == picked);
        }

        /* A gap: the count stops at the first track missing. */
        remove(second);
        for (uint64_t ticks = 0; ticks < 8u; ticks++) {
            sm_test_ticks = ticks;
            sm_music_init(track, saved);
            assert(sm_music_track_count() == 1u && sm_music_track() == 1u && sm_music_playing());
        }
        /* or at the first that does not play. */
        file = fopen(second, "wb");
        assert(file);
        fputs("RIFF and nothing else", file);
        fclose(file);
        sm_music_init(track, saved);
        assert(sm_music_track_count() == 1u && sm_music_track() == 1u);
        /* Eight at most: a ninth is never looked for. */
        for (unsigned n = 2; n <= SM_MUSIC_MAX_TRACKS; n++) {
            char path[512];
            assert(sm_music_track_path(path, sizeof(path), track, n));
            write_track(path);
        }
        snprintf(ninth, sizeof(ninth), "%s/music-9.wav64", argv[1]);
        write_track(ninth);
        sm_music_init(track, saved);
        assert(sm_music_track_count() == SM_MUSIC_MAX_TRACKS);
        remove(ninth);
        for (unsigned n = 2; n <= SM_MUSIC_MAX_TRACKS; n++) {
            char path[512];
            assert(sm_music_track_path(path, sizeof(path), track, n));
            remove(path);
        }
        sm_test_ticks = 0;
    }

    /* A track that is not one is not available, and the setting stays. */
    file = fopen(track, "wb");
    assert(file);
    fputs("RIFF and nothing else", file);
    fclose(file);
    sm_music_init(track, saved);
    assert(!sm_music_available() && sm_music_enabled() && !sm_music_playing());
    assert(sm_music_track_count() == 0u && sm_music_track() == 0u);
    remove(track);
    remove(saved);
    puts("music ok");
    return 0;
}
