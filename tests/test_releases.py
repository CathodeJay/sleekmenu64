# SPDX-License-Identifier: AGPL-3.0-only
"""SleekMenu and the Game Catalog Manager kept in step, against a stand-in
release page: which SleekMenu a card has, when the run replaces it and when
it leaves it alone, and how a newer Game Catalog Manager is found and
offered."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.rom_fixtures import write_rom
from tests.test_direct_boot import stock_os
from tests.test_fetch import Log, Server
from tests.test_sleekmenu_prep import stay_offline, write_collection
from tools import card_layout, direct_boot, releases, sleekmenu_prep, version


def sleekmenu(release: str = version.VERSION, extra: bytes = b"") -> bytes:
    """A file shaped like SleekMenu64.z64: the z64 magic, the title the
    header carries from 2.1 on ("" for the bare title of before), a body."""
    title = (b"SleekMenu 64" + (b" " + release.encode() if release else b"")).ljust(20, b"\0")
    return releases.Z64_MAGIC + bytes(0x1C) + title + bytes(0x1000) + extra


class VersionTests(unittest.TestCase):
    def test_a_release_number_compares_as_numbers(self):
        self.assertEqual(releases.parse("v2.10.0"), (2, 10, 0))
        self.assertIsNone(releases.parse("2.1"))
        self.assertTrue(releases.newer("2.10.0", "2.9.9"))
        self.assertFalse(releases.newer("2.1.0", "2.1.0"))
        self.assertFalse(releases.newer("nonsense", "2.1.0"))

    def test_the_rom_says_which_release_it_is(self):
        self.assertEqual(releases.rom_version(sleekmenu("2.1.0")), (True, "2.1.0"))
        self.assertEqual(releases.rom_version(sleekmenu("")), (True, ""), "a build no release page had")
        self.assertEqual(releases.rom_version(sleekmenu("").replace(b"SleekMenu", b"OtherMenu")), (False, ""))
        self.assertEqual(releases.rom_version(b"\x37\x80\x40\x12" + sleekmenu()[4:]), (False, ""),
                         "a byte-swapped file is not the release's")
        for digest, release in releases.EARLIER.items():
            self.assertRegex(digest, r"\A[0-9a-f]{64}\Z")
            self.assertTrue(releases.newer(version.VERSION, release))

    def test_the_title_still_starts_as_older_tools_compare_it(self):
        """A tool from before 2.1 knows the browser by the first twelve
        bytes of its title, and must go on knowing it."""
        rom = sleekmenu("2.1.0")
        self.assertEqual(rom[direct_boot.TITLE_AT:direct_boot.TITLE_AT + 12], direct_boot.BROWSER_TITLE)
        self.assertLessEqual(len(f"SleekMenu 64 {version.VERSION}"), releases.TITLE_LENGTH)
        makefile = (Path(__file__).resolve().parent.parent / "Makefile.n64").read_text(encoding="utf-8")
        self.assertIn('N64_ROM_TITLE = "SleekMenu 64 $(SM_VERSION)"', makefile)

    def test_the_file_for_this_computer(self):
        asset = releases.asset_for_this_computer
        self.assertEqual(asset(True, "darwin", "arm64"), "SleekMenu-Catalog-Manager-mac-arm64.zip")
        self.assertEqual(asset(True, "darwin", "x86_64"), "SleekMenu-Catalog-Manager-mac-intel.zip")
        self.assertEqual(asset(True, "win32", "AMD64"), "SleekMenu-Catalog-Manager-windows.exe")
        self.assertEqual(asset(True, "linux", "x86_64"), "SleekMenu-Catalog-Manager-linux")
        self.assertEqual(asset(False, "darwin", "arm64", "/Volumes/CARD/sleekmenu-catalog-manager.pyz"),
                         "sleekmenu-catalog-manager.pyz")
        self.assertEqual(asset(False, "linux", "x86_64", "tools/sleekmenu_gui.py"), "")
        self.assertEqual(releases.download_url("2.2.0", "sleekmenu-catalog-manager.pyz"),
                         releases.RELEASES_URL + "/download/v2.2.0/sleekmenu-catalog-manager.pyz")
        self.assertEqual(releases.download_url("2.2.0", ""), releases.RELEASES_URL + "/tag/v2.2.0",
                         "from a checkout: the release's page")


class CardTests(unittest.TestCase):
    def setUp(self):
        stay_offline(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.card = Path(self.temporary.name) / "CARD"
        self.card.mkdir()
        self.rom = self.card / card_layout.BROWSER_ROM
        releases._read.clear()

    def state(self):
        return releases.card_browser(self.card)

    def test_which_sleekmenu_a_card_has(self):
        self.assertEqual(self.state().state, releases.MISSING)
        cases = ((sleekmenu(version.VERSION), releases.CURRENT, version.VERSION),
                 (sleekmenu("1.9.0"), releases.OLDER, "1.9.0"),
                 (sleekmenu("99.0.0"), releases.NEWER, "99.0.0"),
                 (sleekmenu("", b"my own"), releases.OWN, ""),
                 (b"not a rom" * 100, releases.OTHER, ""))
        for data, expected, found in cases:
            with self.subTest(expected=expected):
                self.rom.write_bytes(data)
                self.assertEqual((self.state().state, self.state().version), (expected, found))
        # however the card spells the name
        self.rom.unlink()
        (self.card / "sleekmenu64.Z64").write_bytes(sleekmenu("1.9.0"))
        self.assertEqual(self.state().state, releases.OLDER)

    def test_a_release_from_before_the_title_carried_it_is_known_by_its_fingerprint(self):
        old = sleekmenu("", b"2.0")
        with mock.patch.dict(releases.EARLIER, {__import__("hashlib").sha256(old).hexdigest(): "2.0.0"}):
            self.rom.write_bytes(old)
            self.assertEqual((self.state().state, self.state().version), (releases.OLDER, "2.0.0"))

    def test_an_older_one_or_none_is_replaced_by_this_release_and_nothing_else_is(self):
        mine = sleekmenu(version.VERSION, b"release")
        route = f"/download/v{version.VERSION}/{card_layout.BROWSER_ROM}"
        with Server({route: (200, mine)}) as server, \
             mock.patch.object(releases, "RELEASES_URL", server.url("")):
            # none: put there
            log = Log()
            done = releases.update_card(self.card, log)
            self.assertEqual((done.browser.state, done.failed), (releases.CURRENT, False))
            self.assertEqual(self.rom.read_bytes(), mine)
            self.assertIn(f"{version.VERSION} put on the card", log.text())
            # an older one: replaced, under the name the card spells it in
            self.rom.unlink()
            spelled = self.card / "sleekmenu64.z64"
            spelled.write_bytes(sleekmenu("1.9.0"))
            log = Log()
            releases.update_card(self.card, log)
            self.assertEqual([p.name for p in self.card.iterdir()], ["sleekmenu64.z64"])
            self.assertEqual(spelled.read_bytes(), mine)
            self.assertIn("in place of 1.9.0", log.text())
            self.assertFalse(list(self.card.glob("*.part")))
            # this release, an own build, a newer one, another file: left alone, nothing asked
            server.requests.clear()
            for data, said in ((sleekmenu(version.VERSION, b"dev"), ""),
                               (sleekmenu("", b"own"), "a build of its own"),
                               (sleekmenu("99.0.0"), "newer than this Game Catalog Manager"),
                               (b"homebrew" * 100, "is not SleekMenu")):
                with self.subTest(said=said):
                    spelled.write_bytes(data)
                    log = Log()
                    done = releases.update_card(self.card, log)
                    self.assertEqual(spelled.read_bytes(), data)
                    self.assertFalse(done.failed)
                    self.assertIn(said, log.text())
            self.assertEqual(server.requests, [])
            # downloads off: said, and nothing asked
            spelled.write_bytes(sleekmenu("1.9.0"))
            log = Log()
            done = releases.update_card(self.card, log, offline=True)
            self.assertFalse(done.failed, "a choice, not a failure")
            self.assertIn("downloads are off", log.text())
            self.assertEqual(server.requests, [])

    def test_a_release_page_without_the_rom_or_with_the_wrong_one_changes_nothing(self):
        self.rom.write_bytes(sleekmenu("1.9.0"))
        route = f"/download/v{version.VERSION}/{card_layout.BROWSER_ROM}"
        for routes, said in (({}, "is not on its release page"),
                             ({route: (200, sleekmenu("1.9.5"))}, f"not SleekMenu {version.VERSION}"),
                             ({route: (200, b"<html>nope</html>")}, f"not SleekMenu {version.VERSION}")):
            with self.subTest(said=said), Server(routes) as server, \
                 mock.patch.object(releases, "RELEASES_URL", server.url("")):
                log = Log()
                done = releases.update_card(self.card, log)
                self.assertTrue(done.failed)
                self.assertIn(said, log.text())
                self.assertEqual(self.rom.read_bytes(), sleekmenu("1.9.0"))

    def test_a_run_puts_it_there_before_the_x7_copy_is_brought_into_step(self):
        (self.card / "ED64").mkdir()
        (self.card / "ED64" / "OS64.v64").write_bytes(stock_os())
        old = sleekmenu("1.9.0")
        self.rom.write_bytes(old)
        (self.card / "ED64" / "autoexec.v64").write_bytes(old)
        write_rom(self.card / "ROMS" / "Game.z64", 1, 2, game_code="WR")
        write_collection(self.card / "release-metadata.zip", "NWRE", zipped=True)
        mine = sleekmenu(version.VERSION, b"release")
        route = f"/download/v{version.VERSION}/{card_layout.BROWSER_ROM}"
        direct_boot._facts.clear()
        with Server({route: (200, mine)}) as server, \
             mock.patch.object(releases, "RELEASES_URL", server.url("")), \
             mock.patch.dict("os.environ", {"SLEEKMENU_NO_DOWNLOAD": ""}), \
             mock.patch.object(sleekmenu_prep.fetch, "release_addresses", lambda *a, **k: []), \
             contextlib.redirect_stdout(io.StringIO()):
            log = Log()
            outcome = sleekmenu_prep.Outcome()
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, browser=True), log=log, fail=log,
                                      outcome=outcome)
        self.assertEqual(code, 0, log.text())
        self.assertFalse(outcome.browser_unreached)
        self.assertEqual(self.rom.read_bytes(), mine)
        self.assertEqual((self.card / "ED64" / "autoexec.v64").read_bytes(), mine, "the X7's copy follows")
        # and a run not asked to leaves the card's as it is
        self.rom.write_bytes(old)
        with contextlib.redirect_stdout(io.StringIO()):
            sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card), log=Log(), fail=Log())
        self.assertEqual(self.rom.read_bytes(), old)

    def test_the_command_line_keeps_it_up_to_date_unless_told(self):
        seen = []
        with mock.patch.object(sleekmenu_prep, "run", lambda options, **_k: seen.append(options.browser) or 0):
            sleekmenu_prep.main(["--card", str(self.card)])
            sleekmenu_prep.main(["--card", str(self.card), "--keep-browser"])
        self.assertEqual(seen, [True, False])


class NewerToolTests(unittest.TestCase):
    def test_the_newest_release_from_the_api_or_from_where_latest_leads(self):
        with Server({"/api": (200, json.dumps({"tag_name": "v9.1.0"}).encode()),
                     "/releases/tag/v9.2.0": (200, b"<html></html>")}) as server:
            self.assertEqual(releases.latest_release(server.url("/api"), server.url("/none")), "9.1.0")
            self.assertEqual(releases.latest_release(server.url("/none"), server.url("/releases/tag/v9.2.0")),
                             "9.2.0", "the API refused: the page the browser lands on")
            self.assertIsNone(releases.latest_release(server.url("/none"), server.url("/none")))
        self.assertEqual(releases.newer_tool("99.0.0"), "99.0.0")
        self.assertIsNone(releases.newer_tool(version.VERSION))
        self.assertIsNone(releases.newer_tool("1.0.0"))


if __name__ == "__main__":
    unittest.main()
