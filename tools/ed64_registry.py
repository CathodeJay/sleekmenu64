#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Read, verify and rewrite the EverDrive-64 X7 stock menu's registry.dat.

ED64/sysdata/registry.dat is how the stock firmware (OS 3.11) remembers what it
last launched and, on the next menu boot, what to flush out of the cartridge's
save hardware into ED64/gamedata/. It is undocumented; the layout below was
determined by diffing snapshots taken from a real card, which live in
tests/fixtures/registry/. Fields marked provisional matched every sample but have not
been proved by a controlled experiment.

    [   0 .. 1023]  last launched ROM path, NUL terminated. The menu writes the
                    new path over the old one WITHOUT clearing the tail, so a
                    shorter path leaves readable garbage behind it.
    [1024 .. 1027]  zero in every sample
    [1028 .. 1031]  ROM header CRC1 (header 0x10), copied verbatim
    [1032 .. 1035]  ROM header CRC2 (header 0x14), copied verbatim
    [1036 .. 1039]  PI DOM1 timing, 40 12 07 03 in every sample. This is the
                    cartridge's timing, not the ROM's: Super Mario 64's header
                    says 80 37 12 40 and the registry still says 40 12 07 03.
    [1040 .. 1045]  six-symbol ROM id: header 0x3B..0x3E as characters, with
                    unprintable bytes rendered '?', then header 0x3F as two
                    uppercase hex digits. "NSME00" for Super Mario 64 (USA).
    [1048 .. 1049]  SAVE TYPE, big endian u16. krikzz's SAVE_* id -- the same
                    value the menu writes to REG_GAM_CFG, so 0=off, 1=EEP4K,
                    2=EEP16K, 3=SRM32K, 4=SRM96K, 5=FLASH, 6=SRM128K. This is
                    the field that decides whether a save is written back at
                    all, and which extension and length it gets.
                    PROVEN, not inferred: sample-03 was rewritten with this one
                    byte changed from 1 to 3 and nothing else, and the firmware
                    responded by writing a 32768 byte
                    "Super Mario 64 (USA).srm" -- sample-04.
    [1050 .. 1051]  CIC index, provisional. 1 for Super Mario 64 (CIC-6102),
                    3 for both libdragon ROMs, whose IPL3 the menu cannot
                    fingerprint.
    [1052 .. 1053]  2 in every sample
    [1060 .. 1063]  01 01 01 01 in every sample
    [1064 .. 1071]  browser cursor stack: one u16 per directory level of the
                    path. A root-level ROM sets only the first. Cleared when
                    the menu is left sitting at the root, which is what made
                    this look like an "armed" flag being consumed.
    [1196 ..     ]  the CURRENT browser selection, not a second copy of the
                    record. It happens to equal the path at offset 0 right
                    after a launch, which is why the two looked like one field.
                    Booting the menu and touching nothing clears it while the
                    path at offset 0 and the save type both survive.
    [2223 .. 2251]  menu settings
    [2252 .. 2255]  CRC-32 (zlib, big endian) over bytes [0:2252]

The CRC is the load-bearing discovery: it matched every sample exactly, which
means the file can be rewritten and the firmware will accept it. Without that,
cooperating with the stock menu would not have been possible.

The record is NOT consumed. The firmware rewrites the save file on every menu
boot from the path at offset 0 and the save type, until a launch replaces them.
Anything cooperating with it should therefore skip writing a file whose bytes
have not changed.

