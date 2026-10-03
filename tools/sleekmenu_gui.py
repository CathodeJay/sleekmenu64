#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Prepare a card from a window: the same run as sleekmenu-prep, without a
terminal.

Pick the card (found on its own when it is the only removable disk), read
what is on it, press the one button -- Set up card the first time, Update
card after -- and watch the run go through its four steps, with a Stop if
it is taking too long. What the card lacks is fetched by the run itself;
the choices most people never change are on the Options tab. Nothing here
decides anything about the card: the window collects a handful of answers
and hands them to tools/sleekmenu_prep.run(), which is what the command
line runs. The downloadable builds are this file frozen with its Python;
from a checkout it is `python3 tools/sleekmenu_gui.py`, or
`python3 sleekmenu-prep.pyz --gui`.

Tkinter is imported when the window is made, not when this module is,
because a Python without it still has to run the command line and the
tests. Everything that can be checked without a screen -- which disks look
like cards, what the tab says about one, how the run reports into the
window -- is kept apart from the widgets for that reason.
"""

from __future__ import annotations

import argparse
import io
import os
import queue
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import (card_catalog, card_layout, coverdb, custom_art, fetch, hires, library, make_sprite,
                   metadata_repo, progress, provenance, sleekmenu_prep, version)
from tools.metadata_repo import MetadataRepo

TITLE = f"SleekMenu 64 {version.VERSION} — prepare a card"
DOWNLOAD_URL = metadata_repo.RELEASES_URL
#: The box is 96x72 on the console; twice that on a desktop screen is
#: legible without pretending to be the source picture.
BOX_ZOOM = 2


def available() -> bool:
    """Whether this Python can draw the window at all."""
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return False
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    return True


# -- disks -------------------------------------------------------------------

def removable_volumes(platform: str = sys.platform, listdir=os.listdir, is_root=None) -> list[Path]:
    """Where a card would be mounted, per platform: /Volumes on macOS less the
    boot disk, removable drive letters on Windows, the media folders on
    Linux. Never the system disk, so a wrong click cannot prepare it."""
    found: list[Path] = []
    is_root = is_root or _is_root
    if platform == "darwin":
        for name in sorted(_listing(listdir, "/Volumes")):
            path = Path("/Volumes") / name
            if not is_root(path):
                found.append(path)
    elif platform == "win32":
        found.extend(_windows_removable())
    else:
        for base in ("/media", "/run/media"):
            for user in sorted(_listing(listdir, base)):
                for name in sorted(_listing(listdir, f"{base}/{user}")):
                    found.append(Path(base) / user / name)
        for name in sorted(_listing(listdir, "/mnt")):
            found.append(Path("/mnt") / name)
    return found


def _listing(listdir, path: str) -> list[str]:
    try:
        return [name for name in listdir(path) if not card_layout.hidden(name)]
    except OSError:
        return []


def _is_root(path: Path) -> bool:
    try:
        return os.path.samefile(path, "/")
    except OSError:
        return False


def _windows_removable() -> list[Path]:
    """Drive letters whose type is removable, asked of the system."""
    try:
        import ctypes
        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        return []
    drive_removable = 2
    found = []
    mask = kernel.GetLogicalDrives()
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(ord('A') + i)}:\\"
            if kernel.GetDriveTypeW(root) == drive_removable:
                found.append(Path(root))
    return found


def newcomers(document: dict, roms: list[str]) -> list[str]:
    """ROMs in the catalogued folder that the last run did not catalogue
    and did not set aside: games added since, which the browser lists
    without a box until the next update. `roms` is the card's walk;
    only the folder the catalog covers counts."""
    catalogued = {str(game.get("path", "")).casefold() for game in document.get("games", [])}
    aside = {str(entry.get("path", "")).casefold() for entry in document.get("set_aside", [])}
    folder = str(document.get("roms", "") or "").strip("/")
    prefix = folder.casefold() + "/" if folder else ""
    return [path for path in roms if path.casefold().startswith(prefix)
            and path.casefold() not in catalogued and path.casefold() not in aside]


SET_UP = "Set up card"
UPDATE = "Update card"


@dataclass(frozen=True)
class CardStatus:
    """The Card tab's words for one card: what is on it, what the button is
    called, and what pressing it will do."""
    headline: str
    detail: str = ""
    action: str = SET_UP        # the button's label
    explain: str = ""           # the line under the button
    last: str = ""              # when the card was last written, "" for never
    ready: bool = False         # there is a card for the button to act on


def plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count:,} {one if count == 1 else (many or one + 's')}"


def when(built: str) -> str:
    """A catalog's `built` stamp as a person's clock says it: "20 Sep 2026,
    02:52" in this computer's time; "" for a stamp that will not read."""
    try:
        moment = datetime.fromisoformat(str(built)).astimezone()
    except ValueError:
        return ""
    return f"{moment.day} {moment.strftime('%b %Y, %H:%M')}"


def card_status(card: Path | None, offline: bool = False, roms: list[str] | None = None) -> CardStatus:
    """What the Card tab says about `card`. `roms` is the card's walk when
    the caller already has it. `offline` is the owner's choice not to
    download: the words under the button say what that leaves out."""
    if card is None:
        return CardStatus("Pick your card", "Plug it in and press Refresh, or choose its folder.")
    if roms is None:
        try:
            roms = library.walk(card)
        except library.LibraryError:
            return CardStatus("That is not a card", "Choose the card itself: the folder its games are in.")
    try:
        document = card_catalog.load(card)
    except card_catalog.CatalogJsonError:
        document = None
    kept = " Downloads are off: only what is already on the card is used." if offline else ""
    if document is None:
        if not roms:
            return CardStatus("No games on this card yet",
                              "Copy your games onto it, in any folders you like, then press Refresh.",
                              SET_UP, "Makes the folders SleekMenu uses, and nothing else until there are games.",
                              ready=True)
        earlier = (card / card_layout.CARD_FOLDER / card_layout.CATALOG_NAME).is_file()
        found = f"{plural(len(roms), 'game')} found on it. Nothing is moved or renamed."
        if earlier:
            return CardStatus("Update this card", found + " It was prepared by an earlier version.", UPDATE,
                              "Reads the games again, fetches their boxes and descriptions, and rewrites "
                              "the catalog." + kept, ready=True)
        return CardStatus("Set up this card", found, SET_UP,
                          "Writes the catalog from what is already on the card. Downloads are off, so the "
                          "games get no boxes or descriptions that are not there." if offline else
                          "Fetches a box and a description for each game, then writes the catalog. Up to "
                          "about 330 MB for a complete library, once. You can stop and carry on later.",
                          ready=True)
    games = document.get("games", [])
    new = len(newcomers(document, roms))
    boxless = sum(1 for game in games
                  if str((game.get("sources") or {}).get("cover", provenance.NONE)) == provenance.NONE)
    parts = []
    if new:
        parts.append(f"{new:,} added since the last update.")
    if boxless:
        parts.append(f"{boxless:,} {'has' if boxless == 1 else 'have'} no box.")
    if new:
        explain = (f"Adds the {plural(new, 'new game')} with {'its box and description' if new == 1 else 'their boxes and descriptions'}"
                   ", then rewrites the catalog.")
    else:
        explain = "Nothing new on the card. Update after adding games or changing an option."
    built = when(str(document.get("built", "")))
    return CardStatus(f"{plural(len(games), 'game')} on this card", " ".join(parts) or "Everything is up to date.",
                      UPDATE, explain + kept, f"Last update: {built}" if built else "", ready=True)


# -- a run, in four steps -------------------------------------------------

#: What a run does, as a person would say it. sleekmenu_prep.run() works in
#: this order.
STEPS = ("Read your games", "Fetch boxes and descriptions", "Build the catalog", "Write it to the card")
#: The run's passes, by the label their progress carries, and the step each
#: belongs to.
STEP_OF_PASS = {"scanning": 0, "checksums": 0, "fetching": 1, "boxes": 1, "sprites": 2}
#: Lines of the report that start a step with no pass of its own.
STEP_OF_LINE = (("writing:", 3), ("covers:", 2), ("hires:", 1), ("metadata: not on the card", 1))


class Steps:
    """Where a run is, from what it reports: the step under way and a few
    words beside each. Kept apart from the widgets, which only draw it."""

    def __init__(self):
        self.current = -1                   # -1: no run to show; len(STEPS): ended well
        self.notes = [""] * len(STEPS)
        self.fraction = 0.0                 # of the pass under way
        self._seen = False

    def start(self) -> None:
        self.__init__()
        self.current = 0

    def _reach(self, step: int) -> None:
        self._seen = True
        if step > self.current:
            self.current, self.fraction = step, 0.0

    def progress(self, label: str, count: int, total: int) -> None:
        step = STEP_OF_PASS.get(label)
        if step is None:
            return
        self._reach(step)
        self.fraction = count / total if total else 1.0
        if label == "scanning":
            self.notes[step] = plural(total, "file") if count >= total else f"{count:,} of {total:,}"
        elif label == "fetching":
            pieces = 1048576 // fetch.CHUNK
            self.notes[step] = f"{count // pieces} of {max(1, total // pieces)} MB"
        elif label == "boxes":
            self.notes[step] = plural(total, "box", "boxes") if count >= total else f"{count:,} of {total:,} boxes"
        elif label == "sprites":
            self.notes[step] = plural(total, "cover") if count >= total else f"{count:,} of {total:,} covers"

    def line(self, text: str) -> None:
        for prefix, step in STEP_OF_LINE:
            if text.startswith(prefix):
                self._reach(step)
                return

    def end(self, code: int | None) -> None:
        """A run that ended well has done every step; one that ended any
        other way stays where it stopped. A run that had nothing to do --
        a card with no games -- has no steps to show."""
        if not self._seen:
            self.current = -1
        elif code == 0:
            self.current, self.fraction = len(STEPS), 1.0

    def state(self, step: int) -> str:
        return "done" if step < self.current else "now" if step == self.current else "next"


