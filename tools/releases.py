# SPDX-License-Identifier: AGPL-3.0-only
"""SleekMenu and the Game Catalog Manager, kept in step with each other.

The two are released together under one number, and the catalog they share
has a format of its own: a browser refuses a catalog older than it reads,
and a tool cannot write one newer than it knows. So the SleekMenu a card
should have is the one released with the tool preparing it -- never simply
the newest -- and the newest of everything starts with the tool:

  - Update card puts this release's SleekMenu64.z64 at the card's root
    when the card has an older one, or none. It is fetched from this
    release's own page on GitHub, checked to be that SleekMenu, and
    written by way of a `.part` file, so a pulled card never leaves half a
    browser. A newer SleekMenu than the tool is left alone, and so is one
    the release pages never had -- a build of the owner's own.
  - The window says when a newer Game Catalog Manager is out, and links to
    the file for this computer. It does not replace itself: a program that
    installs what it downloads is a worse thing to trust than the owner
    fetching it, and a running program cannot be overwritten everywhere.

Which SleekMenu a card has is read off the ROM itself: since 2.1 its
header's title is "SleekMenu 64 2.1.0"; an older one says "SleekMenu 64"
and is known by its SHA-256, listed below for every release before 2.1.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from tools import card_layout, direct_boot, fetch, version

REPOSITORY = "CathodeJay/sleekmenu64"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
LATEST_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
LATEST_PAGE = f"{RELEASES_URL}/latest"
ROM_NAME = card_layout.BROWSER_ROM
#: The header's title: "SleekMenu 64", then the release since 2.1.
TITLE_AT = direct_boot.TITLE_AT
TITLE_LENGTH = 20
TITLE = re.compile(rb"SleekMenu 64(?: (\d+\.\d+\.\d+))?[\x00 ]*\Z")
#: The releases from before the title carried the number, by the SHA-256
#: of their SleekMenu64.z64.
EARLIER = {
    "874e50b07c9bccf470818aa766af9e7b06a7782301b9ea79808ebb8d6610bc78": "1.0.0",
    "be7b6b0001ede1484f0ba635aa68ee18dfac932aa2662b03e0abc542b88ba6f2": "1.1.0",
    "57661bf24deea782fa548562c78fd43f1ce89839d5e9515fdfda81e5b0926d63": "1.2.0",
    "d18a5bb76a79190b10e6db6f86ea555f78293daf8b1684c1cd15da1f1007c5f7": "2.0.0",
}
#: A SleekMenu is a few hundred KB; anything past this at that name is not one.
ROM_LIMIT = 8 * 1048576
Z64_MAGIC = b"\x80\x37\x12\x40"

MISSING = "missing"       # no SleekMenu64.z64 at the card's root
OLDER = "older"           # an earlier release
CURRENT = "current"       # this release
NEWER = "newer"           # a later release than this tool
OWN = "own"               # a SleekMenu no release page had: the owner's build
OTHER = "other"           # a file at that name that is not SleekMenu


#: Why this release's SleekMenu could not be put on a card, so the window
#: can say what to do instead of always blaming the connection.
CONNECTION = "connection"       # the release page could not be reached
NOT_RELEASED = "not released"   # the release page has no SleekMenu64.z64
WRONG_FILE = "wrong file"       # what the release page has is not this release's SleekMenu
CARD = "card"                   # the card would not take the file


class ReleaseError(Exception):
    def __init__(self, message: str, reason: str = CONNECTION):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Browser:
    """The SleekMenu on a card, as the tool sees it."""
    state: str
    version: str = ""     # "" when it cannot be told
    path: Path | None = None

    @property
    def wants_update(self) -> bool:
        return self.state in (MISSING, OLDER)

    def describe(self) -> str:
        """The card's SleekMenu in a few words, for a report or a window."""
        if self.state == MISSING:
            return "not on the card"
        if self.state == OTHER:
            return f"{ROM_NAME} on the card is not SleekMenu"
        if self.state == OWN:
            return "a build of its own" + (f" ({self.version})" if self.version else "")
        return self.version


