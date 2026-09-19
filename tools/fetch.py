# SPDX-License-Identifier: AGPL-3.0-only
"""Fetching the box-art collection onto the card.

The collection is 52 MB on the n64-flashcart-menu-metadata releases page,
and the first thing a new card is missing. The tool used to point at the
page and stop; now it fetches the zip onto the card itself, says so in its
report, and falls back to pointing at the page when it cannot. Nothing is
fetched anywhere but onto the card, and nothing on the card is overwritten:
a zip already there is used as it is.

Three addresses are tried in order, because GitHub's stable
`releases/latest/download/` address answers only for a release that is not
marked pre-release, which the collection's may be: the stable address, then
the newest release the API lists that carries the file, then the release
this was written against. The download lands in a `.part` file beside its
destination and is renamed into place only once the zip has been opened and
found to hold boxes, so an interrupted or broken download never leaves a
file the tool would later mistake for the collection.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from tools import metadata_repo
from tools.progress import Cancelled

REPOSITORY = "n64-tools/n64-flashcart-menu-metadata"
ASSET = metadata_repo.RELEASE_ZIP_NAME
LATEST_URL = f"https://github.com/{REPOSITORY}/releases/latest/download/{ASSET}"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=10"
PINNED_URL = f"https://github.com/{REPOSITORY}/releases/download/v0.1.0/{ASSET}"
USER_AGENT = "sleekmenu-prep (+https://github.com/CathodeJay/sleekmenu64)"
CHUNK = 256 * 1024
TIMEOUT = 30
#: How the tool is told to stay offline without a flag: CI, and anyone who
#: would rather it never reached out.
OFFLINE_VARIABLE = "SLEEKMENU_NO_DOWNLOAD"


class FetchError(Exception):
    """An address that did not deliver the collection. Cancelled is not one
    of these: a stop is answered, not reported as a failed address."""


@dataclass(frozen=True)
class Fetched:
    path: Path
    url: str
    bytes: int


def offline_by_request() -> bool:
    return bool(os.environ.get(OFFLINE_VARIABLE))


def open_url(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=TIMEOUT)


def release_addresses(api_url: str = API_URL, latest_url: str = LATEST_URL,
                      pinned_url: str = PINNED_URL) -> list[str]:
    """The addresses worth trying, best first. The API is asked once, and
    its answer is a list of releases newest first; the first that carries
    the file is taken, pre-release or not. An API that will not answer
    (offline, rate-limited) costs one address, not the download."""
    addresses = [latest_url]
    try:
        with open_url(api_url) as response:
            releases = json.loads(response.read().decode("utf-8"))
        for release in releases if isinstance(releases, list) else []:
            for asset in release.get("assets", []):
                if asset.get("name") == ASSET and asset.get("browser_download_url"):
                    addresses.append(asset["browser_download_url"])
                    break
            else:
                continue
            break
    except (urllib.error.URLError, OSError, ValueError):
        pass
    addresses.append(pinned_url)
    return list(dict.fromkeys(addresses))


def download(url: str, destination: Path, progress_factory=None, cancel=None,
             label: str = "download") -> int:
    """`url` into `destination` by way of `destination.part`. Progress is
    counted in 256 KiB pieces with the megabytes so far as the detail;
    `cancel()` true between two pieces stops with Cancelled. Whatever
    interrupts it -- an address that fails, a stop, Ctrl-C -- no file is
    left behind. Returns the byte count."""
    part = destination.with_name(destination.name + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    complete = False
    try:
        with open_url(url) as response:
            total = int(response.headers.get("Content-Length") or 0)
            bar = progress_factory(max(1, (total + CHUNK - 1) // CHUNK), label) if progress_factory else None
            received = 0
            with part.open("wb") as out:
                while True:
                    if cancel is not None and cancel():
                        raise Cancelled("stopped while fetching")
                    piece = response.read(CHUNK)
                    if not piece:
                        break
                    out.write(piece)
                    received += len(piece)
                    if bar is not None:
                        bar.step(f"{received / 1048576:.1f} of {total / 1048576:.1f} MB" if total
                                 else f"{received / 1048576:.1f} MB")
            if total and received != total:
                raise FetchError(f"the download stopped at {received} of {total} bytes")
            if bar is not None:
                bar.done(f"{label}: {received / 1048576:.1f} MB")
        complete = True
    except urllib.error.HTTPError as error:
        raise FetchError(f"{url}: HTTP {error.code}") from error
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise FetchError(f"{url}: {getattr(error, 'reason', error)}") from error
    finally:
        if not complete:
            _discard(part)
    os.replace(part, destination)
    return received


def _discard(part: Path) -> None:
    try:
        part.unlink()
    except OSError:
        pass


def collection(card: Path, progress_factory=None, cancel=None, log=None,
               addresses: list[str] | None = None) -> Fetched:
    """The collection onto the card root, tried from each address in turn
    and kept only once it opens as a collection with boxes in it. Raises
    FetchError with the last reason when none worked; a stop passes
    through as Cancelled."""
    destination = card / ASSET
    last = "no address to try"
    for url in addresses if addresses is not None else release_addresses():
        try:
            received = download(url, destination, progress_factory, cancel, label="fetching")
        except FetchError as error:
            last = str(error)
            if log is not None:
                log(f"          {error}")
            continue
        try:
            with metadata_repo.MetadataRepo.open(destination) as repo:
                boxes = repo.art_count()
        except (metadata_repo.RepoError, OSError) as error:
            _discard(destination)
            last = f"{url}: not a collection ({error})"
            if log is not None:
                log(f"          {last}")
            continue
        if not boxes:
            _discard(destination)
            last = f"{url}: the zip holds no boxes"
            continue
        return Fetched(destination, url, received)
    raise FetchError(last)