def finished_line(code: int | None, outcome, status: CardStatus, games_on_card: bool = True) -> str:
    """One sentence for how a run ended."""
    if code == 3:
        return f"Stopped. What was fetched is kept; press {status.action} to carry on."
    if code != 0:
        return ""
    if not games_on_card:
        return "The folders are ready. Copy your games onto the card, then press Refresh."
    if outcome is not None and outcome.collection_failed:
        return ("Done, but the boxes and descriptions could not be downloaded. Check the connection "
                f"and press {status.action} again.")
    if outcome is not None and outcome.boxes_unreached:
        return (f"Done, but {plural(outcome.boxes_unreached, 'box', 'boxes')} could not be downloaded. "
                f"Press {status.action} again when the connection is back.")
    return "Done. Eject the card and start SleekMenu64.z64 from the EverDrive menu."


def megabytes(size: int) -> str:
    """A file size the way the window says it: whole megabytes, one decimal
    under ten."""
    value = size / 1048576
    return f"{value:.0f} MB" if value >= 10 else f"{value:.1f} MB"


# -- the run, reported into the window --------------------------------------

class Runner:
    """sleekmenu_prep.run() on a thread, with every line and every progress
    step posted to a queue the window drains between frames. The window
    never blocks on the card, and the run never touches a widget. `stop()`
    raises a flag the run looks at before every step; it ends with code 3
    a moment later, having written nothing more."""

    def __init__(self, options: sleekmenu_prep.Options | None = None, job=None, kind: str = "prepare"):
        """`options` for a run of the tool; or `job`, any callable taking
        (log, fail, progress_factory, cancel) and returning an exit code,
        run the same way. `outcome` is what a finished run could not do."""
        self.options = options
        self.outcome = sleekmenu_prep.Outcome()
        self.job = job
        self.kind = kind
        self.events: queue.Queue = queue.Queue()
        self.code: int | None = None
        self.stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._work, name="sleekmenu-prep", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stopping.set()

    def run_inline(self) -> int:
        """The same run on the calling thread, for tests."""
        self._work()
        return self.code if self.code is not None else 1

    def _work(self) -> None:
        events = self.events
        runner = self

        class Bar:
            def __init__(self, total: int, label: str):
                self.total, self.label, self.count = total, label, 0
                events.put(("progress", label, 0, total))

            def step(self, detail: str = "", n: int = 1) -> None:
                self.count += n
                events.put(("progress", self.label, self.count, self.total))
                if detail:
                    events.put(("detail", detail))

            def done(self, summary: str = "") -> None:
                events.put(("progress", self.label, self.total, self.total))
                events.put(("log", summary or f"{self.label}: {self.count}/{self.total}"))

        job = self.job or (lambda log, fail, progress_factory, cancel: sleekmenu_prep.run(
            self.options, log=log, fail=fail, progress_factory=progress_factory, cancel=cancel,
            outcome=self.outcome))
        try:
            runner.code = job(lambda line: events.put(("log", line)),
                              lambda line: events.put(("error", line)),
                              Bar, self.stopping.is_set)
        except Exception as error:  # noqa: BLE001 -- the window must say it, not die
            events.put(("error", f"sleekmenu-prep: {type(error).__name__}: {error}"))
            runner.code = 1
        events.put(("done", runner.code))

    def drain(self) -> list[tuple]:
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out


@dataclass(frozen=True)
class CollectionStatus:
    """The collection a run would read, and the line that says so on the
    Options tab."""
    ready: bool
    line: str
    path: Path | None = None
    downloadable: bool = False     # none on the card, a card to put one on, downloads allowed


_box_counts: dict[tuple[str, int, int], int] = {}


def count_boxes(path: Path) -> int:
    """How many boxes a collection holds, remembered per file so a field
    that changes on every keystroke does not reopen a 52 MB zip each time.
    Raises RepoError for something that is not a collection."""
    try:
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
    except OSError as error:
        raise metadata_repo.RepoError(str(error)) from error
    if key not in _box_counts:
        with MetadataRepo.open(path) as repo:
            _box_counts[key] = repo.art_count()
    return _box_counts[key]


def collection_status(card: Path | None, chosen: str = "", offline: bool = False) -> CollectionStatus:
    """The collection a run would use -- the file chosen on the Options tab, else
    the one on the card -- opened and counted. One that is not there is
    fetched by the run, unless downloads are off."""
    offline = offline or fetch.offline_by_request()
    if chosen.strip():
        path = Path(chosen.strip()).expanduser()
        try:
            boxes = count_boxes(path)
        except metadata_repo.RepoError as error:
            return CollectionStatus(False, f"✗ {path.name} is not the collection: {error}")
        if not boxes:
            return CollectionStatus(False, f"✗ {path.name} holds no boxes.")
        return CollectionStatus(True, f"✓ Using {path.name}: {boxes} boxes.", path)
    if card is None:
        return CollectionStatus(False, "")
    found = metadata_repo.find_on_card(card)
    if found is not None:
        try:
            boxes = count_boxes(found)
        except metadata_repo.RepoError as error:
            return CollectionStatus(False, f"✗ {found.name} on the card will not open ({error}): "
                                    + ("choose a copy (click here for GitHub)." if offline
                                       else "it is fetched again at the next update."),
                                    None, not offline)
        where = found.relative_to(card).as_posix() if found.is_relative_to(card) else str(found)
        size = f", {megabytes(found.stat().st_size)}" if found.is_file() else ""
        return CollectionStatus(True, f"✓ {where} is on the card: {boxes} boxes{size}.", found)
    if offline:
        return CollectionStatus(False, f"✗ Not on the card, and downloads are off: choose a copy of "
                                       f"{metadata_repo.RELEASE_ZIP_NAME} (click here for GitHub).")
    return CollectionStatus(False, "Not on the card yet: it is fetched the first time (about 52 MB, "
                                   "from GitHub).", None, True)


def options_from(card: str, metadata: str = "", roms: str = "", fix_checksums: bool = False,
                 rebuild: bool = False, offline: bool = False,
                 remembered: bool = False) -> sleekmenu_prep.Options:
    """The window's choices as the run takes them. An empty collection
    means whatever is on the card, fetched when there is none. An empty
    games folder is the whole card, said so: the field shows what the card
    remembers, so clearing it is a choice, not an omission.
    High-resolution boxes are always wanted: asked for on a card that has
    none or is being rebuilt, kept complete on one that has them
    (`remembered`), where the boxes libretro was found not to have are not
    asked about every time. Hacks are always checked; `fix_checksums`
    rewrites the stale ones. The box view's pack is always built from the
    window; --no-large-covers is the terminal's."""
    return sleekmenu_prep.Options(
        card=Path(card) if card.strip() else None,
        metadata=Path(metadata) if metadata.strip() else None,
        roms=Path(roms.strip().strip("/")) if roms.strip().strip("/") else sleekmenu_prep.WHOLE_CARD,
        fix_checksums=fix_checksums,
        no_download=bool(offline),
        hires=None if remembered and not rebuild else True,
        rebuild=bool(rebuild),
    )


# -- the games tab -----------------------------------------------------------

# The Show choice above the list.
SHOW_ALL = "all"
SHOW_LOOK = "look"          # no box, or nothing known about the game
SHOW_CHANGED = "changed"    # the owner's own art, text or facts
SHOW_NEW = "new"            # on the card, not in the catalog yet
SHOW_LABELS = {SHOW_ALL: "All", SHOW_LOOK: "Needs a look", SHOW_CHANGED: "Changed by me", SHOW_NEW: "New"}

# The rows the list shows beyond the catalog's own games. A record with one
# of these in `state` is not in catalog.json: the tab made it from the card.
STATE_WAITING = "waiting"    # on the card, not in the catalog: the next update adds it
STATE_ASIDE = "aside"        # set aside by the tool: not a ROM
STATE_PENDING = "pending"    # a catalogued game with an edit the next update will apply

#: What a game is, as its owner can change it, and the blank of each.
FIELDS = {"title": "", "genre": "", "publisher": "", "year": 0, "players": 0, "regions": [], "description": ""}
FIELD_LABELS = {"title": "Title", "genre": "Genre", "publisher": "Publisher", "year": "Year",
                "players": "Players", "regions": "Region", "description": "Description", "cover": "box"}
REGION_ORDER = ("USA", "JAPAN", "EUROPE")
REGION_LABELS = {"USA": "USA", "JAPAN": "Japan", "EUROPE": "Europe"}


def card_rows(card: Path | None, document: dict | None) -> list[dict]:
    """The newcomers and the set-asides as records the list can hold beside
    the catalog's: a path, a title from the file name, a state, and for a
    set-aside the reason."""
    if card is None or document is None:
        return []
    try:
        roms = library.walk(card)
    except library.LibraryError:
        roms = []
    rows = [{"path": path, "title": PurePosixPath(path).stem, "state": STATE_WAITING, "sources": {}}
            for path in newcomers(document, roms)]
    rows += [{"path": str(entry.get("path", "")), "title": PurePosixPath(str(entry.get("path", ""))).stem,
              "state": STATE_ASIDE, "why": str(entry.get("why", "")), "sources": {}}
             for entry in document.get("set_aside", []) if entry.get("path")]
    return rows


def lacks(game: dict) -> list[str]:
    """What a catalogued game is missing that its owner can give it: a box,
    and anything known about it at all. A missing description is not
    counted: half the library has none, and the page reads fine without."""
    missing = []
    if not game.get("cover"):
        missing.append("box")
    if not (game.get("genre") or game.get("publisher") or game.get("year")):
        missing.append("facts")
    return missing


def is_changed(game: dict, pending) -> bool:
    return pending is not None or provenance.edited(game.get("sources") or {})


def status_of(record: dict, pending=None) -> str:
    """The list's last column: the one thing worth knowing about a row, or
    nothing."""
    state = record.get("state")
    if state == STATE_WAITING:
        return "New"
    if state == STATE_ASIDE:
        return "Not a ROM"
    if pending is not None:
        return "Edit waiting"
    missing = lacks(record)
    if missing:
        return "No " + ", no ".join(missing)
    if provenance.edited(record.get("sources") or {}):
        return "Changed by me"
    return ""


