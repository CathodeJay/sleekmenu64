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
from pathlib import Path

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools import card_catalog, card_layout, library, make_sprite, metadata_repo, provenance, sleekmenu_prep

TITLE = "SleekMenu 64 — prepare a card"
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


def describe_card(card: Path) -> str:
    """One line about what is on a candidate card, for the picker."""
    try:
        roms = library.walk(card)
    except library.LibraryError:
        return "not a folder"
    parts = [f"{len(roms)} ROMs"] if roms else ["no ROMs"]
    if (card / card_layout.BROWSER_ROM).is_file():
        parts.append(card_layout.BROWSER_ROM + " present")
    collection = metadata_repo.find_on_card(card)
    parts.append(f"box art: {collection.name}" if collection is not None else "box art: none on the card")
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


def options_from(card: str, metadata: str, check_checksums: bool, fix_checksums: bool) -> sleekmenu_prep.Options:
    """The window's fields as the run takes them. An empty metadata field
    means whatever is on the card, as on the command line."""
    return sleekmenu_prep.Options(
        card=Path(card) if card.strip() else None,
        metadata=Path(metadata) if metadata.strip() else None,
        no_checksums=not check_checksums,
        fix_checksums=fix_checksums,
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
    """The line above the tree."""
    games = document.get("games", [])
    edited = sum(1 for game in games if provenance.edited(game.get("sources") or {}))
    built = str(document.get("built", ""))[:16].replace("T", " ")
    line = f"{len(games)} games" + (f", built {built}" if built else "")
    if edited:
        line += f"; {edited} with your own art or text"
    return line


class CatalogTab:
    """The card as the browser will show it, from sleekmenu/catalog.json:
    the folders as a tree, one row per game with where each field came
    from, and for the selected game the box exactly as the console draws
    it -- decoded from covers.pak, never from the source picture."""

    def __init__(self, parent, card_of):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.card_of = card_of
        self.document = None
        self.covers = None
        self.games: dict[str, dict] = {}
        self.photo = None
        self.only_mine = tk.BooleanVar(value=False)
        self.summary = tk.StringVar(value="No card picked.")
        self.title = tk.StringVar()
        self.facts = tk.StringVar()
        self.sources = tk.StringVar()
        self.notes = tk.StringVar()

        frame = ttk.Frame(parent, padding=12)
        frame.pack(fill="both", expand=True)
        self.frame = frame
        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Button(top, text="Reload", command=self.reload).pack(side="left")
        ttk.Label(top, textvariable=self.summary, foreground="#555").pack(side="left", padx=8)
        ttk.Checkbutton(top, text="Only what I changed", variable=self.only_mine,
                        command=self.fill).pack(side="right")

        panes = ttk.PanedWindow(frame, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(8, 0))
        left = ttk.Frame(panes)
        columns = ("genre", "year", "publisher", "players", "region", "cover", "text")
        self.tree = ttk.Treeview(left, columns=columns, selectmode="browse")
        self.tree.heading("#0", text="Folder / game")
        self.tree.column("#0", width=260, stretch=True)
        for name, width in (("genre", 90), ("year", 50), ("publisher", 110), ("players", 60),
                            ("region", 60), ("cover", 150), ("text", 160)):
            self.tree.heading(name, text=name.capitalize() if name != "text" else "Description")
            self.tree.column(name, width=width, stretch=False, anchor="w")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        across = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=across.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        panes.add(left, weight=3)

        right = ttk.Frame(panes, padding=(12, 0, 0, 0), width=320)
        self.box = ttk.Label(right, text="", anchor="w")
        self.box.pack(anchor="w")
        wrapped = []
        for variable, style in ((self.title, {"font": ("TkDefaultFont", 12, "bold")}),
                                (self.facts, {}), (self.sources, {"foreground": "#555"})):
            label = ttk.Label(right, textvariable=variable, justify="left", **style)
            label.pack(anchor="w", pady=(6, 0) if variable is self.title else (2, 0))
            wrapped.append(label)
        self.description = tk.Text(right, height=8, width=30, wrap="word", state="disabled")
        self.description.pack(fill="both", expand=True, pady=(8, 0))
        notes = ttk.Label(right, textvariable=self.notes, foreground="#8a4b00", justify="left")
        notes.pack(anchor="w", pady=(4, 0))
        wrapped.append(notes)

        def rewrap(event):
            for label in wrapped:
                label.configure(wraplength=max(120, event.width - 16))
        right.bind("<Configure>", rewrap)
        self.detail = right
        panes.add(right, weight=2)

    # -- loading -----------------------------------------------------------

    def reload(self) -> None:
        """Read catalog.json and covers.pak off the card again."""
        card = self.card_of()
        self.document, self.covers, self.games = None, None, {}
        if card is None:
            self.summary.set("No card picked.")
        else:
            try:
                self.document = card_catalog.load(card)
            except card_catalog.CatalogJsonError as error:
                self.summary.set(str(error))
            if self.document is None:
                if not self.summary.get().startswith(str(card)):
                    self.summary.set("No catalog on this card yet: press Prepare.")
            else:
                self.covers = card_catalog.Covers.open(card)
                self.games = {str(game["path"]): game for game in self.document["games"]}
                self.summary.set(summarize(self.document))
        self.fill()
        self.show(None)

    def fill(self) -> None:
        """The tree from the loaded catalog, folders first, honouring the
        'only what I changed' filter."""
        self.tree.delete(*self.tree.get_children())
        if self.document is None:
            return
        games = self.document["games"]
        if self.only_mine.get():
            games = [game for game in games if provenance.edited(game.get("sources") or {})]
        self._add(card_catalog.tree(games), "")

    def _add(self, node: dict, parent: str) -> None:
        for name, child in node["folders"].items():
            iid = self.tree.insert(parent, "end", text=f"{name}/  ({card_catalog.count(child)})", open=True)
            self._add(child, iid)
        for game in node["games"]:
            sources = game.get("sources") or {}
            self.tree.insert(parent, "end", iid=str(game["path"]), text=str(game.get("title", "")),
                             values=(game.get("genre", ""), game.get("year") or "",
                                     game.get("publisher", ""), game.get("players") or "",
                                     "/".join(game.get("regions") or []),
                                     sources.get("cover", ""), sources.get("description", "")))

    # -- the selected game ---------------------------------------------------

    def selected(self) -> dict | None:
        chosen = self.tree.selection()
        return self.games.get(chosen[0]) if chosen else None

    def on_select(self, _event=None) -> None:
        self.show(self.selected())

    def show(self, game: dict | None) -> None:
        self.description.configure(state="normal")
        self.description.delete("1.0", "end")
        if game is None:
            self.title.set("")
            self.facts.set("")
            self.sources.set("")
            self.notes.set("")
            self.box.configure(image="", text="")
            self.photo = None
        else:
            sources = game.get("sources") or {}
            self.title.set(str(game.get("title", "")))
            self.facts.set(facts_line(game))
            self.sources.set(f"Cover: {sources.get('cover', '')} · Description: {sources.get('description', '')}"
                             f" · Title: {sources.get('title', '')}")
            self.description.insert("1.0", str(game.get("description") or ""))
            self.notes.set("\n".join(provenance.notes(game)))
            pixels = self.covers.pixels(game) if self.covers is not None else None
            if pixels is None:
                self.photo = None
                self.box.configure(image="", text="(no box)")
            else:
                width, height, rgb = pixels
                self.photo = self.tk.PhotoImage(data=make_sprite.to_ppm(width, height, rgb),
                                                format="PPM").zoom(BOX_ZOOM, BOX_ZOOM)
                self.box.configure(image=self.photo, text="")
        self.description.configure(state="disabled")


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
    root.minsize(760, 520)
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    frame = ttk.Frame(notebook, padding=12)
    notebook.add(frame, text="Prepare")
    frame.columnconfigure(1, weight=1)

    state = {"runner": None}
    card_var = tk.StringVar()
    card_note = tk.StringVar(value="Pick the card, or plug it in and press Refresh.")
    metadata_var = tk.StringVar()
    metadata_note = tk.StringVar()
    check_var = tk.BooleanVar(value=True)
    fix_var = tk.BooleanVar(value=False)
    status_var = tk.StringVar(value="")

    ttk.Label(frame, text="Card").grid(row=0, column=0, sticky="w")
    card_box = ttk.Combobox(frame, textvariable=card_var)
    card_box.grid(row=0, column=1, sticky="ew", padx=6)
    buttons = ttk.Frame(frame)
    buttons.grid(row=0, column=2, sticky="e")
    ttk.Label(frame, textvariable=card_note, foreground="#555").grid(row=1, column=1, sticky="w", padx=6)

    ttk.Label(frame, text="Box art").grid(row=2, column=0, sticky="w", pady=(10, 0))
    ttk.Entry(frame, textvariable=metadata_var).grid(row=2, column=1, sticky="ew", padx=6, pady=(10, 0))
    note = ttk.Label(frame, textvariable=metadata_note, foreground="#555", cursor="hand2")
    note.grid(row=3, column=1, sticky="w", padx=6)

    options = ttk.Frame(frame)
    options.grid(row=4, column=1, sticky="w", padx=6, pady=(10, 0))
    ttk.Checkbutton(options, text="Check hacks and homebrew for a stale header checksum",
                    variable=check_var).pack(anchor="w")
    ttk.Checkbutton(options, text="Rewrite a stale checksum in the file itself",
                    variable=fix_var).pack(anchor="w")

    bar = ttk.Progressbar(frame, mode="determinate")
    bar.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(12, 2))
    ttk.Label(frame, textvariable=status_var, foreground="#555").grid(row=6, column=0, columnspan=3, sticky="w")
    log = tk.Text(frame, height=12, wrap="word", state="disabled", font=("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10) if sys.platform == "win32" else ("monospace", 10))
    log.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(4, 8))
    frame.rowconfigure(7, weight=1)
    actions = ttk.Frame(frame)
    actions.grid(row=8, column=2, sticky="e")
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
        if not card or not Path(card).is_dir():
            card_note.set("Pick the card, or plug it in and press Refresh.")
            metadata_note.set("")
            return
        card_note.set(describe_card(Path(card)))
        collection = metadata_repo.find_on_card(Path(card))
        if metadata_var.get().strip():
            metadata_note.set("Using the file above.")
        elif collection is not None:
            metadata_note.set(f"{collection.name} found on the card.")
        else:
            metadata_note.set(f"Not on the card: Prepare fetches {metadata_repo.RELEASE_ZIP_NAME} "
                              "(about 52 MB) from GitHub (click to see), or choose a copy with Browse.")

    def browse_card() -> None:
        chosen = filedialog.askdirectory(title="The card")
        if chosen:
            card_var.set(chosen)
            on_card_change()

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
        runner = Runner(options_from(card, metadata_var.get(), check_var.get(), fix_var.get()))
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
    ttk.Button(frame, text="Browse…", command=browse_metadata).grid(row=2, column=2, sticky="e", pady=(10, 0))
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
