/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_ROM_CHECKSUM_H
#define SLEEKMENU_ROM_CHECKSUM_H

/* The checksum the retail boot code verifies before it runs a game.

   IPL3 sums the megabyte that follows it -- 0x1000 to 0x101000 -- and
   compares two words of the result with the two at 0x10 in the header; a
   mismatch stops the console before the game's first instruction, black
   screen. Emulators skip the check, so a hack can ship with the old words
   still in its header and boot everywhere but on hardware. The EverDrive's
   own menu rewrites the words as it loads a game; the browser does the same
   after its load, over cartridge memory (launch.c), and tools/n64_checksum.py
   is the same sum on the computer.

   Each boot code seeds the sum differently, and the 6105 folds bytes of
   its own code into every step, so the caller says which CIC the boot code
   is (launch_policy.c decides that by the boot code's CRC). Written from
   the public description of the algorithm; nothing vendored. Pure: the
   megabyte arrives through a reader callback, so the console can sum
   cartridge memory a few KiB at a time without a buffer for the whole. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SM_CHECKSUM_START 0x1000u
#define SM_CHECKSUM_LENGTH 0x100000u
/* The boot code, as the 6105 sum reads it: the 0xFC0 bytes from 0x40. */
#define SM_CHECKSUM_BOOT_OFFSET 0x40u
#define SM_CHECKSUM_BOOT_LENGTH 0xFC0u
/* The two words, big-endian, at this offset in the header. */
#define SM_CHECKSUM_WORDS_OFFSET 0x10u

/* Fill `dst` with `bytes` bytes of the image from `offset`; false on a
   read failure, which abandons the sum. */
typedef bool (*sm_checksum_reader_t)(uint32_t offset, void *dst, uint32_t bytes, void *context);

/* The sum for a boot code of the given CIC (6101, 6102, 6103, 6105, 6106;
   anything else is refused with false). `boot` is the boot code as loaded,
   SM_CHECKSUM_BOOT_LENGTH bytes; the reader supplies the megabyte. */
bool sm_checksum_compute(unsigned cic, const uint8_t *boot, sm_checksum_reader_t read,
    void *context, uint32_t words[2]);

/* The two words in a big-endian header, and the same two bytes-out. */
void sm_checksum_header_words(const uint8_t *header, uint32_t words[2]);
void sm_checksum_encode(const uint32_t words[2], uint8_t out[8]);

#endif
