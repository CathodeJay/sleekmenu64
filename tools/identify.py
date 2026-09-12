# SPDX-License-Identifier: AGPL-3.0-only
"""Which database row a cartridge is, from its header alone.

Three keys, tried in order, each weaker than the last:

  the CRC pair     exact. Identical for every copy of a dump whatever it is
                   called, different for every other dump.
  the product code the NUS-xxxx-yyy middle group the cartridge carries at
                   0x3B..0x3E. Shared by every revision and language variant
                   of a release -- and inherited, untouched, by every hack and
                   translation built on it, which is exactly why it is worth
                   asking: a patched ROM has a new CRC and the same box.
  the code without its region letter
                   a translation patch rewrites the region byte too.

The weaker keys are only trusted where every row that carries them names the
same game. Two characters of game code was never much room for thirteen
hundred releases, and guessing between two different games is worse than
admitting ignorance.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

from tools import coverdb

_TAG_PART = re.compile(
    r"^(?:(?:u|e|j|usa|us|europe|eur|japan|jpn|germany|france|spain|italy|australia|"
    r"korea|canada|world|pal|ntsc|en|fr|de|es|it|ja)|"
    r"(?:rev(?:ision)?\s*[a-z0-9.]*)|(?:v(?:er(?:sion)?)?\s*\d[\w.]*)|"
    r"(?:demo|kiosk|proto(?:type)?|beta|alpha|sample|preview|debug))$",
    re.IGNORECASE,
)
_SUFFIX = re.compile(r"\.(?:z64|v64|n64)$", re.IGNORECASE)
_DEMO_WORDS = ("demo", "kiosk")
_PRERELEASE_WORDS = ("beta", "proto", "prototype", "alpha", "sample", "preview", "debug")


def _is_metadata_tag(value: str) -> bool:
    parts = [part.strip() for part in re.split(r"[,;/+]", value) if part.strip()]
    return bool(parts) and all(_TAG_PART.fullmatch(part) for part in parts)


def normalize_name(value: str) -> str:
    """A No-Intro name with its region, revision and release tags stripped,
    case-folded and reduced to words: what two rows must agree on before
    they are taken to describe one game."""
    name = unicodedata.normalize("NFKC", PurePosixPath(value.replace("\\", "/")).name)
    name = _SUFFIX.sub("", name)
    name = re.sub(r"\(([^()]*)\)",
                  lambda match: " " if _is_metadata_tag(match.group(1)) else match.group(0),
                  name)
    name = name.casefold().replace("_", " ")
    name = re.sub(r"[^\w]+", " ", name, flags=re.UNICODE)
    return re.sub(r"\s+", " ", name).strip()


def release_rank(value: str) -> int:
    """0 for a plain retail release, higher for anything less canonical, so
    that the row chosen to stand for a serial is the one on the shelf."""
    groups = " ".join(re.findall(r"[([]([^()\[\]]*)[)\]]", PurePosixPath(value).name)).casefold()
    if any(re.search(rf"\b{re.escape(word)}\b", groups) for word in _PRERELEASE_WORDS):
        return 3
    if any(re.search(rf"\b{re.escape(word)}\b", groups) for word in _DEMO_WORDS):
        return 2
    if re.search(r"\b(?:rev(?:ision)?|v(?:er(?:sion)?)?)\s*[0-9.]", groups):
        return 1
    return 0


def _one_game(found: list[coverdb.Entry]) -> coverdb.Entry | None:
    if len({normalize_name(entry.name) for entry in found}) != 1:
        return None
    return sorted(found, key=lambda entry: (release_rank(entry.name),
                                            entry.name.casefold(), entry.crc))[0]


def _entries(database):
    return database.values() if isinstance(database, dict) else database


def by_serial(database) -> dict[str, coverdb.Entry]:
    """Product code -> the row to use for it, for codes that name one game."""
    rows: dict[str, list[coverdb.Entry]] = {}
    for entry in _entries(database):
        if entry.serial:
            rows.setdefault(entry.serial, []).append(entry)
    result = {serial: _one_game(found) for serial, found in rows.items()}
    return {serial: entry for serial, entry in result.items() if entry is not None}


def by_serial_prefix(database) -> dict[str, coverdb.Entry]:
    """The product code without its region letter: NUS-*NSM*E -> NSM."""
    rows: dict[str, list[coverdb.Entry]] = {}
    for entry in _entries(database):
        if len(entry.serial) == 4:
            rows.setdefault(entry.serial[:3], []).append(entry)
    result = {prefix: _one_game(found) for prefix, found in rows.items()}
    return {prefix: entry for prefix, entry in result.items() if entry is not None}


class Index:
    """The two derived lookups, built once per database."""

    def __init__(self, database):
        self.database = database if isinstance(database, dict) else \
            {entry.crc: entry for entry in database}
        self.serials = by_serial(self.database)
        self.prefixes = by_serial_prefix(self.database)

    def identify(self, header) -> tuple[coverdb.Entry | None, str]:
        """The row, and how it was found: "crc", "serial",
        "serial without region", or "" for nothing."""
        crc = header.crc_pair if header else ""
        entry = self.database.get(crc) if crc and crc != coverdb.ZERO_CRC else None
        if entry is not None:
            return entry, "crc"
        if header is not None and header.product_code:
            entry = self.serials.get(header.product_code)
            if entry is not None:
                return entry, "serial"
            entry = self.prefixes.get(header.product_code[:3])
            if entry is not None:
                return entry, "serial without region"
        return None, ""
