# SPDX-License-Identifier: AGPL-3.0-only
"""Cheat codes from libretro, against a stand-in server: which dumps get a
file, what lands in the card's folder and its manifest, and how a card
remembers that it asked."""

import contextlib
import io
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from tests.rom_fixtures import write_rom
from tests.test_fetch import Log, Server
from tests.test_sleekmenu_prep import stay_offline, write_collection
from tools import cheat_codes, coverdb, hires, sleekmenu_prep

ROOT = Path(__file__).resolve().parent.parent
DATABASE = coverdb.load(ROOT / "data" / "coverdb.csv")
FOLDER = "/cht/"
CHT = b'cheats = 1\n\ncheat0_desc = "Infinite Lives"\ncheat0_code = "8033B21D 0064"\ncheat0_enable = false\n'


def route(name: str) -> str:
    return FOLDER + urllib.parse.quote(hires.libretro_name(name) + ".cht")


def row(name: str) -> coverdb.Entry:
    return next(entry for entry in DATABASE.values() if entry.name == name)


class NameTests(unittest.TestCase):
    def test_a_file_is_asked_for_under_the_dumps_name_and_kept_under_its_checksum(self):
        self.assertEqual(cheat_codes.address("Super Mario 64 (USA)"),
                         cheat_codes.BASE_URL + "Super%20Mario%2064%20%28USA%29.cht")
        self.assertEqual(cheat_codes.address("Command & Conquer (USA)", "http://x/"),
                         "http://x/Command%20_%20Conquer%20%28USA%29.cht")
        self.assertIn("/cht/Nintendo%20-%20Nintendo%2064/", cheat_codes.BASE_URL)
        self.assertEqual(cheat_codes.file_name("635a2bff8b022326"), "635A2BFF8B022326.cht")
        self.assertEqual(cheat_codes.folder(Path("/card")), Path("/card/sleekmenu/cheats/libretro"))


