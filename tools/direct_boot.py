# SPDX-License-Identifier: AGPL-3.0-only
"""Starting the console in SleekMenu, on an EverDrive-64 X7.

The X7's stock OS has a start-up file: when ED64/autoexec.v64 exists, the
OS starts it by itself at power-on, after its own start-up work -- the same
launch as choosing the file in its menu, with the last game's save already
written to the card. A copy of the browser under that name is the whole
switch, and removing the copy is the way back. Nothing of the OS is touched.

Two things follow from the OS, not from the browser. A reset inside a game
returns to the EverDrive menu, because the OS starts the file again only
when the file was the last thing it launched. And the EverDrive-64 Pro has
no such file: its menu is firmware, so the switch is not offered there.

The copy is the browser at the card root, byte for byte; an update keeps it
in step when the one at the root is replaced. A start-up file that is some
other program is never overwritten or removed.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from tools import card_layout

#: The name the OS looks for, as it appears inside the OS itself. An OS
#: that carries it has the feature, whatever its version says.
HOOK = (card_layout.FIRMWARE_FOLDER + "/" + card_layout.FIRMWARE_AUTOEXEC).encode("ascii")
#: The browser's title in its ROM header, at 0x20.
BROWSER_TITLE = b"SleekMenu 64"
TITLE_AT = 0x20
AUTOEXEC_SHOWN = card_layout.FIRMWARE_FOLDER + "/" + card_layout.FIRMWARE_AUTOEXEC

X7 = "x7"
PRO = "pro"


@dataclass(frozen=True)
class State:
    """What a card says about starting in SleekMenu."""
    cart: str = ""              # X7, PRO, or "" when the card has neither's folder
    available: bool = False     # the switch can be turned on or off
    on: bool = False            # the start-up file is the browser
    stale: bool = False         # ...but not the copy at the card root
    why: str = ""               # when not available: the reason, in a sentence


_facts: dict[tuple[str, int, int], object] = {}


def _remembered(path: Path, what: str, compute):
    """A fact about a file, kept per size and time: the window asks about
    the card every few seconds and the files change once a release."""
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (what + ":" + str(path), stat.st_size, stat.st_mtime_ns)
    if key not in _facts:
        try:
            _facts[key] = compute(path)
        except OSError:
            return None
    return _facts[key]


def find(folder: Path | None, name: str) -> Path | None:
    """`name` in `folder` as the card spells it; None when it is not there."""
    if folder is None:
        return None
    try:
        for entry in os.listdir(folder):
            if card_layout.same_name(entry, name):
                return folder / card_layout.card_name(entry)
    except OSError:
        pass
    return None


def is_browser(path: Path) -> bool:
    def title(target: Path) -> bool:
        with target.open("rb") as handle:
            head = handle.read(TITLE_AT + len(BROWSER_TITLE))
        return head[TITLE_AT:] == BROWSER_TITLE
    return bool(_remembered(path, "title", title))


def has_hook(os_file: Path) -> bool:
    return bool(_remembered(os_file, "hook", lambda target: HOOK in target.read_bytes()))


def digest(path: Path) -> str:
    return str(_remembered(path, "sha", lambda target: hashlib.sha256(target.read_bytes()).hexdigest()) or "")


def state(card: Path | None) -> State:
    """Read the card: which EverDrive it is for, and where the switch stands."""
    firmware = find(card, card_layout.FIRMWARE_FOLDER)
    if firmware is None or not firmware.is_dir():
        return State(why="The card has no ED64 folder yet.")
    os_file = find(firmware, card_layout.FIRMWARE_OS)
    if os_file is None or not os_file.is_file():
        if find(find(firmware, "sysdata"), "config.ini") is not None:
            return State(PRO, why="The EverDrive-64 Pro has no start-up file; its menu always comes first.")
        return State(why="The card has no EverDrive OS (ED64/OS64.v64).")
    if not has_hook(os_file):
        return State(X7, why="This EverDrive OS does not start a file by itself; a newer OS does.")
    browser = find(card, card_layout.BROWSER_ROM)
    autoexec = find(firmware, card_layout.FIRMWARE_AUTOEXEC)
    if autoexec is not None and autoexec.is_file():
        if not is_browser(autoexec):
            return State(X7, why=f"{AUTOEXEC_SHOWN} is another program; it is left alone.")
        stale = browser is not None and browser.is_file() and digest(browser) != digest(autoexec)
        return State(X7, available=True, on=True, stale=stale)
    if browser is None or not browser.is_file():
        return State(X7, why=f"{card_layout.BROWSER_ROM} is not at the card root yet.")
    return State(X7, available=True)


def turn_on(card: Path) -> None:
    """The browser at the card root, copied as the start-up file."""
    firmware = find(card, card_layout.FIRMWARE_FOLDER)
    browser = find(card, card_layout.BROWSER_ROM)
    target = find(firmware, card_layout.FIRMWARE_AUTOEXEC) or firmware / card_layout.FIRMWARE_AUTOEXEC
    part = target.with_name(target.name + ".part")
    try:
        part.write_bytes(browser.read_bytes())
        os.replace(part, target)
    finally:
        if part.exists():
            part.unlink()


def turn_off(card: Path) -> None:
    autoexec = find(find(card, card_layout.FIRMWARE_FOLDER), card_layout.FIRMWARE_AUTOEXEC)
    if autoexec is not None and is_browser(autoexec):
        autoexec.unlink()


def sync(card: Path, wanted: bool | None, log=None) -> State:
    """Put the switch where the run was told to, or keep the copy in step
    when it was told nothing (`wanted` None). Says what it did in the
    report, and why not when it could not."""
    log = log or (lambda line: None)
    now = state(card)
    if wanted is None:
        if now.on and now.stale:
            turn_on(card)
            log(f"boot:     {AUTOEXEC_SHOWN} brought up to date with {card_layout.BROWSER_ROM}")
        return state(card)
    if wanted:
        if not now.available:
            log(f"boot:     not changed. {now.why}")
        elif not now.on or now.stale:
            turn_on(card)
            log(f"boot:     the console now starts in SleekMenu ({card_layout.BROWSER_ROM} copied to "
                f"{AUTOEXEC_SHOWN})" if not now.on else
                f"boot:     {AUTOEXEC_SHOWN} brought up to date with {card_layout.BROWSER_ROM}")
    elif now.on:
        turn_off(card)
        log(f"boot:     the console starts in the EverDrive menu again ({AUTOEXEC_SHOWN} removed)")
    return state(card)
