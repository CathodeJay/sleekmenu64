# SPDX-License-Identifier: AGPL-3.0-only
"""Screenshots: a game's title screen and a moment of play, from
libretro-thumbnails or from the card owner.

libretro-thumbnails keeps two more pictures beside every box, under the
same No-Intro names: `Named_Titles`, the title screen, and `Named_Snaps`,
the game in play, most at the console's own 320x240. When the card asks
for them (--shots, or Fetch screenshots in the window) both are fetched for
every retail game on the card that the database knows, one pair per game
code, into

    sleekmenu/art/shots/<CODE>.title.png
    sleekmenu/art/shots/<CODE>.snap.png

the same names tried in the same order, and links followed, as for the
high-resolution boxes (tools/hires.py). `shots/downloads.json` records what
was fetched and from where, which pictures libretro does not have, and
whether the card still wants them: a card that asked keeps its screenshots
complete on every run until it is told to stop. A hack, a translation or
homebrew is given none, since its parent's screens show another game.

The card owner's own come first, by the ROM's name, beside it or in
sleekmenu/art/:

    <ROM name>.title.png     the title screen
    <ROM name>.snap.png      the game in play

PNG or JPEG, any size; a picture is fitted, never stretched. The window's
Screenshots button writes these into sleekmenu/art/ and nothing else.

On the card each game's pair becomes two pictures in each of two packs,
the way its box does (tools/cover_pack.py): `shots.pak` at 48x36 for the
thumbnails on the details screen, `shots-large.pak` at 224x168 for the box
view. Games with the same pair share one numbered set -- every region and
revision of a game copied into four folders is still one set -- and the
catalog record carries the number (tools/build_catalog.py), 0 for none.
The pictures are named `<number>.title` and `<number>.snap` in both packs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from tools import (card_layout, coverdb, custom_art, fetch, headers, hires, identify, kinds,
                   make_sprite, metadata_repo, provenance)
from tools.progress import Cancelled

FOLDER = card_layout.SHOTS_FOLDER
MANIFEST = "downloads.json"
MANIFEST_VERSION = 1
#: The two pictures a game can have, in the order the console shows them
#: after the box.
SLOTS = ("title", "snap")
NAMES = {"title": "title screen", "snap": "in game"}
LIBRETRO_FOLDERS = {"title": "Named_Titles", "snap": "Named_Snaps"}
ROOT_URL = "https://raw.githubusercontent.com/libretro-thumbnails/Nintendo_-_Nintendo_64/master/"
#: The box view's picture: 4:3, as large as fits between the title band and
#: the footer. src/display.h has the same numbers.
CANVAS = (224, 168)
#: The details screen's thumbnail, two stacked beside the facts.
THUMB = (48, 36)
#: Named in every picture's identity in the catalog, so a change to how
#: they are made converts every one again.
FORMAT = "rgba16-48x36+224x168-fit1"
#: The console reads at most 8,192 pictures from a pack, two per set.
MAX_SETS = 4096
#: Connection failures in a row before the fetch gives up, as for boxes.
GIVE_UP_AFTER = 3
#: About what a game's pair costs on the card: the two pictures fetched,
#: and the four sprites made from them.
BYTES_PER_GAME = 360 * 1024


@dataclass(frozen=True)
class Wanted:
    code: str
    slot: str               # "title" or "snap"
    names: list[str]        # No-Intro names to try, best first
    destination: Path


@dataclass
class Report:
    fetched: int = 0
    missing: list[str] = field(default_factory=list)     # code.slot libretro has no picture for
    failed: list[str] = field(default_factory=list)      # code.slot the network would not give
    stopped: bool = False


def folder(card: Path | None) -> Path | None:
    """`sleekmenu/art/shots/` on the card, whether or not it exists."""
    art = custom_art.art_dir(card)
    return None if art is None else art / FOLDER


def base_url(slot: str, root: str | None = None) -> str:
    return (root or ROOT_URL) + LIBRETRO_FOLDERS[slot] + "/"


def key(code: str, slot: str) -> str:
    return f"{code.upper()}.{slot}"


def file_name(code: str, slot: str) -> str:
    return key(code, slot) + ".png"


def sprite_name(number: int, slot: str) -> str:
    """A set's picture, as both packs name it and the console asks for it."""
    return f"{number}.{slot}"


# -- the manifest --------------------------------------------------------------

