/* SPDX-License-Identifier: AGPL-3.0-only */
#include "music.h"
#include <libdragon.h>
#include <stdio.h>
#include <string.h>
#ifdef __mips__
#include <fcntl.h>
#include <unistd.h>
#endif

/* How loud, against a full-scale mix: under the browser, not over it. */
#define MUSIC_VOLUME 0.6f
/* Audio buffers queued ahead, each a twenty-fifth of a second. Six ride out
   a frame that spends a few hundred milliseconds reading a big picture. */
#define MUSIC_BUFFERS 6
#define MUSIC_QUEUED_MS (MUSIC_BUFFERS * 40u)
#define MUSIC_FADE_MS 250u

static sm_music_info_t track;
static char track_path[256];
static bool available, enabled = true, playing;
static float resume_at;

static uint32_t big32(const uint8_t *p) {
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

bool sm_music_read_header(const uint8_t *bytes, size_t size, uint32_t file_size,
    sm_music_info_t *info) {
    uint32_t frequency, samples, offset, room;
    if (!bytes || size < SM_MUSIC_HEADER_SIZE || !info) return false;
    if (memcmp(bytes, "WV64", 4) != 0) return false;
    /* version 2; format 0 (raw samples); one channel; 16 bits */
    if (bytes[4] != 2 || bytes[5] != 0 || bytes[6] != 1 || bytes[7] != 16) return false;
    frequency = big32(bytes + 8);
    samples = big32(bytes + 12);
    offset = big32(bytes + 20);
    if (frequency < SM_MUSIC_MIN_RATE || frequency > SM_MUSIC_MAX_RATE) return false;
    if (offset < SM_MUSIC_HEADER_SIZE || offset >= file_size) return false;
    room = (file_size - offset) / 2u;
    if (samples > room) samples = room;
    /* Less than a tenth of a second is not music, and would make the mixer
       loop faster than it reads. */
    if (samples < frequency / 10u) return false;
    info->frequency = frequency;
    info->samples = samples;
    info->data_offset = offset;
    return true;
}

static bool blank(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }

bool sm_music_setting_from_text(const char *text, size_t length) {
    size_t start = 0, end;
    if (!text) return true;
    if (length >= 3 && (unsigned char)text[0] == 0xEF && (unsigned char)text[1] == 0xBB &&
        (unsigned char)text[2] == 0xBF) start = 3;
    while (start < length && blank(text[start])) start++;
    end = start;
    while (end < length && text[end] && !blank(text[end])) end++;
    if (end - start != 3) return true;
    return !((text[start] | 0x20) == 'o' && (text[start + 1] | 0x20) == 'f' &&
             (text[start + 2] | 0x20) == 'f');
}

static bool find_track(const char *path) {
    uint8_t header[SM_MUSIC_HEADER_SIZE];
    long size;
    bool ok = false;
    FILE *file = fopen(path, "rb");
    if (!file) return false;
    if (fread(header, 1, sizeof(header), file) == sizeof(header) &&
        fseek(file, 0, SEEK_END) == 0 && (size = ftell(file)) > 0)
        ok = sm_music_read_header(header, sizeof(header), (uint32_t)size, &track);
    fclose(file);
    return ok;
}

#ifdef __mips__
/* The samples come off the card in blocks of this size, kept until the
   mixer has taken them. Under the Pro file driver's 16 KiB window, so a
   block is served by its fast read rather than the slow one. */
#define STAGE_SAMPLES 4096u
static int16_t stage[STAGE_SAMPLES] __attribute__((aligned(16)));
static uint32_t stage_first, stage_count;
static int track_fd = -1;
static bool broken;
static waveform_t wave;

static bool refill(uint32_t at) {
    uint32_t want = track.samples - at;
    if (want > STAGE_SAMPLES) want = STAGE_SAMPLES;
    if (lseek(track_fd, (off_t)(track.data_offset + at * 2u), SEEK_SET) < 0) return false;
    if (read(track_fd, stage, want * 2u) != (int)(want * 2u)) return false;
    stage_first = at;
    stage_count = want;
    return true;
}

/* The mixer asks for at least `wlen` samples from `wpos`, and loops by
   asking from 0 again. A card that stops answering gets silence, and
   sm_music_poll stops the music. */
static void read_samples(void *ctx, samplebuffer_t *sbuf, int wpos, int wlen, bool seeking) {
    int16_t *out = samplebuffer_append(sbuf, wlen);
    uint32_t at = (uint32_t)wpos % track.samples;
    uint32_t left = (uint32_t)wlen;
    (void)ctx; (void)seeking;
    while (left) {
        uint32_t from, take;
        if (broken || ((at < stage_first || at >= stage_first + stage_count) && !refill(at))) {
            broken = true;
            memset(out, 0, left * 2u);
            return;
        }
        from = at - stage_first;
        take = stage_count - from;
        if (take > left) take = left;
        memcpy(out, stage + from, take * 2u);
        out += take;
        left -= take;
        at += take;
        if (at >= track.samples) at = 0;
    }
}

/* Mix into every audio buffer the hardware has finished with. */
static void pump(void) {
    while (audio_can_write()) {
        short *out = audio_write_begin();
        mixer_poll(out, audio_get_buffer_length());
        audio_write_end();
    }
}

static bool start(float from) {
    track_fd = open(track_path, O_RDONLY);
    if (track_fd < 0) return false;
    stage_first = stage_count = 0;
    broken = false;
    audio_init((int)track.frequency, MUSIC_BUFFERS);
    mixer_init(1);
    /* The rate the hardware settled on can be a little under the track's;
       the channel's buffer is sized for the track. */
    mixer_ch_set_limits(0, 16, (float)track.frequency * 1.05f, 0);
    wave = (waveform_t){ .name = "music", .bits = 16, .channels = 1,
        .frequency = (float)track.frequency, .len = (int)track.samples,
        .loop_len = (int)track.samples, .read = read_samples, .ctx = NULL };
    mixer_ch_set_vol(0, MUSIC_VOLUME, MUSIC_VOLUME);
    mixer_ch_play(0, &wave);
    if (from > 0.0f && from < (float)track.samples) mixer_ch_set_pos(0, from);
    return true;
}

static void stop(void) {
    mixer_ch_stop(0);
    mixer_close();
    audio_close();
    /* The RSP was started for the mixer; the game's boot code waits for
       it to be halted. */
    rspq_close();
    close(track_fd);
    track_fd = -1;
}

void sm_music_poll(void) {
    if (!playing) return;
    /* The card stopped giving the track back: the MUSIC row says None
       from here on rather than an On that plays nothing. */
    if (broken) { stop(); playing = false; available = false; return; }
    pump();
}

void sm_music_fade_out(void) {
    uint64_t began;
    if (!playing) return;
    /* What is already queued plays at the old volume, so the wait is the
       fade and then the queue. */
    began = get_ticks_ms();
    for (;;) {
        uint32_t elapsed = (uint32_t)(get_ticks_ms() - began);
        float volume;
        if (elapsed >= MUSIC_FADE_MS + MUSIC_QUEUED_MS) break;
        volume = elapsed >= MUSIC_FADE_MS ? 0.0f
            : MUSIC_VOLUME * (float)(MUSIC_FADE_MS - elapsed) / (float)MUSIC_FADE_MS;
        mixer_ch_set_vol(0, volume, volume);
        pump();
    }
    resume_at = mixer_ch_get_pos(0);
    stop();
    playing = false;
}
#else
/* The host has no audio hardware: starting and stopping is the state. */
static bool start(float from) { (void)from; return true; }
static void stop(void) {}
void sm_music_poll(void) {}
void sm_music_fade_out(void) {
    if (!playing) return;
    resume_at = 1.0f;
    stop();
    playing = false;
}
#endif

void sm_music_init(const char *path, const char *setting_path) {
    char text[16];
    size_t read = 0;
    FILE *file;
    if (playing) { stop(); playing = false; }
    file = fopen(setting_path, "rb");
    if (file) {
        read = fread(text, 1, sizeof(text), file);
        fclose(file);
        enabled = sm_music_setting_from_text(text, read);
    }
    snprintf(track_path, sizeof(track_path), "%s", path);
    available = strlen(path) < sizeof(track_path) && find_track(path);
    resume_at = 0.0f;
    if (available && enabled) playing = start(0.0f);
}

bool sm_music_available(void) { return available; }
bool sm_music_enabled(void) { return enabled; }
bool sm_music_playing(void) { return playing; }

void sm_music_set_enabled(bool on) {
    enabled = on;
    if (!available) return;
    if (on && !playing) {
        resume_at = 0.0f;
        playing = start(0.0f);
    } else if (!on && playing) {
        stop();
        playing = false;
    }
}

bool sm_music_save_setting(const char *path) {
    bool written;
    FILE *file = fopen(path, "wb");
    if (!file) return false;
    written = fprintf(file, "%s\n", enabled ? "on" : "off") > 0;
    return fclose(file) == 0 && written;
}

void sm_music_resume(void) {
    if (available && enabled && !playing) playing = start(resume_at);
}
