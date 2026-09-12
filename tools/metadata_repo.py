# SPDX-License-Identifier: AGPL-3.0-only
"""Read the n64-flashcart-menu-metadata collection, as a folder or as its zip.

The collection (github.com/n64-tools/n64-flashcart-menu-metadata, public
domain) files everything under the four characters of the cartridge's own
game code -- GoldenEye USA is NGEE, so its box is

    metadata/N/G/E/E/boxart_front.png

with metadata.ini and description.txt beside it. That is the key the header
carries at 0x3B..0x3E, so a ROM finds its picture without a database, a name
or a network: a hack or a translation keeps the code of the game it was built
on and gets the same box, which no CRC or filename match ever managed.

Two fallbacks, in the order the N64FlashcartMenu uses them. A file at the
three-character level, metadata/N/G/E/boxart_front.png, serves every region;
the release generator hoists the USA description there. After that, another
region's folder: the PAL box for a French cartridge is right, and the USA box
for a Japanese one beats an empty frame.

The release zip is read in place -- 52 MB, 2,200 entries -- rather than
extracted onto a card where every one of those files would cost a directory
entry. A folder works the same, whether it is the zip unpacked, the
collection's own `metadata` tree, the `menu/metadata` an SC64 owner already
has, or the `ED64/metadata` krikzz's edmeta converter writes for the
EverDrive-64 Pro. That last one is the same layout and the same text files,
with every picture pre-stretched to twice its width for the Pro menu's
640-pixel mode -- Super Mario 64's box is 240x85 there -- so pictures from it
are read at half width to get the box back.
"""

from __future__ import annotations

import configparser
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tools import card_layout

ART_NAME = "boxart_front.png"
INI_NAME = "metadata.ini"
DESCRIPTION_NAME = "description.txt"
ROOT_NAME = "metadata"
RELEASE_ZIP_NAME = "release-metadata.zip"
RELEASES_URL = "https://github.com/n64-tools/n64-flashcart-menu-metadata/releases"

# Where a collection is looked for on a card, in order. The zip first because
# it is what the releases page hands out; the other menus' layouts last, for
# a card that already serves one of them -- the N64FlashcartMenu's originals
# before the Pro's converted copies.
PRO_FOLDER = PurePosixPath(card_layout.FIRMWARE_FOLDER) / ROOT_NAME
CARD_CANDIDATES = (
    PurePosixPath(card_layout.CARD_FOLDER) / RELEASE_ZIP_NAME,
    PurePosixPath(RELEASE_ZIP_NAME),
    PurePosixPath(card_layout.CARD_FOLDER) / ROOT_NAME,
    PurePosixPath(ROOT_NAME),
    PurePosixPath("menu") / ROOT_NAME,
    PRO_FOLDER,
)

# The region letter the cartridge carries, mapped to the folders worth trying
# after its own. Every PAL market shares the PAL box.
_EUROPE = frozenset("PDFISHXYUWL")
_CODE = re.compile(r"^[A-Za-z0-9]{4}$")
_MAX_DESCRIPTION = 2000


class RepoError(ValueError):
    pass


@dataclass(frozen=True)
class Found:
    key: str    # the folder the file was found in, "N/G/E/E" or "N/G/E"
    path: str   # the file, relative to the collection root


@dataclass(frozen=True)
class Info:
    """What metadata.ini says, in the catalog's vocabulary. Zero and empty
    mean the file did not say."""
    name: str = ""
    author: str = ""
    year: int = 0
    players: int = 0
    short_description: str = ""
    long_description: str = ""     # the file name, resolved by description()


def region_order(code: str) -> list[str]:
    """The region folders that are the cartridge's own: its letter, and for
    any PAL market the PAL folder too. Tried before the region-neutral file
    at the three-character level; every other region comes after that."""
    own = code[3].upper()
    return [own, "P"] if own in _EUROPE and own != "P" else [own]


_ANY_REGION = ("E", "P", "J")


def _year(value: str) -> int:
    match = re.match(r"\s*(\d{4})", value)
    return int(match.group(1)) if match else 0


def _players(value: str) -> int:
    match = re.match(r"\s*(\d+)", value)
    number = int(match.group(1)) if match else 0
    return number if 0 < number <= 8 else 0


def parse_ini(text: str) -> Info:
    """The [meta] section of a metadata.ini. Tolerant: a file with a
    duplicated key or an unexpected section still yields what it can."""
    parser = configparser.ConfigParser(interpolation=None, strict=False,
                                       comment_prefixes=(";", "#"),
                                       inline_comment_prefixes=None)
    try:
        parser.read_string(text)
    except configparser.Error:
        return Info()
    if not parser.has_section("meta"):
        return Info()
    meta = parser["meta"]
    get = lambda key: meta.get(key, "").strip()
    return Info(
        name=get("name"),
        author=get("author"),
        year=_year(get("release-date")),
        players=_players(get("num-players")),
        short_description=get("short-desc"),
        long_description=get("long-desc"),
    )


def is_pro_layout(path: Path) -> bool:
    """The EverDrive-64 Pro's own metadata folder, ED64/metadata, as edmeta
    writes it: pictures stretched to double width for a 640-pixel screen."""
    return (path.name.casefold() == ROOT_NAME
            and path.parent.name.casefold() == card_layout.FIRMWARE_FOLDER.casefold())


