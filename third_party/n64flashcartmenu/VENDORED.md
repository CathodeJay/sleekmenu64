# N64FlashcartMenu — boot handoff (vendored, unmodified)

Source: https://github.com/Polprzewodnikowy/N64FlashcartMenu
Commit: 6407ab15f6c19d1bf9ded5104c1c8b3c36471379 (tag v0.3.2)
Path:   src/boot/  ->  third_party/n64flashcartmenu/boot/
Files:  boot.c boot.h boot_io.h cic.c cic.h cheats.c cheats.h vr4300_asm.h reboot.S reboot.h

Unmodified, byte for byte; MANIFEST.sha256 pins every file and a host test
verifies it. Nothing else from that project is used — in particular none of
its flashcart drivers, whose EverDrive X-series support is an empty stub
(`ed64_xseries_ll.h` declares nothing and `set_save_type` is a FIXME no-op).
What is used is the generic IPL2->IPL3 handoff, which is hardware-generic.

## LICENCE — READ THIS

N64FlashcartMenu is **AGPL-3.0** (see LICENSE.md). Linking it in makes the
combined ROM a derivative work, so **EverBrowse 64 is AGPL-3.0-only** — see
the top-level LICENSE. That was not a preference; it is what this dependency
requires, and it is the same licence the upstream boot code already ships
under. AGPL section 13 is inert for a cartridge ROM (there is no network
service to interact with), so in practice the terms behave as GPL-3.0: anyone
distributing a modified build must offer complete corresponding source.

The alternative reference, krikzz's `boot_simulator()` in ed64-x-pub, is
GPL-3.0 — also copyleft, and technically weaker: it hardcodes CIC 6102 and
performs no RCP quiesce.

If the licence is unacceptable, the handoff can be rewritten from the
published IPL2->IPL3 register contract; the CIC checksum tables in cic.c are
the part that would take real work to reproduce independently.

## Why one compatibility shim is needed

boot.c uses `C0_STATUS_CU0`, `C0_STATUS_CU1` and `C0_STATUS_FR`, defined in
libdragon's include/cop0.h on the **preview** branch, which N64FlashcartMenu
pins. EverBrowse vendors libdragon **trunk** (494f1f5), where they are absent.
src/boot_compat.h supplies exactly the preview values under `#ifndef` guards
and is injected with -include, so the vendored sources stay byte-for-byte
upstream and a later libdragon upgrade cannot clash (an identical macro
redefinition is legal C).
