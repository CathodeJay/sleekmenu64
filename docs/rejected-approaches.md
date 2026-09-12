# Approaches that were tried and abandoned

Negative results, kept because each one cost real time to discover and the
next person to have the same idea deserves the shortcut. None of this code
is in the tree any more; this is the reasoning, not the implementation.

## A hand-rolled X7 SD register driver

An EverDrive-64 X7 SD driver written directly against the cartridge
registers, used to stream ROM data.

**Why it was dropped.** It duplicated libcart's `edx_*` driver, which
libdragon already links and initialises through `debug_init_sdfs()`. Running
both at once corrupts libcart's private SD direction-latch cache, after which
its untimed poll loops hang. It also re-locked `EDX_KEY_REG`, which libcart
never re-unlocks.

If you are tempted to talk to the SD hardware directly, check what libcart is
already doing to it first. Two drivers on one bus is not a performance
question, it is a correctness one.

## A FAT/exFAT cluster-chain planner

Code that walked the filesystem's cluster chains to compute physical LBAs, so
that `cart_card_rd_cart()` could be handed a contiguous run and stream a ROM
into cartridge RAM without the filesystem layer in the way.

**Why it was dropped.** Unnecessary. `f_read()` with a cartridge destination
pointer already routes through libdragon's `disk_read_sdram` dispatch, which
handles fragmentation itself. The planner was solving a problem the layer
below had already solved.

## Box art compiled into the ROM

Cover images were converted to sprites at build time and emitted as a
915-entry name-to-sprite index in a generated `src/embedded_covers.c`.

**Why it was dropped.** Three independent reasons, any one of which was
enough:

- The generated table only gave correct answers for the single art collection
  that produced it. Anyone with a different pack got sprite numbers that meant
  nothing — the exact opposite of the portability this project wants.
- It cost about 10 MB of ROM.
- `make slim` could not build at all unless that specific art collection was
  present on disk, which made the build unreproducible for everyone else.

Covers now live on the card as a cover pack (`covers.pak`), matched once on a
desktop against `data/coverdb.csv`. See `docs/CARD_LAYOUT.md`.
