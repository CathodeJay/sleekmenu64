# SPDX-License-Identifier: AGPL-3.0-only
"""Saves: every one on the card copied to one file on the computer, and put
back from it.

The saves live in

    ED64/gamedata/

written by the EverDrive and by the browser, under the EverDrive's own
names: an X7 keeps a file per game there, a Pro a folder per game. This
module treats that folder as a tree of files and never looks inside one,
so whatever the firmware keeps there is carried as it is.

A backup is a zip: the tree under `gamedata/`, each file with its date,
and `sleekmenu-saves.json` beside it, which says it is a backup and when it
was made. It is written as a `.part` file and renamed, so a backup that
fails halfway leaves no zip that looks whole.

A restore writes the files back under `ED64/gamedata/`, each through a
`.part` file and a rename, and gives each the date it had in the backup.
A file that is the same on the card is left alone. A file that changed on
the card since the backup was made is kept unless the owner says to
replace it. Nothing on the card is deleted, and a zip that names a file
outside the folder (an absolute path, or `..`) is refused whole.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# Runnable as a script as well as importable -- see tools/__init__.py.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import card_layout

#: The backup's own record, at the root of the zip.
MANIFEST = "sleekmenu-saves.json"
#: The saves, under this folder in the zip.
TREE = card_layout.GAMEDATA_FOLDER + "/"
#: What this module writes and the newest it reads.
FORMAT = 1
#: A zip keeps a file's time to two seconds; a file on the card no newer
#: than that is the backup's own.
SLACK_SECONDS = 2

NOT_A_BACKUP = "This file isn't a SleekMenu saves backup."
NO_SAVES = "There are no saves on this card yet."

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


class SavesError(Exception):
    """A backup that can't be made or read, said the way the window says it."""


@dataclass(frozen=True)
class Save:
    path: str           # under ED64/gamedata/, with forward slashes
    size: int
    modified: float     # seconds since the epoch


@dataclass(frozen=True)
class Backup:
    """What a backup holds, for the question before a restore."""
    made: datetime.date
    saves: tuple        # the paths under ED64/gamedata/

    @property
    def count(self) -> int:
        return len(self.saves)


@dataclass
class Plan:
    """What a restore would do with each save in the backup."""
    put: list = field(default_factory=list)       # missing from the card, or older there
    newer: list = field(default_factory=list)     # changed on the card since the backup
    same: list = field(default_factory=list)      # already on the card as it is


@dataclass(frozen=True)
class Restored:
    put: int
    kept: int
    same: int


def folder(card: Path) -> Path:
    return card / card_layout.FIRMWARE_FOLDER / card_layout.GAMEDATA_FOLDER


def has_folder(card: Path | None) -> bool:
    return card is not None and folder(card).is_dir()


def find(card: Path) -> list[Save]:
    """Every save on the card, in name order. What the operating systems
    leave beside them (`._` twins, `.DS_Store`) is not a save."""
    root = folder(card)
    found = []
    for at, folders, files in os.walk(root):
        folders[:] = sorted(name for name in folders if not card_layout.hidden(name))
        for name in sorted(files):
            if card_layout.hidden(name):
                continue
            path = Path(at) / name
            stat = path.stat()
            found.append(Save(path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime))
    return found


def file_name(today: datetime.date | None = None) -> str:
    """The name the window suggests for a backup made today."""
    return f"SleekMenu saves {(today or datetime.date.today()).isoformat()}.zip"


def spoken_date(day: datetime.date) -> str:
    """November 17, 2026."""
    return f"{MONTHS[day.month - 1]} {day.day}, {day.year}"


def count_of(count: int) -> str:
    return f"{count:,} save" + ("" if count == 1 else "s")


def backup(card: Path, zip_path: Path, now: datetime.datetime | None = None) -> int:
    """Every save on the card into one zip. Returns how many."""
    found = find(card)
    if not found:
        raise SavesError(NO_SAVES)
    now = now or datetime.datetime.now()
    record = {"format": FORMAT, "date": now.isoformat(timespec="seconds"), "files": len(found)}
    part = zip_path.with_name(zip_path.name + ".part")
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
            archive.writestr(MANIFEST, json.dumps(record, indent=1) + "\n")
            for save in found:
                archive.write(folder(card) / save.path, TREE + save.path)
        os.replace(part, zip_path)
    finally:
        if part.exists():
            part.unlink()
    return len(found)


