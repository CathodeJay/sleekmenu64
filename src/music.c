/* SPDX-License-Identifier: AGPL-3.0-only */
#include "music.h"
#include <libdragon.h>
#include <stdio.h>
#include <string.h>
#ifdef __mips__
#include <fcntl.h>
#include <unistd.h>
#endif

/* How loud, against full scale: under the browser, not over it. Q15. */
#define MUSIC_VOLUME 19661          /* 0.6 */
/* Audio buffers, each a twenty-fifth of a second. The hardware has two
   queued at a time and the music is mixed into each as it goes in, from
   the audio interrupt, so a frame that takes long changes nothing here:
   these only set how soon a change of volume is heard. */
#define MUSIC_BUFFERS 4
#define MUSIC_FADE_MS 250u
#define MUSIC_TAIL_MS 100u          /* the two queued buffers, played out */

static sm_music_info_t track;
static char track_path[256];
static bool available, enabled = true, playing;
static uint32_t resume_at;

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
    /* Less than a tenth of a second is not music. */
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
/* Read-ahead: about a second of the track, read off the card by the main
   loop, a block a frame while the card is free, and played out by the
   audio interrupt. While the browser lists a folder the card is the
   listing's (folder_scan.h), and while it works on something long, like
   the pictures of a game's details, the main loop is not here at all: the
   interrupt plays on from what was read before either way. A block is
   under the Pro file driver's 16 KiB window, so it is served by the fast
   read rather than the slow one.

   One writer and one reader: the main loop moves `head`, the interrupt
   moves `tail`, each only ever forward, and a sample is written before
   `head` passes it. */
#define RING_SAMPLES 32768u
#define BLOCK_SAMPLES 4096u
static int16_t ring[RING_SAMPLES] __attribute__((aligned(16)));
static volatile uint32_t head, tail;
static uint32_t fill_pos;                 /* the track position `head` reads next */
static volatile int32_t volume = MUSIC_VOLUME;
static int track_fd = -1;
static bool broken;

/* The audio interrupt: the next buffer, from what has been read. Run dry,
   it is silence, and the track picks up where it was. */
static void fill(short *out, size_t frames) {
    uint32_t at = tail;
    uint32_t held = head - at;
    int32_t level = volume;
    for (size_t i = 0; i < frames; i++) {
        int32_t sample = 0;
        if (held) {
            sample = (ring[at & (RING_SAMPLES - 1u)] * level) >> 15;
            at++;
            held--;
        }
        out[2 * i] = out[2 * i + 1] = (short)sample;
    }
    tail = at;
}

/* One block onto the end of what is held, from where the track goes on;
   past its end, from its start. It is read into a buffer of its own and
   copied in by the CPU: a card driver may fill a read by DMA, behind the
   cache, and the interrupt reads the ring through it. */
static int16_t block[BLOCK_SAMPLES] __attribute__((aligned(16)));

static bool read_block(void) {
    uint32_t space = RING_SAMPLES - (head - tail);
    uint32_t end = head & (RING_SAMPLES - 1u);
    uint32_t want = BLOCK_SAMPLES;
    if (want > space) want = space;
    if (want > RING_SAMPLES - end) want = RING_SAMPLES - end;
    if (want > track.samples - fill_pos) want = track.samples - fill_pos;
    if (!want) return true;
    if (lseek(track_fd, (off_t)(track.data_offset + fill_pos * 2u), SEEK_SET) < 0) return false;
    if (read(track_fd, block, want * 2u) != (int)(want * 2u)) return false;
    memcpy(ring + end, block, want * 2u);
    fill_pos += want;
    if (fill_pos == track.samples) fill_pos = 0;
    head += want;
    return true;
}

static bool start(uint32_t from) {
    track_fd = open(track_path, O_RDONLY);
    if (track_fd < 0) return false;
    head = tail = 0;
    fill_pos = from < track.samples ? from : 0;
    broken = false;
    volume = MUSIC_VOLUME;
    /* A head start, so the first buffers are not silence. */
    if (!read_block() || !read_block()) {
        close(track_fd);
        track_fd = -1;
        return false;
    }
    audio_init((int)track.frequency, MUSIC_BUFFERS);
    audio_set_buffer_callback(fill);
    /* Nothing calls the interrupt until a buffer is queued: this queues the
       first, which `fill` writes, and the interrupt carries on from there. */
    audio_write_silence();
    return true;
}

static void stop(void) {
    audio_set_buffer_callback(NULL);
    audio_close();
    close(track_fd);
    track_fd = -1;
}

void sm_music_poll(bool card_free) {
    if (!playing) return;
    /* The card stopped giving the track back: the MUSIC row says None
       from here on rather than an On that plays nothing. */
    if (broken) { stop(); playing = false; available = false; return; }
    if (card_free && RING_SAMPLES - (head - tail) >= BLOCK_SAMPLES && !read_block())
        broken = true;
}

void sm_music_fade_out(void) {
    uint64_t began;
    uint32_t held;
    if (!playing) return;
    began = get_ticks_ms();
    for (;;) {
        uint32_t elapsed = (uint32_t)(get_ticks_ms() - began);
        if (elapsed >= MUSIC_FADE_MS + MUSIC_TAIL_MS) break;
        volume = elapsed >= MUSIC_FADE_MS ? 0
            : (int32_t)(MUSIC_VOLUME * (MUSIC_FADE_MS - elapsed) / MUSIC_FADE_MS);
    }
    /* Where the music stopped: what was read, less what was not played. */
    held = head - tail;
    resume_at = (fill_pos + track.samples - held % track.samples) % track.samples;
    stop();
    playing = false;
}
#else
/* The host has no audio hardware: starting and stopping is the state. */
static bool start(uint32_t from) { (void)from; return true; }
static void stop(void) {}
void sm_music_poll(bool card_free_now) { (void)card_free_now; }
void sm_music_fade_out(void) {
    if (!playing) return;
    resume_at = 1u;
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
    resume_at = 0;
    if (available && enabled) playing = start(0);
}

bool sm_music_available(void) { return available; }
bool sm_music_enabled(void) { return enabled; }
bool sm_music_playing(void) { return playing; }

void sm_music_set_enabled(bool on) {
    enabled = on;
    if (!available) return;
    if (on && !playing) {
        resume_at = 0;
        playing = start(0);
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