class MetadataRepo:
    def __init__(self, names, reader, label: str, closer=None, width_scale: float = 1.0):
        # Every path in the collection, relative to its root, forward slashes.
        # Looked up case-folded: the codes are upper case but a card is not a
        # case-sensitive place and a hand-made folder should not have to be.
        self._actual: dict[str, str] = {}
        self._regions: dict[str, set[str]] = {}
        for name in names:
            folded = name.casefold()
            self._actual.setdefault(folded, name)
            parts = name.split("/")
            if len(parts) == 5:
                self._regions.setdefault("/".join(parts[:3]).casefold(), set()).add(parts[3])
        self._read = reader
        self._close = closer
        self.label = label
        #: What to multiply a picture's width by before fitting it. 0.5 for
        #: the Pro's pre-stretched copies, 1.0 for everything else.
        self.width_scale = width_scale

    # -- opening -----------------------------------------------------------

    @classmethod
    def open(cls, path: Path) -> "MetadataRepo":
        path = Path(path)
        if path.is_file():
            return cls.from_zip(path)
        if path.is_dir():
            return cls.from_folder(path)
        raise RepoError(f"no metadata collection at {path}")

    @classmethod
    def from_zip(cls, path: Path) -> "MetadataRepo":
        try:
            archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise RepoError(f"{path} is not a zip file: {exc}") from exc
        prefix = None
        for name in archive.namelist():
            marker = f"{ROOT_NAME}/"
            at = name.find(marker)
            if at != -1 and (at == 0 or name[at - 1] == "/"):
                candidate = name[:at + len(marker)]
                if prefix is None or len(candidate) < len(prefix):
                    prefix = candidate
        if prefix is None:
            archive.close()
            raise RepoError(f"{path} has no {ROOT_NAME}/ folder in it")
        names = [name[len(prefix):] for name in archive.namelist()
                 if name.startswith(prefix) and not name.endswith("/")]
        return cls(names, lambda rel: archive.read(prefix + rel), str(path), archive.close)

    @classmethod
    def from_folder(cls, path: Path) -> "MetadataRepo":
        root = path / ROOT_NAME if (path / ROOT_NAME).is_dir() else path
        names = []
        for directory, folders, files in os.walk(root):
            folders.sort()
            base = Path(directory)
            for filename in files:
                names.append((base / filename).relative_to(root).as_posix())
        if not names:
            raise RepoError(f"{root} is empty")
        return cls(names, lambda rel: (root / rel).read_bytes(), str(root),
                   width_scale=0.5 if is_pro_layout(root) else 1.0)

    def close(self) -> None:
        if self._close is not None:
            self._close()
            self._close = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # -- lookup ------------------------------------------------------------

    @staticmethod
    def valid_code(code: str) -> bool:
        return bool(code) and _CODE.match(code) is not None

    def _folders(self, code: str) -> list[str]:
        """Folders to try for a code, most specific first."""
        code = code.upper()
        stem = "/".join(code[:3])
        tried = [f"{stem}/{region}" for region in region_order(code)]
        tried.append(stem)
        tried.extend(f"{stem}/{region}" for region in _ANY_REGION)
        tried.extend(f"{stem}/{region}"
                     for region in sorted(self._regions.get(stem.casefold(), ())))
        return list(dict.fromkeys(tried))

    def find(self, code: str, name: str) -> Found | None:
        if not self.valid_code(code):
            return None
        for folder in self._folders(code):
            actual = self._actual.get(f"{folder}/{name}".casefold())
            if actual is not None:
                return Found(key=actual.rsplit("/", 1)[0], path=actual)
        return None

    def read(self, found: Found) -> bytes:
        try:
            return self._read(found.path)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise RepoError(f"cannot read {found.path} from {self.label}: {exc}") from exc

    def art(self, code: str) -> Found | None:
        return self.find(code, ART_NAME)

    def info(self, code: str) -> Info | None:
        found = self.find(code, INI_NAME)
        if found is None:
            return None
        return parse_ini(self.read(found).decode("utf-8-sig", errors="replace"))

    def description(self, code: str) -> str:
        """The long description if the collection has one, else the short one,
        else nothing. Whitespace collapsed; the console wraps it itself."""
        info = self.info(code)
        text = ""
        found = self.find(code, DESCRIPTION_NAME)
        if info is not None and info.long_description and info.long_description != DESCRIPTION_NAME:
            named = self.find(code, info.long_description)
            found = named or found
        if found is not None:
            text = self.read(found).decode("utf-8-sig", errors="replace")
        if not text.strip() and info is not None:
            text = info.short_description
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > _MAX_DESCRIPTION:
            cut = text.rfind(" ", 0, _MAX_DESCRIPTION)
            text = text[:cut if cut > 0 else _MAX_DESCRIPTION].rstrip() + "..."
        return text

    def art_count(self) -> int:
        return sum(1 for name in self._actual if name.endswith("/" + ART_NAME))


def find_on_card(card: Path) -> Path | None:
    """The first collection present on a card, or None."""
    for candidate in CARD_CANDIDATES:
        path = card / Path(*candidate.parts)
        if path.is_file() or path.is_dir():
            return path
    return None
