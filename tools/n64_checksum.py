#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""The checksum the N64's boot code verifies, and the repair of a hack whose
author never recomputed it.

The retail boot code (IPL3) sums the first megabyte of the game, starting
right after itself at 0x1000, and compares the two words it gets with the
two at 0x10 in the header. A mismatch stops the console before the game's
first instruction, black screen; emulators skip the check, which is how a
hack ships with the old words still in its header and boots everywhere but
on hardware. The EverDrive's own menu quietly rewrites the words as it
loads; SleekMenu does the same at launch (src/launch.c), and this module is
the same sum on the computer, for the report the prep tool prints and for
`--fix-checksums`.

The sum depends on the boot code: each CIC variant seeds it differently, and
the 6105 folds bytes of its own boot code into every step. Which one a ROM
carries is decided the way the browser decides it, by the CRC-32 of the boot
code. A ROM with a boot code none of the five retail CRCs match -- homebrew,
a re-signed boot code -- has its own rules and is left alone.

    python3 tools/n64_checksum.py Game.z64          # prints header and computed
    python3 tools/n64_checksum.py --fix Game.z64    # rewrites the header in place

Public algorithm, written from its description; no code is vendored.
"""
from __future__ import annotations

import argparse
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import rom_header

BOOT_CODE_OFFSET = 0x40
BOOT_CODE_LENGTH = 0xFC0
SUM_START = 0x1000
SUM_LENGTH = 0x100000
#: Bytes a file must hold for the sum to be defined: the header, the boot
#: code and the whole summed megabyte.
NEEDED = SUM_START + SUM_LENGTH

MASK = 0xFFFFFFFF

#: The boot code, by the CRC-32 of its 0xFC0 bytes, exactly as
#: src/launch_policy.c names it.
CIC_BY_BOOT_CRC = {
    0x6170A4A1: 6101,
    0x90BB6CB5: 6102,
    0x0B050EE0: 6103,
    0x98BC2C86: 6105,
    0xACC8580A: 6106,
}

#: The value every accumulator starts from, per boot code. 6101 and 6102
#: (and their PAL twins 7102 and 7101) share one.
SEED = {6101: 0xF8CA4DDC, 6102: 0xF8CA4DDC, 6103: 0xA3886759, 6105: 0xDF26F436, 6106: 0x1FEA617A}


class ChecksumError(ValueError):
    pass


@dataclass(frozen=True)
class Verdict:
    cic: int                 # 6101..6106, or 0 for a boot code the table does not know
    header: tuple[int, int]  # the two words in the header
    computed: tuple[int, int] | None   # None when the boot code is unknown

    @property
    def matches(self) -> bool:
        return self.computed is not None and self.computed == self.header

    @property
    def known(self) -> bool:
        return self.computed is not None


def _rol(value: int, bits: int) -> int:
    bits &= 31
    return ((value << bits) | (value >> (32 - bits))) & MASK if bits else value


def cic_of(rom: bytes) -> int:
    """Which retail boot code the (big-endian) image carries, or 0."""
    if len(rom) < BOOT_CODE_OFFSET + BOOT_CODE_LENGTH:
        return 0
    crc = zlib.crc32(rom[BOOT_CODE_OFFSET:BOOT_CODE_OFFSET + BOOT_CODE_LENGTH]) & MASK
    return CIC_BY_BOOT_CRC.get(crc, 0)


def compute(rom: bytes, cic: int) -> tuple[int, int]:
    """The two words the boot code expects at 0x10, over a big-endian image
    of at least NEEDED bytes."""
    if len(rom) < NEEDED:
        raise ChecksumError(f"image is {len(rom)} bytes; the checksum covers the first {NEEDED}")
    if cic not in SEED:
        raise ChecksumError(f"no checksum rules for CIC {cic}")
    seed = SEED[cic]
    t1 = t2 = t3 = t4 = t5 = t6 = seed
    words = memoryview(rom)
    boot = rom[BOOT_CODE_OFFSET:BOOT_CODE_OFFSET + BOOT_CODE_LENGTH]
    for i in range(SUM_START, SUM_START + SUM_LENGTH, 4):
        d = int.from_bytes(words[i:i + 4], "big")
        summed = (t6 + d) & MASK
        if summed < t6:
            t4 = (t4 + 1) & MASK
        t6 = summed
        t3 ^= d
        r = _rol(d, d & 0x1F)
        t5 = (t5 + r) & MASK
        if t2 > d:
            t2 ^= r
        else:
            t2 ^= t6 ^ d
        if cic == 6105:
            # The 6105 mixes in its own boot code: the word at 0x0710 of it,
            # stepping through a 256-byte window as the position advances.
            k = 0x0710 + (i & 0xFF)
            t1 = (t1 + (int.from_bytes(boot[k:k + 4], "big") ^ d)) & MASK
        else:
            t1 = (t1 + (t5 ^ d)) & MASK
    if cic == 6103:
        return ((t6 ^ t4) + t3) & MASK, ((t5 ^ t2) + t1) & MASK
    if cic == 6106:
        return (t6 * t4 + t3) & MASK, (t5 * t2 + t1) & MASK
    return (t6 ^ t4 ^ t3) & MASK, (t5 ^ t2 ^ t1) & MASK


def native(data: bytes) -> bytes:
    """The image in big-endian order, whatever order the file is in."""
    form = rom_header.MAGIC.get(bytes(data[:4]))
    if form is None:
        raise ChecksumError("not an N64 ROM: no header magic")
    return rom_header.deswap(data, form)


def verify(path: Path) -> Verdict:
    """Read what the sum needs and compare. Only the first NEEDED bytes are
    read, whatever the file's size."""
    with path.open("rb") as handle:
        data = handle.read(NEEDED)
    rom = native(data)
    header = (int.from_bytes(rom[0x10:0x14], "big"), int.from_bytes(rom[0x14:0x18], "big"))
    cic = cic_of(rom)
    if not cic or len(rom) < NEEDED:
        return Verdict(cic, header, None)
    return Verdict(cic, header, compute(rom, cic))


def fix(path: Path) -> Verdict:
    """Rewrite the header's two words in place, in the file's own byte
    order. Returns the verdict from before the write; nothing is written
    when it already matched or the boot code is unknown."""
    verdict = verify(path)
    if verdict.matches or not verdict.known:
        return verdict
    with path.open("r+b") as handle:
        form = rom_header.MAGIC[bytes(handle.read(4))]
        words = verdict.computed[0].to_bytes(4, "big") + verdict.computed[1].to_bytes(4, "big")
        handle.seek(0x10)
        handle.write(rom_header.deswap(words, form))
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roms", type=Path, nargs="+", help="ROM files to check")
    parser.add_argument("--fix", action="store_true", help="rewrite a header that does not match")
    args = parser.parse_args(argv)
    bad = 0
    for path in args.roms:
        try:
            verdict = fix(path) if args.fix else verify(path)
        except (ChecksumError, OSError) as error:
            print(f"{path}: {error}", file=sys.stderr)
            bad += 1
            continue
        if not verdict.known:
            state = "unknown boot code, not checked"
        elif verdict.matches:
            state = "ok"
        else:
            state = "fixed" if args.fix else "MISMATCH"
            bad += not args.fix
        print(f"{path}: CIC {verdict.cic or '?'} header {verdict.header[0]:08X} {verdict.header[1]:08X}"
              + (f" computed {verdict.computed[0]:08X} {verdict.computed[1]:08X}" if verdict.known else "")
              + f" {state}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
