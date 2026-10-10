# SPDX-License-Identifier: AGPL-3.0-only
"""What a game is: a retail cartridge, a hack, a translation or homebrew.

Nobody labels a ROM, so the kind is read off what the file gives away, in
order, the first answer winning:

  its name         the tags dumpers and patchers put there: "(Hack)", "[h1C]",
                   "[T+Eng]", "(Translated)", "(PD)", "(Homebrew)"; and the
                   tags of a real release that the database may not list,
                   "(Beta)", "(Proto)", "(Rev 1)", "(v1.1)", which say retail
  its folder       the same words in the name of any folder above it: a
                   "Hacks" folder, "ROM Hacks", "Translations", "Homebrew"
  the database     how tools/identify.py knew the dump. By its CRC: a retail
                   dump. By its game code only: something built on a retail
                   game -- a hack, almost always, since the database knows
                   the No-Intro set. By the code without its region letter: a
                   translation, which is what a patch that rewrites the region
                   byte usually is. Not at all: homebrew, whose code is blank
                   or made up.

The name goes first because the database can be fooled: the CRC it reads
is the pair stored in the header, which a hack that never recomputed it
still carries, so a stale hack is "known" by CRC. A name or a folder saying
hack is believed over that. What is still wrong -- an unlisted revision
taken for a hack, a hack nobody tagged with its header intact -- the card's
owner corrects in the Games tab, and the correction is a "Kind:" line in
the game's text file like any other fact.

The console stores the kind in three bits of a record's flags in
catalog.ebc (src/catalog.h names the same values): it draws a tag on the
game's row and filters by it on the filter page.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

RETAIL = "retail"
HACK = "hack"
TRANSLATION = "translation"
HOMEBREW = "homebrew"
KINDS = (RETAIL, HACK, TRANSLATION, HOMEBREW)
#: What a person reads, in the window and the docs.
NAMES = {RETAIL: "Retail", HACK: "Hack", TRANSLATION: "Translation", HOMEBREW: "Homebrew"}
#: The kind in a record's flags: bits 2..4. 0 is retail, and is what every
#: record of a catalog written before kinds existed reads as.
FLAG_SHIFT = 2
FLAG_MASK = 0b111 << FLAG_SHIFT
CODES = {RETAIL: 0, HACK: 1, TRANSLATION: 2, HOMEBREW: 3}

_TRANSLATION = re.compile(r"\[t[+-]|\(t[+-]|translat|traduc|traduz|\bfan ?tl\b", re.IGNORECASE)
_HACK = re.compile(r"\(hack\)|\[hack\]|\[h\d*[a-z]*\]|\bhack(?:s|ed)?\b|romhack", re.IGNORECASE)
_HOMEBREW = re.compile(r"\(pd\)|\[pd\]|\bhomebrew\b|\bhome-brew\b", re.IGNORECASE)
_RELEASE = re.compile(r"\((?:beta|proto(?:type)?|demo|kiosk|sample|rev\s*[a-z0-9.]+|v\d[\w.]*)[^)]*\)",
                      re.IGNORECASE)


#: A genre, not a kind: a folder of hack-and-slash games is not of hacks.
_NOT_A_KIND = re.compile(r"hack\s*(?:&|and|'?n'?)\s*slash", re.IGNORECASE)


def from_words(text: str) -> str | None:
    """The kind a file or folder name says, or None when it says nothing."""
    text = _NOT_A_KIND.sub(" ", text)
    if _TRANSLATION.search(text):
        return TRANSLATION
    if _HACK.search(text):
        return HACK
    if _HOMEBREW.search(text):
        return HOMEBREW
    return None


def classify(rom_path: str, identified: str, disk: bool = False) -> str:
    """The kind of the game at `rom_path` (relative, any depth), which
    tools/identify.py found by `identified` ("crc", "serial", "serial
    without region" or ""). A 64DD disk image has no header to go by and is
    retail unless its name or folder says otherwise."""
    path = PurePosixPath(rom_path)
    said = from_words(path.stem)
    if said is not None:
        return said
    if _RELEASE.search(path.stem) and identified:
        return RETAIL
    for folder in reversed(path.parts[:-1]):
        said = from_words(folder)
        if said is not None:
            return said
    if disk or identified == "crc":
        return RETAIL
    if identified == "serial without region":
        return TRANSLATION
    if identified == "serial":
        return HACK
    return HOMEBREW


def parse(value: str) -> str | None:
    """A kind as a person writes it in a text file: the name in any case,
    plural or not, or the short tags the console draws."""
    word = value.strip().casefold().rstrip("s")
    aliases = {"retail": RETAIL, "original": RETAIL, "hack": HACK, "romhack": HACK, "rom hack": HACK,
               "translation": TRANSLATION, "tl": TRANSLATION, "homebrew": HOMEBREW, "hb": HOMEBREW}
    return aliases.get(word)


def flags(kind: str | None) -> int:
    """The kind's bits for a record's flags."""
    return CODES.get(kind or RETAIL, 0) << FLAG_SHIFT
