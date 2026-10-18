# SPDX-License-Identifier: AGPL-3.0-only
"""Starting the console in SleekMenu, on an EverDrive-64 X7 or Pro.

Each EverDrive has a file it starts by itself at power-on, and a copy of
the browser under that name is the whole switch; removing the copy is the
way back. Nothing of the firmware is touched.

  - The X7's stock OS starts ED64/autoexec.v64, after its own start-up
    work -- the same launch as choosing the file in its menu, with the last
    game's save already written to the card. A reset inside a game returns
    to the EverDrive menu, because the OS starts the file again only when
    it was the last thing it launched. An OS too old to know the file does
    not get the switch: the name is looked for inside the OS itself.
  - The Pro starts ED64/menu.n64 in place of its own menu (firmware 26.1014
    and newer). The cartridge writes the last game's save to the card at
    power-on whichever menu comes up. Games started from SleekMenu then
    have no in-game menu and no save states: those come with the Pro's
    menu, which unticking the switch brings back.

Which EverDrive a card is for is read off its ED64 folder: the X7's OS file,
or the Pro's settings. The copy is the browser at the card root, byte for
byte; an update keeps it in step when the one at the root is replaced. A
start-up file that is some other program -- another menu, say -- is never
overwritten or removed.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from tools import card_layout

#: The name the X7's OS looks for, as it appears inside the OS itself. An
#: OS that carries it has the feature, whatever its version says.
HOOK = (card_layout.FIRMWARE_FOLDER + "/" + card_layout.FIRMWARE_AUTOEXEC).encode("ascii")
#: The browser's title in its ROM header, at 0x20.
BROWSER_TITLE = b"SleekMenu 64"
TITLE_AT = 0x20

X7 = "x7"
PRO = "pro"
#: Each EverDrive's start-up file, in its ED64 folder.
START_FILE = {X7: card_layout.FIRMWARE_AUTOEXEC, PRO: card_layout.FIRMWARE_MENU}
AUTOEXEC_SHOWN = card_layout.FIRMWARE_FOLDER + "/" + card_layout.FIRMWARE_AUTOEXEC
MENU_SHOWN = card_layout.FIRMWARE_FOLDER + "/" + card_layout.FIRMWARE_MENU


def shown(cart: str) -> str:
    """The start-up file of an EverDrive, as the card shows it."""
    return card_layout.FIRMWARE_FOLDER + "/" + START_FILE[cart]


@dataclass(frozen=True)
class State:
    """What a card says about starting in SleekMenu."""
    cart: str = ""              # X7, PRO, or "" when the card has neither's folder
    available: bool = False     # the switch can be turned on or off
    on: bool = False            # the start-up file is the browser
    stale: bool = False         # ...but not the copy at the card root
    why: str = ""               # when not available: the reason, in a sentence

    @property
    def file(self) -> str:
        """The start-up file this card's EverDrive looks for, "" for none."""
        return shown(self.cart) if self.cart else ""


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


def cart_of(card: Path | None) -> tuple[str, str]:
    """Which EverDrive a card's ED64 folder is for, and when it cannot be
    told, why not."""
    firmware = find(card, card_layout.FIRMWARE_FOLDER)
    if firmware is None or not firmware.is_dir():
        return "", "The card has no ED64 folder yet. Use it in your EverDrive once first."
    os_file = find(firmware, card_layout.FIRMWARE_OS)
    if os_file is not None and os_file.is_file():
        return X7, ""
    if find(find(firmware, "sysdata"), "config.ini") is not None:
        return PRO, ""
    return "", "Use this card in your EverDrive once first."


def state(card: Path | None) -> State:
    """Read the card: which EverDrive it is for, and where the switch stands."""
    cart, why = cart_of(card)
    if not cart:
        return State(why=why)
    firmware = find(card, card_layout.FIRMWARE_FOLDER)
    if cart == X7 and not has_hook(find(firmware, card_layout.FIRMWARE_OS)):
        return State(X7, why="Your EverDrive OS is too old for this. Update it to use this option.")
    browser = find(card, card_layout.BROWSER_ROM)
    start = find(firmware, START_FILE[cart])
    if start is not None and start.is_file():
        if not is_browser(start):
            return State(cart, why=f"{shown(cart)} already holds another program, so this option is off.")
        stale = browser is not None and browser.is_file() and digest(browser) != digest(start)
        return State(cart, available=True, on=True, stale=stale)
    if browser is None or not browser.is_file():
        return State(cart, why="Available once SleekMenu is on the card.")
    return State(cart, available=True)


def turn_on(card: Path) -> None:
    """The browser at the card root, copied as the start-up file of the
    card's EverDrive."""
    cart, _ = cart_of(card)
    firmware = find(card, card_layout.FIRMWARE_FOLDER)
    browser = find(card, card_layout.BROWSER_ROM)
    target = find(firmware, START_FILE[cart]) or firmware / START_FILE[cart]
    part = target.with_name(target.name + ".part")
    try:
        part.write_bytes(browser.read_bytes())
        os.replace(part, target)
    finally:
        if part.exists():
            part.unlink()


def turn_off(card: Path) -> None:
    cart, _ = cart_of(card)
    if not cart:
        return
    start = find(find(card, card_layout.FIRMWARE_FOLDER), START_FILE[cart])
    if start is not None and is_browser(start):
        start.unlink()


def sync(card: Path, wanted: bool | None, log=None) -> State:
    """Put the switch where the run was told to, or keep the copy in step
    when it was told nothing (`wanted` None). Says what it did in the
    report, and why not when it could not."""
    log = log or (lambda line: None)
    now = state(card)
    if wanted is None:
        if now.on and now.stale:
            turn_on(card)
            log(f"boot:     {now.file} brought up to date with {card_layout.BROWSER_ROM}")
        return state(card)
    if wanted:
        if not now.available:
            log(f"boot:     not changed. {now.why}")
        elif not now.on or now.stale:
            turn_on(card)
            log(f"boot:     the console now starts in SleekMenu ({card_layout.BROWSER_ROM} copied to "
                f"{now.file})" if not now.on else
                f"boot:     {now.file} brought up to date with {card_layout.BROWSER_ROM}")
    elif now.on:
        turn_off(card)
        log(f"boot:     the console starts in the EverDrive menu again ({now.file} removed)")
    return state(card)