def shown_records(document: dict | None, rows: list[dict], pending: dict, mode: str) -> list[dict]:
    """The records one Show choice lists."""
    games = list((document or {}).get("games", []))
    waiting = [row for row in rows if row.get("state") == STATE_WAITING]
    if mode == SHOW_LOOK:
        return [game for game in games if lacks(game)]
    if mode == SHOW_CHANGED:
        return [game for game in games if is_changed(game, pending.get(str(game.get("path", ""))))]
    if mode == SHOW_NEW:
        return waiting
    return games + list(rows)


def show_counts(document: dict | None, rows: list[dict], pending: dict) -> dict[str, int]:
    return {mode: len(shown_records(document, rows, pending, mode)) for mode in SHOW_LABELS}


def owned_fields(game: dict, own, pending=None) -> set[str]:
    """The fields of a game that are its owner's word rather than the
    database's or the collection's: what the catalog has as theirs, what
    their file says, and what an edit not yet on the card will make so.
    "cover" is the box."""
    sources = game.get("sources") or {}
    owned = {name for name in FIELDS if sources.get(name) == provenance.YOURS}
    if provenance.is_yours(str(sources.get("cover", ""))):
        owned.add("cover")
    if own is not None:
        owned.update(own.facts)
        if own.title:
            owned.add("title")
        if own.description:
            owned.add("description")
    if pending is not None:
        owned.update(pending.fields)
        if pending.picture is not None:
            owned.add("cover")
    return owned


def _plain(name: str, value):
    """A field's value in the one shape two of them are compared in."""
    if name == "regions":
        return [region for region in REGION_ORDER if region in (value or [])]
    if name in ("year", "players"):
        return int(value or 0)
    return " ".join(str(value or "").split())


def edit_values(game: dict, own, form: dict) -> tuple[str, str, dict]:
    """What goes in the owner's file for a game, from the panel's fields as
    they stand: the title, the description and the facts.

    The fields show the game as the console will, whoever each value came
    from, so most of them say what the card already has. A field that is
    the owner's already is written with whatever it now says; one that is
    not is written only when it no longer says what the catalog does; and
    an emptied field is written nowhere, which is how the original comes
    back."""
    mine = set(own.facts) if own is not None else set()
    if own is not None and own.title:
        mine.add("title")
    if own is not None and own.description:
        mine.add("description")
    out = {}
    for name, blank in FIELDS.items():
        value = _plain(name, form.get(name, blank))
        if value in ("", 0, []):
            continue
        if name in mine or value != _plain(name, game.get(name, blank)):
            out[name] = value
    return out.pop("title", ""), out.pop("description", ""), out


def pending_line(pending) -> str:
    """One line for the panel: what the card does not have yet."""
    parts = []
    changed = [FIELD_LABELS[name].lower() for name in FIELDS if name in pending.fields]
    if pending.picture is not None:
        changed.append("box")
    if changed:
        parts.append("Changed here, not on the card yet: " + ", ".join(changed) + ".")
    if pending.removed:
        parts.append("Your " + ", ".join(FIELD_LABELS[name].lower() for name in pending.removed
                                         if name in FIELD_LABELS)
                     + " was removed: the original comes back at the next update.")
    return " ".join(parts)


def pending_picture(path: Path) -> tuple[int, int, bytes] | None:
    """A picture fitted into the box view's frame, for the panel: the
    sprite does not exist until the next update, so the picture stands in,
    sized the way the sprite will be. None when it will not open."""
    try:
        from PIL import Image
    except ImportError:
        return None
    width, height = make_sprite.LARGE_CANVAS_SIZE
    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((width, height))
    except (OSError, ValueError):
        return None
    canvas = Image.new("RGB", (width, height), (35, 42, 52))
    canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    return width, height, canvas.tobytes()


def matches(record: dict, query: str) -> bool:
    """Every word of the query somewhere in the game: title, file name,
    publisher, genre, year or game code, whatever the case."""
    words = query.casefold().split()
    if not words:
        return True
    haystack = " ".join(str(record.get(key) or "") for key in
                        ("title", "path", "publisher", "genre", "year", "code")).casefold()
    return all(word in haystack for word in words)


def game_notes(game: dict) -> list[str]:
    """What is worth saying about a game that its fields do not say
    themselves: how sure the tool is of what it is, and a box that is not
    quite its own."""
    notes = []
    identified = game.get("identified", "")
    if identified == "":
        notes.append("Not recognised: nothing is known about it but its file name. Fill in what you like.")
    elif identified != "crc":
        notes.append("Recognised by its game code, not as this exact file: the box, text and facts are "
                     "the original game's.")
    cover = str((game.get("sources") or {}).get("cover", ""))
    if cover == provenance.COVER_COLLECTION_REGION:
        notes.append("The box is another region's.")
    elif cover == provenance.COVER_LIBRETRO_MODIFIED:
        notes.append("The box was changed since the tool fetched it.")
    return notes


def enable_drop(widget, on_files) -> bool:
    """Let files be dropped onto a widget, when tkinterdnd2 is installed
    in this Python and its native library loads; False otherwise, and the
    button beside the widget is the same thing without the drop. The
    frozen builds do not carry it: a native extension that fails to load
    on some systems is not worth the feature depending on it."""
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
        TkinterDnD._require(widget.winfo_toplevel())
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", lambda event: on_files(list(widget.tk.splitlist(event.data))))
    except Exception:  # noqa: BLE001 -- any failure means no drop, which is fine
        return False
    return True


# -- the boxes a game could have -------------------------------------------------

def region_label(letter: str) -> str:
    """The region a game code's last letter stands for, as the picker says
    it: every PAL market shares Europe's box."""
    return {"E": "USA", "J": "Japan"}.get(letter.upper(), "Europe")


def box_choices(database: dict, game: dict) -> list[tuple[str, list[str]]]:
    """The boxes libretro may have for a game: one per region the database
    knows the game in, its own first, each with the names to try. The
    release itself before its revisions and betas, which libretro files as
    links to it."""
    code = str(game.get("code") or "").upper()
    if not re.fullmatch(r"[A-Z0-9]{4}", code):
        return []
    regions: dict[str, list[str]] = {}
    for entry in database.values():
        serial = str(entry.serial or "").upper()
        if len(serial) == 4 and serial[:3] == code[:3]:
            regions.setdefault(region_label(serial[3]), []).append(entry.name)
    own = region_label(code[3])
    order = sorted(regions, key=lambda label: (label != own, ("USA", "Europe", "Japan").index(label)))
    return [(label, sorted(regions[label], key=lambda name: (name.count("("), name.casefold())))
            for label in order]


def fetch_choice(names: list[str], base_url: str | None = None, limit: int = 4) -> tuple[bytes, str] | None:
    """The first of `names` libretro has a picture for, and that name."""
    for name in names[:limit]:
        found = hires.box_for(name, base_url or hires.BASE_URL)
        if found is not None:
            return found[0], name
    return None


