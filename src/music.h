/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_MUSIC_H
#define SLEEKMENU_MUSIC_H

/* Background music: one track on the card, looped while the browser runs.

   The Game Catalog Manager writes the track as sleekmenu/music.wav64, a
   libdragon WAV64 file holding plain 16-bit mono samples, and the browser
   streams it from the card a few kilobytes at a time. Nothing is decoded:
   samples are copied into the mixer as they are. Whether it plays is the
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

/* Find the track and the setting, and start playing if both say so. */
void sm_music_init(const char *track_path, const char *setting_path);
/* A playable track was found. */
bool sm_music_available(void);
bool sm_music_enabled(void);
bool sm_music_playing(void);
/* Turn it on or off now. Not saved: sm_music_save_setting does that. */
void sm_music_set_enabled(bool on);
bool sm_music_save_setting(const char *path);

/* Once a frame: hands the audio hardware what it has used up. */
void sm_music_poll(void);
/* Before a game is loaded: fades out, then lets go of the card and the
   audio hardware. Where the track was is kept for sm_music_resume. */
void sm_music_fade_out(void);
/* After a launch that did not happen: plays on from where it stopped. */
void sm_music_resume(void);

#endif
