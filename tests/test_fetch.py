# SPDX-License-Identifier: AGPL-3.0-only
"""Fetching the collection onto the card, against a local stand-in for
GitHub. The real addresses are never touched by a test: every one is
pointed at a server in this process that serves what the test says.
"""

import contextlib
import http.server
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.rom_fixtures import write_rom
from tests.test_sleekmenu_prep import write_collection
from tools import fetch, sleekmenu_prep


class Server:
    """Serves a dict of path -> (status, bytes). Anything else is a 404."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.requests: list[str] = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                server.requests.append(self.path)
                status, body = server.routes.get(self.path, (404, b"Not Found"))
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client stopped reading: the cancel case

            def log_message(self, *_args):
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"


class Log:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)

    def text(self):
        return "\n".join(self.lines)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name) / "CARD"
        self.card.mkdir()
        self.zip_bytes = write_collection(Path(self.temporary.name) / "src.zip", "NWRE", zipped=True).read_bytes()

    def tearDown(self):
        self.temporary.cleanup()

    def test_a_download_lands_through_a_part_file_and_reports_progress(self):
        steps = []

        class Bar:
            def __init__(self, total, label):
                self.total, self.label = total, label
                steps.append(("start", label, total))

            def step(self, detail="", n=1):
                steps.append(("step", detail))

            def done(self, summary=""):
                steps.append(("done", summary))

        with Server({"/release-metadata.zip": (200, self.zip_bytes)}) as server:
            received = fetch.download(server.url("/release-metadata.zip"), self.card / "release-metadata.zip",
                                      progress_factory=Bar)
        self.assertEqual(received, len(self.zip_bytes))
        self.assertEqual((self.card / "release-metadata.zip").read_bytes(), self.zip_bytes)
        self.assertFalse((self.card / "release-metadata.zip.part").exists())
        self.assertEqual(steps[0], ("start", "download", 1))
        self.assertEqual(steps[-1][0], "done")
        self.assertIn(" of ", steps[1][1])

    def test_a_missing_file_is_an_error_with_nothing_left_behind(self):
        with Server({}) as server:
            with self.assertRaises(fetch.FetchError) as caught:
                fetch.download(server.url("/gone.zip"), self.card / "gone.zip")
        self.assertIn("HTTP 404", str(caught.exception))
        self.assertEqual(list(self.card.iterdir()), [])

    def test_a_server_that_is_not_there_is_an_error_not_a_hang(self):
        with Server({}) as server:
            url = server.url("/x.zip")
        with self.assertRaises(fetch.FetchError):
            fetch.download(url, self.card / "x.zip")

    def test_a_cancel_between_pieces_stops_and_cleans_up(self):
        big = self.zip_bytes + bytes(fetch.CHUNK * 3)
        with Server({"/big.zip": (200, big)}) as server:
            with self.assertRaises(fetch.Cancelled):
                fetch.download(server.url("/big.zip"), self.card / "big.zip", cancel=lambda: True)
        self.assertEqual(list(self.card.iterdir()), [])


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name) / "CARD"
        self.card.mkdir()
        self.zip_bytes = write_collection(Path(self.temporary.name) / "src.zip", "NWRE", zipped=True).read_bytes()

    def tearDown(self):
        self.temporary.cleanup()

    def test_the_addresses_are_latest_then_the_api_then_the_pinned_one(self):
        listing = [{"tag_name": "v0.2.0", "prerelease": True,
                    "assets": [{"name": "release-metadata.zip",
                                "browser_download_url": "http://example.test/v0.2.0/release-metadata.zip"}]}]
        with Server({"/api": (200, json.dumps(listing).encode())}) as server:
            addresses = fetch.release_addresses(api_url=server.url("/api"), latest_url="http://example.test/latest",
                                                pinned_url="http://example.test/pinned")
        self.assertEqual(addresses, ["http://example.test/latest",
                                     "http://example.test/v0.2.0/release-metadata.zip",
                                     "http://example.test/pinned"])
        # An API that will not answer costs one address, not the download.
        with Server({}) as server:
            addresses = fetch.release_addresses(api_url=server.url("/api"), latest_url="L", pinned_url="P")
        self.assertEqual(addresses, ["L", "P"])

    def test_the_first_address_that_answers_with_a_real_collection_wins(self):
        log = Log()
        with Server({"/second.zip": (200, b"PK not really a zip"),
                     "/third.zip": (200, self.zip_bytes)}) as server:
            fetched = fetch.collection(self.card, log=log, addresses=[
                server.url("/first.zip"), server.url("/second.zip"), server.url("/third.zip")])
            self.assertEqual(fetched.url, server.url("/third.zip"))
            self.assertEqual(server.requests, ["/first.zip", "/second.zip", "/third.zip"])
        self.assertEqual((self.card / "release-metadata.zip").read_bytes(), self.zip_bytes)
        self.assertIn("HTTP 404", log.text())
        self.assertIn("not a collection", log.text())

    def test_no_address_working_is_one_error_and_a_clean_card(self):
        with Server({}) as server:
            with self.assertRaises(fetch.FetchError):
                fetch.collection(self.card, addresses=[server.url("/a.zip"), server.url("/b.zip")])
        self.assertEqual(list(self.card.iterdir()), [])


class RunTests(unittest.TestCase):
    """The run fetches the collection when the card lacks it, and keeps its
    hands off the network when told to or when there are no games."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name) / "CARD"
        write_rom(self.card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
        self.zip_bytes = write_collection(Path(self.temporary.name) / "src.zip", "NWRE", zipped=True).read_bytes()
        self.environment = mock.patch.dict(os.environ, {fetch.OFFLINE_VARIABLE: ""})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def run_with(self, addresses, **options):
        log = Log()
        with mock.patch.object(fetch, "release_addresses", lambda *a, **k: addresses), \
             contextlib.redirect_stdout(io.StringIO()):
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, **options), log=log, fail=log)
        return code, log.text()

    def test_a_card_without_the_zip_gets_it_and_its_covers(self):
        with Server({"/release-metadata.zip": (200, self.zip_bytes)}) as server:
            code, text = self.run_with([server.url("/release-metadata.zip")])
        self.assertEqual(code, 0, text)
        self.assertIn("fetching release-metadata.zip", text)
        self.assertTrue((self.card / "release-metadata.zip").is_file())
        self.assertTrue((self.card / "sleekmenu" / "covers.pak").is_file())
        # and a second run leaves the zip alone
        with Server({}) as server:
            code, text = self.run_with([server.url("/release-metadata.zip")])
            self.assertEqual(server.requests, [])
        self.assertEqual(code, 0, text)
        self.assertNotIn("fetching", text)

    def test_offline_means_the_link_and_a_card_without_covers(self):
        with Server({}) as server:
            code, text = self.run_with([server.url("/release-metadata.zip")])
        self.assertEqual(code, 0, text)
        self.assertIn("could not fetch it", text)
        self.assertIn("github.com/n64-tools/n64-flashcart-menu-metadata/releases", text)
        self.assertTrue((self.card / "sleekmenu" / "catalog.ebc").is_file())
        self.assertFalse((self.card / "sleekmenu" / "covers.pak").exists())
        self.assertFalse((self.card / "release-metadata.zip").exists())

    def test_no_download_and_the_environment_both_keep_it_off_the_network(self):
        with Server({"/release-metadata.zip": (200, self.zip_bytes)}) as server:
            code, text = self.run_with([server.url("/release-metadata.zip")], no_download=True)
            self.assertEqual(server.requests, [])
            with mock.patch.dict(os.environ, {fetch.OFFLINE_VARIABLE: "1"}):
                code, text = self.run_with([server.url("/release-metadata.zip")])
            self.assertEqual(server.requests, [])
        self.assertEqual(code, 0, text)
        self.assertNotIn("fetching", text)
        self.assertIn("download release-metadata.zip from", text)

    def test_a_dry_run_and_a_card_with_no_games_fetch_nothing(self):
        with Server({"/release-metadata.zip": (200, self.zip_bytes)}) as server:
            self.run_with([server.url("/release-metadata.zip")], dry_run=True)
            for rom in (self.card / "ROMS").iterdir():
                rom.unlink()
            self.run_with([server.url("/release-metadata.zip")])
            self.assertEqual(server.requests, [])

    def test_a_cancel_stops_the_run_with_its_own_code(self):
        big = self.zip_bytes + bytes(fetch.CHUNK * 2)
        log = Log()
        with Server({"/release-metadata.zip": (200, big)}) as server, \
             mock.patch.object(fetch, "release_addresses", lambda *a, **k: [server.url("/release-metadata.zip")]), \
             contextlib.redirect_stdout(io.StringIO()):
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card), log=log, fail=log,
                                      cancel=lambda: True)
        self.assertEqual(code, 3)
        self.assertIn("stopped", log.text())
        self.assertFalse((self.card / "release-metadata.zip").exists())
        self.assertFalse((self.card / "release-metadata.zip.part").exists())


if __name__ == "__main__":
    unittest.main()
