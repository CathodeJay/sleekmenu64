/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_MUSIC_H
#define SLEEKMENU_MUSIC_H

/* Background music: up to eight tracks on the card, one of them picked
   each time the browser starts and looped while it runs.

   The Game Catalog Manager writes the tracks as sleekmenu/music.wav64,
   then music-2.wav64 to music-8.wav64, with no gaps, each a libdragon
   WAV64 file holding plain 16-bit mono samples. The browser streams the
   one it picked from the card a few kilobytes at a time. Nothing is decoded,
   and nothing is mixed but a volume: the audio interrupt copies the
   samples into each buffer as the hardware takes it, so a frame that takes
   long is not heard. Whether it plays is the
   MUSIC row of the filter page, kept in sleekmenu/music.txt ("on" or
   "off"); a card that says nothing plays it.

   The music stops before a game is loaded, because the load needs the card
   to itself and the game needs the audio hardware as it was at power-on.

   Reading the header and the setting is pure and tested on the host. The
   playback itself only exists in the console build; on the host it keeps
   the state the browser asks about, so the UI tests can see it start and
   stop. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SM_MUSIC_HEADER_SIZE 24u
#define SM_MUSIC_MIN_RATE 8000u
#define SM_MUSIC_MAX_RATE 48000u
/* The most tracks a card holds: music.wav64 and music-2 to music-8. */
#define SM_MUSIC_MAX_TRACKS 8u

typedef struct {
    uint32_t frequency;     /* samples per second */
    uint32_t samples;       /* in the whole track */
    uint32_t data_offset;   /* where the first sample is, from the file's start */
} sm_music_info_t;

/* Whether these are the first bytes of a track this browser can play: a
   WAV64 version 2 header for uncompressed, 16-bit, mono samples at a rate
   the audio hardware takes. `file_size` is the whole file's; a track that
   says it is longer than the file is cut to what the file holds. */
bool sm_music_read_header(const uint8_t *bytes, size_t size, uint32_t file_size,
    sm_music_info_t *info);
/* The setting file's first word: "off" turns the music off, anything else
   leaves it on. */
bool sm_music_setting_from_text(const char *text, size_t length);

/* The path of track `number`, 1 to SM_MUSIC_MAX_TRACKS, from the first
   track's: "-2" to "-8" goes before the extension. False when the number
   is out of range or the path does not fit `size`. */
bool sm_music_track_path(char *out, size_t size, const char *first, unsigned number);
/* Which track to play, 1 to `count`, from a seed; 0 when there is none.
   Every bit of the seed counts, the lowest ones as much as any: two
   seeds a few ticks apart are as likely to pick different tracks as two
   seeds an hour apart. */
unsigned sm_music_pick(unsigned count, uint64_t seed);

/* Find the setting and the tracks, pick one with the tick counter as the
   seed, and start playing it if the setting says so. The tracks are
   counted from the first, each opened, read and closed before the next,
   and the count stops at the first one missing or not playable. */
void sm_music_init(const char *track_path, const char *setting_path);
/* A playable track was found. */
bool sm_music_available(void);
/* How many tracks were found, 0 when none is playable. */
unsigned sm_music_track_count(void);
/* The track picked at start-up, 1 to sm_music_track_count(), 0 when none.
   Turning the music off and on, and a launch that did not happen, keep
   it. */
unsigned sm_music_track(void);
bool sm_music_enabled(void);
bool sm_music_playing(void);
/* Turn it on or off now. Not saved: sm_music_save_setting does that. */
void sm_music_set_enabled(bool on);
bool sm_music_save_setting(const char *path);

/* Once a frame: hands the audio hardware what it has used up, and reads a
   little more of the track ahead -- unless the card is busy listing a
   folder (`card_free` false), when it plays from what it read before. */
void sm_music_poll(bool card_free);
/* Before a game is loaded: fades out, then lets go of the card and the
   audio hardware. Where the track was is kept for sm_music_resume. */
void sm_music_fade_out(void);
/* After a launch that did not happen: plays on from where it stopped,
   the same track. */
void sm_music_resume(void);

#endif
