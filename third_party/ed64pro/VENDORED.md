# ed64-pro-pub — EverDrive-64 Pro cartridge access (vendored, unmodified)

Source: https://github.com/krikzz/ed64-pro-pub
Commit: 5d7e96905331a841f97f8c51e0b0cba878e72fe3 (2026-08-04)
Path:   edio/  ->  third_party/ed64pro/edio/
Files:  appmain.h everdrive.c everdrive.h n64.c n64.h netgate.h types.h errors.h

Unmodified, byte for byte; MANIFEST.sha256 pins every file and a host test
verifies it. This is krikzz's own reference for talking to the Pro: the FIFO
command protocol to the onboard MCU that owns the SD card and the filesystem,
the "FCI" cartridge-memory transfers, device configuration (backup RAM type,
64DD, RTC), and the sys-info queries. Nothing else from the sample is used:
`appmain.c` is the demo menu, `netgate.c` the USB internet demo, and neither
is compiled. `netgate.h` is here only because `appmain.h` includes it and
`appmain.h` is what `everdrive.c` includes.

## Licence

MIT (see LICENSE), copyright 2026 krikzz. Compatible with the project's
AGPL-3.0-only; the combined ROM stays AGPL-3.0 because of the boot handoff
vendored from N64FlashcartMenu, not because of anything here.

## Why the Pro needs this and the X7 does not

The X7 exposes its SD card to the console as a plain SPI-over-registers
device, which libdragon's libcart already drives; SleekMenu reads the card
through libdragon's filesystem and never touches an EverDrive register except
to set the save type. The Pro exposes no SD interface at all. An MCU on the
cartridge mounts the card, and the console asks it -- open this path, list
this folder, copy this file into cartridge memory -- over a 2 KB FIFO at
0x1F800000. There is no libcart driver for it and no other open
implementation; this is the protocol as its author wrote it.

## Things to know

`types.h` defines `u8`, `u16`, `u32`, `s32` and friends as bare macros
(`#define u32 unsigned long`). Anything including `everdrive.h` inherits
them, so only the Pro backend includes it, through `appmain.h`, and nothing
in `src/` outside that backend does.

`n64.c` provides `pi_rd`/`pi_wr` on top of libdragon's `dma_read_raw_async`
and `dma_write_raw_async`, which exist on trunk (494f1f5) as well as on the
preview branch the sample was built against.