def parse(text: str) -> tuple[int, ...] | None:
    """"2.1.0" (or "v2.1.0") as a tuple that compares; None for anything else."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def newer(candidate: str, than: str) -> bool:
    a, b = parse(candidate), parse(than)
    return a is not None and b is not None and a > b


def rom_version(data: bytes) -> tuple[bool, str]:
    """Whether bytes are a SleekMenu ROM, and which release: from the
    header's title, else from the fingerprint of a release before 2.1, else
    "" for a build no release page had."""
    if not data.startswith(Z64_MAGIC) or len(data) < TITLE_AT + TITLE_LENGTH:
        return False, ""
    match = TITLE.match(data[TITLE_AT:TITLE_AT + TITLE_LENGTH])
    if match is None:
        return False, ""
    if match.group(1):
        return True, match.group(1).decode("ascii")
    return True, EARLIER.get(hashlib.sha256(data).hexdigest(), "")


_read: dict[tuple[str, int, int], tuple[bool, str]] = {}


def _rom_on_card(path: Path) -> tuple[bool, str]:
    """rom_version() of a file, kept per size and time: the window asks
    about the card every time it comes back to the front."""
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in _read:
        _read[key] = (False, "") if stat.st_size > ROM_LIMIT else rom_version(path.read_bytes())
    return _read[key]


def card_browser(card: Path | None) -> Browser:
    """Which SleekMenu the card has at its root, against this tool's release."""
    if card is None:
        return Browser(MISSING)
    path = direct_boot.find(card, ROM_NAME)
    if path is None:
        return Browser(MISSING)
    try:
        sleekmenu, found = _rom_on_card(path)
    except OSError:
        return Browser(OTHER, path=path)
    if not sleekmenu:
        return Browser(OTHER, path=path)
    if not found:
        return Browser(OWN, path=path)
    if found == version.VERSION:
        # Built from this release's source: whether it is the very file on
        # the release page does not matter, it reads the same catalog.
        return Browser(CURRENT, found, path)
    if newer(found, version.VERSION):
        return Browser(NEWER, found, path)
    return Browser(OLDER, found, path)


def rom_url(release: str = version.VERSION) -> str:
    return f"{RELEASES_URL}/download/v{release}/{ROM_NAME}"


def fetch_rom(release: str = version.VERSION, url: str | None = None) -> bytes:
    """This release's SleekMenu64.z64 from its release page, checked to be
    that SleekMenu before anything is done with it."""
    url = url or rom_url(release)
    try:
        with fetch.open_url(url) as response:
            data = response.read(ROM_LIMIT + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ReleaseError(f"SleekMenu {release} is not on its release page", NOT_RELEASED) from error
        raise ReleaseError(f"{url}: HTTP {error.code}") from error
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise ReleaseError(f"{url}: {getattr(error, 'reason', error)}") from error
    if len(data) > ROM_LIMIT:
        raise ReleaseError(f"{url}: too big to be SleekMenu", WRONG_FILE)
    sleekmenu, found = rom_version(data)
    if not sleekmenu or found != release:
        raise ReleaseError(f"{url}: not SleekMenu {release}", WRONG_FILE)
    return data


def install(card: Path, data: bytes, current: Browser | None = None) -> Path:
    """Write a SleekMenu at the card's root, by way of a `.part` file, over
    the one there under whatever case the card spells its name in."""
    target = (current.path if current is not None and current.path is not None else None) \
        or direct_boot.find(card, ROM_NAME) or card / ROM_NAME
    part = target.with_name(target.name + ".part")
    try:
        part.write_bytes(data)
        os.replace(part, target)
    finally:
        try:
            part.unlink()
        except OSError:
            pass
    return target


@dataclass(frozen=True)
class Updated:
    """What update_card() found and left: the card's SleekMenu afterwards,
    and, when this release's was wanted there and could not be put there,
    why not (one of the reasons above)."""
    browser: Browser
    failure: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.failure)


