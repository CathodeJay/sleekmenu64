#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Generate src/rom_db.c/.h from the ares N64 save-type database.

The stock EverDrive firmware carries a save-type database inside OS64.v64;
save_db.txt only holds per-user overrides on top of it. SleekMenu needs an
equivalent or it resolves almost every game to "no save". ares is the same
source N64FlashcartMenu uses, and is ISC licensed rather than AGPL.
"""
from __future__ import annotations
import argparse, re, sys, urllib.request
from pathlib import Path

SOURCE = "https://raw.githubusercontent.com/ares-emulator/ares/master/mia/medium/nintendo-64.cpp"

# ares size -> krikzz REG_GAM_CFG save-type id (ED64-XIO/inc/bios.h)
EEPROM = {"512": 1, "2_KiB": 2}
SRAM = {"32_KiB": 3, "96_KiB": 4, "128_KiB": 6}
FLASH = {"128_KiB": 5}
FEAT = {"cpak": 1, "rpak": 2, "tpak": 4, "rtc": 8}

# ares expresses a handful of games as multi-line blocks with region/revision
# branches. Parsing arbitrary C++ conditionals is not worth it, so these are
# transcribed explicitly -- and the generator refuses to run if the set of
# multi-line blocks in the source ever stops matching this table, so a new one
# fails loudly instead of being silently dropped (which is how Super Mario 64
# went missing from the first generated database).
#   id: [(region or None, rev_max or None, save, feat), ...]  first match wins
SPECIAL = {
    "N3H": [("J", None, 3, 2), (None, None, 0, 3)],   # International Track & Field
    "ND3": [("J", None, 2, 2), (None, None, 0, 1)],   # Castlevania
    "ND4": [("J", None, 2, 2), (None, None, 0, 1)],   # Castlevania: Legacy of Darkness
    "NSM": [(None, None, 1, 0)],                      # Super Mario 64
    "NWR": [(None, None, 1, 1)],                      # Wave Race 64
    "NK4": [("J", 1, 3, 2), (None, None, 2, 2)],      # Kirby 64: The Crystal Shards
    "NWT": [("J", None, 1, 0), (None, None, 0, 1)],   # Wetrix
}

MULTILINE = re.compile(r'^[ \t]*if\(id == "([A-Z0-9]{3})"[^}\n]*\{[ \t]*$', re.M)

ENTRY = re.compile(
    r'^\s*if\(id == "(?P<id>[A-Z0-9]{3})"'
    r'(?:\s*&&\s*region_code == \'(?P<region>[A-Z])\')?\s*\)\s*\{(?P<body>[^}]*)\}'
    r'(?:\s*//\s*(?P<comment>.*?))?\s*$')

def parse(text: str):
    found = set(MULTILINE.findall(text))
    if found != set(SPECIAL):
        raise SystemExit(
            "ares multi-line entries changed; update SPECIAL in this script.\n"
            f"  in source but not transcribed: {sorted(found - set(SPECIAL))}\n"
            f"  transcribed but not in source: {sorted(set(SPECIAL) - found)}")
    out = []
    for rom_id, variants in SPECIAL.items():
        for region, rev_max, save, feat in variants:
            out.append((rom_id, region or "\\0", save, feat,
                        255 if rev_max is None else rev_max, "special case"))
    for line in text.splitlines():
        m = ENTRY.match(line)
        if not m:
            continue
        body, save, feat = m.group("body"), 0, 0
        for kind, table in (("eeprom", EEPROM), ("sram", SRAM), ("flash", FLASH)):
            v = re.search(rf'\b{kind}\s*=\s*([0-9_A-Za-z]+)', body)
            if v and v.group(1) in table:
                save = table[v.group(1)]
        for name, bit in FEAT.items():
            if re.search(rf'\b{name}\s*=\s*true', body):
                feat |= bit
        if save == 0 and feat == 0:
            continue  # nothing worth storing
        if m.group("id") in SPECIAL:
            continue  # transcribed above, with its branches
        out.append((m.group("id"), m.group("region") or "\\0", save, feat, 255,
                    (m.group("comment") or "").strip()[:58]))
    # deterministic, and most specific first so the first match wins:
    # region+revision, then region, then generic
    out.sort(key=lambda e: (e[0], e[1] == "\\0", e[4] == 255))
    return out

ISC_NOTICE = """/* SPDX-License-Identifier: ISC
 *
 * Derived from the Nintendo 64 save-type database in the ares emulator
 * (mia/medium/nintendo-64.cpp). ares is ISC licensed and its notice is
 * retained here as that licence requires:
 *
 *   Copyright (c) 2004-2025 ares team, Near et al
 *
 *   Permission to use, copy, modify, and/or distribute this software for any
 *   purpose with or without fee is hereby granted, provided that the above
 *   copyright notice and this permission notice appear in all copies.
 *
 *   THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
 *   WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
 *   MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
 *   ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
 *   WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
 *   ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
 *   OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
 */
