# SPDX-License-Identifier: AGPL-3.0-only
"""High-resolution boxes from libretro-thumbnails, one per game code.

The collection's scans are 158 pixels wide, which is what a 96x72 thumbnail
needs and nothing more. libretro keeps a 512-pixel box for every retail
cartridge, filed by the No-Intro name of the dump, and data/coverdb.csv
knows that name for every dump it knows -- so a card's boxes can be fetched
by game code, one file per code, into

    sleekmenu/art/hires/<CODE>.png

which the cover plan takes before the collection's scan: a 512-pixel box
downscaled to 96x72 beats a 158-pixel one downscaled. Hacks keep their
parent's box, as they do from the collection; homebrew gets none.

The file name is the No-Intro name with the characters libretro cannot
put in a file name (& * / : ` < > ? \\ | ") turned into `_`. A code is
tried under every name the database has for it, the name of the dump on
the card first, so a beta whose own box does not exist still gets its
game's. What is fetched is written verbatim and recorded in
`hires/downloads.json` -- address, date, SHA-256 -- which is how the window
tells a box the tool fetched from one changed by hand, and how a re-fetch
knows which files are its own. Nothing outside hires/ is ever written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from tools import coverdb, custom_art, fetch, headers, identify, provenance
from tools.progress import Cancelled

FOLDER = "hires"
MANIFEST = "downloads.json"
REPOSITORY_URL = "https://github.com/libretro-thumbnails/Nintendo_-_Nintendo_64"
BASE_URL = ("https://raw.githubusercontent.com/libretro-thumbnails/Nintendo_-_Nintendo_64"
            "/master/Named_Boxarts/")
#: What libretro's file names cannot carry; each becomes an underscore.
FORBIDDEN = re.compile(r'[&*/:`<>?\\|"]')
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: Connection failures in a row before the fetch gives up: one is a blip,
#: three is being offline, and a card of 700 boxes must not wait out 700
#: timeouts to find that out.
GIVE_UP_AFTER = 3


@dataclass(frozen=True)
class Hires:
    """A fetched box on disk and the sprite it becomes: the collection's
    own name for the code, so it stands in for the collection's box
    wherever that would have been used."""
    path: Path
    sprite: str


@dataclass(frozen=True)
class Wanted:
    code: str
    names: list[str]        # No-Intro names to try, best first
    destination: Path


@dataclass
class Report:
    fetched: int = 0
    missing: list[str] = field(default_factory=list)     # codes libretro has no box for
    failed: list[str] = field(default_factory=list)      # codes the network would not give
    stopped: bool = False


def folder(art_folder: Path | None) -> Path | None:
    return None if art_folder is None else art_folder / FOLDER


def libretro_name(name: str) -> str:
    return FORBIDDEN.sub("_", name)


def address(name: str, base_url: str | None = None) -> str:
    return (base_url or BASE_URL) + urllib.parse.quote(libretro_name(name) + ".png")


def find(index: custom_art.Index, hires_folder: Path | None, code: str) -> Hires | None:
    """The fetched box for a code, whatever the case of its file name."""
    if hires_folder is None or not code:
        return None
    found = index.lookup(hires_folder, code + ".png")
    return Hires(found, custom_art.code_sprite(code)) if found is not None else None


# -- the manifest --------------------------------------------------------------

def manifest_path(hires_folder: Path) -> Path:
    return hires_folder / MANIFEST


def load_document(hires_folder: Path | None) -> dict:
    """The manifest as written: `boxes` (code -> name, url, sha256, date)
    and `missing` (code -> date libretro was found to have no box for it).
    Empty for no manifest, or one that will not read."""
    if hires_folder is None:
        return {}
    try:
        document = json.loads(manifest_path(hires_folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict):
        return {}
    return {key: value for key, value in document.items() if key in ("boxes", "missing")
            and isinstance(value, dict)}


def load_manifest(hires_folder: Path | None) -> dict:
    """The fetched boxes: code -> its record."""
    return load_document(hires_folder).get("boxes", {})


def save_manifest(hires_folder: Path, boxes: dict, missing: dict | None = None) -> None:
    hires_folder.mkdir(parents=True, exist_ok=True)
    manifest_path(hires_folder).write_text(
        json.dumps({"schema_version": 1, "source": REPOSITORY_URL, "boxes": boxes,
                    "missing": missing or {}}, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def remembered(art_folder: Path | None) -> bool:
    """Whether this card has fetched boxes before: the manifest is there.
    A card that has them keeps them complete on every run, so a game added
    later gets its box without the choice being made again."""
    target = folder(art_folder)
    return target is not None and manifest_path(target).is_file()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for piece in iter(lambda: handle.read(1 << 16), b""):
            digest.update(piece)
    return digest.hexdigest()


def origin(hires_folder: Path | None, path: Path) -> str:
    """Whether a box in hires/ is still the one the tool fetched."""
    entry = load_manifest(hires_folder).get(path.stem.upper())
    try:
        if entry and entry.get("sha256") == sha256_of(path):
            return provenance.COVER_LIBRETRO
    except OSError:
        pass
    return provenance.COVER_LIBRETRO_MODIFIED


# -- what to fetch ---------------------------------------------------------------

def plan(roms_root: Path, rom_paths: list[str], database: dict, art_folder: Path | None,
         retry_missing: bool = False) -> list[Wanted]:
    """One Wanted per game code on the card that the database knows and
    hires/ lacks. The names to try: the dump's own when the database knows
    it by CRC, then every other name the database files under that code.
    A code the manifest records libretro as having no box for is left out
    unless `retry_missing`: an explicit --hires asks again, a remembered
    run does not spend sixty requests a time on the same absences."""
    target = folder(art_folder)
    if target is None:
        return []
    known_missing = set() if retry_missing else set(load_document(target).get("missing", {}))
    index = identify.Index(database)
    listing = custom_art.Index()
    by_serial: dict[str, list[str]] = {}
    for entry in database.values():
        if entry.serial:
            by_serial.setdefault(entry.serial.upper(), []).append(entry.name)
    wanted: dict[str, list[str]] = {}
    for rom_path in rom_paths:
        header = headers.read(roms_root / rom_path)
        if header is None or not header.product_code:
            continue
        code = header.product_code.upper()
        if not re.fullmatch(r"[A-Z0-9]{4}", code) or find(listing, target, code) is not None:
            continue
        if code in known_missing:
            continue
        entry, matched = index.identify(header)
        if entry is None:
            continue
        names = wanted.setdefault(code, [])
        first = [entry.name] if matched == "crc" else []
        for name in first + by_serial.get(code, []):
            if name not in names:
                names.append(name)
        if matched == "crc" and names[0] != entry.name:
            names.remove(entry.name)
            names.insert(0, entry.name)
    return [Wanted(code, names, target / f"{code}.png") for code, names in sorted(wanted.items())]


def _get(url: str) -> bytes | None:
    """The file at `url`, None for a 404. Anything else raises."""
    try:
        with fetch.open_url(url) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def fetch_boxes(wanted: list[Wanted], hires_folder: Path, progress_factory=None, cancel=None,
                log=None, base_url: str | None = None) -> Report:
    """Fetch every Wanted box into hires/, verbatim, recording each in the
    manifest as it lands so a stop or a crash loses nothing already
    fetched. A code whose every name is a 404 is reported missing; three
    connection failures in a row end the run as offline."""
    report = Report()
    if not wanted:
        return report
    base_url = base_url or BASE_URL
    document = load_document(hires_folder)
    boxes, missing = document.get("boxes", {}), document.get("missing", {})
    bar = progress_factory(len(wanted), "boxes") if progress_factory else None
    consecutive_failures = 0
    for item in wanted:
        if cancel is not None and cancel():
            report.stopped = True
            break
        data, found_name = None, ""
        try:
            for name in item.names:
                data = _get(address(name, base_url))
                if data is not None:
                    found_name = name
                    break
            consecutive_failures = 0
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            report.failed.append(item.code)
            consecutive_failures += 1
            if log is not None:
                log(f"          {item.code}: {getattr(error, 'reason', error)}")
            if consecutive_failures >= GIVE_UP_AFTER:
                if log is not None:
                    log("          three connection failures in a row: giving up on the rest")
                report.failed.extend(other.code for other in wanted[wanted.index(item) + 1:])
                break
            if bar is not None:
                bar.step(item.code)
            continue
        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if data is None or not data.startswith(PNG_SIGNATURE):
            report.missing.append(item.code)
            missing[item.code] = stamp
            save_manifest(hires_folder, boxes, missing)
        else:
            hires_folder.mkdir(parents=True, exist_ok=True)
            part = item.destination.with_name(item.destination.name + ".part")
            part.write_bytes(data)
            os.replace(part, item.destination)
            boxes[item.code] = {"name": found_name, "url": address(found_name, base_url),
                                "sha256": hashlib.sha256(data).hexdigest(), "date": stamp}
            missing.pop(item.code, None)
            save_manifest(hires_folder, boxes, missing)
            report.fetched += 1
        if bar is not None:
            bar.step(item.code)
    if bar is not None and not report.stopped:
        bar.done(f"boxes:    {report.fetched} fetched from libretro"
                 + (f", {len(report.missing)} not there" if report.missing else "")
                 + (f", {len(report.failed)} not reached" if report.failed else ""))
    return report


def fetch_for_card(roms_root: Path, rom_paths: list[str], database_path: Path, art_folder: Path,
                   progress_factory=None, cancel=None, log=None, asked: bool = True) -> Report:
    """plan() then fetch_boxes(), with the report in the tool's own words.
    `asked` false is the remembered run: the card has boxes and keeps them
    complete, without asking libretro again for the ones it lacks. A stop
    between two boxes surfaces as Cancelled, like every other."""
    database = coverdb.load(database_path) if database_path.is_file() else {}
    wanted = plan(roms_root, rom_paths, database, art_folder, retry_missing=asked)
    target = folder(art_folder)
    if log is not None:
        how = "" if asked else " (the card has them; keeping them complete)"
        log(f"hires:    {len(wanted)} boxes to fetch from libretro (about 250 KB each){how}"
            if wanted else "hires:    every box the database knows is already in "
                           f"{target.parent.name}/{FOLDER}/{how}")
    report = fetch_boxes(wanted, target, progress_factory, cancel, log)
    if report.stopped:
        raise Cancelled("stopped while fetching boxes")
    if report.missing and log is not None:
        shown = ", ".join(report.missing[:12]) + (", ..." if len(report.missing) > 12 else "")
        log(f"          no box on libretro for {len(report.missing)}: {shown}")
    return report
