#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Prepare a card from a window: the same run as sleekmenu-prep, without a
terminal.

Pick the card (found on its own when it is the only removable disk), see
whether the box-art collection is on it -- it is fetched onto the card when
not -- press Prepare, watch the progress, Stop if it is taking too long.
Nothing here decides anything about the card: the window collects five
answers and hands them to tools/sleekmenu_prep.run(), which is what the
command line runs. The downloadable builds are this file frozen with its
Python; from a checkout it is `python3 tools/sleekmenu_gui.py`, or
`python3 sleekmenu-prep.pyz --gui`.

Tkinter is imported when the window is made, not when this module is,
because a Python without it still has to run the command line and the
tests. Everything that can be checked without a screen -- which disks look
like cards, how the run reports into the window -- is kept apart from the
widgets for that reason.
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
from pathlib import Path, PurePosixPath

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import (card_catalog, card_layout, custom_art, hires, library, make_sprite, metadata_repo,
                   provenance, sleekmenu_prep)

TITLE = "SleekMenu 64 — prepare a card"
DOWNLOAD_URL = metadata_repo.RELEASES_URL
#: The box is 96x72 on the console; twice that on a desktop screen is
#: legible without pretending to be the source picture.
BOX_ZOOM = 2
ROMS_HINT = "Empty: every game on the card. Or one folder, and only it is scanned; the menu opens there."


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
    """ROMs in the catalogued folder that the last Prepare did not
    catalogue and did not set aside: games added since, which the browser
    lists without a box until the next Prepare. `roms` is the card's walk;
    only the folder the catalog covers counts."""
    catalogued = {str(game.get("path", "")).casefold() for game in document.get("games", [])}
    aside = {str(entry.get("path", "")).casefold() for entry in document.get("set_aside", [])}
    folder = str(document.get("roms", "") or "").strip("/")
    prefix = folder.casefold() + "/" if folder else ""
    return [path for path in roms if path.casefold().startswith(prefix)
            and path.casefold() not in catalogued and path.casefold() not in aside]


def added_since(card: Path, roms: list[str]) -> int | None:
    """How many games were added since the last Prepare, or None when the
    card has no catalog to compare with. The count is what tells a person
    the card needs a Prepare at all."""
    try:
        document = card_catalog.load(card)
    except card_catalog.CatalogJsonError:
        return None
    if document is None:
        return None
    return len(newcomers(document, roms))


def describe_card(card: Path) -> str:
    """One line about what is on a candidate card, for the picker."""
    try:
        roms = library.walk(card)
    except library.LibraryError:
        return "not a folder"
    parts = [f"{len(roms)} ROMs"] if roms else ["no ROMs"]
    new = added_since(card, roms)
    if new:
        parts.append(f"{new} added since the last Prepare")
    if (card / card_layout.BROWSER_ROM).is_file():
        parts.append(card_layout.BROWSER_ROM + " present")
    collection = metadata_repo.find_on_card(card)
    parts.append(f"collection: {collection.name}" if collection is not None else "collection: not on the card")
    return ", ".join(parts)


# -- the run, reported into the window --------------------------------------

class Runner:
    """sleekmenu_prep.run() on a thread, with every line and every progress
    step posted to a queue the window drains between frames. The window
    never blocks on the card, and the run never touches a widget. `stop()`
    raises a flag the run looks at before every step; it ends with code 3
    a moment later, having written nothing more."""

    def __init__(self, options: sleekmenu_prep.Options):
        self.options = options
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

        try:
            runner.code = sleekmenu_prep.run(
                self.options,
                log=lambda line: events.put(("log", line)),
                fail=lambda line: events.put(("error", line)),
                progress_factory=Bar,
                cancel=self.stopping.is_set)
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


