#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Prepare a card from a window: the same run as sleekmenu-prep, without a
terminal.

Pick the card (found on its own when it is the only removable disk), see
whether the box-art collection is on it, press Prepare, watch the progress.
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

from tools import card_layout, library, metadata_repo, sleekmenu_prep

TITLE = "SleekMenu 64 — prepare a card"
DOWNLOAD_URL = metadata_repo.RELEASES_URL


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
    never blocks on the card, and the run never touches a widget."""

    def __init__(self, options: sleekmenu_prep.Options):
        self.options = options
        self.events: queue.Queue = queue.Queue()
        self.code: int | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._work, name="sleekmenu-prep", daemon=True)
        self._thread.start()

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
                progress_factory=Bar)
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
    root.minsize(560, 420)
    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)
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
    prepare = ttk.Button(frame, text="Prepare")
    prepare.grid(row=8, column=2, sticky="e")

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

    def on_card_change(*_args) -> None:
        card = card_var.get().strip()
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
            metadata_note.set(f"Not on the card. Download {metadata_repo.RELEASE_ZIP_NAME} (click), "
                              "put it on the card or choose it with Browse.")

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
        if "Download" in metadata_note.get():
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
                bar["value"] = bar["maximum"]
                if event[1] == 0:
                    status_var.set("Done. Eject the card and start SleekMenu64.z64 from the EverDrive menu.")
                    say("")
                    say("Eject the card and start SleekMenu64.z64 from the EverDrive menu.")
                else:
                    status_var.set("Stopped; see the last line above.")
                state["last_code"] = event[1]
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
        runner = Runner(options_from(card, metadata_var.get(), check_var.get(), fix_var.get()))
        state["runner"] = runner
        runner.start()
        root.after(100, poll)

    ttk.Button(buttons, text="Browse…", command=browse_card).pack(side="left")
    ttk.Button(buttons, text="Refresh", command=refresh_cards).pack(side="left", padx=(6, 0))
    ttk.Button(frame, text="Browse…", command=browse_metadata).grid(row=2, column=2, sticky="e", pady=(10, 0))
    note.bind("<Button-1>", open_download)
    card_box.bind("<<ComboboxSelected>>", on_card_change)
    card_var.trace_add("write", on_card_change)
    metadata_var.trace_add("write", on_card_change)
    prepare.configure(command=start)
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
