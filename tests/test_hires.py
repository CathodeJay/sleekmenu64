# SPDX-License-Identifier: AGPL-3.0-only
"""High-resolution boxes from libretro, against a stand-in server: which
codes are fetched under which names, what lands in hires/ and its
manifest, and how the cover plan and the catalog take them."""

import contextlib
import io
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from PIL import Image

from tests.rom_fixtures import write_rom
from tests.test_custom_art import picture
from tests.test_fetch import Log, Server
from tests.test_sleekmenu_prep import stay_offline, write_collection
from tools import card_catalog, coverdb, custom_art, hires, pack_covers, provenance, sleekmenu_prep

ROOT = Path(__file__).resolve().parent.parent
DATABASE = coverdb.load(ROOT / "data" / "coverdb.csv")


def box_png(color=(20, 160, 60, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (512, 357), color).save(buffer, format="PNG")
    return buffer.getvalue()


def route(name: str) -> str:
    return "/Named_Boxarts/" + urllib.parse.quote(hires.libretro_name(name) + ".png")


def row(name: str) -> coverdb.Entry:
    return next(entry for entry in DATABASE.values() if entry.name == name)


class NameTests(unittest.TestCase):
    def test_libretros_forbidden_characters_become_underscores(self):
        self.assertEqual(hires.libretro_name("Command & Conquer (USA)"), "Command _ Conquer (USA)")
        self.assertEqual(hires.libretro_name("Rayman 2 - The Great Escape (USA)"),
                         "Rayman 2 - The Great Escape (USA)")
        self.assertEqual(hires.libretro_name('A: B/C?D*E"F'), "A_ B_C_D_E_F")

    def test_the_address_is_the_file_under_the_named_boxarts_folder(self):
        self.assertEqual(hires.address("Super Mario 64 (USA)"),
                         hires.BASE_URL + "Super%20Mario%2064%20%28USA%29.png")
        self.assertEqual(hires.address("Command & Conquer (USA)", "http://x/"),
                         "http://x/Command%20_%20Conquer%20%28USA%29.png")


class CardTests(unittest.TestCase):
    """A card with a dump the database knows by CRC, a hack of another game
    it knows only by code, and a homebrew it does not know at all."""

    def setUp(self):
        stay_offline(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name) / "CARD"
        mario = row("Super Mario 64 (USA)")
        write_rom(self.card / "ROMS" / "Super Mario 64 (USA).z64",
                  int(mario.crc[:8], 16), int(mario.crc[8:], 16), game_code="SM")
        write_rom(self.card / "ROMS" / "Hacks" / "Wave Race Kaizo.z64", 0x33, 0x44, game_code="WR")
        write_rom(self.card / "ROMS" / "Homebrew" / "Flappy.z64", 3, 4, game_code="\0\0", country="\0")
        self.art = custom_art.art_dir(self.card)
        self.hires = hires.folder(self.art)
        self.rom_paths = ["ROMS/Super Mario 64 (USA).z64", "ROMS/Hacks/Wave Race Kaizo.z64",
                          "ROMS/Homebrew/Flappy.z64"]

    def tearDown(self):
        self.temporary.cleanup()

    def test_the_plan_is_one_box_per_known_code_with_the_dumps_own_name_first(self):
        wanted = hires.plan(self.card, self.rom_paths, DATABASE, self.art)
        self.assertEqual([w.code for w in wanted], ["NSME", "NWRE"])
        self.assertEqual(wanted[0].names, ["Super Mario 64 (USA)"])
        self.assertEqual(wanted[0].destination, self.hires / "NSME.png")
        # the hack is known only by code: every name under that code, in database order
        self.assertEqual(wanted[1].names[0], "Wave Race 64 - Kawasaki Jet Ski (USA)")
        self.assertIn("Wave Race 64 - Kawasaki Jet Ski (USA) (Rev 1)", wanted[1].names)
        # a box already there is not planned again
        self.hires.mkdir(parents=True)
        (self.hires / "nsme.png").write_bytes(box_png())
        self.assertEqual([w.code for w in hires.plan(self.card, self.rom_paths, DATABASE, self.art)], ["NWRE"])

    def test_boxes_land_verbatim_with_a_manifest_and_a_missing_one_is_reported(self):
        mario_png, wave_png = box_png(), box_png((200, 30, 30, 255))
        routes = {route("Super Mario 64 (USA)"): (200, mario_png),
                  # the first Wave Race name is not there; the revision is
                  route("Wave Race 64 - Kawasaki Jet Ski (USA) (Rev 1)"): (200, wave_png)}
        wanted = hires.plan(self.card, self.rom_paths, DATABASE, self.art)
        log = Log()
        with Server(routes) as server:
            report = hires.fetch_boxes(wanted, self.hires, log=log, base_url=server.url("/Named_Boxarts/"))
            self.assertEqual((report.fetched, report.missing, report.failed), (2, [], []))
            requested = server.requests
        self.assertEqual((self.hires / "NSME.png").read_bytes(), mario_png)
        self.assertEqual((self.hires / "NWRE.png").read_bytes(), wave_png)
        self.assertEqual(requested[0], route("Super Mario 64 (USA)"))
        self.assertEqual(requested[1], route("Wave Race 64 - Kawasaki Jet Ski (USA)"), "tried first, 404")
        manifest = json.loads((self.hires / hires.MANIFEST).read_text())
        self.assertEqual(manifest["boxes"]["NWRE"]["name"], "Wave Race 64 - Kawasaki Jet Ski (USA) (Rev 1)")
        self.assertEqual(len(manifest["boxes"]["NSME"]["sha256"]), 64)
        self.assertFalse(list(self.hires.glob("*.part")))
        # what the tool fetched is libretro's; a byte changed is not
        self.assertEqual(hires.origin(self.hires, self.hires / "NSME.png"), provenance.COVER_LIBRETRO)
        (self.hires / "NSME.png").write_bytes(mario_png + b"\0")
        self.assertEqual(hires.origin(self.hires, self.hires / "NSME.png"), provenance.COVER_LIBRETRO_MODIFIED)
        # a code libretro has nothing for
        with Server({}) as server:
            report = hires.fetch_boxes([hires.Wanted("NZLE", ["Zelda (USA)"], self.hires / "NZLE.png")],
                                       self.hires, base_url=server.url("/Named_Boxarts/"))
        self.assertEqual(report.missing, ["NZLE"])
        self.assertFalse((self.hires / "NZLE.png").exists())

    def test_offline_gives_up_after_three_failures_and_a_stop_is_honoured(self):
        with Server({}) as server:
            dead = server.url("/Named_Boxarts/")
        wanted = [hires.Wanted(code, ["x"], self.hires / f"{code}.png") for code in ("A", "B", "C", "D", "E")]
        log = Log()
        report = hires.fetch_boxes(wanted, self.hires, log=log, base_url=dead)
        self.assertEqual(report.failed, ["A", "B", "C", "D", "E"])
        self.assertEqual(report.fetched, 0)
        self.assertIn("giving up", log.text())
        self.assertLess(len([line for line in log.lines if ": " in line]), 5, "not one line per box")
        with Server({route("x"): (200, box_png())}) as server:
            report = hires.fetch_boxes(wanted, self.hires, cancel=lambda: True,
                                       base_url=server.url("/Named_Boxarts/"))
        self.assertTrue(report.stopped)
        self.assertEqual(report.fetched, 0)

    def test_the_cover_plan_takes_a_fetched_box_after_the_owners_and_before_the_collection(self):
        write_collection(self.card / "release-metadata.zip", "NSME", "NWRE", zipped=True)
        self.hires.mkdir(parents=True)
        (self.hires / "NSME.png").write_bytes(box_png())
        (self.hires / "NWRE.png").write_bytes(box_png())
        picture(self.art / "NWRE.png")
        from tools.metadata_repo import MetadataRepo
        with MetadataRepo.open(self.card / "release-metadata.zip") as repo:
            planned = pack_covers.plan(self.card, self.rom_paths, repo, self.art)
        self.assertEqual(planned.covers["ROMS/Super Mario 64 (USA).z64"], "NSME.sprite")
        self.assertIsInstance(planned.sources["NSME.sprite"], hires.Hires)
        self.assertEqual(planned.origins["ROMS/Super Mario 64 (USA).z64"], provenance.COVER_LIBRETRO_MODIFIED,
                         "not in the manifest: not what the tool fetched")
        self.assertEqual(planned.origins["ROMS/Hacks/Wave Race Kaizo.z64"], provenance.yours_code("NWRE"))
        self.assertIsInstance(planned.sources["NWRE.sprite"], custom_art.Custom)
        self.assertEqual((planned.hires, planned.custom), (1, 1))

    def test_a_run_with_hires_fetches_then_builds_the_covers_from_the_fetched_boxes(self):
        write_collection(self.card / "release-metadata.zip", "NSME", zipped=True)
        green = box_png()
        with Server({route("Super Mario 64 (USA)"): (200, green)}) as server, \
             mock.patch.object(hires, "BASE_URL", server.url("/Named_Boxarts/")), \
             mock.patch.dict("os.environ", {"SLEEKMENU_NO_DOWNLOAD": ""}), \
             mock.patch.object(sleekmenu_prep.fetch, "release_addresses", lambda *a, **k: []), \
             contextlib.redirect_stdout(io.StringIO()):
            log = Log()
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, hires=True), log=log, fail=log)
            self.assertEqual(code, 0, log.text())
            self.assertIn("2 boxes to fetch", log.text())
            self.assertIn("no box on libretro for 1: NWRE", log.text())
            self.assertIn("(1 high-resolution)", log.text())
            self.assertTrue((self.hires / "NSME.png").is_file())
            self.assertFalse((self.hires / "NWRE.png").exists())
            # a second explicit run has nothing new to fetch; it asks libretro
            # about the missing one again, since it was asked to
            server.requests.clear()
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, hires=True), log=log, fail=log)
            self.assertEqual(code, 0)
            self.assertEqual([r for r in server.requests if "Mario" in r], [])
            self.assertTrue(any("Wave" in r for r in server.requests), "asked again: --hires retries")
            # a run that says nothing about boxes remembers the card has them:
            # a game added since gets its box, the known absence is not retried
            manifest = json.loads((self.hires / hires.MANIFEST).read_text())
            self.assertIn("NWRE", manifest["missing"])
            fzero = row("F-Zero X (USA)")
            write_rom(self.card / "ROMS" / "F-Zero X (USA).z64", int(fzero.crc[:8], 16), int(fzero.crc[8:], 16),
                      game_code=fzero.serial[1:3])
            server.routes[route("F-Zero X (USA)")] = (200, box_png((90, 90, 200, 255)))
            server.requests.clear()
            log = Log()
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card), log=log, fail=log)
            self.assertEqual(code, 0, log.text())
            self.assertIn("keeping them complete", log.text())
            self.assertTrue((self.hires / "NFZE.png").is_file(), "the fixture header spells the code NFZE")
            self.assertFalse(any("Wave" in r for r in server.requests), "a known absence is not asked again")
            # and a card that never fetched boxes is left alone
            self.assertFalse(hires.remembered(custom_art.art_dir(Path(self.temporary.name))))
        document = card_catalog.load(self.card)
        games = {game["path"]: game for game in document["games"]}
        self.assertEqual(games["ROMS/Super Mario 64 (USA).z64"]["sources"]["cover"], provenance.COVER_LIBRETRO)
        covers = card_catalog.Covers.open(self.card)
        width, height, rgb = covers.pixels(games["ROMS/Super Mario 64 (USA).z64"])
        self.assertIn(bytes((16, 160, 56)), rgb, "the green of the fetched box, not the collection's blue")
        # downloads off: the run says so and builds anyway
        with mock.patch.dict("os.environ", {"SLEEKMENU_NO_DOWNLOAD": "1"}), \
             contextlib.redirect_stdout(io.StringIO()):
            log = Log()
            self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, hires=True, no_download=True),
                                                log=log, fail=log), 0)
            self.assertIn("downloads are off", log.text())


if __name__ == "__main__":
    unittest.main()
