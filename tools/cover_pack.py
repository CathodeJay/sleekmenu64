#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""One file for all the box art, with an index the console reads once.

745 loose sprites in one directory is what a card looked like before this, and
it is slower than it sounds. FatFs has no directory index: opening
`sleekmenu/covers/007 - The World Is Not Enough (Europe) (En,Fr,De).sprite`
walks the directory from the start, and long filenames cost four or five
32-byte entries each, so 745 covers is well over 100 KB of directory to read
before the first byte of the picture. Twice per cover, as it happened, because
existence was probed before the load. That is the visible pause between moving
the cursor and the art appearing.

A pack replaces the walk with one seek. The index is 16 bytes per cover, read
once at startup and kept in RAM; a lookup is a binary search over sorted
64-bit name hashes. It also makes the card one file to copy rather than 745,
which matters more than it sounds on a slow reader.

    offset  0   magic "EBCP"
            4   u32 version
            8   u32 count
           12   u32 index offset
           16   u32 names offset      (host tooling only; the console ignores it)
           20   u32 names length
           24   u32 payload offset
           28   u32 reserved
           32   index: count x { u64 hash, u32 offset, u32 length }
                payloads, each aligned to 8
                names, NUL-terminated, in index order
       end -4   u32 CRC-32 of everything before it

Everything is big-endian, like the catalog and like the console.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"EBCP"
VERSION = 1
HEADER_SIZE = 32
ENTRY_SIZE = 16
ALIGN = 8
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
MASK64 = 0xFFFFFFFFFFFFFFFF


class CoverPackError(ValueError):
    pass


@dataclass(frozen=True)
class PackEntry:
    name: str
    hash: int
    offset: int
    length: int


def cover_hash(name: str) -> int:
    """FNV-1a over the lowercased name. Lowercased because a card formatted
    exFAT is case-insensitive and nobody should have to care which case the
    catalog happened to record."""
    digest = FNV_OFFSET
    for byte in name.casefold().encode("utf-8"):
        digest = ((digest ^ byte) * FNV_PRIME) & MASK64
    return digest


def _align(value: int) -> int:
    return (value + ALIGN - 1) & ~(ALIGN - 1)


def build(covers: dict[str, bytes]) -> bytes:
    """covers maps cover name (as the catalog spells it) to sprite bytes."""
    if not covers:
        raise CoverPackError("refusing to build an empty cover pack")
    names = sorted(covers, key=lambda name: (cover_hash(name), name))
    hashes = [cover_hash(name) for name in names]
    for first, second in zip(hashes, hashes[1:]):
        if first == second:
            raise CoverPackError("two cover names hash to the same value; rename one")

    index_offset = HEADER_SIZE
    payload_offset = _align(index_offset + ENTRY_SIZE * len(names))
    payloads, offsets, cursor = [], [], payload_offset
    for name in names:
        data = covers[name]
        offsets.append(cursor)
        payloads.append(data)
        cursor = _align(cursor + len(data))
    names_offset = cursor
    names_blob = b"".join(name.encode("utf-8") + b"\0" for name in names)

    body = bytearray()
    body += struct.pack(">4sIIIIIII", MAGIC, VERSION, len(names), index_offset,
                        names_offset, len(names_blob), payload_offset, 0)
    for name_hash, offset, data in zip(hashes, offsets, payloads):
        body += struct.pack(">QII", name_hash, offset, len(data))
    for offset, data in zip(offsets, payloads):
        body += b"\0" * (offset - len(body))
        body += data
    body += b"\0" * (names_offset - len(body))
    body += names_blob
    return bytes(body) + struct.pack(">I", zlib.crc32(bytes(body)) & 0xFFFFFFFF)


def read_index(blob: bytes) -> list[PackEntry]:
    """Parse a pack, verifying its checksum. Used by the tests and by anyone
    wanting to know what is actually on a card."""
    if len(blob) < HEADER_SIZE + 4:
        raise CoverPackError("cover pack is too small to contain a header")
    if zlib.crc32(blob[:-4]) & 0xFFFFFFFF != struct.unpack(">I", blob[-4:])[0]:
        raise CoverPackError("cover pack checksum does not match its contents")
    magic, version, count, index_offset, names_offset, names_length, payload_offset, _ = \
        struct.unpack_from(">4sIIIIIII", blob, 0)
    if magic != MAGIC:
        raise CoverPackError(f"not a cover pack: magic is {magic!r}")
    if version != VERSION:
        raise CoverPackError(f"cover pack version {version}, expected {VERSION}")
    if index_offset + ENTRY_SIZE * count > len(blob):
        raise CoverPackError("cover pack index runs past the end of the file")
    names = blob[names_offset:names_offset + names_length].split(b"\0")
    entries = []
    for number in range(count):
        name_hash, offset, length = struct.unpack_from(">QII", blob, index_offset + ENTRY_SIZE * number)
        if offset < payload_offset or offset + length > len(blob) - 4:
            raise CoverPackError(f"entry {number} points outside the pack")
        name = names[number].decode("utf-8") if number < len(names) else ""
        if name and cover_hash(name) != name_hash:
            raise CoverPackError(f"entry {number} name {name!r} does not match its hash")
        entries.append(PackEntry(name, name_hash, offset, length))
    if any(a.hash >= b.hash for a, b in zip(entries, entries[1:])):
        raise CoverPackError("cover pack index is not sorted; the console binary-searches it")
    return entries


def read_cover(blob: bytes, name: str) -> bytes | None:
    """One sprite out of a pack, by the name the catalog gives it; None when
    the pack has no such cover. The index is walked the way the console
    walks it, by hash."""
    wanted = cover_hash(name)
    for entry in read_index(blob):
        if entry.hash == wanted:
            return blob[entry.offset:entry.offset + entry.length]
    return None


def pack_directory(source: Path, destination: Path) -> tuple[int, int]:
    """Every .sprite in a directory, keyed by filename as the catalog names it."""
    sprites = sorted(source.glob("*.sprite"), key=lambda p: (p.name.casefold(), p.name))
    if not sprites:
        raise CoverPackError(f"no .sprite files under {source}")
    blob = build({path.name: path.read_bytes() for path in sprites})
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(blob)
    return len(sprites), len(blob)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pack a covers directory into covers.pak.")
    parser.add_argument("source", type=Path, help="a directory of .sprite files")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--list", action="store_true", help="read the result back and list it")
    args = parser.parse_args(argv)
    try:
        count, size = pack_directory(args.source, args.output)
        if args.list:
            for entry in read_index(args.output.read_bytes()):
                print(f"  {entry.length:7}  {entry.name}")
    except (CoverPackError, OSError) as exc:
        parser.error(str(exc))
    print(f"{count} covers -> {args.output} ({size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