def options_from(card: str, metadata: str, check_checksums: bool, fix_checksums: bool,
                 hires: bool = False, roms: str = "") -> sleekmenu_prep.Options:
    """The window's fields as the run takes them. An empty metadata field
    means whatever is on the card, as on the command line. An empty games
    folder is the whole card, said so, and an unticked box is no fetch,
    said so: both fields show what the card remembers, so clearing one is
    a choice, not an omission. The box view's pack is always built from
    the window; --no-large-covers is the terminal's."""
    return sleekmenu_prep.Options(
        card=Path(card) if card.strip() else None,
        metadata=Path(metadata) if metadata.strip() else None,
        roms=Path(roms.strip().strip("/")) if roms.strip().strip("/") else sleekmenu_prep.WHOLE_CARD,
        no_checksums=not check_checksums,
        fix_checksums=fix_checksums,
        hires=bool(hires),
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

    def __init__(self, parent, card_of):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.card_of = card_of
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
                               "a box, and plays it. Press Prepare to add its box and facts.")
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
        self.edit_note.set("")
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
        self.redraw(str(game["path"]))
        self.edit_note.set(f"Saved {names} in {card_layout.CARD_FOLDER}/{card_layout.ART_FOLDER}/. "
                           "Shown here now; press Prepare to put it on the card's catalog and covers.")
        self.remove_button.configure(state="normal" if touched else "disabled")

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
        self.redraw(str(game["path"]))
        self.remove_button.configure(state="disabled")
        self.edit_note.set(("Removed " + ", ".join(path.name for path in removed) + ". " if removed
                            else "Nothing of yours to remove. ")
                           + "Press Prepare to bring the original back.")


# -- the window -------------------------------------------------------------