"""


def emit(entries, header: Path, source: Path, origin: str):
    header.write_text(f'''{ISC_NOTICE}#ifndef SLEEKMENU_ROM_DB_H
#define SLEEKMENU_ROM_DB_H

/* GENERATED by tools/build_rom_db.py -- do not edit by hand.
   Source: {origin}
   ares is ISC licensed. Save-type ids are krikzz's REG_GAM_CFG values. */

#include <stddef.h>
#include <stdint.h>

#define SM_FEAT_CPAK 1u  /* Controller Pak */
#define SM_FEAT_RPAK 2u  /* Rumble Pak */
#define SM_FEAT_TPAK 4u  /* Transfer Pak */
#define SM_FEAT_RTC 8u   /* real time clock */

typedef struct {{
    char id[3];      /* ROM header bytes 0x3B..0x3D */
    char region;     /* header 0x3E, or 0 when the entry is region agnostic */
    uint8_t rev_max; /* entry applies when header 0x3F <= this; 255 = any */
    uint8_t save;    /* sm_save_type_t value */
    uint8_t feat;    /* SM_FEAT_* bits */
}} sm_rom_db_entry_t;

#define SM_ROM_DB_COUNT {len(entries)}u

/* header must be at least 0x40 bytes. Returns NULL when the game is absent,
   which means "no save hardware" exactly as it does for the stock firmware. */
const sm_rom_db_entry_t *sm_rom_db_lookup(const uint8_t *header, size_t length);

#endif
''', encoding="utf-8")
    rows = "\n".join(
        f'    {{{{\'{i[0]}\',\'{i[1]}\',\'{i[2]}\'}}, \'{r}\', {v}u, {s}u, {f}u}},'
        + (f' /* {c} */' if c else '')
        for i, r, s, f, v, c in entries)
    source.write_text(f'''{ISC_NOTICE}#include "rom_db.h"

/* GENERATED by tools/build_rom_db.py -- do not edit by hand.
   Source: {origin} (ISC) */

static const sm_rom_db_entry_t ROM_DB[SM_ROM_DB_COUNT] = {{
{rows}
}};

const sm_rom_db_entry_t *sm_rom_db_lookup(const uint8_t *header, size_t length) {{
    if (!header || length < 0x40u) return NULL;
    {{
        const char a = (char)header[0x3Bu], b = (char)header[0x3Cu];
        const char c = (char)header[0x3Du], region = (char)header[0x3Eu];
        const uint8_t revision = header[0x3Fu];
        /* Entries are emitted most specific first, so the first hit wins. */
        for (size_t i = 0; i < SM_ROM_DB_COUNT; i++) {{
            const sm_rom_db_entry_t *e = &ROM_DB[i];
            if (e->id[0] != a || e->id[1] != b || e->id[2] != c) continue;
            if (e->region != '\\0' && e->region != region) continue;
            if (e->rev_max != 255u && revision > e->rev_max) continue;
            return e;
        }}
        return NULL;
    }}
}}
''', encoding="utf-8")

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default=SOURCE)
    p.add_argument("--header", type=Path, default=Path("src/rom_db.h"))
    p.add_argument("--output", type=Path, default=Path("src/rom_db.c"))
    a = p.parse_args()
    raw = (Path(a.source).read_text(encoding="utf-8", errors="replace")
           if Path(a.source).exists()
           else urllib.request.urlopen(a.source, timeout=120).read().decode("utf-8", "replace"))
    entries = parse(raw)
    if len(entries) < 300:
        print(f"refusing to write a suspiciously small database ({len(entries)} entries)", file=sys.stderr)
        return 1
    emit(entries, a.header, a.output, a.source)
    saves = sum(1 for e in entries if e[2])
    print(f"rom_db: {len(entries)} entries, {saves} with a save type -> {a.output}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