def load_document(target: Path | None) -> dict:
    """The manifest as written: `shots` (code.slot -> name, url, sha256,
    date), `missing` (code.slot -> the date libretro was found to have
    none) and `enabled` (whether the card still wants them). Empty for no
    manifest, or one that will not read."""
    if target is None:
        return {}
    try:
        document = json.loads((target / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict) or document.get("schema_version") != MANIFEST_VERSION:
        return {}
    out = {name: value for name, value in document.items()
           if name in ("shots", "missing") and isinstance(value, dict)}
    out["enabled"] = document.get("enabled") is not False
    return out


def save_manifest(target: Path, shots: dict, missing: dict, enabled: bool = True) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / MANIFEST).write_text(
        json.dumps({"schema_version": MANIFEST_VERSION, "source": hires.REPOSITORY_URL,
                    "enabled": bool(enabled), "shots": shots, "missing": missing},
                   indent=1, sort_keys=True) + "\n", encoding="utf-8")


def remembered(card: Path | None) -> bool:
    """Whether this card asked for screenshots and has not been told to
    stop. Such a card keeps them complete on every run, so a game added
    later gets its pair without the choice being made again."""
    return card is not None and bool(load_document(folder(card)).get("enabled"))


def forget(card: Path) -> bool:
    """Stop keeping the card's screenshots complete. The pictures stay, and
    the console goes on showing them. True when that changed anything."""
    target = folder(card)
    document = load_document(target)
    if not document.get("enabled"):
        return False
    save_manifest(target, document.get("shots", {}), document.get("missing", {}), enabled=False)
    return True


def count(card: Path | None) -> int:
    """How many fetched pictures the card holds."""
    target = folder(card)
    if target is None:
        return 0
    try:
        return sum(1 for name in os.listdir(target) if name.lower().endswith(".png")
                   and not name.startswith("."))
    except OSError:
        return 0


def origin(target: Path | None, path: Path) -> str:
    """Whether a picture in shots/ is still the one the tool fetched."""
    parts = path.name.split(".")
    label = key(parts[0], parts[1].lower()) if len(parts) == 3 else ""
    entry = load_document(target).get("shots", {}).get(label)
    try:
        if entry and entry.get("sha256") == hires.sha256_of(path):
            return provenance.COVER_LIBRETRO
    except OSError:
        pass
    return provenance.COVER_LIBRETRO_MODIFIED


# -- what to fetch ---------------------------------------------------------------

def plan(roms_root: Path, rom_paths: list[str], database: dict, card: Path,
         retry_missing: bool = False) -> list[Wanted]:
    """One Wanted per picture a retail game on the card can have and
    shots/ lacks: the title screen and the snap, per game code the
    database knows. The names to try: the dump's own when the database
    knows it by checksum, then every other name it files under that code.
    A picture the manifest records libretro as not having is left out
    unless `retry_missing`: asking for screenshots asks again, a
    remembered run does not."""
    target = folder(card)
    if target is None:
        return []
    known_missing = set() if retry_missing else set(load_document(target).get("missing", {}))
    index = identify.Index(database)
    lineages = kinds.Lineage(database)
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
        if not re.fullmatch(r"[A-Z0-9]{4}", code):
            continue
        entry, matched = index.identify(header)
        if entry is None or kinds.classify(rom_path, matched,
                                           lineage=lineages.of(rom_path, header, matched)) != kinds.RETAIL:
            continue
        names = wanted.setdefault(code, [])
        first = [entry.name] if matched == "crc" else []
        for name in first + by_serial.get(code, []):
            if name not in names:
                names.append(name)
        if matched == "crc" and names[0] != entry.name:
            names.remove(entry.name)
            names.insert(0, entry.name)
    out: list[Wanted] = []
    for code, names in sorted(wanted.items()):
        for slot in SLOTS:
            if key(code, slot) in known_missing or listing.lookup(target, file_name(code, slot)) is not None:
                continue
            out.append(Wanted(code, slot, names, target / file_name(code, slot)))
    return out