def update_card(card: Path, log=print, offline: bool = False, url: str | None = None) -> Updated:
    """Put this release's SleekMenu on the card when it has an older one or
    none, and say what was done, or why not."""
    found = card_browser(card)
    mine = version.VERSION
    if found.state == CURRENT:
        return Updated(found)
    if found.state == NEWER:
        log(f"sleekmenu: the card has SleekMenu {found.version}, newer than this Game Catalog Manager "
            f"({mine}); get the newer Game Catalog Manager from {RELEASES_URL}")
        return Updated(found)
    if found.state == OWN:
        log(f"sleekmenu: {ROM_NAME} is a build of its own; left as it is")
        return Updated(found)
    if found.state == OTHER:
        log(f"sleekmenu: {ROM_NAME} at the card's root is not SleekMenu; left as it is")
        return Updated(found)
    if offline:
        log(f"sleekmenu: {'SleekMenu ' + found.version if found.version else 'not'} on the card; "
            f"{mine} not fetched, downloads are off")
        return Updated(found)
    try:
        data = fetch_rom(mine, url)
    except ReleaseError as error:
        log(f"sleekmenu: {mine} not put on the card ({error})")
        return Updated(found, error.reason)
    try:
        install(card, data, found)
    except OSError as error:
        log(f"sleekmenu: {mine} not put on the card ({error})")
        return Updated(found, CARD)
    log(f"sleekmenu: {mine} put on the card"
        + (f", in place of {found.version}" if found.state == OLDER and found.version else ""))
    return Updated(card_browser(card))


# -- a newer Game Catalog Manager ----------------------------------------------

def latest_release(api_url: str = LATEST_API, page_url: str = LATEST_PAGE) -> str | None:
    """The newest release's number, from the API, else from where the
    releases page's /latest sends a browser; None offline or unanswered."""
    try:
        with fetch.open_url(api_url) as response:
            tag = json.loads(response.read(1 << 20).decode("utf-8")).get("tag_name", "")
        if parse(tag):
            return tag.lstrip("v")
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, AttributeError):
        pass
    try:
        with fetch.open_url(page_url) as response:
            landed = response.geturl()
        match = re.search(r"/tag/v?(\d+\.\d+\.\d+)$", landed)
        if match:
            return match.group(1)
    except (urllib.error.URLError, OSError, TimeoutError):
        pass
    return None


def asset_for_this_computer(frozen: bool | None = None, system: str | None = None,
                            machine: str | None = None, program: str | None = None) -> str:
    """The file of a release this copy of the tool would be replaced by:
    the window built for this system, or the archive when it runs as one,
    or "" when it runs from a checkout, where the releases page is the
    answer."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    program = program if program is not None else (sys.argv[0] if sys.argv else "")
    if frozen:
        if system == "darwin":
            return "SleekMenu-Catalog-Manager-mac-" + ("arm64" if machine in ("arm64", "aarch64") else "intel") + ".zip"
        if system.startswith("win"):
            return "SleekMenu-Catalog-Manager-windows.exe"
        return "SleekMenu-Catalog-Manager-linux"
    if program.lower().endswith(".pyz"):
        return "sleekmenu-catalog-manager.pyz"
    return ""


def download_url(release: str, asset: str | None = None) -> str:
    """Where a person gets `release` for this computer: the file itself,
    else the release's page."""
    asset = asset_for_this_computer() if asset is None else asset
    return f"{RELEASES_URL}/download/v{release}/{asset}" if asset else f"{RELEASES_URL}/tag/v{release}"


def newer_tool(latest: str | None = None) -> str | None:
    """A release newer than this tool, or None."""
    latest = latest_release() if latest is None else latest
    return latest if latest and newer(latest, version.VERSION) else None