ED64/sysdata/recent.dat is a different, simpler thing and holds nothing we
need: 20 records of 1025 bytes, each a NUL terminated path in a 1024 byte field
plus one trailing byte that is only ever a leftover of a longer previous path.
It drives the menu's recent list and nothing else.
"""
from __future__ import annotations
import argparse, struct, sys, zlib
from pathlib import Path

SIZE = 2256
CRC_AT = 2252
PATH_A, PATH_A_MAX = 0, 1024
# The short field's true length is unknown; every sample zero-fills past it
# and [1217:2223] is empty in each, so 256 is safe to read and to clear.
PATH_B, PATH_B_MAX = 1196, 256
ROM_CRC_AT = 1028
DOM1_AT, ID_AT, ID_LEN = 1036, 1040, 6
SAVE_TYPE_AT = 1048
CIC_AT = 1050

# krikzz's save-type ids, from ed64-x-pub docs/rom_config_database.md and
# ED64-XIO/inc/bios.h. Shared with src/save_type.h -- keep the two in step.
SAVE_TYPES = {0: "OFF", 1: "EEP4K", 2: "EEP16K", 3: "SRM32K",
              4: "SRM96K", 5: "FLASH", 6: "SRM128K"}
# What the stock firmware calls the file it writes into ED64/gamedata/.
SAVE_EXT = {0: None, 1: ".eep", 2: ".eep", 3: ".srm",
            4: ".srm", 5: ".fla", 6: ".srm"}
# Bytes the firmware writes for each id. .eep at 512 and .srm at 32768 were
# both observed on the card; the rest follow the parts they name.
SAVE_BYTES = {0: 0, 1: 512, 2: 2048, 3: 32768, 4: 98304, 5: 131072, 6: 131072}


def crc(payload: bytes) -> int:
    return zlib.crc32(payload) & 0xFFFFFFFF


def verify(blob: bytes) -> bool:
    return (len(blob) == SIZE
            and struct.unpack(">I", blob[CRC_AT:])[0] == crc(blob[:CRC_AT]))


def read_str(blob: bytes, at: int, cap: int) -> str:
    end = blob.find(b"\0", at, at + cap)
    return blob[at:(end if end >= 0 else at + cap)].decode("latin-1")


def u16(blob: bytes, at: int) -> int:
    return struct.unpack_from(">H", blob, at)[0]


def describe(blob: bytes) -> str:
    ok = "OK" if verify(blob) else "MISMATCH"
    save = u16(blob, SAVE_TYPE_AT)
    name = SAVE_TYPES.get(save, f"?{save}")
    ext = SAVE_EXT.get(save) or "(no writeback)"
    return (f"size      {len(blob)}\n"
            f"crc32     {struct.unpack('>I', blob[CRC_AT:])[0]:08X} ({ok})\n"
            f"path      {read_str(blob, PATH_A, PATH_A_MAX)!r}\n"
            f"path(alt) {read_str(blob, PATH_B, PATH_B_MAX)!r}\n"
            f"rom id    {blob[ID_AT:ID_AT + ID_LEN].decode('latin-1')!r}\n"
            f"rom crc   {blob[ROM_CRC_AT:ROM_CRC_AT + 4].hex().upper()}"
            f" {blob[ROM_CRC_AT + 4:ROM_CRC_AT + 8].hex().upper()}\n"
            f"save type {save} {name} -> {ext}"
            f"{'' if not SAVE_BYTES.get(save) else f' ({SAVE_BYTES[save]} bytes)'}\n"
            f"cic       {u16(blob, CIC_AT)}\n"
            f"pi dom1   {' '.join(f'{b:02X}' for b in blob[DOM1_AT:DOM1_AT + 4])}")


def rewrite(blob: bytes, path: str | None = None, rom_id: str | None = None,
            save_type: int | None = None, rom_crc: bytes | None = None) -> bytes:
    """Point the stock menu's writeback at another ROM, leaving the rest be."""
    out = bytearray(blob)
    if path is not None:
        raw = path.encode("latin-1")
        if len(raw) >= PATH_B_MAX:
            raise ValueError(
                f"path is {len(raw)} bytes; the short field holds {PATH_B_MAX - 1}")
        # Clear then write, so no tail of a longer previous path survives. The
        # firmware itself does not bother, but a clean field is easier to diff.
        out[PATH_A:PATH_A + PATH_A_MAX] = b"\0" * PATH_A_MAX
        out[PATH_A:PATH_A + len(raw)] = raw
        out[PATH_B:PATH_B + PATH_B_MAX] = b"\0" * PATH_B_MAX
        out[PATH_B:PATH_B + len(raw)] = raw
    if rom_id is not None:
        if len(rom_id) != ID_LEN:
            raise ValueError(f"rom id must be exactly {ID_LEN} symbols")
        out[ID_AT:ID_AT + ID_LEN] = rom_id.encode("latin-1")
    if save_type is not None:
        if save_type not in SAVE_TYPES:
            raise ValueError(f"save type must be one of {sorted(SAVE_TYPES)}")
        struct.pack_into(">H", out, SAVE_TYPE_AT, save_type)
    if rom_crc is not None:
        if len(rom_crc) != 8:
            raise ValueError("rom crc must be the 8 header bytes at 0x10")
        out[ROM_CRC_AT:ROM_CRC_AT + 8] = rom_crc
    out[CRC_AT:] = struct.pack(">I", crc(bytes(out[:CRC_AT])))
    return bytes(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("registry", type=Path)
    p.add_argument("--set-path", help="rewrite the last-launched ROM path")
    p.add_argument("--set-id", help="rewrite the six-symbol ROM id")
    p.add_argument("--set-save-type", type=int, metavar="N",
                   help="rewrite the save type: " +
                        ", ".join(f"{k}={v}" for k, v in SAVE_TYPES.items()))
    p.add_argument("--set-rom-crc", metavar="HEX16",
                   help="rewrite the ROM's header CRC pair, 16 hex digits")
    p.add_argument("--output", type=Path, help="write the result here (never in place)")
    a = p.parse_args(argv)

    blob = a.registry.read_bytes()
    if len(blob) != SIZE:
        print(f"expected {SIZE} bytes, got {len(blob)}", file=sys.stderr)
        return 1
    if not verify(blob):
        print("refusing to work on a file whose CRC does not verify", file=sys.stderr)
        return 1
    print(describe(blob))

    edits = (a.set_path, a.set_id, a.set_save_type, a.set_rom_crc)
    if any(e is not None for e in edits):
        rom_crc = bytes.fromhex(a.set_rom_crc) if a.set_rom_crc else None
        out = rewrite(blob, a.set_path, a.set_id, a.set_save_type, rom_crc)
        assert verify(out), "rewritten file failed its own CRC check"
        if a.output:
            a.output.write_bytes(out)
            print(f"\nwrote {a.output}")
        print("\n--- after ---")
        print(describe(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