def _safe(name: str) -> bool:
    """A name that stays inside the folder it is unpacked into."""
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return False
    return ".." not in PurePosixPath(name).parts


def _read(archive: zipfile.ZipFile) -> Backup:
    if not all(_safe(info.filename) for info in archive.infolist()):
        raise SavesError(NOT_A_BACKUP)
    try:
        record = json.loads(archive.read(MANIFEST).decode("utf-8"))
        version = record["format"]
        made = datetime.date.fromisoformat(str(record["date"])[:10])
    except (KeyError, TypeError, ValueError):
        raise SavesError(NOT_A_BACKUP) from None
    if not isinstance(version, int) or not 1 <= version <= FORMAT:
        raise SavesError(NOT_A_BACKUP)
    saves = tuple(info.filename[len(TREE):] for info in archive.infolist()
                  if info.filename.startswith(TREE) and not info.is_dir() and len(info.filename) > len(TREE))
    return Backup(made, saves)


def _open(zip_path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, zipfile.LargeZipFile):
        raise SavesError(NOT_A_BACKUP) from None


def inspect(zip_path: Path) -> Backup:
    """What a backup holds. Raises SavesError for a file that isn't one."""
    with _open(zip_path) as archive:
        return _read(archive)


def _when(info: zipfile.ZipInfo) -> float:
    return time.mktime(info.date_time + (0, 0, -1))


def _same(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> bool:
    if target.stat().st_size != info.file_size:
        return False
    with archive.open(info) as theirs, target.open("rb") as ours:
        while True:
            chunk = theirs.read(65536)
            if chunk != ours.read(65536):
                return False
            if not chunk:
                return True


def _plan(card: Path, archive: zipfile.ZipFile, backup_: Backup) -> Plan:
    plan = Plan()
    root = folder(card)
    for name in backup_.saves:
        info = archive.getinfo(TREE + name)
        target = root / name
        if not target.is_file():
            plan.put.append(name)
        elif _same(archive, info, target):
            plan.same.append(name)
        elif target.stat().st_mtime > _when(info) + SLACK_SECONDS:
            plan.newer.append(name)
        else:
            plan.put.append(name)
    return plan


def plan(card: Path, zip_path: Path) -> Plan:
    """What restore() would do, without doing it: for the question about
    saves that are newer on the card."""
    with _open(zip_path) as archive:
        return _plan(card, archive, _read(archive))


def _write(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    try:
        with archive.open(info) as source, part.open("wb") as out:
            shutil.copyfileobj(source, out)
        os.replace(part, target)
    finally:
        if part.exists():
            part.unlink()
    when = _when(info)
    os.utime(target, (when, when))


def restore(card: Path, zip_path: Path, replace_newer: bool = False) -> Restored:
    """The backup's saves back under ED64/gamedata/. Saves newer on the
    card are kept unless `replace_newer`. Nothing is deleted."""
    with _open(zip_path) as archive:
        held = _read(archive)
        todo = _plan(card, archive, held)
        writing = todo.put + (todo.newer if replace_newer else [])
        for name in writing:
            _write(archive, archive.getinfo(TREE + name), folder(card) / name)
    return Restored(len(writing), 0 if replace_newer else len(todo.newer), len(todo.same))


# -- what the window and the terminal say ------------------------------------

def backed_up_line(count: int, zip_path: Path) -> str:
    return f"Backed up {count_of(count)} to {zip_path.name}."


def restore_question(held: Backup) -> str:
    return f"This backup holds {count_of(held.count)} from {spoken_date(held.made)}. Put them back on the card?"


def newer_question(count: int) -> str:
    if count == 1:
        return "1 save on the card is newer than the backup."
    return f"{count:,} saves on the card are newer than the backup."


def restored_line(result: Restored) -> str:
    line = f"Put {count_of(result.put)} back."
    if result.kept == 1:
        line += " 1 newer save on the card was kept."
    elif result.kept:
        line += f" {result.kept:,} newer saves on the card were kept."
    return line

