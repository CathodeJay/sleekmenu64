# SPDX-License-Identifier: AGPL-3.0-only
"""What a game is: a retail cartridge, a hack, a translation or homebrew.

Nobody labels a ROM, so the kind is read off what the file gives away, in
order, the first answer winning:

  its name         the tags dumpers and patchers put there. A translation:
                   "[T+Eng]", "T-Spa", "(Translated)", "English", "Dubbed".
                   A hack: "(Hack)", "[h1C]", GoodN64's "[f1]" (fixed) and
                   "[t1]" (trainer), "(NTSC)" on a PAL game, "Patched",
                   "Randomizer", "Mod". Homebrew: "(PD)", "(Homebrew)".
                   And the tags of a real release the database may not
                   list -- "(Beta)", "(Proto)", "(Demo)", "(Kiosk)",
                   "(LodgeNet)", "(Rev 1)" -- which say retail when the
                   file is built on a game the database knows. A version
                   number, "(v1.2)", says nothing: hacks carry them too.
  its folder       the same words in the name of any folder above it: a
                   "Hacks" folder, "ROM Hacks", "Translations", "Homebrew".
                   A hint, never needed: a card in one flat folder is told
                   apart by the other two.
  the database     what the file is built on (Lineage). Its CRC known: a
                   retail dump. Its game code known, even one two games
                   share: a hack, almost always, since the database knows
                   the No-Intro set. The code of a game only ever released
                   in Japan with another region letter, and nothing in the
                   name saying a western release: a translation, which is
                   what a patch that rewrites the region byte usually is.
                   No code the database knows but a known game's title in
                   the file name ("Doom 64 - Merciless Edition"): a hack.
                   Nothing at all: homebrew, whose code is blank or made up.

The name goes first because the database can be fooled: the CRC it reads
is the pair stored in the header, which a hack that never recomputed it
still carries, so a stale hack is "known" by CRC. A name or a folder saying
hack is believed over that. What is still wrong -- a hack nobody tagged
with its header intact -- the card's owner corrects in the Games tab, and
the correction is a "Kind:" line in the game's text file like any other
fact.

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

_LANGUAGES = ("eng|spa|fre|fra|ger|deu|ita|por|bra|rus|pol|chi|kor|jap|jpn|dut|ned|swe|nor|dan|fin|gre|"
              "hun|cze|tur|ara|heb|cat|rom|ukr|vie")
_TRANSLATION = re.compile(r"\[t[+-]|\(t[+-]|\bt[+-](?:" + _LANGUAGES + r")|translat|traduc|traduz|\bfan ?tl\b"
                          r"|\benglish\b|\bdub(?:bed)?\b|\bsub(?:titles?|titled|bed|s)\b", re.IGNORECASE)
_HACK = re.compile(r"\(hack\)|\[hack\]|\[h\d*[a-z]*\]|\bhack(?:s|ed)?\b|romhack|\[[ftp]\d+[a-z]*\]|\(ntsc\)"
                   r"|\bpal[- ]?to[- ]?ntsc\b|\bntsc[- ]?to[- ]?pal\b|randomi[sz]er|\bpatch(?:ed)?\b"
                   r"|\bmod(?:ded|s)?\b|\buncensored\b", re.IGNORECASE)
_HOMEBREW = re.compile(r"\(pd\)|\[pd\]|\bhomebrew\b|\bhome-brew\b", re.IGNORECASE)
_RELEASE = re.compile(r"\((?:beta|proto(?:type)?|demo|kiosk|sample|lodgenet|rev\s*[a-z0-9.]+)[^)]*\)",
                      re.IGNORECASE)
#: A region tag of a western release in a file name: a dump whose code the
#: database files under Japan only, named as a USA or European release, is
#: that release, not a translation of the Japanese one.
_WESTERN = re.compile(r"\((?:u|e|a|f|g|i|s|ue|ju|je|usa|europe|australia|france|germany|italy|spain|uk)\)",
                      re.IGNORECASE)
#: Titles shorter than this are too common a word to say what a file is.
_TITLE_MIN = 6


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


#: What a file is built on, by the database (Lineage.of): its dump, a
#: known game's code, a Japanese game's code with another region letter,
#: a known game's title in its name, or nothing.
CRC, CODE, TRANSLATED_CODE, TITLE, NOTHING = "crc", "code", "translated code", "title", ""


class Lineage:
    """The database as tools/kinds.py asks it: which game a file is built
    on, more loosely than tools/identify.py, which must be sure of a game to
    give it that game's text and facts. A code two games share is no use to
    the text and still says the file is built on a retail game."""

    def __init__(self, database):
        from tools import identify
        self._normalize = identify.normalize_name
        entries = database.values() if isinstance(database, dict) else database
        self.codes: set[str] = set()
        self.regions: dict[str, set[str]] = {}
        self.titles: set[str] = set()
        for entry in entries:
            serial = entry.serial.upper()
            if len(serial) == 4:
                self.codes.add(serial)
                self.regions.setdefault(serial[:3], set()).update(entry.regions or ("?",))
            base = re.sub(r"\s*[(\[].*$", "", entry.name)
            for part in [base] + base.split(" - "):
                title = re.sub(r"^the |,? the$", "", self._normalize(part)).strip()
                if len(title) >= _TITLE_MIN:
                    self.titles.add(title)

    def of(self, rom_path: str, header, identified: str = "") -> str:
        """What the file at `rom_path` is built on: CRC, CODE,
        TRANSLATED_CODE, TITLE or NOTHING. `identified` is how
        tools/identify.py knew it."""
        if identified == "crc":
            return CRC
        code = (getattr(header, "product_code", "") or "").upper()
        if re.fullmatch(r"[A-Z0-9]{4}", code):
            if code in self.codes:
                return CODE
            regions = self.regions.get(code[:3])
            if regions is not None:
                if (regions == {"JAPAN"} and code[3] != "J"
                        and not _WESTERN.search(PurePosixPath(rom_path).stem)):
                    return TRANSLATED_CODE
                return CODE
        name = f" {self._normalize(PurePosixPath(rom_path).stem)} "
        if any(f" {title} " in name for title in self.titles):
            return TITLE
        return NOTHING


def _lineage_of(identified: str) -> str:
    """The lineage tools/identify.py's answer alone gives, for a caller
    without the database at hand."""
    return {"crc": CRC, "serial": CODE, "serial without region": TRANSLATED_CODE}.get(identified, NOTHING)


def classify(rom_path: str, identified: str, disk: bool = False, lineage: str | None = None) -> str:
    """The kind of the game at `rom_path` (relative, any depth), which
    tools/identify.py found by `identified` ("crc", "serial", "serial
    without region" or "") and Lineage.of() found built on `lineage`. A
    64DD disk image has no header to go by and is retail unless its name or
    folder says otherwise."""
    if lineage is None:
        lineage = _lineage_of(identified)
    path = PurePosixPath(rom_path)
    said = from_words(path.stem)
    if said is not None:
        return said
    if _RELEASE.search(path.stem) and lineage:
        return RETAIL
    for folder in reversed(path.parts[:-1]):
        said = from_words(folder)
        if said is not None:
            return said
    if disk or lineage == CRC:
        return RETAIL
    if lineage == TRANSLATED_CODE:
        return TRANSLATION
    if lineage in (CODE, TITLE):
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