def fetch_files(wanted: list[Wanted], target: Path, progress_factory=None, cancel=None, log=None,
                root_url: str | None = None) -> Report:
    """Fetch every Wanted picture into shots/, verbatim, recording each in
    the manifest as it lands so a stop or a crash loses nothing already
    fetched. A picture under none of its names is reported missing; three
    connection failures in a row end the run as offline."""
    report = Report()
    if not wanted:
        return report
    document = load_document(target)
    shots, missing = document.get("shots", {}), document.get("missing", {})
    enabled = document.get("enabled", True)
    bar = progress_factory(len(wanted), "screenshots") if progress_factory else None
    consecutive_failures = 0
    for position, item in enumerate(wanted):
        if cancel is not None and cancel():
            report.stopped = True
            break
        label = key(item.code, item.slot)
        data, found_name, found_url = None, "", ""
        try:
            for name in item.names:
                found = hires.box_for(name, base_url(item.slot, root_url))
                if found is not None:
                    (data, found_url), found_name = found, name
                    break
            consecutive_failures = 0
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            report.failed.append(label)
            consecutive_failures += 1
            if log is not None:
                log(f"          {label}: {getattr(error, 'reason', error)}")
            if consecutive_failures >= GIVE_UP_AFTER:
                if log is not None:
                    log("          three connection failures in a row: giving up on the rest")
                report.failed.extend(key(other.code, other.slot) for other in wanted[position + 1:])
                break
            if bar is not None:
                bar.step(label)
            continue
        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if data is None:
            report.missing.append(label)
            missing[label] = stamp
        else:
            target.mkdir(parents=True, exist_ok=True)
            part = item.destination.with_name(item.destination.name + ".part")
            part.write_bytes(data)
            os.replace(part, item.destination)
            shots[label] = {"name": found_name, "url": found_url,
                            "sha256": hashlib.sha256(data).hexdigest(), "date": stamp}
            missing.pop(label, None)
            report.fetched += 1
        save_manifest(target, shots, missing, enabled)
        if bar is not None:
            bar.step(label)
    if bar is not None and not report.stopped:
        bar.done(f"shots:    {report.fetched} fetched from libretro"
                 + (f", {len(report.missing)} not there" if report.missing else "")
                 + (f", {len(report.failed)} not reached" if report.failed else ""))
    return report


def fetch_for_card(roms_root: Path, rom_paths: list[str], database_path: Path, card: Path,
                   progress_factory=None, cancel=None, log=None, asked: bool = True) -> Report:
    """plan() then fetch_files(), with the report in the tool's own words.
    `asked` false is the remembered run: the card has screenshots and
    keeps them complete, without asking libretro again for the ones it
    lacks. A stop between two pictures surfaces as Cancelled, like every
    other."""
    database = coverdb.load(database_path) if database_path.is_file() else {}
    wanted = plan(roms_root, rom_paths, database, card, retry_missing=asked)
    target = folder(card)
    where = target.relative_to(card).as_posix()
    if log is not None:
        how = "" if asked else " (the card has them; keeping them complete)"
        games = len({item.code for item in wanted})
        log(f"shots:    {len(wanted)} screenshot{'s' if len(wanted) != 1 else ''} of {games} "
            f"game{'s' if games != 1 else ''} to fetch from libretro (about 100 KB each){how}" if wanted
            else f"shots:    nothing to fetch; what libretro has for these games is in {where}/{how}")
    document = load_document(target)
    if not document.get("enabled"):
        # The choice is remembered before anything is fetched, so a run
        # that finds nothing, or no network, does not lose it.
        save_manifest(target, document.get("shots", {}), document.get("missing", {}))
    report = fetch_files(wanted, target, progress_factory, cancel, log)
    if report.stopped:
        raise Cancelled("stopped while fetching screenshots")
    if report.missing and log is not None:
        shown = ", ".join(report.missing[:8]) + (", ..." if len(report.missing) > 8 else "")
        log(f"          libretro has no picture for {len(report.missing)}: {shown}")
    return report


# -- which pictures each game gets ---------------------------------------------------

def find_own(index: custom_art.Index, card: Path, rom_path: str, slot: str) -> Path | None:
    """The owner's picture for one of a game's slots: `<ROM name>.<slot>`
    beside the ROM, then in sleekmenu/art/. `rom_path` is relative to the
    card."""
    stem = PurePosixPath(rom_path).stem
    beside = (card / rom_path).parent
    for place in (beside, custom_art.art_dir(card)):
        for suffix in custom_art.ART_SUFFIXES:
            found = index.lookup(place, f"{stem}.{slot}{suffix}")
            if found is not None:
                return found
    return None


def find_fetched(index: custom_art.Index, card: Path, code: str, slot: str) -> Path | None:
    if not re.fullmatch(r"[A-Za-z0-9]{4}", code or ""):
        return None
    return index.lookup(folder(card), file_name(code, slot))


