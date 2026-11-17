/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_PERF_H
#define SLEEKMENU_PERF_H

/* make perf builds with SM_SHOW_FRAME_TIME, for measuring on a console.
   SM_PERF(...) is code for that build alone, and nothing in any other.

   It goes at the end of a line that is already there. The released ROM
   carries the source line of every function, for its crash screen, so a
   line added above a function changes the ROM even when the preprocessor
   drops it. Whatever else the measuring build needs goes after a file's
   last function, or in a header. */
#ifdef SM_SHOW_FRAME_TIME
#define SM_PERF(...) __VA_ARGS__
#else
#define SM_PERF(...)
#endif

#endif