class BoxPicker:
    """Choose a box for one game: the one on the card, the ones libretro
    has for it in each region -- fetched as the window opens, each shown as
    it arrives -- or a picture of the owner's own. The choice goes back to
    the Games tab's panel, where Save puts it on the card."""

    TILE = (176, 124)

    def __init__(self, tab, game: dict, current: tuple[int, int, bytes] | None):
        tk, ttk = tab.tk, tab.ttk
        self.tab, self.game = tab, game
        self.results: queue.Queue = queue.Queue()
        self.boxes: dict[str, bytes] = {}
        self.photos: dict[str, object] = {}
        self.tiles: dict[str, object] = {}
        self.choice = tk.StringVar(value="current")
        self.note = tk.StringVar()
        self.closed = False
        window = self.window = tk.Toplevel(tab.frame)
        window.title("Choose a box")
        window.transient(tab.frame.winfo_toplevel())
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=str(game.get("title", "")), font=tab.strong).grid(row=0, column=0, sticky="w")
        self.row = ttk.Frame(frame)
        self.row.grid(row=1, column=0, sticky="w", pady=(12, 0))
        width, height = self.TILE
        self.blank = tk.PhotoImage(master=window, format="PPM",
                                   data=make_sprite.to_ppm(width, height, bytes((35, 42, 52)) * (width * height)))
        self.add_tile("current", "On the card now", self.fitted_pixels(current))
        choices = [] if tab.database is None else box_choices(tab.database(), game)
        offline = fetch.offline_by_request() or (tab.offline is not None and tab.offline())
        if offline or not choices:
            self.note.set("Downloads are off: only a picture of your own can be chosen." if offline and choices
                          else "libretro has no other box for this game.")
        else:
            for label, _names in choices:
                self.add_tile(label, f"{label}: looking…", None)
            self.note.set("The found boxes come from the libretro thumbnails project.")
            threading.Thread(target=self.work, args=(choices,), name="sleekmenu-boxes", daemon=True).start()
            window.after(100, self.poll)
        ttk.Label(frame, textvariable=self.note, foreground=tab.colors["muted"], wraplength=540,
                  justify="left").grid(row=2, column=0, sticky="w", pady=(12, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        ttk.Button(buttons, text="My own picture…", command=self.own_picture).pack(side="left")
        self.use = ttk.Button(buttons, text="Use this box", command=self.confirm, state="disabled")
        self.use.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="right", padx=(0, 8))
        self.choice.trace_add("write", lambda *_args: self.use.configure(
            state="normal" if self.choice.get() in self.boxes else "disabled"))
        try:
            window.grab_set()
        except tk.TclError:
            pass

    def fitted_pixels(self, pixels: tuple[int, int, bytes] | None):
        """Decoded pixels as a tile's picture, or None."""
        if pixels is None:
            return None
        try:
            from PIL import Image
        except ImportError:
            return None
        width, height, rgb = pixels
        return self.fitted(Image.frombytes("RGB", (width, height), rgb))

    def fitted(self, image):
        from PIL import Image
        width, height = self.TILE
        image = image.convert("RGB")
        image.thumbnail((width, height))
        canvas = Image.new("RGB", (width, height), (35, 42, 52))
        canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
        return self.tab.tk.PhotoImage(master=self.window, format="PPM",
                                      data=make_sprite.to_ppm(width, height, canvas.tobytes()))

    def add_tile(self, key: str, text: str, photo) -> None:
        self.photos[key] = photo or self.blank
        tile = self.tab.ttk.Radiobutton(self.row, text=text, image=self.photos[key], compound="top",
                                        variable=self.choice, value=key)
        tile.pack(side="left", padx=(0, 12))
        self.tiles[key] = tile

    def work(self, choices) -> None:
        """Off the window's thread: one box per region, each posted as it
        lands."""
        for label, names in choices:
            if self.closed:
                return
            try:
                found = fetch_choice(names)
                self.results.put((label, found[0] if found else None, ""))
            except Exception as error:  # noqa: BLE001 -- said in the tile, never raised into a thread
                self.results.put((label, None, str(getattr(error, "reason", error))))
        self.results.put(None)

    def poll(self) -> None:
        if self.closed:
            return
        while True:
            try:
                item = self.results.get_nowait()
            except queue.Empty:
                break
            if item is None:
                return
            label, data, trouble = item
            photo = None
            if data is not None:
                try:
                    from PIL import Image
                    photo = self.fitted(Image.open(io.BytesIO(data)))
                except (ImportError, OSError, ValueError):
                    data = None
            if data is None:
                self.tiles[label].configure(text=f"{label}: " + ("not reached" if trouble else "none"),
                                            state="disabled")
                continue
            self.boxes[label] = data
            self.photos[label] = photo
            self.tiles[label].configure(text=label, image=photo)
        self.window.after(100, self.poll)

    def own_picture(self) -> None:
        from tkinter import filedialog
        chosen = filedialog.askopenfilename(
            parent=self.window, title="A box picture",
            filetypes=[("PNG or JPEG", "*.png *.jpg *.jpeg"), ("All files", "*")])
        if chosen:
            self.tab.set_picture(chosen)
            self.close()

    def confirm(self) -> None:
        """The chosen region's box, written where the panel can take it
        from: Save copies it to the card as the owner's picture."""
        label = self.choice.get()
        data = self.boxes.get(label)
        if data is not None:
            target = self.tab.scratch_file(f"{label}.png")
            target.write_bytes(data)
            self.tab.set_picture(str(target))
        self.close()

    def close(self) -> None:
        self.closed = True
        try:
            self.window.grab_release()
        except Exception:  # noqa: BLE001 -- a window already gone has no grab
            pass
        self.window.destroy()
        self.tab.picker = None


class GamesTab:
    """The card's games as the browser will show them, from
    sleekmenu/catalog.json, and the one place to change one.

    Two regions. The list on the left follows the card's folders, narrowed
    by the search and the Show choice, with the one thing worth knowing
    about each row in its last column. The panel on the right is the
    selected game: its box as the console draws it -- decoded from
    covers.pak, never from the source picture -- and every field the
    console shows, in a box that can be typed in. The fields say what the
    card has, whoever it came from; Save writes the ones that are the
    owner's to say, as the files tools/custom_art.py reads."""

    DETAIL_WIDTH = 400

    def __init__(self, parent, card_of, apply=None, colors=None, database=None, offline=None):
        """`apply(path)`, when given, puts the owner's files on the card's
        catalog -- a run of the tool -- after a Save or an Undo, and answers
        "started", "queued", or why not ("no card", "no collection"); the
        window calls applied() when that run ends. `database()` gives the
        shipped database for the box picker, and `offline()` says whether
        the owner has turned downloads off."""
        import tkinter as tk
        from tkinter import font as tkfont
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.card_of = card_of
        self.apply = apply
        self.database = database
        self.offline = offline
        self.colors = colors or {"muted": "#555555", "good": "#2e7d32", "warn": "#8a4b00", "info": "#1f5fa8"}
        # The line under the panel for one game, kept across redraws until
        # another game is shown: a Save's outcome arrives after the list has
        # been rebuilt.
        self.note_for: tuple[str, str] | None = None
        self.document = None
        self.covers = None
        self.games: dict[str, dict] = {}
        self.rows: list[dict] = []       # newcomers and set-asides, from the card
        self.pending: dict[str, custom_art.Pending] = {}
        self.photo = None
        self.picker = None
        self.shown_path: str | None = None    # the game in the panel
        self._scratch = None
        self.show = tk.StringVar(value=SHOW_ALL)
        self.query = tk.StringVar()
        self.shown = tk.StringVar()
        self.note = tk.StringVar(value="No card picked.")
        # the panel: the selected game, every field as the console shows it
        self.file_name = tk.StringVar()
        self.title = tk.StringVar()
        self.genre = tk.StringVar()
        self.publisher = tk.StringVar()
        self.year = tk.StringVar()
        self.players = tk.StringVar()
        self.regions = {name: tk.BooleanVar(value=False) for name in REGION_ORDER}
        self.picture = tk.StringVar()    # a new box chosen and not saved yet
        self.others = tk.BooleanVar(value=False)
        self.notes = tk.StringVar()
        self.edit_note = tk.StringVar()
        self.strong = tkfont.nametofont("TkDefaultFont").copy()
        self.strong.configure(weight="bold")
        muted = self.colors["muted"]

        frame = ttk.Frame(parent, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        self.frame = frame

        # -- search and the Show choice --------------------------------------
        top = ttk.Frame(frame)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(top, text="Search").pack(side="left")
        search = ttk.Entry(top, textvariable=self.query, width=26)
        search.pack(side="left", padx=(6, 0))
        search.bind("<KeyRelease>", lambda _event: self.fill())
        search.bind("<Escape>", lambda _event: (self.query.set(""), self.fill()))
        self.search = search
        self.show_buttons = {}
        for mode, label in SHOW_LABELS.items():
            button = ttk.Radiobutton(top, text=label, variable=self.show, value=mode, command=self.fill)
            button.pack(side="left", padx=(14, 0))
            self.show_buttons[mode] = button
        ttk.Label(top, textvariable=self.shown, foreground=muted).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Reload", command=self.reload).pack(side="right")
        note = ttk.Label(frame, textvariable=self.note, foreground=self.colors["warn"], justify="left")
        note.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 6))

        # -- the list ----------------------------------------------------------
        left = ttk.Frame(frame)
        left.grid(row=2, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(left, columns=("genre", "year", "status"), selectmode="browse")
        self.tree.heading("#0", text="Game")
        self.tree.column("#0", width=300, minwidth=180, stretch=True)
        for name, heading, width in (("genre", "Genre", 120), ("year", "Year", 48), ("status", "", 124)):
            self.tree.heading(name, text=heading)
            self.tree.column(name, width=width, minwidth=width, stretch=False, anchor="w")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.tag_configure(STATE_WAITING, foreground=self.colors["warn"])
        self.tree.tag_configure(STATE_ASIDE, foreground=muted)
        self.tree.tag_configure(STATE_PENDING, foreground=self.colors["info"])
        self.tree.tag_configure("look", foreground=self.colors["warn"])

        # -- the selected game ---------------------------------------------------
        right = ttk.Frame(frame, padding=(14, 0, 0, 0), width=self.DETAIL_WIDTH)
        right.grid(row=2, column=1, sticky="nsew")
        right.grid_propagate(False)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(6, weight=1)
        self.detail = right
        wrap = self.DETAIL_WIDTH - 20
        # The box is always the box view's size, a placeholder when there
        # is none, so the fields stay put as the selection moves.
        width, height = make_sprite.LARGE_CANVAS_SIZE
        self.placeholder = tk.PhotoImage(
            master=right, format="PPM",
            data=make_sprite.to_ppm(width, height, bytes((35, 42, 52)) * (width * height)))
        self.box = ttk.Label(right, image=self.placeholder, text="", compound="center", foreground="#8291a0")
        self.box.grid(row=0, column=0, sticky="w")
        under = ttk.Frame(right)
        under.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        under.columnconfigure(0, weight=1)
        ttk.Label(under, textvariable=self.file_name, foreground=muted, wraplength=wrap - 130,
                  justify="left").grid(row=0, column=0, sticky="w")
        self.box_button = ttk.Button(under, text="Change box…", command=self.choose_box)
        self.box_button.grid(row=0, column=1, sticky="e")
        self.drop_works = enable_drop(self.box, self.dropped)

        self.labels: dict[str, object] = {}

        def label(parent_, name: str):
            made = ttk.Label(parent_, text=FIELD_LABELS[name])
            self.labels[name] = made
            return made
        form = ttk.Frame(right)
        form.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        label(form, "title").grid(row=0, column=0, sticky="w")
        self.title_entry = ttk.Entry(form, textvariable=self.title)
        self.title_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(6, 0))
        # The genres and publishers already on the card are offered;
        # anything else can be typed.
        label(form, "genre").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.genre_box = ttk.Combobox(form, textvariable=self.genre, width=14)
        self.genre_box.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        label(form, "publisher").grid(row=1, column=2, sticky="w", padx=(10, 0), pady=(6, 0))
        self.publisher_box = ttk.Combobox(form, textvariable=self.publisher, width=14)
        self.publisher_box.grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=(6, 0))
        label(form, "year").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.year_entry = ttk.Entry(form, textvariable=self.year, width=6)
        self.year_entry.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(6, 0))
        label(form, "players").grid(row=2, column=2, sticky="w", padx=(10, 0), pady=(6, 0))
        self.players_box = ttk.Combobox(form, textvariable=self.players, width=3, state="readonly",
                                        values=("", "1", "2", "3", "4"))
        self.players_box.grid(row=2, column=3, sticky="w", padx=(6, 0), pady=(6, 0))
        region_row = ttk.Frame(right)
        region_row.grid(row=3, column=0, sticky="w", pady=(6, 0))
        label(region_row, "regions").pack(side="left")
        self.region_checks = []
        for name in REGION_ORDER:
            check = ttk.Checkbutton(region_row, text=REGION_LABELS[name], variable=self.regions[name])
            check.pack(side="left", padx=(8, 0))
            self.region_checks.append(check)
        label(right, "description").grid(row=5, column=0, sticky="w", pady=(8, 0))
        self.text = tk.Text(right, height=5, width=20, wrap="word", font="TkDefaultFont", undo=True)
        self.text.grid(row=6, column=0, sticky="nsew", pady=(2, 0))
        self.others_check = ttk.Checkbutton(right, variable=self.others)
        ttk.Label(right, textvariable=self.notes, foreground=muted, justify="left", wraplength=wrap).grid(
            row=8, column=0, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(right)
        buttons.grid(row=9, column=0, sticky="e", pady=(8, 0))
        self.undo_button = ttk.Button(buttons, text="Undo my changes", command=self.remove_edit)
        self.undo_button.pack(side="left", padx=(0, 6))
        self.save_button = ttk.Button(buttons, text="Save", command=self.save_edit, default="active")
        self.save_button.pack(side="left")
        ttk.Label(right, textvariable=self.edit_note, foreground=muted, justify="left", wraplength=wrap).grid(
            row=10, column=0, sticky="w", pady=(4, 0))
        self.inputs = [self.title_entry, self.genre_box, self.publisher_box, self.year_entry,
                       *self.region_checks, self.box_button, self.save_button]
        self.show_game(None)

    # -- loading -----------------------------------------------------------

    def reload(self) -> None:
        """Read catalog.json and covers.pak off the card again."""
        card = self.card_of()
        self.document, self.covers, self.games = None, None, {}
        if card is None:
            self.note.set("No card picked.")
        else:
            broken = None
            try:
                self.document = card_catalog.load(card)
            except card_catalog.CatalogJsonError as error:
                broken = str(error)
            if self.document is None:
                self.note.set(broken or card_catalog.why_missing(card))
            else:
                self.covers = card_catalog.Covers.open(card)
                self.games = {str(game["path"]): game for game in self.document["games"]}
                self.note.set("")
        self.rows = card_rows(card, self.document)
        self.games.update({str(row["path"]): row for row in self.rows})
        self.refresh_pending()
        self.shown_path = None
        self.fill()
        self.show_game(None)

    def refresh_pending(self) -> None:
        """What the owner's files on the card would change at the next
        update, read again: after a load, a Save and an Undo. The Show
        choices are counted from it."""
        card = self.card_of()
        self.pending = (custom_art.pending_edits(card, card, self.document)
                        if card is not None and self.document is not None else {})
        games = (self.document or {}).get("games", [])
        self.genre_box.configure(values=sorted({str(g.get("genre") or "") for g in games} - {""}, key=str.casefold))
        self.publisher_box.configure(values=sorted({str(g.get("publisher") or "") for g in games} - {""},
                                                   key=str.casefold))
        counts = show_counts(self.document, self.rows, self.pending)
        for mode, button in self.show_buttons.items():
            button.configure(text=f"{SHOW_LABELS[mode]} {counts[mode]:,}" if self.document is not None
                             else SHOW_LABELS[mode])
        if self.document is not None:
            aside = sum(1 for row in self.rows if row["state"] == STATE_ASIDE)
            waiting = [name for name, edit in self.pending.items()]
            parts = []
            if waiting:
                parts.append(f"{plural(len(waiting), 'edit')} not on the card yet: press Update card on the "
                             "Card tab.")
            if aside:
                parts.append(f"{plural(aside, 'file')} set aside as not a ROM; the browser never lists "
                             f"{'it' if aside == 1 else 'them'}.")
            self.note.set(" ".join(parts))

    def effective(self, game: dict) -> dict:
        """The game as the next update will catalog it: the record with
        the owner's pending fields laid over it."""
        pending = self.pending.get(str(game.get("path", "")))
        if pending is None or not pending.fields:
            return game
        return dict(game, **pending.fields)

    def fill(self) -> None:
        """The list from the loaded catalog and the card's own rows, folders
        first, narrowed by the Show choice and the search. The game in the
        panel stays selected, and what was typed there stays, while it is
        still in the list; when it is not, the panel empties."""
        keep = self.shown_path
        self.tree.delete(*self.tree.get_children())
        if self.document is None:
            self.shown.set("")
            return
        records = shown_records(self.document, self.rows, self.pending, self.show.get())
        total = len(records)
        query = self.query.get().strip()
        if query:
            records = [record for record in records if matches(self.effective(record), query)]
        self.shown.set(f"{len(records):,} of {total:,}" if query else "")
        self._add(card_catalog.tree(records), "")
        if keep is not None and self.tree.exists(keep):
            self.tree.selection_set(keep)
            self.tree.see(keep)
        elif keep is not None:
            self.show_game(None)

    def _add(self, node: dict, parent: str) -> None:
        for name, child in node["folders"].items():
            iid = self.tree.insert(parent, "end", text=f"{name}/  ({card_catalog.count(child)})", open=True)
            self._add(child, iid)
        for record in node["games"]:
            state = str(record.get("state") or "")
            pending = self.pending.get(str(record.get("path", "")))
            game = self.effective(record)
            status = status_of(record, pending)
            tag = state or (STATE_PENDING if pending is not None else "look" if status.startswith("No ") else "")
            self.tree.insert(parent, "end", iid=str(game["path"]), text=str(game.get("title", "")),
                             tags=(tag,) if tag else (),
                             values=(game.get("genre", ""), game.get("year") or "", status))

    # -- the selected game ---------------------------------------------------

    def selected(self) -> dict | None:
        chosen = self.tree.selection()
        return self.games.get(chosen[0]) if chosen else None

    def on_select(self, _event=None) -> None:
        """Another game was picked. The same one selected again -- the list
        was rebuilt around it -- leaves the panel as it is."""
        game = self.selected()
        if game is not None and str(game.get("path", "")) == self.shown_path:
            return
        if game is not None or not self.tree.exists(self.shown_path or ""):
            self.show_game(game)

    def own_text(self, game: dict):
        """The owner's file for a game, as it is on the card now."""
        card = self.card_of()
        if card is None:
            return None
        return custom_art.find_text(custom_art.Index(), card, str(game.get("path", "")),
                                    custom_art.art_dir(card), str(game.get("code") or ""))

    def _set_fields(self, game: dict | None) -> None:
        shown = self.effective(game) if game is not None else {}
        self.title.set(str(shown.get("title", "") or ""))
        self.genre.set(str(shown.get("genre", "") or ""))
        self.publisher.set(str(shown.get("publisher", "") or ""))
        self.year.set(str(shown.get("year") or ""))
        players = str(shown.get("players") or "")
        self.players_box.configure(values=("", "1", "2", "3", "4") if players in ("", "1", "2", "3", "4")
                                   else ("", "1", "2", "3", "4", players))
        self.players.set(players)
        for name, variable in self.regions.items():
            variable.set(name in (shown.get("regions") or []))
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", str(shown.get("description") or ""))
        self.text.edit_reset()

    def show_game(self, game: dict | None) -> None:
        """The panel for a game: every field as the console will show it,
        marked where the value is the owner's own."""
        self.picture.set("")
        self.shown_path = str(game.get("path", "")) if game is not None else None
        state = str((game or {}).get("state") or "")
        catalogued = game is not None and not state
        # A reload shows no game for a moment; only another game's being
        # shown ends the note.
        path = str((game or {}).get("path", ""))
        if self.note_for is not None and game is not None and self.note_for[0] != path:
            self.note_for = None
        self.edit_note.set(self.note_for[1] if self.note_for is not None and game is not None else "")
        self._set_fields(game if catalogued else None)
        if not catalogued and game is not None:
            self.title.set(str(game.get("title", "")))
        self.file_name.set(PurePosixPath(path).name if game is not None else "")
        for widget in self.inputs:
            widget.configure(state="normal" if catalogued else "disabled")
        self.players_box.configure(state="readonly" if catalogued else "disabled")
        self.text.configure(state="normal" if catalogued else "disabled")
        self.undo_button.configure(state="disabled")
        self.others_check.grid_remove()
        for name, made in self.labels.items():
            made.configure(text=FIELD_LABELS[name], foreground="")
        if game is None:
            self.notes.set("")
            self.box.configure(image=self.placeholder, text="")
            self.photo = None
            return
        if state:
            # A row the card gave, not the catalog: what it is and what
            # happens next, and nothing to edit until it is catalogued.
            self.photo = None
            if state == STATE_WAITING:
                self.notes.set("Not in the catalog yet: the browser lists it in its folder, without a "
                               "box, and plays it. Press Update card on the Card tab to add its box and "
                               "facts.")
                self.box.configure(image=self.placeholder, text="NOT YET", compound="center",
                                   foreground="#8291a0")
            else:
                self.notes.set(f"Set aside by the tool ({game.get('why', '')}): the browser never lists "
                               "it, and an update will not add it.")
                self.box.configure(image=self.placeholder, text="NOT A ROM", compound="center",
                                   foreground="#8291a0")
            return
        pending = self.pending.get(path)
        card = self.card_of()
        own = self.own_text(game)
        for name in owned_fields(game, own, pending) & set(self.labels):
            self.labels[name].configure(text=FIELD_LABELS[name] + " · yours", foreground=self.colors["info"])
        # Others with this game's code: its revisions, and hacks built on it.
        count = custom_art.sharing_code(self.document["games"], game) - 1 if self.document else 0
        if count > 0:
            self.others_check.configure(
                text=f"Also change the {plural(count, 'other version')} of this game")
            self.others_check.grid(row=7, column=0, sticky="w", pady=(6, 0))
            sources = game.get("sources") or {}
            self.others.set(str(sources.get("cover", "")).startswith("yours (code")
                            or (own is not None and own.path is not None
                                and card_layout.fold(own.path.stem) == card_layout.fold(str(game.get("code") or ""))))
        else:
            self.others.set(False)
        notes = game_notes(game)
        if pending is not None:
            notes.insert(0, pending_line(pending))
        removable, beside = custom_art.edits_of(card, card, game) if card is not None else ([], [])
        self.undo_button.configure(state="normal" if removable else "disabled")
        if beside and not removable:
            notes.append("This game's picture or text sits beside the ROM; to undo it, remove that file "
                         "yourself.")
        self.notes.set("\n".join(notes))
        self.draw_box(game)

    def draw_box(self, game: dict) -> None:
        """The box view's sprite when the card has the large pack -- what
        the console draws full screen -- else the thumbnail, doubled so it
        is legible. A picture chosen here, or one of the owner's the catalog
        does not carry yet, is shown instead, fitted to the same size."""
        pending = self.pending.get(str(game.get("path", "")))
        chosen = self.picture.get().strip()
        preview = pending_picture(Path(chosen)) if chosen else (
            pending_picture(pending.picture) if pending is not None and pending.picture else None)
        if preview is not None:
            width, height, rgb = preview
            self.photo = self.tk.PhotoImage(master=self.box, format="PPM",
                                            data=make_sprite.to_ppm(width, height, rgb))
            self.box.configure(image=self.photo, text="NOT SAVED YET" if chosen else "NOT ON THE CARD YET",
                               compound="top", foreground=self.colors["warn"])
            return
        pixels = self.current_pixels(game)
        if pixels is None:
            self.photo = None
            self.box.configure(image=self.placeholder, text="NO BOX", compound="center", foreground="#8291a0")
            return
        width, height, rgb = pixels
        self.photo = self.tk.PhotoImage(master=self.box, format="PPM", data=make_sprite.to_ppm(width, height, rgb))
        if width < make_sprite.LARGE_CANVAS_SIZE[0]:
            self.photo = self.photo.zoom(BOX_ZOOM, BOX_ZOOM)
        self.box.configure(image=self.photo, text="", compound="center")

    def current_pixels(self, game: dict) -> tuple[int, int, bytes] | None:
        if self.covers is None:
            return None
        return self.covers.pixels(game, large=True) or self.covers.pixels(game)

    # -- changing it -----------------------------------------------------------

    def form(self) -> tuple[dict, list[str]]:
        """The panel's fields as values, and what is wrong with them: a
        year that is not one."""
        problems: list[str] = []
        year = self.year.get().strip()
        if year and not (year.isdigit() and 1970 <= int(year) <= 2100):
            problems.append("the year must be from 1970 to 2100")
        players = self.players.get().strip()
        return ({"title": self.title.get(), "genre": self.genre.get(), "publisher": self.publisher.get(),
                 "year": int(year) if year.isdigit() else 0,
                 "players": int(players) if players.isdigit() else 0,
                 "regions": [name for name in REGION_ORDER if self.regions[name].get()],
                 "description": self.text.get("1.0", "end")}, problems)

    def scratch_file(self, name: str) -> Path:
        """Somewhere to keep a fetched box until it is saved."""
        if self._scratch is None:
            self._scratch = tempfile.TemporaryDirectory(prefix="sleekmenu-boxes-")
        return Path(self._scratch.name) / name

    def choose_box(self) -> None:
        game = self.selected()
        if game is None or game.get("state") or self.picker is not None:
            return
        self.picker = BoxPicker(self, game, self.current_pixels(game))

    def set_picture(self, path: str) -> None:
        """A new box for the selected game, shown in the panel until Save
        puts it on the card."""
        game = self.selected()
        if game is None:
            return
        self.picture.set(path)
        self.draw_box(game)
        self.edit_note.set("Press Save to put this box on the card.")

    def dropped(self, files: list[str]) -> None:
        if files:
            self.set_picture(files[0])

    def save_edit(self) -> None:
        game, card = self.selected(), self.card_of()
        if game is None or card is None or game.get("state"):
            return
        values, problems = self.form()
        if problems:
            self.edit_note.set("Not saved: " + "; ".join(problems))
            return
        picture = Path(self.picture.get().strip()) if self.picture.get().strip() else None
        title, description, facts = edit_values(game, self.own_text(game), values)
        scope = custom_art.SCOPE_CODE if self.others.get() else custom_art.SCOPE_ROM
        try:
            touched = custom_art.save(card, game, picture, title, description, scope, facts)
        except (custom_art.EditError, OSError) as error:
            self.edit_note.set(f"Not saved: {error}")
            return
        path = str(game["path"])
        if not touched:
            self.note_for = (path, "Nothing to save: every field says what the card already has.")
        else:
            self.note_for = (path, "Saved. " + self.put_on_card(path))
        self.redraw(path)

    def put_on_card(self, path: str) -> str:
        """Ask the window to apply the owner's files to the card's catalog,
        and say what happens next. The console reads only the catalog, so
        a file saved and not applied changes nothing on the console."""
        answer = self.apply(path) if self.apply is not None else "no apply"
        if answer in ("started", "queued"):
            return "Putting it on the card…"
        if answer == "no collection":
            return "The console shows it once the card is updated: press the button on the Card tab."
        return "The console shows it once you press Update card."

    def applied(self, path: str | None, code: int | None) -> None:
        """A run that put an edit on the card ended: read the catalog again,
        keep the row that is selected now, and say how it went under the
        game that was saved."""
        current = self.selected()
        keep = str(current["path"]) if current is not None else path
        if code == 0:
            message = "On the card: SleekMenu shows it the next time it starts."
        elif code == 3:
            message = "Saved, but putting it on the card was stopped: press Update card to finish."
        else:
            message = "Saved, but the card was not updated: see the Card tab for why."
        if path is not None:
            self.note_for = (path, message)
        self.reload()
        if keep is not None:
            self.back_to(keep)

    def redraw(self, path: str) -> None:
        """After a Save or an Undo: what is pending again, the list again
        with the same row selected, the panel again."""
        self.refresh_pending()
        self.back_to(path)

    def back_to(self, path: str) -> None:
        """The panel on `path` again after the list was rebuilt. A game the
        Show choice no longer lists -- it needed a look, and now has its box
        -- leaves the panel, and what became of it is still said."""
        self.shown_path = path
        self.fill()
        if self.tree.exists(path):
            self.show_game(self.games.get(path))
        elif self.note_for is not None and self.note_for[0] == path:
            self.edit_note.set(f"{PurePosixPath(path).stem}: {self.note_for[1]}")

    def remove_edit(self) -> None:
        """Undo my changes: the owner's files for this game go, and the
        original comes back."""
        game, card = self.selected(), self.card_of()
        if game is None or card is None or game.get("state"):
            return
        try:
            removed = custom_art.remove(card, card, game)
        except OSError as error:
            self.edit_note.set(f"Not undone: {error}")
            return
        path = str(game["path"])
        self.note_for = (path, ("Your changes are removed. " + self.put_on_card(path)) if removed
                         else "Nothing of yours to undo.")
        self.redraw(path)


# -- the window -------------------------------------------------------------

#: The games-folder choice that means every game on the card.
WHOLE_CARD_LABEL = "The whole card"
STEP_MARKS = {"done": "✓", "now": "●", "next": "○"}


def palette(root, tk, ttk) -> dict[str, str]:
    """The colours the window adds to the system's: a quieter text, a good
    outcome, a warning and a mark for what is the owner's own, chosen
    against the background this window
    actually has, so they read in a dark appearance as in a light one."""
    def rgb(*names):
        for name in names:
            if not name:
                continue
            try:
                return root.winfo_rgb(name)
            except tk.TclError:
                continue
        return None
    style = ttk.Style(root)
    back = rgb(style.lookup("TFrame", "background"), "systemWindowBackgroundColor",
               root.cget("background")) or (65535, 65535, 65535)
    fore = rgb(style.lookup("TLabel", "foreground"), "systemTextColor", "black") or (0, 0, 0)
    dark = sum(back) < sum(fore)
    muted = "#%02x%02x%02x" % tuple(((f * 6 + b * 4) // 10) >> 8 for f, b in zip(fore, back))
    return {"muted": muted, "good": "#7bd3a0" if dark else "#2e7d32", "warn": "#f0b46a" if dark else "#8a4b00",
            "info": "#8fc7f0" if dark else "#1f5fa8"}


def build(smoke: bool = False, card: str = "", metadata: str = ""):
    """The window, as a Tk root. `smoke` closes it after a moment, which is
    how a build is checked to start at all; with `card` as well it presses
    the button and closes when the run is done, which is how the whole
    window is checked to work. A build check never downloads."""
    import tkinter as tk
    from tkinter import filedialog, ttk
    from tkinter import font as tkfont
    import webbrowser

    root = tk.Tk()
    root.title(TITLE)
    root.minsize(960, 680)
    root.geometry("1080x720")
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    page = ttk.Frame(notebook, padding=12)
    notebook.add(page, text="Card")
    page.columnconfigure(0, weight=1)
    page.rowconfigure(1, weight=1)
    colors = palette(root, tk, ttk)

    state: dict = {"runner": None, "steps": Steps(), "status": card_status(None), "walk": None}
    card_var = tk.StringVar()
    roms_var = tk.StringVar()               # "" is the whole card
    roms_shown = tk.StringVar(value=WHOLE_CARD_LABEL)
    metadata_var = tk.StringVar()
    metadata_note = tk.StringVar()
    fix_var = tk.BooleanVar(value=False)
    rebuild_var = tk.BooleanVar(value=False)
    offline_var = tk.BooleanVar(value=smoke or fetch.offline_by_request())
    headline_var = tk.StringVar()
    detail_var = tk.StringVar()
    explain_var = tk.StringVar()
    result_var = tk.StringVar()
    last_var = tk.StringVar()

    # -- which card ----------------------------------------------------------
    top = ttk.Frame(page)
    top.grid(row=0, column=0, sticky="ew")
    top.columnconfigure(1, weight=1)
    ttk.Label(top, text="Card").grid(row=0, column=0, sticky="w")
    card_box = ttk.Combobox(top, textvariable=card_var)
    card_box.grid(row=0, column=1, sticky="ew", padx=6)
    card_buttons = ttk.Frame(top)
    card_buttons.grid(row=0, column=2, sticky="e")

    # -- what is on it, and the one button -------------------------------------
    # A column of a readable width in the middle of the tab, whatever the
    # window's.
    width = 640
    middle = ttk.Frame(page)
    middle.grid(row=1, column=0, sticky="nsew", pady=(28, 0))
    middle.columnconfigure(0, weight=1)
    middle.columnconfigure(2, weight=1)
    middle.rowconfigure(0, weight=1)
    body = ttk.Frame(middle)
    body.grid(row=0, column=1, sticky="nsew")
    body.columnconfigure(0, weight=1)
    ttk.Frame(body, width=width, height=1).grid(row=99, column=0)

    big = tkfont.nametofont("TkDefaultFont").copy()
    big.configure(size=int(abs(big.cget("size")) * 2.2) or 24, weight="bold")
    strong = tkfont.nametofont("TkDefaultFont").copy()
    strong.configure(weight="bold")
    state["fonts"] = (big, strong)          # a font nothing holds is collected, and the label falls back
    ttk.Label(body, textvariable=headline_var, font=big, wraplength=width, justify="left").grid(
        row=0, column=0, sticky="w")
    ttk.Label(body, textvariable=detail_var, foreground=colors["muted"], wraplength=width,
              justify="left").grid(row=1, column=0, sticky="w", pady=(6, 0))
    actions = ttk.Frame(body)
    actions.grid(row=2, column=0, sticky="w", pady=(22, 0))
    ttk.Style(root).configure("Action.TButton", font=strong, padding=(18, 8))
    action = ttk.Button(actions, text=SET_UP, style="Action.TButton", default="active")
    action.pack(side="left")
    stop = ttk.Button(actions, text="Stop", state="disabled")
    ttk.Label(body, textvariable=explain_var, foreground=colors["muted"], wraplength=width - 80,
              justify="left").grid(row=3, column=0, sticky="w", pady=(10, 0))

    # The run's four steps, drawn once one starts.
    steps_frame = ttk.Frame(body)
    steps_frame.columnconfigure(1, weight=1)
    step_rows = []
    for index, name in enumerate(STEPS):
        mark = ttk.Label(steps_frame, text=STEP_MARKS["next"], width=2)
        label = ttk.Label(steps_frame, text=name)
        note = ttk.Label(steps_frame, text="", foreground=colors["muted"])
        mark.grid(row=index * 2, column=0, sticky="w", pady=(8, 0))
        label.grid(row=index * 2, column=1, sticky="w", pady=(8, 0))
        note.grid(row=index * 2, column=2, sticky="e", pady=(8, 0))
        step_rows.append((mark, label, note))
    bar = ttk.Progressbar(steps_frame, mode="determinate", maximum=1000)
    result = ttk.Label(body, textvariable=result_var, wraplength=width, justify="left")
    result.grid(row=5, column=0, sticky="w", pady=(16, 0))

    ttk.Separator(body, orient="horizontal").grid(row=6, column=0, sticky="ew", pady=(18, 8))
    ttk.Label(body, textvariable=last_var, foreground=colors["muted"]).grid(row=7, column=0, sticky="w")

    # -- the options, on a tab of their own -----------------------------------
    # Made here and added to the window after the Games tab, so the tabs
    # read Card, Games, Options, Details.
    options_page = ttk.Frame(notebook, padding=12)
    options_page.columnconfigure(0, weight=1)
    options_page.columnconfigure(2, weight=1)
    options = ttk.Frame(options_page)
    options.grid(row=0, column=1, sticky="n", pady=(28, 0))
    options.columnconfigure(0, weight=1)
    ttk.Frame(options, width=width, height=1).grid(row=99, column=0)
    ttk.Label(options, text="Options", font=big).grid(row=0, column=0, sticky="w")
    ttk.Label(options, text="They apply the next time you press the button on the Card tab.",
              foreground=colors["muted"]).grid(row=1, column=0, sticky="w", pady=(6, 18))
    ttk.Label(options, text="Where the games are", font=strong).grid(row=2, column=0, sticky="w")
    where = ttk.Frame(options)
    where.grid(row=3, column=0, sticky="ew", pady=(4, 0))
    where.columnconfigure(0, weight=1)
    roms_box = ttk.Combobox(where, textvariable=roms_shown, values=[WHOLE_CARD_LABEL])
    roms_box.grid(row=0, column=0, sticky="ew")
    choose_roms = ttk.Button(where, text="Choose a folder…")
    choose_roms.grid(row=0, column=1, padx=(6, 0))
    roms_note = tk.StringVar()
    ttk.Label(options, textvariable=roms_note, foreground=colors["muted"], wraplength=width - 40,
              justify="left").grid(row=4, column=0, sticky="w", pady=(2, 0))
    for row, (variable, text, hint) in enumerate((
            (fix_var, "Repair hacks that show a black screen on a console",
             "Rewrites the checksum inside those files."),
            (rebuild_var, "Rebuild everything from scratch",
             "Slower. For a card whose boxes or names look wrong."),
            (offline_var, "Do not download anything",
             "Uses only what is already on the card.")), start=0):
        ttk.Checkbutton(options, text=text, variable=variable).grid(row=5 + row * 2, column=0, sticky="w",
                                                                    pady=(14, 0))
        ttk.Label(options, text=hint, foreground=colors["muted"]).grid(row=6 + row * 2, column=0, sticky="w",
                                                                       padx=(24, 0))
    ttk.Label(options, text="Boxes and descriptions", font=strong).grid(row=11, column=0, sticky="w",
                                                                         pady=(20, 0))
    pack_row = ttk.Frame(options)
    pack_row.grid(row=12, column=0, sticky="ew", pady=(4, 0))
    pack_row.columnconfigure(0, weight=1)
    ttk.Label(pack_row, text="Use a release-metadata.zip you already have").grid(row=0, column=0, sticky="w")
    choose_pack = ttk.Button(pack_row, text="Choose the file…")
    choose_pack.grid(row=0, column=1, padx=(6, 0))
    forget_pack = ttk.Button(pack_row, text="Use the card's")
    note = ttk.Label(options, textvariable=metadata_note, foreground=colors["muted"], wraplength=width - 40,
                     justify="left", cursor="hand2")
    note.grid(row=13, column=0, sticky="w", pady=(2, 0))

    # -- the report, on a tab of its own ----------------------------------------
    details_page = ttk.Frame(notebook, padding=12)
    details_page.columnconfigure(0, weight=1)
    details_page.rowconfigure(0, weight=1)
    log = tk.Text(details_page, height=8, width=20, wrap="word", state="disabled",
                  font=("Menlo", 11) if sys.platform == "darwin"
                  else ("Consolas", 10) if sys.platform == "win32" else ("monospace", 10))
    log.grid(row=0, column=0, sticky="nsew")
    log_scroll = ttk.Scrollbar(details_page, orient="vertical", command=log.yview)
    log_scroll.grid(row=0, column=1, sticky="ns")
    log.configure(yscrollcommand=log_scroll.set)

    def say(line: str) -> None:
        log.configure(state="normal")
        log.insert("end", line + "\n")
        log.see("end")
        log.configure(state="disabled")
    say("Nothing has run yet. The report of each run shows here, as the command line prints it.")

    def current_card() -> Path | None:
        chosen = card_var.get().strip()
        return Path(chosen) if chosen and Path(chosen).is_dir() else None

    def walk(fresh: bool = False) -> list[str] | None:
        """The card's games, read once per card and again after a run or a
        Refresh: the fields change far more often than the card does."""
        chosen = current_card()
        if chosen is None:
            state["walk"] = None
            return None
        if fresh or state["walk"] is None or state["walk"][0] != str(chosen):
            state["walked"] = time.monotonic()
            try:
                state["walk"] = (str(chosen), library.walk(chosen))
            except library.LibraryError:
                state["walk"] = (str(chosen), None)
        return state["walk"][1]

    def draw_steps() -> None:
        steps = state["steps"]
        if steps.current < 0:
            steps_frame.grid_remove()
            return
        steps_frame.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        running = state["runner"] is not None
        for index, (mark, label, step_note) in enumerate(step_rows):
            where_it_is = steps.state(index)
            mark.configure(text=STEP_MARKS[where_it_is],
                           foreground=colors["good"] if where_it_is == "done" else "")
            label.configure(font=strong if where_it_is == "now" and running else "TkDefaultFont",
                            foreground=colors["muted"] if where_it_is == "next" else "")
            step_note.configure(text=steps.notes[index])
        if running and 0 <= steps.current < len(STEPS):
            bar.grid(row=steps.current * 2 + 1, column=1, columnspan=2, sticky="ew", pady=(4, 0))
            bar["value"] = int(steps.fraction * 1000)
        else:
            bar.grid_remove()

    catalog_page = ttk.Frame(notebook)
    notebook.add(catalog_page, text="Games")
    notebook.add(options_page, text="Options")
    notebook.add(details_page, text="Details")

    def apply_edits(path: str) -> str:
        """A Save or a Remove on the Games tab, put on the card: the same
        run as the button, with the choices the card remembers (its games
        folder, its boxes) rather than what the Options tab says, which
        may be half-set, and with nothing downloaded. Incremental, so
        seconds. One at a time; a second edit while one runs is applied
        after it."""
        chosen = current_card()
        collection = state.get("collection")
        if chosen is None:
            return "no card"
        if collection is None or not collection.ready:
            return "no collection"
        if state["runner"] is not None:
            state["apply_pending"] = path
            return "queued"
        state["apply_path"] = path
        pack = metadata_var.get().strip()
        begin(Runner(sleekmenu_prep.Options(card=chosen, metadata=Path(pack).expanduser() if pack else None,
                                            no_download=True), kind="apply"))
        result_var.set("Putting your edit on the card…")
        return "started"

    def database() -> dict:
        """The shipped database, read the first time something asks."""
        if "database" not in state:
            state["data"] = tempfile.TemporaryDirectory(prefix="sleekmenu-data-")
            state["database"] = coverdb.load(sleekmenu_prep.data_file("coverdb.csv", Path(state["data"].name)))
        return state["database"]

    catalog = GamesTab(catalog_page, current_card, apply=lambda path: apply_edits(path), colors=colors,
                       database=database, offline=offline_var.get)
    state["catalog"] = catalog

    def refresh(*_args, fresh: bool = False) -> None:
        """The tab's words for the card as it is now."""
        chosen = current_card()
        roms = walk(fresh)
        typed = card_var.get().strip()
        status = (card_status(chosen, offline_var.get(), roms) if chosen is not None and roms is not None
                  else card_status(None) if not typed else
                  CardStatus("That is not a card", "Choose the card itself: the folder its games are in."))
        state["status"] = status
        headline_var.set(status.headline)
        detail_var.set(status.detail)
        explain_var.set(status.explain)
        last_var.set(status.last)
        collection = collection_status(chosen, metadata_var.get(), offline_var.get())
        state["collection"] = collection
        metadata_note.set(collection.line)
        note.configure(foreground=colors["good"] if collection.ready else colors["muted"]
                       if collection.downloadable else colors["warn"])
        if metadata_var.get().strip():
            forget_pack.grid(row=0, column=2, padx=(6, 0))
        else:
            forget_pack.grid_remove()
        folders = sorted({path.split("/", 1)[0] for path in roms or [] if "/" in path}, key=str.casefold)
        roms_box.configure(values=[WHOLE_CARD_LABEL] + folders)
        update_buttons()

    def on_card_change(*_args) -> None:
        chosen = card_var.get().strip()
        if state.get("shown_card") != chosen:
            state["shown_card"] = chosen
            catalog.reload()
            remembered = card_catalog.remembered_roms(Path(chosen)) if chosen and Path(chosen).is_dir() else ""
            roms_var.set(remembered)
            state["steps"] = Steps()
            result_var.set("")
            draw_steps()
        refresh()

    def on_roms_change(*_args) -> None:
        """The raw folder ("" for the whole card) and the words in the box,
        kept the same whichever one changed."""
        raw = roms_var.get().strip().strip("/")
        shown = raw or WHOLE_CARD_LABEL
        if roms_shown.get() != shown:
            roms_shown.set(shown)
        roms_note.set(f"Only {raw}/ is read, and the menu opens there." if raw else
                      "Every game on the card, wherever it is.")

    def on_roms_shown(*_args) -> None:
        shown = roms_shown.get().strip()
        raw = "" if shown == WHOLE_CARD_LABEL else shown.strip("/")
        if roms_var.get().strip().strip("/") != raw:
            roms_var.set(raw)

    def update_buttons() -> None:
        """The button acts on a card and is named for what it will do;
        nothing starts while a run is going, and only then can one stop."""
        busy = state["runner"] is not None
        status = state["status"]
        action.configure(text=status.action, state="normal" if status.ready and not busy else "disabled")
        if busy:
            stop.pack(side="left", padx=(8, 0))
        else:
            stop.pack_forget()

    def refresh_cards() -> None:
        found = removable_volumes()
        card_box["values"] = [str(p) for p in found]
        if len(found) == 1 and not card_var.get():
            card_var.set(str(found[0]))
        state["shown_card"] = None          # read the card again, even the same one
        state["walk"] = None
        on_card_change()

    def browse_card() -> None:
        chosen = filedialog.askdirectory(title="The card")
        if chosen:
            card_var.set(chosen)

    def browse_roms() -> None:
        chosen_card = current_card()
        if chosen_card is None:
            return
        chosen = filedialog.askdirectory(title="The folder your games are in", initialdir=str(chosen_card))
        if not chosen:
            return
        try:
            relative = Path(chosen).resolve().relative_to(chosen_card.resolve()).as_posix()
        except ValueError:
            roms_note.set("That folder is not on the card; the games must be on the card to launch.")
            return
        roms_var.set("" if relative == "." else relative)

    def browse_metadata() -> None:
        chosen = filedialog.askopenfilename(
            title=metadata_repo.RELEASE_ZIP_NAME,
            filetypes=[("Collection zip", "*.zip"), ("All files", "*")])
        if chosen:
            metadata_var.set(chosen)

    def open_download(_event=None) -> None:
        if "GitHub" in metadata_note.get():
            webbrowser.open(DOWNLOAD_URL)

    def begin(runner: Runner) -> None:
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")
        state["runner"] = runner
        state["steps"].start()
        result.configure(foreground="")
        result_var.set("")
        update_buttons()
        stop.configure(state="normal")
        draw_steps()
        runner.start()
        root.after(100, poll)

    def poll() -> None:
        runner = state["runner"]
        if runner is None:
            return
        steps = state["steps"]
        for event in runner.drain():
            kind = event[0]
            if kind == "log":
                say(event[1])
                steps.line(event[1])
            elif kind == "error":
                say(event[1])
                state["error"] = event[1]
            elif kind == "progress":
                _kind, label, count, total = event
                steps.progress(label, count, total)
            elif kind == "done":
                end_run(runner, event[1])
                return
        draw_steps()
        root.after(100, poll)

    def end_run(runner: Runner, code: int | None) -> None:
        steps = state["steps"]
        state["runner"] = None
        steps.end(code)
        state["outcome"] = runner.outcome
        error = state.pop("error", "")
        if runner.kind == "apply":
            state["last_apply"] = code
            refresh(fresh=True)
            draw_steps()
            result.configure(foreground=colors["good"] if code == 0 else colors["warn"])
            result_var.set("Your edit is on the card." if code == 0
                           else "Your edit was saved but the card was not updated; the Details tab says why.")
            catalog.applied(state.pop("apply_path", None), code)
            waiting = state.pop("apply_pending", None)
            if waiting is not None:
                apply_edits(waiting)
            return
        state["last_code"] = code
        # The card as the run left it: its catalog, and the games folder the
        # run was given, which the card now remembers.
        state["walk"] = None
        catalog.reload()
        refresh(fresh=True)
        draw_steps()
        line = finished_line(code, runner.outcome, state["status"], bool(walk()))
        plain = code == 0 and line.startswith("Done.")
        result.configure(foreground=colors["good"] if plain else colors["warn"])
        error = error.removeprefix("sleekmenu-prep: ")
        result_var.set(line or (error + " The Details tab has the whole report." if error
                                else "Something went wrong; the Details tab says what."))
        if smoke:
            root.after(200, root.destroy)

    def start() -> None:
        if state["runner"] is not None:
            return
        chosen = current_card()
        if chosen is None or not state["status"].ready:
            if smoke:
                # nothing to act on: a build check says so and ends
                state["last_code"] = 1
                root.after(200, root.destroy)
            return
        begin(Runner(options_from(str(chosen), metadata_var.get(), roms_var.get(), fix_var.get(),
                                  rebuild_var.get(), offline_var.get(),
                                  hires.remembered(custom_art.art_dir(chosen)))))

    def on_focus(event) -> None:
        """Back from copying games onto the card in another window: the
        card is read again, so the tab counts them without a Refresh."""
        if event.widget is root and state["runner"] is None and time.monotonic() - state.get("walked", 0) > 3:
            refresh(fresh=True)

    def ask_stop() -> None:
        runner = state["runner"]
        if runner is None:
            return
        runner.stop()
        stop.configure(state="disabled")
        result.configure(foreground="")
        result_var.set("Stopping…")

    ttk.Button(card_buttons, text="Choose…", command=browse_card).pack(side="left")
    ttk.Button(card_buttons, text="Refresh", command=refresh_cards).pack(side="left", padx=(6, 0))
    choose_roms.configure(command=browse_roms)
    choose_pack.configure(command=browse_metadata)
    forget_pack.configure(command=lambda: metadata_var.set(""))
    note.bind("<Button-1>", open_download)
    card_box.bind("<<ComboboxSelected>>", on_card_change)
    card_var.trace_add("write", on_card_change)
    metadata_var.trace_add("write", refresh)
    offline_var.trace_add("write", refresh)
    roms_var.trace_add("write", on_roms_change)
    roms_shown.trace_add("write", on_roms_shown)
    action.configure(command=start)
    stop.configure(command=ask_stop)
    root.bind("<FocusIn>", on_focus)
    on_roms_change()
    refresh_cards()
    if card:
        card_var.set(card)
    if metadata:
        metadata_var.set(metadata)
    state["last_code"] = None
    # For the tests: the fields and the buttons, without walking widgets.
    state["fields"] = {"card": card_var, "roms": roms_var, "metadata": metadata_var}
    state["options"] = {"fix": fix_var, "rebuild": rebuild_var, "offline": offline_var}
    state["words"] = {"headline": headline_var, "detail": detail_var, "explain": explain_var,
                      "result": result_var, "last": last_var, "pack": metadata_note}
    state["start"] = start
    state["stop"] = ask_stop
    state["buttons"] = {"action": action, "stop": stop}
    state["notebook"] = notebook
    state["pages"] = {"card": page, "games": catalog_page, "options": options_page, "details": details_page}
    root.sleekmenu_state = state  # type: ignore[attr-defined]

    if smoke and card:
        root.after(100, start)
    elif smoke:
        root.after(500, root.destroy)
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare an SD card for SleekMenu 64 from a window.")
    parser.add_argument("--smoke", action="store_true",
                        help="open the window and close it at once; a build check")
    parser.add_argument("--card", default="", help="with --smoke: prepare this card, then close")
    parser.add_argument("--metadata", default="", help="with --smoke: the collection to use")
    args = parser.parse_args(argv)
    if not available():
        print("sleekmenu-prep: no window toolkit (tkinter) in this Python, or no display; "
              "run sleekmenu-prep.pyz from a terminal instead", file=sys.stderr)
        return 2
    root = build(smoke=args.smoke, card=args.card, metadata=args.metadata)
    root.mainloop()
    if args.smoke:
        code = root.sleekmenu_state.get("last_code")
        print("window opened and closed" + (f"; the run returned {code}" if code is not None else ""))
        return int(code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