class CardTests(unittest.TestCase):
    """A card with a dump the database knows by checksum, twice; a hack of
    a game it knows only by code; and a homebrew it does not know."""

    def setUp(self):
        stay_offline(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name) / "CARD"
        self.mario = row("Super Mario 64 (USA)")
        for where in ("ROMS/Super Mario 64 (USA).z64", "ROMS/Copies/mario.z64"):
            write_rom(self.card / where, int(self.mario.crc[:8], 16), int(self.mario.crc[8:], 16), game_code="SM")
        write_rom(self.card / "ROMS" / "Hacks" / "Wave Race Kaizo.z64", 0x33, 0x44, game_code="WR")
        write_rom(self.card / "ROMS" / "Homebrew" / "Flappy.z64", 3, 4, game_code="\0\0", country="\0")
        self.rom_paths = ["ROMS/Super Mario 64 (USA).z64", "ROMS/Copies/mario.z64",
                          "ROMS/Hacks/Wave Race Kaizo.z64", "ROMS/Homebrew/Flappy.z64"]
        self.folder = cheat_codes.folder(self.card)

    def tearDown(self):
        self.temporary.cleanup()

    def add_fzero(self) -> coverdb.Entry:
        fzero = row("F-Zero X (USA)")
        write_rom(self.card / "ROMS" / "F-Zero X (USA).z64", int(fzero.crc[:8], 16), int(fzero.crc[8:], 16),
                  game_code=fzero.serial[1:3])
        self.rom_paths.append("ROMS/F-Zero X (USA).z64")
        return fzero

    def test_the_plan_is_one_file_per_dump_the_database_knows_by_checksum(self):
        wanted = cheat_codes.plan(self.card, self.rom_paths, DATABASE, self.card)
        self.assertEqual([(w.crc, w.name) for w in wanted], [(self.mario.crc, "Super Mario 64 (USA)")],
                         "one for two copies of a dump; none for a hack, whose addresses are its own, "
                         "nor for a homebrew")
        self.assertEqual(wanted[0].destination, self.folder / f"{self.mario.crc}.cht")
        self.folder.mkdir(parents=True)
        (self.folder / f"{self.mario.crc.lower()}.cht").write_bytes(CHT)
        self.assertEqual(cheat_codes.plan(self.card, self.rom_paths, DATABASE, self.card), [],
                         "what is there is not fetched again, however the card spells it")

    def test_files_land_verbatim_with_a_manifest_and_an_absence_is_remembered(self):
        fzero = self.add_fzero()
        wanted = cheat_codes.plan(self.card, self.rom_paths, DATABASE, self.card)
        self.assertEqual([w.name for w in wanted], ["F-Zero X (USA)", "Super Mario 64 (USA)"])
        log = Log()
        with Server({route("Super Mario 64 (USA)"): (200, CHT)}) as server:
            report = cheat_codes.fetch_files(wanted, self.folder, log=log, base_url=server.url(FOLDER))
            self.assertEqual(server.requests, [route("F-Zero X (USA)"), route("Super Mario 64 (USA)")])
        self.assertEqual((report.fetched, report.missing, report.failed), (1, [fzero.crc], []))
        self.assertEqual((self.folder / f"{self.mario.crc}.cht").read_bytes(), CHT)
        self.assertEqual(cheat_codes.count(self.card), 1)
        manifest = json.loads((self.folder / cheat_codes.MANIFEST).read_text())
        self.assertEqual(manifest["files"][self.mario.crc]["name"], "Super Mario 64 (USA)")
        self.assertIn("sha256", manifest["files"][self.mario.crc])
        self.assertIn(fzero.crc, manifest["missing"])
        self.assertTrue(manifest["enabled"])
        self.assertEqual(cheat_codes.plan(self.card, self.rom_paths, DATABASE, self.card), [],
                         "a known absence is not asked about again")
        self.assertEqual([w.name for w in cheat_codes.plan(self.card, self.rom_paths, DATABASE, self.card,
                                                           retry_missing=True)], ["F-Zero X (USA)"])
        self.assertEqual(list(self.folder.glob("*.part")), [])

    def test_a_reply_that_is_not_a_cheat_file_counts_as_none(self):
        wanted = cheat_codes.plan(self.card, self.rom_paths, DATABASE, self.card)
        with Server({route("Super Mario 64 (USA)"): (200, b"<html>rate limited</html>")}) as server:
            report = cheat_codes.fetch_files(wanted, self.folder, base_url=server.url(FOLDER))
        self.assertEqual((report.fetched, report.missing), (0, [self.mario.crc]))
        self.assertFalse((self.folder / f"{self.mario.crc}.cht").exists())

    def test_offline_gives_up_after_three_failures_and_a_stop_is_honoured(self):
        with Server({}) as server:
            dead = server.url(FOLDER)
        wanted = [cheat_codes.Wanted(f"{n:016X}", f"Game {n}", self.folder / f"{n:016X}.cht") for n in range(1, 8)]
        log = Log()
        report = cheat_codes.fetch_files(wanted, self.folder, log=log, base_url=dead)
        self.assertEqual((report.fetched, len(report.failed)), (0, 7))
        self.assertIn("three connection failures in a row", log.text())
        with Server({route("Game 1"): (200, CHT)}) as server:
            report = cheat_codes.fetch_files(wanted, self.folder, cancel=lambda: True, base_url=server.url(FOLDER))
            self.assertEqual(server.requests, [])
        self.assertTrue(report.stopped)

    def test_a_card_remembers_that_it_asked_until_it_is_told_to_stop(self):
        self.assertFalse(cheat_codes.remembered(self.card))
        self.assertFalse(cheat_codes.remembered(None))
        self.assertFalse(cheat_codes.forget(self.card), "nothing to forget, and nothing written")
        self.assertFalse(self.folder.exists())
        cheat_codes.save_manifest(self.folder, {"A": {"name": "a"}}, {"B": "then"})
        self.assertTrue(cheat_codes.remembered(self.card))
        self.assertTrue(cheat_codes.forget(self.card))
        self.assertFalse(cheat_codes.remembered(self.card))
        kept = cheat_codes.load_document(self.folder)
        self.assertEqual((kept["files"], kept["missing"]), ({"A": {"name": "a"}}, {"B": "then"}),
                         "told to stop, the card keeps what it has")
        (self.folder / cheat_codes.MANIFEST).write_text("not json")
        self.assertFalse(cheat_codes.remembered(self.card))

    def test_a_run_fetches_when_asked_keeps_complete_after_and_stops_when_told(self):
        write_collection(self.card / "release-metadata.zip", "NSME", zipped=True)
        with Server({route("Super Mario 64 (USA)"): (200, CHT)}) as server, \
             mock.patch.object(cheat_codes, "BASE_URL", server.url(FOLDER)), \
             mock.patch.dict("os.environ", {"SLEEKMENU_NO_DOWNLOAD": ""}), \
             mock.patch.object(sleekmenu_prep.fetch, "release_addresses", lambda *a, **k: []), \
             contextlib.redirect_stdout(io.StringIO()):
            log, outcome = Log(), sleekmenu_prep.Outcome()
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card), log=log, fail=log)
            self.assertEqual(code, 0, log.text())
            self.assertEqual(server.requests, [], "a card that never asked for cheats is not given any")
            self.assertNotIn("cheats:", log.text())

            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, cheats=True), log=log, fail=log,
                                      outcome=outcome)
            self.assertEqual(code, 0, log.text())
            self.assertIn("cheats:   1 file to fetch from libretro", log.text())
            self.assertEqual(outcome.cheats_unreached, 0)
            self.assertEqual((self.folder / f"{self.mario.crc}.cht").read_bytes(), CHT)

            # a run that says nothing keeps the card complete: the game added
            # since is asked about, the one already there is not
            self.add_fzero()
            server.requests.clear()
            log = Log()
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card), log=log, fail=log)
            self.assertEqual(code, 0, log.text())
            self.assertIn("keeping them complete", log.text())
            self.assertEqual(server.requests, [route("F-Zero X (USA)")])
            server.requests.clear()
            sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card), log=log, fail=log)
            self.assertEqual(server.requests, [], "nor is a known absence asked about again")

            # told to stop: nothing fetched from then on, and the files stay
            log = Log()
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, cheats=False), log=log, fail=log)
            self.assertEqual(code, 0, log.text())
            self.assertIn("no longer fetched; the files already on the card stay", log.text())
            self.assertTrue((self.folder / f"{self.mario.crc}.cht").is_file())
            log = Log()
            sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card), log=log, fail=log)
            self.assertNotIn("cheats:", log.text())
            self.assertEqual(server.requests, [])

    def test_downloads_off_says_so_and_a_dry_run_fetches_nothing(self):
        write_collection(self.card / "release-metadata.zip", "NSME", zipped=True)
        with contextlib.redirect_stdout(io.StringIO()):
            log = Log()
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, cheats=True, no_download=True),
                                      log=log, fail=log)
            self.assertEqual(code, 0, log.text())
            self.assertIn("cheats:   not fetched; downloads are off", log.text())
            log = Log()
            sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, cheats=True, dry_run=True), log=log, fail=log)
            self.assertNotIn("cheats:", log.text())
        self.assertFalse(self.folder.exists())

    def test_the_command_line_takes_the_choice(self):
        with mock.patch.object(sleekmenu_prep, "run", return_value=0) as run:
            sleekmenu_prep.main(["--card", str(self.card), "--cheats"])
            self.assertIs(run.call_args.args[0].cheats, True)
            sleekmenu_prep.main(["--card", str(self.card), "--no-cheats"])
            self.assertIs(run.call_args.args[0].cheats, False)
            sleekmenu_prep.main(["--card", str(self.card)])
            self.assertIsNone(run.call_args.args[0].cheats)


if __name__ == "__main__":
    unittest.main()
