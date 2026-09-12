/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_BOOT_COMPAT_H
#define SLEEKMENU_BOOT_COMPAT_H

/* The vendored N64FlashcartMenu boot code is written against libdragon's
   preview branch, which defines these in include/cop0.h. SleekMenu vendors
   trunk (494f1f5), where they are absent. Values are copied exactly from
   preview cop0.h lines 324-327, so if a later libdragon does define them the
   redefinition is identical and therefore legal C rather than a -Werror stop.

     0x04000000  FR   FPU register mode
     0x10000000  CU0  coprocessor 0 usable
     0x20000000  CU1  coprocessor 1 usable

   Supplied via -include so the vendored sources stay byte-for-byte upstream. */
#ifndef C0_STATUS_FR
#define C0_STATUS_FR 0x04000000
#endif
#ifndef C0_STATUS_CU0
#define C0_STATUS_CU0 0x10000000
#endif
#ifndef C0_STATUS_CU1
#define C0_STATUS_CU1 0x20000000
#endif

#endif