@dataclass
class Plan:
    numbers: dict[str, int] = field(default_factory=dict)              # ROM path -> set number
    sets: dict[int, dict[str, Path]] = field(default_factory=dict)     # set number -> slot -> picture
    origins: dict[str, dict[str, str]] = field(default_factory=dict)   # ROM path -> slot -> provenance
    dropped: int = 0          # games past the packs' limit, given none
    own: int = 0              # games with at least one picture of the owner's

    def identities(self) -> dict[str, str]:
        """What each picture was made from, by its name in the packs: the
        next run keeps a picture whose identity is unchanged."""
        out = {}
        for number, pictures in self.sets.items():
            for slot, path in pictures.items():
                inner = metadata_repo.file_identity(path)
                if inner:
                    out[sprite_name(number, slot)] = f"{FORMAT}|{inner}"
        return out


def plan_sets(card: Path, games: list[dict]) -> Plan:
    """Each game's pictures, per slot: the owner's, else the fetched one
    for its game code when the game is retail (its kind as catalogued,
    the owner's correction included). `games` are catalog records: path
    relative to the card, code, kind. Games with the same pictures share a
    set; the sets are numbered from 1 in a fixed order, so a card that has
    not changed numbers them the same way twice."""
    index = custom_art.Index()
    target = folder(card)
    chosen: dict[str, dict[str, Path]] = {}
    plan = Plan()
    for game in games:
        rom_path = str(game.get("path", ""))
        code = str(game.get("code") or "")
        retail = (game.get("kind") or kinds.RETAIL) == kinds.RETAIL
        pictures: dict[str, Path] = {}
        origins: dict[str, str] = {}
        for slot in SLOTS:
            own = find_own(index, card, rom_path, slot)
            if own is not None:
                pictures[slot] = own
                origins[slot] = provenance.COVER_YOURS_ROM
                continue
            fetched = find_fetched(index, card, code, slot) if retail else None
            if fetched is not None:
                pictures[slot] = fetched
                origins[slot] = origin(target, fetched)
        if pictures:
            chosen[rom_path] = pictures
            plan.origins[rom_path] = origins
            if any(provenance.is_yours(label) for label in origins.values()):
                plan.own += 1
    keys = {rom_path: tuple(sorted((slot, str(path)) for slot, path in pictures.items()))
            for rom_path, pictures in chosen.items()}
    numbered: dict[tuple, int] = {}
    for set_key in sorted(set(keys.values())):
        if len(numbered) >= MAX_SETS:
            break
        numbered[set_key] = len(numbered) + 1
    for rom_path, set_key in keys.items():
        number = numbered.get(set_key)
        if number is None:
            plan.dropped += 1
            plan.origins.pop(rom_path, None)
            continue
        plan.numbers[rom_path] = number
        plan.sets[number] = {slot: Path(path) for slot, path in set_key}
    return plan


# -- the packs -------------------------------------------------------------------

def convert(path: Path) -> tuple[bytes, bytes]:
    """One picture as the two sprites the console draws: the thumbnail and
    the box view's. Decoded once."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise make_sprite.SpriteError("Pillow is required to convert images: pip install pillow") from exc
    try:
        with Image.open(path) as image:
            image.load()
            return (make_sprite.encode(make_sprite.fit_image(image, THUMB)),
                    make_sprite.encode(make_sprite.fit_image(image, CANVAS)))
    except OSError as exc:
        raise make_sprite.SpriteError(f"cannot read image {path}: {exc}") from exc


def build(planned: Plan, reuse: dict[str, tuple[bytes, bytes]] | None = None,
          progress=None) -> tuple[dict[str, bytes], dict[str, bytes], int, list[str]]:
    """The two packs' contents, name -> sprite: small and large. `reuse`
    maps a picture's name to what the last run made from the same file.
    Returns the two maps, how many pictures were converted, and the
    pictures that would not read -- left out, with the game keeping the
    rest of its set."""
    small: dict[str, bytes] = {}
    large: dict[str, bytes] = {}
    converted = 0
    unreadable: list[str] = []
    for number in sorted(planned.sets):
        for slot, path in sorted(planned.sets[number].items()):
            name = sprite_name(number, slot)
            kept = (reuse or {}).get(name)
            if kept is not None:
                small[name], large[name] = kept
            else:
                try:
                    small[name], large[name] = convert(path)
                    converted += 1
                except make_sprite.SpriteError:
                    unreadable.append(str(path))
            if progress is not None:
                progress.step(name)
    return small, large, converted, unreadable