def build(smoke: bool = False, card: str = "", metadata: str = ""):
    """The window, as a Tk root. `smoke` closes it after a moment, which is
    how a build is checked to start at all; with `card` as well it presses
    Prepare and closes when the run is done, which is how the whole window
    is checked to work."""
    import tkinter as tk
    from tkinter import filedialog, ttk
    import webbrowser

    root = tk.Tk()
    root.title(TITLE)
    root.minsize(960, 680)
    root.geometry("1080x720")
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    frame = ttk.Frame(notebook, padding=12)
    notebook.add(frame, text="Prepare")
    frame.columnconfigure(1, weight=1)

    state = {"runner": None}
    card_var = tk.StringVar()
    card_note = tk.StringVar(value="Pick the card, or plug it in and press Refresh.")
    roms_var = tk.StringVar()
    roms_note = tk.StringVar(value=ROMS_HINT)
    metadata_var = tk.StringVar()
    metadata_note = tk.StringVar()
    check_var = tk.BooleanVar(value=True)
    fix_var = tk.BooleanVar(value=False)
    hires_var = tk.BooleanVar(value=False)
    status_var = tk.StringVar(value="")

    ttk.Label(frame, text="Card").grid(row=0, column=0, sticky="w")
    card_box = ttk.Combobox(frame, textvariable=card_var)
    card_box.grid(row=0, column=1, sticky="ew", padx=6)
    buttons = ttk.Frame(frame)
    buttons.grid(row=0, column=2, sticky="e")
    ttk.Label(frame, textvariable=card_note, foreground="#555").grid(row=1, column=1, sticky="w", padx=6)

    ttk.Label(frame, text="Games folder").grid(row=2, column=0, sticky="w", pady=(10, 0))
    ttk.Entry(frame, textvariable=roms_var).grid(row=2, column=1, sticky="ew", padx=6, pady=(10, 0))
    ttk.Label(frame, textvariable=roms_note, foreground="#555").grid(row=3, column=1, sticky="w", padx=6)

    ttk.Label(frame, text="Collection").grid(row=4, column=0, sticky="w", pady=(10, 0))
    ttk.Entry(frame, textvariable=metadata_var).grid(row=4, column=1, sticky="ew", padx=6, pady=(10, 0))
    note = ttk.Label(frame, textvariable=metadata_note, foreground="#555", cursor="hand2")
    note.grid(row=5, column=1, sticky="w", padx=6)

    options = ttk.Frame(frame)
    options.grid(row=6, column=1, sticky="w", padx=6, pady=(10, 0))
    ttk.Checkbutton(options, text="Check hacks and homebrew for a stale header checksum",
                    variable=check_var).pack(anchor="w")
    ttk.Checkbutton(options, text="Rewrite a stale checksum in the file itself",
                    variable=fix_var).pack(anchor="w")
    ttk.Checkbutton(options, text="High-resolution boxes for the box view: fetch the missing ones "
                                  "from libretro (about 250 KB a game)",
                    variable=hires_var).pack(anchor="w")

    bar = ttk.Progressbar(frame, mode="determinate")
    bar.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(12, 2))
    ttk.Label(frame, textvariable=status_var, foreground="#555").grid(row=8, column=0, columnspan=3, sticky="w")
    log = tk.Text(frame, height=12, wrap="word", state="disabled", font=("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10) if sys.platform == "win32" else ("monospace", 10))
    log.grid(row=9, column=0, columnspan=3, sticky="nsew", pady=(4, 8))
    frame.rowconfigure(9, weight=1)
    actions = ttk.Frame(frame)
    actions.grid(row=10, column=2, sticky="e")
    stop = ttk.Button(actions, text="Stop", state="disabled")
    stop.pack(side="left", padx=(0, 6))
    prepare = ttk.Button(actions, text="Prepare")
    prepare.pack(side="left")

    def say(line: str) -> None:
        log.configure(state="normal")
        log.insert("end", line + "\n")
        log.see("end")
        log.configure(state="disabled")

    def refresh_cards() -> None:
        found = removable_volumes()
        card_box["values"] = [str(p) for p in found]
        if len(found) == 1 and not card_var.get():
            card_var.set(str(found[0]))
        on_card_change()

    def current_card() -> Path | None:
        card = card_var.get().strip()
        return Path(card) if card and Path(card).is_dir() else None

    catalog_page = ttk.Frame(notebook)
    notebook.add(catalog_page, text="Catalog")
    catalog = CatalogTab(catalog_page, current_card)
    state["catalog"] = catalog

    def on_card_change(*_args) -> None:
        card = card_var.get().strip()
        if state.get("shown_card") != card:
            state["shown_card"] = card
            catalog.reload()
            remembered = card_catalog.remembered_roms(Path(card)) if card and Path(card).is_dir() else ""
            roms_var.set(remembered)
            roms_note.set(f"Chosen last time; only {remembered}/ is scanned. Empty the field for the whole card."
                          if remembered else ROMS_HINT)
            # A card that has fetched boxes keeps them complete: the box is
            # what the card remembers, and unticking it is a choice.
            hires_var.set(bool(card) and Path(card).is_dir()
                          and hires.remembered(custom_art.art_dir(Path(card))))
        if not card or not Path(card).is_dir():
            card_note.set("Pick the card, or plug it in and press Refresh.")
            metadata_note.set("")
            return
        card_note.set(describe_card(Path(card)))
        collection = metadata_repo.find_on_card(Path(card))
        if metadata_var.get().strip():
            metadata_note.set("Using the file above.")
        elif collection is not None:
            metadata_note.set(f"{collection.name} found on the card: the box scans and descriptions.")
        elif (Path(card) / card_layout.CARD_FOLDER / card_layout.COVER_PACK_NAME).is_file():
            metadata_note.set("The card has its covers, but the collection they came from is no longer on "
                              f"it: Prepare fetches {metadata_repo.RELEASE_ZIP_NAME} (about 52 MB) from "
                              "GitHub (click to see), or choose a copy with Browse.")
        else:
            metadata_note.set(f"Not on the card: Prepare fetches {metadata_repo.RELEASE_ZIP_NAME} "
                              "(about 52 MB) from GitHub (click to see), or choose a copy with Browse.")

    def browse_card() -> None:
        chosen = filedialog.askdirectory(title="The card")
        if chosen:
            card_var.set(chosen)
            on_card_change()

    def browse_roms() -> None:
        card = current_card()
        if card is None:
            status_var.set("Pick the card first.")
            return
        chosen = filedialog.askdirectory(title="The folder your games are in", initialdir=str(card))
        if not chosen:
            return
        try:
            relative = Path(chosen).resolve().relative_to(card.resolve()).as_posix()
        except ValueError:
            roms_note.set("That folder is not on the card; the games must be on the card to launch.")
            return
        roms_var.set("" if relative == "." else relative)
        roms_note.set(ROMS_HINT)

    def browse_metadata() -> None:
        chosen = filedialog.askopenfilename(
            title=metadata_repo.RELEASE_ZIP_NAME,
            filetypes=[("Collection zip", "*.zip"), ("All files", "*")])
        if chosen:
            metadata_var.set(chosen)
            on_card_change()

    def open_download(_event=None) -> None:
        if "GitHub" in metadata_note.get():
            webbrowser.open(DOWNLOAD_URL)

    def poll() -> None:
        runner = state["runner"]
        if runner is None:
            return
        for event in runner.drain():
            kind = event[0]
            if kind == "log":
                say(event[1])
            elif kind == "error":
                say(event[1])
                status_var.set(event[1])
            elif kind == "progress":
                _kind, label, count, total = event
                bar["maximum"] = max(total, 1)
                bar["value"] = count
                status_var.set(f"{label}: {count}/{total}")
            elif kind == "detail":
                status_var.set(f"{status_var.get().split('  ')[0]}  {event[1]}")
            elif kind == "done":
                state["runner"] = None
                prepare.configure(state="normal")
                stop.configure(state="disabled")
                bar["value"] = bar["maximum"]
                if event[1] == 0:
                    status_var.set("Done. Eject the card and start SleekMenu64.z64 from the EverDrive menu.")
                    say("")
                    say("Eject the card and start SleekMenu64.z64 from the EverDrive menu.")
                elif event[1] == 3:
                    status_var.set("Stopped. Press Prepare to start again.")
                else:
                    status_var.set("Stopped; see the last line above.")
                state["last_code"] = event[1]
                on_card_change()
                catalog.reload()
                if smoke:
                    root.after(200, root.destroy)
                return
        root.after(100, poll)

    def start() -> None:
        if state["runner"] is not None:
            return
        card = card_var.get().strip()
        if not card:
            status_var.set("Pick the card first.")
            return
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")
        bar["value"] = 0
        prepare.configure(state="disabled")
        stop.configure(state="normal")
        runner = Runner(options_from(card, metadata_var.get(), check_var.get(), fix_var.get(),
                                     hires_var.get(), roms_var.get()))
        state["runner"] = runner
        runner.start()
        root.after(100, poll)

    def ask_stop() -> None:
        runner = state["runner"]
        if runner is None:
            return
        runner.stop()
        stop.configure(state="disabled")
        status_var.set("Stopping…")

    ttk.Button(buttons, text="Browse…", command=browse_card).pack(side="left")
    ttk.Button(buttons, text="Refresh", command=refresh_cards).pack(side="left", padx=(6, 0))
    ttk.Button(frame, text="Browse…", command=browse_roms).grid(row=2, column=2, sticky="e", pady=(10, 0))
    ttk.Button(frame, text="Browse…", command=browse_metadata).grid(row=4, column=2, sticky="e", pady=(10, 0))
    note.bind("<Button-1>", open_download)
    card_box.bind("<<ComboboxSelected>>", on_card_change)
    card_var.trace_add("write", on_card_change)
    metadata_var.trace_add("write", on_card_change)
    prepare.configure(command=start)
    stop.configure(command=ask_stop)
    refresh_cards()
    if card:
        card_var.set(card)
    if metadata:
        metadata_var.set(metadata)
    state["last_code"] = None
    # For the tests: the fields and the button, without walking widgets.
    state["fields"] = {"card": card_var, "roms": roms_var, "metadata": metadata_var}
    state["start"] = start
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
