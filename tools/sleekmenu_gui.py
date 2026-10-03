#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Prepare a card from a window: the same run as sleekmenu-prep, without a
terminal.

Pick the card (found on its own when it is the only removable disk), read
what is on it, press the one button -- Set up card the first time, Update
card after -- and watch the run go through its four steps, with a Stop if
it is taking too long. What the card lacks is fetched by the run itself;
the choices most people never change are under Options. Nothing here
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
import os
import queue
import sys
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

from tools import (card_catalog, card_layout, custom_art, fetch, hires, library, make_sprite,
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


def added_since(card: Path, roms: list[str]) -> int | None:
    """How many games were added since the card was last updated, or None
    when it has no catalog to compare with."""
    try:
        document = card_catalog.load(card)
    except card_catalog.CatalogJsonError:
        return None
    if document is None:
        return None
    return len(newcomers(document, roms))


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
    """The collection a run would read, and the line that says so under
    Options."""
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
    """The collection a run would use -- the file chosen under Options, else
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


# -- the catalog tab ---------------------------------------------------------

def facts_line(game: dict) -> str:
    """One line of what the browser will show under the title."""
    parts = [str(game.get(key)) for key in ("genre", "publisher") if game.get(key)]
    if game.get("year"):
        parts.append(str(game["year"]))
    if game.get("players"):
        parts.append(f"{game['players']} player" + ("s" if game["players"] != 1 else ""))
    if game.get("regions"):
        parts.append("/".join(game["regions"]))
    return " · ".join(parts) if parts else "no genre, publisher, year or players known"


def summarize(document: dict) -> str:
    """The line above the tree: how many games, when, how many boxes are
    high-resolution ones, how many the owner's own."""
    games = document.get("games", [])
    edited = sum(1 for game in games if provenance.edited(game.get("sources") or {}))
    covers = [str((game.get("sources") or {}).get("cover", provenance.NONE)) for game in games]
    boxed = sum(1 for cover in covers if cover != provenance.NONE)
    high = sum(1 for cover in covers if cover.startswith(provenance.COVER_LIBRETRO))
    built = str(document.get("built", ""))[:16].replace("T", " ")
    line = f"{len(games)} games" + (f", built {built}" if built else "")
    if boxed:
        line += f"; {boxed} with a box, {high} of them high-resolution"
    if edited:
        line += f"; {edited} with your own art or text"
    return line


def short_cover_source(source: str) -> str:
    """The cover's origin as a word or two for a table cell; the detail
    pane has the whole phrase. What matters at a glance is whether the box
    view will be full screen (high-res), the owner's, the collection's
    small scan, another region's, or nothing."""
    if source.startswith(provenance.COVER_LIBRETRO):
        return "high-res" + (", edited" if source != provenance.COVER_LIBRETRO else "")
    if provenance.is_yours(source):
        return "yours"
    if source == provenance.COVER_COLLECTION_REGION:
        return "other region"
    return source


def short_text_source(source: str) -> str:
    """Same for the description."""
    if source == provenance.TEXT_COLLECTION_BY_CODE:
        return "by code"
    return source


def waiting_line(new: int, aside: int) -> str:
    """The tab's second header line: the games added since the last
    Prepare, which the browser lists without a box until the next one, and
    the ROM-shaped files the tool set aside; "" when there is neither."""
    parts = []
    if new:
        parts.append(f"{new} ROM{'s' if new != 1 else ''} on the card {'are' if new != 1 else 'is'} "
                     f"not in it yet: the browser lists {'them' if new != 1 else 'it'} without a box "
                     "until the next Prepare.")
    if aside:
        parts.append(f"{aside} file{'s' if aside != 1 else ''} set aside as not a ROM "
                     f"(no N64 header); the browser never lists {'them' if aside != 1 else 'it'}.")
    return " ".join(parts)


# The Show choice above the tree.
SHOW_ALL = "everything"
SHOW_CHANGED = "only what I changed"
SHOW_WAITING = "only what is not in the catalog"
SHOW_CHOICES = (SHOW_ALL, SHOW_CHANGED, SHOW_WAITING)

# The rows the tree shows beyond the catalog's own games. A record with one
# of these in `state` is not in catalog.json: the tab made it from the card.
STATE_WAITING = "waiting"    # on the card, not in the catalog: the next Prepare adds it
STATE_ASIDE = "aside"        # set aside by the tool: not a ROM
STATE_PENDING = "pending"    # a catalogued game with an edit the next Prepare will apply


def card_rows(card: Path | None, document: dict | None) -> list[dict]:
    """The newcomers and the set-asides as records the tree can hold beside
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


def pending_line(pending) -> str:
    """One line for the pane: what the next Prepare will change."""
    names = {"title": "title", "description": "text", "genre": "genre", "publisher": "publisher",
             "year": "year", "players": "players", "regions": "regions", "cover": "picture"}
    parts = []
    changed = [names[k] for k in names if k in pending.fields]
    if pending.picture is not None:
        changed.append("picture")
    if changed:
        parts.append("Changed here, not in the catalog yet: " + ", ".join(changed)
                     + ". Shown as the next Prepare will catalog it.")
    if pending.removed:
        parts.append("Your " + ", ".join(names[k] for k in pending.removed if k in names)
                     + " file is gone: the next Prepare brings the original back.")
    return " ".join(parts)


def pending_picture(path: Path) -> tuple[int, int, bytes] | None:
    """The owner's picture fitted into the box view's frame, for the pane:
    the sprite does not exist until the next Prepare, so the picture stands
    in, sized the way the sprite will be. None when it will not open."""
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


def box_view_line(game: dict) -> str:
    """What the console's full-screen box view will draw for a game."""
    cover = str((game.get("sources") or {}).get("cover", provenance.NONE))
    if cover.startswith(provenance.COVER_LIBRETRO):
        return "Box view: high-resolution, from libretro"
    if provenance.is_yours(cover):
        return "Box view: your picture, fitted to the screen"
    if cover == provenance.NONE:
        return "Box view: no box"
    return "Box view: the collection's small scan; fetch high-resolution boxes to fill the screen"


def enable_drop(widget, on_files) -> bool:
    """Let files be dropped onto a widget, when tkinterdnd2 is installed
    in this Python and its native library loads; False otherwise, and the
    Browse button beside the widget is the same panel without the drop.
    The frozen builds do not carry it: a native extension that fails to
    load on some systems is not worth the feature depending on it."""
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
        TkinterDnD._require(widget.winfo_toplevel())
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", lambda event: on_files(list(widget.tk.splitlist(event.data))))
    except Exception:  # noqa: BLE001 -- any failure means no drop, which is fine
        return False
    return True


def edit_summary(games: list[dict], game: dict, scope: str) -> str:
    """What saving would reach, in one line."""
    if scope == custom_art.SCOPE_CODE:
        count = custom_art.sharing_code(games, game)
        code = str(game.get("code") or "")
        return (f"For every game with code {code}: {count} on this card." if count > 1
                else f"For every game with code {code}: only this one is on the card.")
    return "For this ROM only."


class CatalogTab:
    """The card as the browser will show it, from sleekmenu/catalog.json:
    the folders as a tree, one row per game with where each field came
    from, and for the selected game the box exactly as the console draws
    it -- decoded from covers.pak, never from the source picture.

    Three regions: the tree, the selected game beside it as the console
    shows it, and under the tree the owner's own art and text for that
    game. The right column is a fixed width, wide enough for the box view's
    sprite, so nothing there is ever clipped; the tree takes the rest."""

    DETAIL_WIDTH = 300

    def __init__(self, parent, card_of, apply=None):
        """`apply(path)`, when given, puts the owner's files on the card's
        catalog -- a run of the tool -- after a Save or a Remove, and answers
        "started", "queued", or why not ("no card", "no collection"); the
        window calls applied() when that run ends."""
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.card_of = card_of
        self.apply = apply
        # The line under the edit panel for one game, kept across redraws
        # until another game is shown: a Save's outcome arrives after the
        # tree has been rebuilt.
        self.note_for: tuple[str, str] | None = None
        self.document = None
        self.covers = None
        self.games: dict[str, dict] = {}
        self.photo = None
        self.show = tk.StringVar(value=SHOW_ALL)
        self.query = tk.StringVar()
        self.shown = tk.StringVar()
        self.summary = tk.StringVar(value="No card picked.")
        self.waiting = tk.StringVar()
        self.rows: list[dict] = []       # newcomers and set-asides, from the card
        self.title = tk.StringVar()
        self.facts = tk.StringVar()
        self.sources = tk.StringVar()
        self.notes = tk.StringVar()
        # the edit panel: the owner's picture and text for the selected game
        self.picture = tk.StringVar()
        self.own_title = tk.StringVar()
        self.own_genre = tk.StringVar()
        self.own_publisher = tk.StringVar()
        self.own_year = tk.StringVar()
        self.own_players = tk.StringVar()
        self.own_regions = {name: tk.BooleanVar(value=False) for name in ("USA", "JAPAN", "EUROPE")}
        self.pending: dict[str, custom_art.Pending] = {}
        self.scope = tk.StringVar(value=custom_art.SCOPE_ROM)
        self.reach = tk.StringVar()
        self.edit_note = tk.StringVar()

        frame = ttk.Frame(parent, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        self.frame = frame

        top = ttk.Frame(frame)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        top.columnconfigure(1, weight=1)
        controls = ttk.Frame(top)
        controls.grid(row=0, column=0, sticky="w")
        ttk.Button(controls, text="Reload", command=self.reload).pack(side="left")
        ttk.Label(controls, text="Show").pack(side="left", padx=(12, 4))
        chooser = ttk.Combobox(controls, textvariable=self.show, state="readonly", width=30,
                               values=list(SHOW_CHOICES))
        chooser.pack(side="left")
        chooser.bind("<<ComboboxSelected>>", lambda _event: self.fill())
        ttk.Label(controls, text="Search").pack(side="left", padx=(12, 4))
        search = ttk.Entry(controls, textvariable=self.query, width=24)
        search.pack(side="left")
        search.bind("<KeyRelease>", lambda _event: self.fill())
        search.bind("<Escape>", lambda _event: (self.query.set(""), self.fill()))
        ttk.Label(controls, textvariable=self.shown, foreground="#555").pack(side="left", padx=(8, 0))
        self.search = search
        lines = ttk.Frame(top)
        lines.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        summary = ttk.Label(lines, textvariable=self.summary, foreground="#555", justify="left")
        summary.pack(anchor="w")
        waiting = ttk.Label(lines, textvariable=self.waiting, foreground="#8a4b00", justify="left")
        waiting.pack(anchor="w")

        # -- the tree ---------------------------------------------------------
        left = ttk.Frame(frame)
        left.grid(row=1, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        columns = ("genre", "year", "publisher", "players", "region", "cover", "text")
        self.tree = ttk.Treeview(left, columns=columns, selectmode="browse")
        self.tree.heading("#0", text="Folder / game")
        self.tree.column("#0", width=232, minwidth=160, stretch=True)
        for name, heading, width in (("genre", "Genre", 76), ("year", "Year", 44),
                                     ("publisher", "Publisher", 96), ("players", "Players", 58),
                                     ("region", "Region", 66), ("cover", "Box", 96),
                                     ("text", "Text", 64)):
            self.tree.heading(name, text=heading)
            self.tree.column(name, width=width, minwidth=width, stretch=False, anchor="w")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        across = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=across.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.tag_configure(STATE_WAITING, foreground="#8a4b00")
        self.tree.tag_configure(STATE_ASIDE, foreground="#8a8a8a")
        self.tree.tag_configure(STATE_PENDING, foreground="#1f5fa8")

        # -- the selected game, as the console shows it -----------------------
        right = ttk.Frame(frame, padding=(12, 0, 0, 0), width=self.DETAIL_WIDTH)
        right.grid(row=1, column=1, rowspan=2, sticky="nsew")
        right.grid_propagate(False)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(5, weight=1)
        # The box is always the box view's size, a placeholder when there
        # is none, so the title and the rest stay put as the selection moves.
        width, height = make_sprite.LARGE_CANVAS_SIZE
        self.placeholder = tk.PhotoImage(
            master=right, format="PPM",
            data=make_sprite.to_ppm(width, height, bytes((35, 42, 52)) * (width * height)))
        self.box = ttk.Label(right, image=self.placeholder, text="", compound="center",
                             foreground="#8291a0", anchor="w")
        self.box.grid(row=0, column=0, sticky="w")
        wrap = self.DETAIL_WIDTH - 16
        ttk.Label(right, textvariable=self.title, justify="left", wraplength=wrap,
                  font=("TkDefaultFont", 12, "bold")).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(right, textvariable=self.facts, justify="left", wraplength=wrap).grid(
            row=2, column=0, sticky="w", pady=(2, 0))
        # What it is, where it came from, what to know -- then the text,
        # which takes whatever height is left.
        ttk.Label(right, textvariable=self.sources, foreground="#555", justify="left",
                  wraplength=wrap).grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Label(right, textvariable=self.notes, foreground="#8a4b00", justify="left",
                  wraplength=wrap).grid(row=4, column=0, sticky="w", pady=(4, 0))
        self.description = tk.Text(right, height=4, width=20, wrap="word", state="disabled",
                                   relief="flat", font="TkDefaultFont",
                                   background=parent.winfo_toplevel().cget("background"))
        self.description.grid(row=5, column=0, sticky="nsew", pady=(8, 0))
        self.detail = right

        # -- the owner's own art and text, under the tree ---------------------
        edit = ttk.LabelFrame(left, text="Your own art and text", padding=8)
        edit.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        edit.columnconfigure(1, weight=1)
        ttk.Label(edit, text="Picture").grid(row=0, column=0, sticky="w")
        picture_entry = ttk.Entry(edit, textvariable=self.picture)
        picture_entry.grid(row=0, column=1, sticky="ew", padx=(6, 4))
        ttk.Button(edit, text="Browse…", command=self.browse_picture).grid(row=0, column=2, sticky="w")
        self.drop_works = enable_drop(picture_entry, self.dropped)
        ttk.Label(edit, text="Title").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(edit, textvariable=self.own_title).grid(row=1, column=1, columnspan=2, sticky="ew",
                                                          padx=(6, 0), pady=(4, 0))
        # The facts, one row: the genres and publishers already on the card
        # are offered, anything else can be typed. An empty field keeps
        # what the catalog has.
        ttk.Label(edit, text="Genre").grid(row=2, column=0, sticky="w", pady=(4, 0))
        facts = ttk.Frame(edit)
        facts.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(4, 0))
        self.genre_box = ttk.Combobox(facts, textvariable=self.own_genre, width=18)
        self.genre_box.pack(side="left")
        ttk.Label(facts, text="Publisher").pack(side="left", padx=(12, 6))
        self.publisher_box = ttk.Combobox(facts, textvariable=self.own_publisher, width=22)
        self.publisher_box.pack(side="left")
        ttk.Label(edit, text="Year").grid(row=3, column=0, sticky="w", pady=(4, 0))
        more = ttk.Frame(edit)
        more.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(4, 0))
        ttk.Entry(more, textvariable=self.own_year, width=6).pack(side="left")
        ttk.Label(more, text="Players").pack(side="left", padx=(12, 6))
        ttk.Combobox(more, textvariable=self.own_players, width=2, state="readonly",
                     values=("", "1", "2", "3", "4")).pack(side="left")
        ttk.Label(more, text="Region").pack(side="left", padx=(12, 6))
        for name, label in (("USA", "USA"), ("JAPAN", "Japan"), ("EUROPE", "Europe")):
            ttk.Checkbutton(more, text=label, variable=self.own_regions[name]).pack(side="left", padx=(0, 6))
        ttk.Label(edit, text="Text").grid(row=4, column=0, sticky="nw", pady=(4, 0))
        self.own_text = tk.Text(edit, height=2, width=20, wrap="word", font="TkDefaultFont")
        self.own_text.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(4, 0))
        scopes = ttk.Frame(edit)
        scopes.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Radiobutton(scopes, text="This ROM only", variable=self.scope,
                        value=custom_art.SCOPE_ROM, command=self.update_reach).pack(side="left")
        self.by_code = ttk.Radiobutton(scopes, text="Every game with this code", variable=self.scope,
                                       value=custom_art.SCOPE_CODE, command=self.update_reach)
        self.by_code.pack(side="left", padx=(12, 0))
        ttk.Label(edit, textvariable=self.reach, foreground="#555").grid(
            row=6, column=0, columnspan=2, sticky="w")
        buttons = ttk.Frame(edit)
        buttons.grid(row=5, column=2, rowspan=2, sticky="e", pady=(6, 0))
        self.remove_button = ttk.Button(buttons, text="Remove my edit", command=self.remove_edit)
        self.remove_button.pack(side="left", padx=(0, 6))
        self.save_button = ttk.Button(buttons, text="Save", command=self.save_edit)
        self.save_button.pack(side="left")
        edit_note = ttk.Label(edit, textvariable=self.edit_note, foreground="#555", justify="left")
        edit_note.grid(row=7, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.edit = edit

        def rewrap_edit(event):
            edit_note.configure(wraplength=max(200, event.width - 24))
        left.bind("<Configure>", rewrap_edit)

        def rewrap_top(event):
            summary.configure(wraplength=max(200, event.width - 8))
            waiting.configure(wraplength=max(200, event.width - 8))
        lines.bind("<Configure>", rewrap_top)

    # -- loading -----------------------------------------------------------

    def reload(self) -> None:
        """Read catalog.json and covers.pak off the card again."""
        card = self.card_of()
        self.document, self.covers, self.games = None, None, {}
        if card is None:
            self.summary.set("No card picked.")
        else:
            broken = None
            try:
                self.document = card_catalog.load(card)
            except card_catalog.CatalogJsonError as error:
                broken = str(error)
            if self.document is None:
                self.summary.set(broken or card_catalog.why_missing(card))
            else:
                self.covers = card_catalog.Covers.open(card)
                self.games = {str(game["path"]): game for game in self.document["games"]}
                self.summary.set(summarize(self.document))
        self.rows = card_rows(card, self.document)
        self.games.update({str(row["path"]): row for row in self.rows})
        self.refresh_pending()
        self.waiting.set(waiting_line(sum(1 for row in self.rows if row["state"] == STATE_WAITING),
                                      sum(1 for row in self.rows if row["state"] == STATE_ASIDE)))
        self.fill()
        self.show_game(None)

    def refresh_pending(self) -> None:
        """What the owner's files on the card would change at the next
        Prepare, read again: after a load, a Save and a Remove."""
        card = self.card_of()
        self.pending = (custom_art.pending_edits(card, card, self.document)
                        if card is not None and self.document is not None else {})
        games = (self.document or {}).get("games", [])
        self.genre_box.configure(values=sorted({str(g.get("genre") or "") for g in games} - {""}, key=str.casefold))
        self.publisher_box.configure(values=sorted({str(g.get("publisher") or "") for g in games} - {""},
                                                   key=str.casefold))
        if self.document is not None:
            line = summarize(self.document)
            if self.pending:
                line += f"; {len(self.pending)} edit{'s' if len(self.pending) != 1 else ''} waiting for a Prepare"
            self.summary.set(line)

    def effective(self, game: dict) -> dict:
        """The game as the next Prepare will catalog it: the record with
        the owner's pending fields laid over it."""
        pending = self.pending.get(str(game.get("path", "")))
        if pending is None or not pending.fields:
            return game
        return dict(game, **pending.fields)

    def fill(self) -> None:
        """The tree from the loaded catalog and the card's own rows, folders
        first, narrowed by the Show choice and the search."""
        self.tree.delete(*self.tree.get_children())
        if self.document is None:
            self.shown.set("")
            return
        mode = self.show.get()
        if mode == SHOW_CHANGED:
            records = [game for game in self.document["games"]
                       if provenance.edited(game.get("sources") or {})
                       or str(game.get("path", "")) in self.pending]
        elif mode == SHOW_WAITING:
            records = list(self.rows)
        else:
            records = list(self.document["games"]) + list(self.rows)
        total = len(records)
        query = self.query.get().strip()
        if query:
            records = [record for record in records if matches(record, query)]
        self.shown.set(f"{len(records)} of {total}" if query or mode != SHOW_ALL else "")
        self._add(card_catalog.tree(records), "")

    def _add(self, node: dict, parent: str) -> None:
        for name, child in node["folders"].items():
            iid = self.tree.insert(parent, "end", text=f"{name}/  ({card_catalog.count(child)})", open=True)
            self._add(child, iid)
        for record in node["games"]:
            sources = record.get("sources") or {}
            state = str(record.get("state") or "")
            pending = self.pending.get(str(record.get("path", "")))
            game = self.effective(record)
            if state == STATE_WAITING:
                box = text = "not yet"
            elif state == STATE_ASIDE:
                box = text = "not a ROM"
            else:
                box = short_cover_source(str(sources.get("cover", "")))
                text = short_text_source(str(sources.get("description", "")))
                if pending is not None and pending.picture is not None:
                    box = "yours, pending"
                if pending is not None and "description" in pending.fields:
                    text = "yours, pending"
            tag = state or (STATE_PENDING if pending is not None else "")
            self.tree.insert(parent, "end", iid=str(game["path"]), text=str(game.get("title", "")),
                             tags=(tag,) if tag else (),
                             values=(game.get("genre", ""), game.get("year") or "",
                                     game.get("publisher", ""), game.get("players") or "",
                                     "/".join(game.get("regions") or []), box, text))

    # -- the selected game ---------------------------------------------------

    def selected(self) -> dict | None:
        chosen = self.tree.selection()
        return self.games.get(chosen[0]) if chosen else None

    def on_select(self, _event=None) -> None:
        self.show_game(self.selected())

    def show_game(self, game: dict | None) -> None:
        self.description.configure(state="normal")
        self.description.delete("1.0", "end")
        state = str((game or {}).get("state") or "")
        self.fill_edit(None if state else game)
        if game is None:
            self.title.set("")
            self.facts.set("")
            self.sources.set("")
            self.notes.set("")
            self.box.configure(image=self.placeholder, text="")
            self.photo = None
            self.edit.configure(text="Your own art and text")
        elif state:
            # A row the card gave, not the catalog: what it is and what
            # happens next, and nothing to edit until it is catalogued.
            self.title.set(str(game.get("title", "")))
            self.facts.set(str(game.get("path", "")))
            self.sources.set("")
            self.photo = None
            if state == STATE_WAITING:
                self.notes.set("Not in the catalog yet: the browser lists it in its folder, without "
                               "a box, and plays it. Press Update card to add its box and facts.")
                self.box.configure(image=self.placeholder, text="NOT YET")
            else:
                self.notes.set(f"Set aside by the tool ({game.get('why', '')}): the browser never "
                               "lists it, and Prepare will not add it.")
                self.box.configure(image=self.placeholder, text="NO ART")
            self.edit.configure(text="Your own art and text")
        else:
            sources = game.get("sources") or {}
            pending = self.pending.get(str(game.get("path", "")))
            shown = self.effective(game)
            self.title.set(str(shown.get("title", "")))
            self.facts.set(facts_line(shown))
            self.sources.set(f"Cover: {sources.get('cover', '')}\nText: {sources.get('description', '')}"
                             f"\nTitle: {sources.get('title', '')}\n{box_view_line(game)}")
            self.edit.configure(text=f"Your own art and text for {game.get('title', '')}")
            self.description.insert("1.0", str(shown.get("description") or ""))
            notes = list(provenance.notes(game))
            if pending is not None:
                # What the edit answers is no longer worth a note.
                if pending.picture is not None:
                    notes = [note for note in notes if not note.startswith("No box")]
                if "description" in pending.fields:
                    notes = [note for note in notes if not note.startswith("No description")]
                notes.insert(0, pending_line(pending))
            self.notes.set("\n".join(notes))
            # The box view's sprite when the card has the large pack --
            # what the console draws full screen -- else the thumbnail,
            # doubled so it is legible. A picture of the owner's the catalog
            # does not carry yet is shown instead, fitted to the same size.
            large = self.covers.pixels(game, large=True) if self.covers is not None else None
            pixels = large or (self.covers.pixels(game) if self.covers is not None else None)
            preview = pending_picture(pending.picture) if pending is not None and pending.picture else None
            if preview is not None:
                width, height, rgb = preview
                self.photo = self.tk.PhotoImage(master=self.box, format="PPM",
                                                data=make_sprite.to_ppm(width, height, rgb))
                self.box.configure(image=self.photo, text="PENDING", compound="top")
            elif pixels is None:
                self.photo = None
                self.box.configure(image=self.placeholder, text="NO ART", compound="center")
            else:
                width, height, rgb = pixels
                self.photo = self.tk.PhotoImage(master=self.box, format="PPM",
                                                data=make_sprite.to_ppm(width, height, rgb))
                if large is None:
                    self.photo = self.photo.zoom(BOX_ZOOM, BOX_ZOOM)
                self.box.configure(image=self.photo, text="", compound="center")
        self.description.configure(state="disabled")


    # -- the edit panel ------------------------------------------------------

    def fill_edit(self, game: dict | None) -> None:
        """The panel for a game: the fields hold what the owner's file on
        the card says -- prepared or not -- and nothing otherwise; an
        empty field keeps what the card has."""
        self.picture.set("")
        self.own_text.delete("1.0", "end")
        # A reload shows no game for a moment; only another game's being
        # shown ends the note.
        shown = str((game or {}).get("path", ""))
        if self.note_for is not None and game is not None and self.note_for[0] != shown:
            self.note_for = None
        self.edit_note.set(self.note_for[1] if self.note_for is not None and game is not None else "")
        for variable in (self.own_title, self.own_genre, self.own_publisher, self.own_year, self.own_players):
            variable.set("")
        for variable in self.own_regions.values():
            variable.set(False)
        sources = (game or {}).get("sources") or {}
        card = self.card_of()
        own = (custom_art.find_text(custom_art.Index(), card, str(game.get("path", "")),
                                    custom_art.art_dir(card), str(game.get("code") or ""))
               if game is not None and card is not None else None)
        if own is not None:
            self.own_title.set(own.title)
            self.own_text.insert("1.0", own.description)
            self.own_genre.set(str(own.facts.get("genre", "")))
            self.own_publisher.set(str(own.facts.get("publisher", "")))
            self.own_year.set(str(own.facts.get("year") or ""))
            self.own_players.set(str(own.facts.get("players") or ""))
            for name in own.facts.get("regions", []):
                if name in self.own_regions:
                    self.own_regions[name].set(True)
        enabled = "normal" if game is not None else "disabled"
        for widget in (self.save_button, self.remove_button, self.by_code):
            widget.configure(state=enabled)
        if game is not None:
            code = str(game.get("code") or "")
            self.by_code.configure(text=f"Every game with code {code}" if code.strip("\0 ")
                                   else "Every game with this code", state="normal" if code.strip("\0 ")
                                   else "disabled")
            if sources.get("cover", "").startswith("yours (code"):
                self.scope.set(custom_art.SCOPE_CODE)
            else:
                self.scope.set(custom_art.SCOPE_ROM)
            removable, beside = custom_art.edits_of(self.card_of(), self.card_of(), game) \
                if self.card_of() is not None else ([], [])
            self.remove_button.configure(state="normal" if removable else "disabled")
            if beside and not removable:
                self.edit_note.set("This game's picture or text sits beside the ROM; to undo it, "
                                   "remove that file yourself.")
        self.update_reach()

    def update_reach(self) -> None:
        game = self.selected()
        if game is None or self.document is None:
            self.reach.set("")
            return
        self.reach.set(edit_summary(self.document["games"], game, self.scope.get()))

    def browse_picture(self) -> None:
        from tkinter import filedialog
        chosen = filedialog.askopenfilename(
            title="A box picture", filetypes=[("PNG or JPEG", "*.png *.jpg *.jpeg"), ("All files", "*")])
        if chosen:
            self.picture.set(chosen)

    def dropped(self, files: list[str]) -> None:
        if files:
            self.picture.set(files[0])

    def save_edit(self) -> None:
        game, card = self.selected(), self.card_of()
        if game is None or card is None:
            return
        picture = Path(self.picture.get().strip()) if self.picture.get().strip() else None
        facts, problems = self.own_facts()
        if problems:
            self.edit_note.set("Not saved: " + "; ".join(problems))
            return
        try:
            touched = custom_art.save(card, game, picture, self.own_title.get(),
                                      self.own_text.get("1.0", "end"), self.scope.get(), facts)
        except (custom_art.EditError, OSError) as error:
            self.edit_note.set(f"Not saved: {error}")
            return
        names = ", ".join(path.name for path in touched) or "nothing to write"
        self.note_for = (str(game["path"]),
                         f"Saved {names} in {card_layout.CARD_FOLDER}/{card_layout.ART_FOLDER}/. "
                         + self.put_on_card(str(game["path"])))
        self.redraw(str(game["path"]))
        self.remove_button.configure(state="normal" if touched else "disabled")

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
        if keep is not None and self.tree.exists(keep):
            self.tree.selection_set(keep)
            self.tree.see(keep)
            self.show_game(self.games.get(keep))

    def own_facts(self) -> tuple[dict, list[str]]:
        """The fact fields as a dict for custom_art.save, and what is wrong
        with them: a year or a player count that is not one."""
        facts: dict = {}
        problems: list[str] = []
        if self.own_genre.get().strip():
            facts["genre"] = self.own_genre.get().strip()
        if self.own_publisher.get().strip():
            facts["publisher"] = self.own_publisher.get().strip()
        year = self.own_year.get().strip()
        if year:
            if year.isdigit() and 1970 <= int(year) <= 2100:
                facts["year"] = int(year)
            else:
                problems.append("the year must be from 1970 to 2100")
        players = self.own_players.get().strip()
        if players:
            facts["players"] = int(players)
        regions = [name for name, variable in self.own_regions.items() if variable.get()]
        if regions:
            facts["regions"] = regions
        return facts, problems

    def redraw(self, path: str) -> None:
        """After a Save or a Remove: the overlay again, the tree again with
        the same row selected, the pane again."""
        self.refresh_pending()
        self.fill()
        if self.tree.exists(path):
            self.tree.selection_set(path)
            self.tree.see(path)
        self.show_game(self.games.get(path))

    def remove_edit(self) -> None:
        game, card = self.selected(), self.card_of()
        if game is None or card is None:
            return
        try:
            removed = custom_art.remove(card, card, game)
        except OSError as error:
            self.edit_note.set(f"Not removed: {error}")
            return
        self.note_for = (str(game["path"]),
                         ("Removed " + ", ".join(path.name for path in removed) + ". " if removed
                          else "Nothing of yours to remove. ")
                         + (self.put_on_card(str(game["path"])) if removed else ""))
        self.redraw(str(game["path"]))
        self.remove_button.configure(state="disabled")


# -- the window -------------------------------------------------------------

#: The games-folder choice that means every game on the card.
WHOLE_CARD_LABEL = "The whole card"
STEP_MARKS = {"done": "✓", "now": "●", "next": "○"}


def palette(root, tk, ttk) -> dict[str, str]:
    """The three colours the window adds to the system's: a quieter text, a
    good outcome and a warning, chosen against the background this window
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
    return {"muted": muted, "good": "#7bd3a0" if dark else "#2e7d32", "warn": "#f0b46a" if dark else "#8a4b00"}


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

    # -- the options, closed until asked for ----------------------------------
    # Two ordinary buttons side by side, each opening what is under them.
    ttk.Style(root).configure("Disclose.TButton", padding=(14, 6))
    toggles = ttk.Frame(body)
    toggles.grid(row=8, column=0, sticky="w", pady=(12, 0))
    options_toggle = ttk.Button(toggles, text="▸ Options", style="Disclose.TButton")
    options_toggle.pack(side="left")
    details_toggle = ttk.Button(toggles, text="▸ Details", style="Disclose.TButton")
    details_toggle.pack(side="left", padx=(8, 0))
    options = ttk.Frame(body, padding=(18, 4, 0, 0))
    options.columnconfigure(0, weight=1)
    ttk.Label(options, text="Where the games are").grid(row=0, column=0, sticky="w")
    where = ttk.Frame(options)
    where.grid(row=1, column=0, sticky="ew", pady=(2, 0))
    where.columnconfigure(0, weight=1)
    roms_box = ttk.Combobox(where, textvariable=roms_shown, values=[WHOLE_CARD_LABEL])
    roms_box.grid(row=0, column=0, sticky="ew")
    choose_roms = ttk.Button(where, text="Choose a folder…")
    choose_roms.grid(row=0, column=1, padx=(6, 0))
    roms_note = tk.StringVar()
    ttk.Label(options, textvariable=roms_note, foreground=colors["muted"], wraplength=width - 40,
              justify="left").grid(row=2, column=0, sticky="w")
    for row, (variable, text, hint) in enumerate((
            (fix_var, "Repair hacks that show a black screen on a console",
             "Rewrites the checksum inside those files."),
            (rebuild_var, "Rebuild everything from scratch",
             "Slower. For a card whose boxes or names look wrong."),
            (offline_var, "Do not download anything",
             "Uses only what is already on the card.")), start=0):
        ttk.Checkbutton(options, text=text, variable=variable).grid(row=3 + row * 2, column=0, sticky="w",
                                                                    pady=(8, 0))
        ttk.Label(options, text=hint, foreground=colors["muted"]).grid(row=4 + row * 2, column=0, sticky="w",
                                                                       padx=(24, 0))
    pack_row = ttk.Frame(options)
    pack_row.grid(row=9, column=0, sticky="ew", pady=(10, 0))
    pack_row.columnconfigure(0, weight=1)
    ttk.Label(pack_row, text="Boxes and descriptions from a release-metadata.zip you already have").grid(
        row=0, column=0, sticky="w")
    choose_pack = ttk.Button(pack_row, text="Choose the file…")
    choose_pack.grid(row=0, column=1, padx=(6, 0))
    forget_pack = ttk.Button(pack_row, text="Use the card's")
    note = ttk.Label(options, textvariable=metadata_note, foreground=colors["muted"], wraplength=width - 40,
                     justify="left", cursor="hand2")
    note.grid(row=10, column=0, sticky="w")

    # -- the report, closed until asked for -------------------------------------
    log = tk.Text(body, height=8, width=20, wrap="word", state="disabled",
                  font=("Menlo", 11) if sys.platform == "darwin"
                  else ("Consolas", 10) if sys.platform == "win32" else ("monospace", 10))

    def disclose(toggle, widget, label: str, row: int, grow: bool = False):
        """A line that opens and closes what is under it."""
        def show(shown: bool) -> None:
            if shown:
                widget.grid(row=row, column=0, sticky="nsew" if grow else "ew", pady=(10, 0))
            else:
                widget.grid_remove()
            body.rowconfigure(row, weight=1 if grow and shown else 0)
            toggle.configure(text=("▾ " if shown else "▸ ") + label)
        return show
    open_options = disclose(options_toggle, options, "Options", 9)
    open_details = disclose(details_toggle, log, "Details", 11, grow=True)

    # One at a time, so the tab never grows past the window: the options
    # take the place of the last run's steps, and the report closes them.
    def show_options(shown: bool | None = None) -> None:
        shown = not options.winfo_manager() if shown is None else shown
        if shown:
            open_details(False)
        open_options(shown)
        draw_steps()

    def show_details(shown: bool | None = None) -> None:
        shown = not log.winfo_manager() if shown is None else shown
        if shown:
            open_options(False)
        open_details(shown)
        draw_steps()
    options_toggle.configure(command=show_options)
    details_toggle.configure(command=show_details)

    def say(line: str) -> None:
        log.configure(state="normal")
        log.insert("end", line + "\n")
        log.see("end")
        log.configure(state="disabled")

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
        if steps.current < 0 or (options.winfo_manager() and state["runner"] is None):
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

    def apply_edits(path: str) -> str:
        """A Save or a Remove on the Games tab, put on the card: the same
        run as the button, with the choices the card remembers (its games
        folder, its boxes) rather than the options on the Card tab, which
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

    catalog = CatalogTab(catalog_page, current_card, apply=lambda path: apply_edits(path))
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
        open_options(False)
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
                           else "Your edit was saved but the card was not updated; see the details.")
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
        result_var.set(line or error.removeprefix("sleekmenu-prep: ") or "Something went wrong; see the details.")
        if code not in (0, 3):
            show_details(True)
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
    state["show"] = {"options": show_options, "details": show_details}
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
