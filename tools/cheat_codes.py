# SPDX-License-Identifier: AGPL-3.0-only
"""Cheat codes from libretro's database, one file per dump on the card.

The pack the EverDrive-64 Pro's menu ships in ED64/CHEATS is the older half
of libretro's Nintendo 64 cheat database, named the GoodN64 way, and the
browser has to guess a game's file there from its name and region. The
newer half is filed by the No-Intro name of the dump, and data/coverdb.csv
knows that name for every dump it knows by checksum -- so a card's cheats
can be fetched exactly, one file per dump, into

    sleekmenu/cheats/libretro/<CRC1><CRC2>.cht

named by the two checksum words in the ROM's own header, which is what the
browser has in hand when a game is opened. The browser reads that file
after the card owner's own (`sleekmenu/cheats/<ROM name>.cht`) and after
the pack's when the pack is sure of its match, so it serves the games the
pack lacks, has for another region only, or can only guess at: the pack's
lists are short and chosen, libretro's per-dump files are everything anyone
collected. Only a dump the database knows by checksum gets one: a hack
carries its parent's game code and other addresses, so it is given nothing
rather than codes that write to the wrong place.

What is fetched is written verbatim and recorded in `libretro/downloads.json`
-- name, address, date, SHA-256 -- with the dumps libretro was found to have
no file for, so a later run does not ask about them again, and with the
choice itself: a card that asked for cheats keeps them complete on every
run until it is told to stop. Nothing outside that folder is ever written.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from tools import card_layout, coverdb, fetch, headers, hires
from tools.progress import Cancelled

REPOSITORY_URL = "https://github.com/libretro/libretro-database"
BASE_URL = ("https://raw.githubusercontent.com/libretro/libretro-database/master/cht/"
            + urllib.parse.quote("Nintendo - Nintendo 64") + "/")
MANIFEST = "downloads.json"
MANIFEST_VERSION = 1
#: What every .cht starts by saying; a reply without it is not one.
SIGNATURE = b"cheats"
#: Connection failures in a row before the fetch gives up, as for boxes.
GIVE_UP_AFTER = 3


@dataclass(frozen=True)
class Wanted:
    crc: str                # the dump's checksum pair, sixteen hex digits
    name: str               # its No-Intro name
    destination: Path


@dataclass
class Report:
    fetched: int = 0
    missing: list[str] = field(default_factory=list)     # dumps libretro has no file for
    failed: list[str] = field(default_factory=list)      # dumps the network would not give
    stopped: bool = False


def folder(card: Path) -> Path:
    return card / card_layout.CARD_FOLDER / card_layout.CHEATS_FOLDER / card_layout.CHEATS_FETCHED_FOLDER


def file_name(crc: str) -> str:
    return crc.upper() + ".cht"


def address(name: str, base_url: str | None = None) -> str:
    return (base_url or BASE_URL) + urllib.parse.quote(hires.libretro_name(name) + ".cht")


# -- the manifest --------------------------------------------------------------

def load_document(target: Path) -> dict:
    """The manifest as written: `files` (checksum pair -> name, url, sha256,
    date), `missing` (checksum pair -> the date libretro was found to have
    no file) and `enabled` (whether the card still wants them). Empty for
    no manifest, or one that will not read."""
    try:
        document = json.loads((target / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict) or document.get("schema_version") != MANIFEST_VERSION:
        return {}
    out = {key: value for key, value in document.items()
           if key in ("files", "missing") and isinstance(value, dict)}
    out["enabled"] = document.get("enabled") is not False
    return out


def save_manifest(target: Path, files: dict, missing: dict, enabled: bool = True) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / MANIFEST).write_text(
        json.dumps({"schema_version": MANIFEST_VERSION, "source": REPOSITORY_URL, "enabled": bool(enabled),
                    "files": files, "missing": missing}, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def remembered(card: Path | None) -> bool:
    """Whether this card asked for cheats and has not been told to stop.
    Such a card keeps them complete on every run, so a game added later
    gets its file without the choice being made again."""
    return card is not None and bool(load_document(folder(card)).get("enabled"))


def forget(card: Path) -> bool:
    """Stop keeping the card's cheats complete. The files stay, and the
    browser goes on reading them. True when that changed anything."""
    target = folder(card)
    document = load_document(target)
    if not document.get("enabled"):
        return False
    save_manifest(target, document.get("files", {}), document.get("missing", {}), enabled=False)
    return True


def count(card: Path | None) -> int:
    """How many fetched files the card holds."""
    if card is None:
        return 0
    try:
        return sum(1 for name in os.listdir(folder(card)) if name.lower().endswith(".cht"))
    except OSError:
        return 0


# -- what to fetch ---------------------------------------------------------------

def plan(roms_root: Path, rom_paths: list[str], database: dict, card: Path,
         retry_missing: bool = False) -> list[Wanted]:
    """One Wanted per dump on the card that the database knows by checksum
    and the folder lacks. A dump the manifest records libretro as having
    no file for is left out unless `retry_missing`: asking for cheats asks
    again, a remembered run does not spend a request a game on the same
    absences."""
    target = folder(card)
    known_missing = set() if retry_missing else set(load_document(target).get("missing", {}))
    try:
        present = {name.upper() for name in os.listdir(target)}
    except OSError:
        present = set()
    wanted: dict[str, Wanted] = {}
    for rom_path in rom_paths:
        header = headers.read(roms_root / rom_path)
        if header is None:
            continue
        crc = header.crc_pair.upper()
        entry = database.get(crc) if crc != coverdb.ZERO_CRC else None
        if entry is None or crc in wanted or crc in known_missing or file_name(crc).upper() in present:
            continue
        wanted[crc] = Wanted(crc, entry.name, target / file_name(crc))
    return [wanted[crc] for crc in sorted(wanted, key=lambda crc: wanted[crc].name.casefold())]


def _get(url: str) -> bytes | None:
    """The file at `url`, None for a 404. Anything else raises."""
    try:
        with fetch.open_url(url) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def fetch_files(wanted: list[Wanted], target: Path, progress_factory=None, cancel=None, log=None,
                base_url: str | None = None) -> Report:
    """Fetch every Wanted file, verbatim, recording each in the manifest as
    it lands so a stop or a crash loses nothing already fetched. A dump
    with no file under its name is reported missing; three connection
    failures in a row end the run as offline."""
    report = Report()
    if not wanted:
        return report
    document = load_document(target)
    files, missing = document.get("files", {}), document.get("missing", {})
    bar = progress_factory(len(wanted), "cheats") if progress_factory else None
    consecutive_failures = 0
    for position, item in enumerate(wanted):
        if cancel is not None and cancel():
            report.stopped = True
            break
        url = address(item.name, base_url)
        try:
            data = _get(url)
            consecutive_failures = 0
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            report.failed.append(item.crc)
            consecutive_failures += 1
            if log is not None:
                log(f"          {item.name}: {getattr(error, 'reason', error)}")
            if consecutive_failures >= GIVE_UP_AFTER:
                if log is not None:
                    log("          three connection failures in a row: giving up on the rest")
                report.failed.extend(other.crc for other in wanted[position + 1:])
                break
            if bar is not None:
                bar.step(item.name)
            continue
        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if data is None or SIGNATURE not in data[:4096]:
            report.missing.append(item.crc)
            missing[item.crc] = stamp
        else:
            target.mkdir(parents=True, exist_ok=True)
            part = item.destination.with_name(item.destination.name + ".part")
            part.write_bytes(data)
            os.replace(part, item.destination)
            files[item.crc] = {"name": item.name, "url": url,
                               "sha256": hashlib.sha256(data).hexdigest(), "date": stamp}
            missing.pop(item.crc, None)
            report.fetched += 1
        save_manifest(target, files, missing)
        if bar is not None:
            bar.step(item.name)
    if bar is not None and not report.stopped:
        bar.done(f"cheats:   {report.fetched} fetched from libretro"
                 + (f", {len(report.missing)} not there" if report.missing else "")
                 + (f", {len(report.failed)} not reached" if report.failed else ""))
    return report


def fetch_for_card(roms_root: Path, rom_paths: list[str], database_path: Path, card: Path,
                   progress_factory=None, cancel=None, log=None, asked: bool = True) -> Report:
    """plan() then fetch_files(), with the report in the tool's own words.
    `asked` false is the remembered run: the card has cheats and keeps
    them complete, without asking libretro again for the ones it lacks. A
    stop between two files surfaces as Cancelled, like every other."""
    database = coverdb.load(database_path) if database_path.is_file() else {}
    wanted = plan(roms_root, rom_paths, database, card, retry_missing=asked)
    target = folder(card)
    where = target.relative_to(card).as_posix()
    if log is not None:
        how = "" if asked else " (the card has them; keeping them complete)"
        log(f"cheats:   {len(wanted)} file{'s' if len(wanted) != 1 else ''} to fetch from libretro{how}" if wanted
            else f"cheats:   nothing to fetch; what libretro has for these games is in {where}/{how}")
    document = load_document(target)
    if not document.get("enabled"):
        # The choice is remembered before anything is fetched, so a run
        # that finds nothing, or no network, does not lose it.
        save_manifest(target, document.get("files", {}), document.get("missing", {}))
    report = fetch_files(wanted, target, progress_factory, cancel, log)
    if report.stopped:
        raise Cancelled("stopped while fetching cheats")
    return report
