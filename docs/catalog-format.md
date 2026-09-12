# SleekMenu catalog format v1

All integers are little-endian. The file is a 32-byte header, `record_count` fixed 28-byte records, then one NUL-terminated UTF-8 string table. Offsets in records are relative to the start of the string table. Offset zero always selects the empty string. Readers must bounds-check each offset and find its terminator within the table.

## Header (32 bytes)

| Offset | Type | Meaning |
|---:|---|---|
| 0 | char[4] | `EBC1` magic |
| 4 | u16 | format version (`1`) |
| 6 | u16 | header size (`32`) |
| 8 | u32 | record count |
| 12 | u32 | records offset (`32`) |
| 16 | u32 | strings offset |
| 20 | u32 | string-table size |
| 24 | u32 | IEEE CRC-32 of everything after the header |
| 28 | u32 | format flags; zero in v1 |

## Game record (28 bytes)

| Offset | Type | Meaning |
|---:|---|---|
| 0 | u32 | title string offset |
| 4 | u32 | ROM path string offset |
| 8 | u32 | optional cover path offset |
| 12 | u32 | publisher string offset |
| 16 | u32 | genre string offset |
| 20 | u16 | release year |
| 22 | u8 | player count, 1–4 |
| 23 | u8 | region bits: USA=1, Japan=2, Europe=4 |
| 24 | u8 | flags: favorite=1 |
| 25 | u8[3] | reserved zero padding |

Records are ordered by case-folded normalized ROM path, then title. Identical strings are interned in first-use order, making identical normalized input deterministic. The manifest is not required on-console; it gives staging and release tools the SHA-256, byte size, record size, count, and filenames needed to check a copied catalog.

The on-console missing/invalid-catalog fallback is deliberately not another on-disk format. It holds at most 8,192 discovered ROM entries in memory, supplies empty metadata fields, and is discarded at shutdown/reset. Use `make discover-sd SD_ROOT=...` to persist inferred titles through this catalog format and optionally merge richer user metadata.

A cover string names a `.sprite` entry inside `sd:/sleekmenu/covers.pak`, which the console binary-searches; with `--loose-covers` the same string is a safe relative path beneath `sd:/sleekmenu/covers/`. Either way it is a name, never a path that can escape that folder. Thumbnails are 96x72. The repository contains no redistributable art; `tools/pack_covers.py` converts an explicit mapping of local, user-owned inputs without downloading or scraping anything.
