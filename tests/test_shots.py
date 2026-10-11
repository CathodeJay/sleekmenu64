# SPDX-License-Identifier: AGPL-3.0-only
"""Screenshots from libretro and from the card owner, against a stand-in
server: which pictures are fetched for which games, what lands in
art/shots/ and its manifest, which picture each game gets, and what the
packs and the catalog carry to the console."""

import contextlib
import io
import json
import struct
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
from tools import (card_catalog, card_layout, cover_pack, coverdb, custom_art, hires, make_sprite,
                   provenance, shots, sleekmenu_prep)

ROOT = Path(__file__).resolve().parent.parent
DATABASE = coverdb.load(ROOT / "data" / "coverdb.csv")


def shot_png(color=(20, 160, 60, 255), size=(320, 240)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def route(slot: str, name: str) -> str:
    return f"/{shots.LIBRETRO_FOLDERS[slot]}/" + urllib.parse.quote(hires.libretro_name(name) + ".png")


def row(name: str) -> coverdb.Entry:
    return next(entry for entry in DATABASE.values() if entry.name == name)


def records(card: Path) -> dict[str, int]:
    """Each game's screenshot set as catalog.ebc carries it, by path."""
    data = (card / card_layout.CARD_FOLDER / card_layout.CATALOG_NAME).read_bytes()
    count, records_at, strings_at = struct.unpack_from("<III", data, 8)
    out = {}
    for number in range(count):
        record = data[records_at + 32 * number:records_at + 32 * (number + 1)]
        start = strings_at + struct.unpack_from("<I", record, 4)[0]
        path = data[start:data.index(b"\0", start)].decode("utf-8")
        out[path] = struct.unpack_from("<H", record, 30)[0]
    return out


class Card(unittest.TestCase):
    """A card with a dump the database knows by CRC, twice, a hack of
    another game it knows only by code, and homebrew it does not know."""

    def setUp(self):
        stay_offline(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.card = Path(self.temporary.name) / "CARD"
        mario = row("Super Mario 64 (USA)")
        for path in ("ROMS/Super Mario 64 (USA).z64", "ROMS/Best/Super Mario 64 (USA).z64"):
            write_rom(self.card / path, int(mario.crc[:8], 16), int(mario.crc[8:], 16), game_code="SM")
        write_rom(self.card / "ROMS" / "Hacks" / "Wave Race Kaizo.z64", 0x33, 0x44, game_code="WR")
        write_rom(self.card / "ROMS" / "Homebrew" / "Flappy.z64", 3, 4, game_code="\0\0", country="\0")
        self.rom_paths = ["ROMS/Super Mario 64 (USA).z64", "ROMS/Best/Super Mario 64 (USA).z64",
                          "ROMS/Hacks/Wave Race Kaizo.z64", "ROMS/Homebrew/Flappy.z64"]
        self.target = shots.folder(self.card)


class FetchTests(Card):
    def test_the_addresses_are_the_two_folders_beside_the_boxes(self):
        self.assertEqual(shots.base_url("title"), shots.ROOT_URL + "Named_Titles/")
        self.assertEqual(shots.base_url("snap", "http://x/"), "http://x/Named_Snaps/")
        self.assertEqual(shots.file_name("nsme", "snap"), "NSME.snap.png")
        self.assertEqual(self.target, self.card / "sleekmenu" / "art" / "shots")

    def test_only_retail_games_are_planned_a_pair_per_code(self):
        wanted = shots.plan(self.card, self.rom_paths, DATABASE, self.card)
        self.assertEqual([(w.code, w.slot) for w in wanted], [("NSME", "title"), ("NSME", "snap")],
                         "one pair for two copies; nothing for the hack or the homebrew")
        self.assertEqual(wanted[0].names[0], "Super Mario 64 (USA)")
        self.assertEqual(wanted[1].destination, self.target / "NSME.snap.png")
        # a picture already there is not planned again
        self.target.mkdir(parents=True)
        (self.target / "nsme.title.png").write_bytes(shot_png())
        self.assertEqual([(w.code, w.slot) for w in shots.plan(self.card, self.rom_paths, DATABASE, self.card)],
                         [("NSME", "snap")])

    def test_pictures_land_with_a_manifest_and_a_missing_one_is_remembered(self):
        title = shot_png()
        wanted = shots.plan(self.card, self.rom_paths, DATABASE, self.card)
        with Server({route("title", "Super Mario 64 (USA)"): (200, title)}) as server:
            report = shots.fetch_files(wanted, self.target, root_url=server.url("/"))
            self.assertEqual(server.requests, [route("title", "Super Mario 64 (USA)"),
                                               route("snap", "Super Mario 64 (USA)")])
        self.assertEqual((report.fetched, report.missing, report.failed), (1, ["NSME.snap"], []))
        self.assertEqual((self.target / "NSME.title.png").read_bytes(), title)
        self.assertFalse((self.target / "NSME.snap.png").exists())
        self.assertFalse(list(self.target.glob("*.part")))
        manifest = json.loads((self.target / shots.MANIFEST).read_text())
        self.assertEqual(manifest["shots"]["NSME.title"]["name"], "Super Mario 64 (USA)")
        self.assertEqual(len(manifest["shots"]["NSME.title"]["sha256"]), 64)
        self.assertIn("NSME.snap", manifest["missing"])
        # what the tool fetched is libretro's; a byte changed is not
        self.assertEqual(shots.origin(self.target, self.target / "NSME.title.png"), provenance.COVER_LIBRETRO)
        (self.target / "NSME.title.png").write_bytes(title + b"\0")
        self.assertEqual(shots.origin(self.target, self.target / "NSME.title.png"),
                         provenance.COVER_LIBRETRO_MODIFIED)
        # the absence is not asked about again, unless the card asks
        self.assertEqual(shots.plan(self.card, self.rom_paths, DATABASE, self.card), [])
        self.assertEqual([w.slot for w in shots.plan(self.card, self.rom_paths, DATABASE, self.card,
                                                     retry_missing=True)], ["snap"])

    def test_a_link_is_followed_as_for_boxes(self):
        png = shot_png()
        routes = {route("snap", "Castlevania (USA) (Rev 1)"): (200, b"Castlevania (USA).png"),
                  route("snap", "Castlevania (USA)"): (200, png)}
        wanted = [shots.Wanted("NDLE", "snap", ["Castlevania (USA) (Rev 1)"], self.target / "NDLE.snap.png")]
        with Server(routes) as server:
            report = shots.fetch_files(wanted, self.target, root_url=server.url("/"))
        self.assertEqual(report.fetched, 1)
        self.assertEqual((self.target / "NDLE.snap.png").read_bytes(), png)

    def test_offline_gives_up_after_three_failures(self):
        with Server({}) as server:
            dead = server.url("/")
        wanted = [shots.Wanted(code, "title", ["x"], self.target / f"{code}.title.png")
                  for code in ("NAAE", "NBBE", "NCCE", "NDDE")]
        log = Log()
        report = shots.fetch_files(wanted, self.target, log=log, root_url=dead)
        self.assertEqual(report.fetched, 0)
        self.assertEqual(len(report.failed), 4)
        self.assertIn("giving up", log.text())

    def test_the_card_remembers_the_choice_until_told_to_stop(self):
        self.assertFalse(shots.remembered(self.card))
        self.assertFalse(shots.forget(self.card))
        with Server({}) as server, mock.patch.object(shots, "ROOT_URL", server.url("/")):
            shots.fetch_for_card(self.card, self.rom_paths, ROOT / "data" / "coverdb.csv", self.card,
                                 log=Log())
        self.assertTrue(shots.remembered(self.card), "remembered even when nothing could be fetched")
        self.assertTrue(shots.forget(self.card))
        self.assertFalse(shots.remembered(self.card))
        self.assertTrue((self.target / shots.MANIFEST).is_file(), "the record stays, and the pictures")


class SetTests(Card):
    def games(self, kinds_by_path=None):
        kinds_by_path = kinds_by_path or {}
        return [{"path": path, "code": code, "kind": kinds_by_path.get(path, kind)} for path, code, kind in (
            ("ROMS/Super Mario 64 (USA).z64", "NSME", "retail"),
            ("ROMS/Best/Super Mario 64 (USA).z64", "NSME", "retail"),
            ("ROMS/Hacks/Wave Race Kaizo.z64", "NWRE", "hack"),
            ("ROMS/Homebrew/Flappy.z64", "", "homebrew"))]

    def test_the_owners_come_first_and_a_hack_gets_only_its_owners(self):
        self.target.mkdir(parents=True)
        for name in ("NSME.title.png", "NSME.snap.png", "NWRE.title.png"):
            (self.target / name).write_bytes(shot_png())
        own_snap = picture(custom_art.art_dir(self.card) / "Super Mario 64 (USA).snap.png")
        beside = picture(self.card / "ROMS" / "Hacks" / "Wave Race Kaizo.title.jpg")
        planned = shots.plan_sets(self.card, self.games())
        mario, best = planned.numbers["ROMS/Super Mario 64 (USA).z64"], planned.numbers[
            "ROMS/Best/Super Mario 64 (USA).z64"]
        self.assertEqual(mario, best, "two copies of one game are one set")
        self.assertEqual(planned.sets[mario], {"title": self.target / "NSME.title.png", "snap": own_snap})
        self.assertEqual(planned.origins["ROMS/Super Mario 64 (USA).z64"],
                         {"title": provenance.COVER_LIBRETRO_MODIFIED, "snap": provenance.COVER_YOURS_ROM},
                         "not in a manifest: not what the tool fetched")
        hack = planned.numbers["ROMS/Hacks/Wave Race Kaizo.z64"]
        self.assertEqual(planned.sets[hack], {"title": beside}, "its parent's pictures are another game's")
        self.assertNotIn("ROMS/Homebrew/Flappy.z64", planned.numbers)
        self.assertEqual(len(planned.sets), 2)
        self.assertEqual(planned.own, 3)
        self.assertEqual(shots.plan_sets(self.card, self.games()).numbers, planned.numbers,
                         "the same card numbers its sets the same way twice")
        # the kind the catalog has decides, the owner's correction included
        corrected = shots.plan_sets(self.card, self.games({"ROMS/Best/Super Mario 64 (USA).z64": "hack"}))
        self.assertEqual(corrected.sets[corrected.numbers["ROMS/Best/Super Mario 64 (USA).z64"]],
                         {"snap": own_snap})

    def test_the_packs_hold_both_sizes_under_the_set_numbers(self):
        self.target.mkdir(parents=True)
        (self.target / "NSME.title.png").write_bytes(shot_png(size=(640, 480)))
        (self.target / "NSME.snap.png").write_bytes(b"not a picture")
        planned = shots.plan_sets(self.card, self.games())
        small, large, converted, unreadable = shots.build(planned)
        self.assertEqual(sorted(small), ["1.title"])
        self.assertEqual(unreadable, [str(self.target / "NSME.snap.png")], "left out, not fatal")
        self.assertEqual(converted, 1)
        self.assertEqual(make_sprite.decode(small["1.title"])[:2], shots.THUMB)
        self.assertEqual(make_sprite.decode(large["1.title"])[:2], shots.CANVAS)
        kept, _large, converted, _ = shots.build(planned, reuse={"1.title": (b"small", b"large")})
        self.assertEqual((kept["1.title"], converted), (b"small", 0))
        self.assertTrue(planned.identities()["1.title"].startswith(shots.FORMAT + "|file:"))


class RunTests(Card):
    def run_tool(self, server, log, **options):
        with mock.patch.object(shots, "ROOT_URL", server.url("/")), \
             mock.patch.dict("os.environ", {"SLEEKMENU_NO_DOWNLOAD": ""}), \
             mock.patch.object(sleekmenu_prep.fetch, "release_addresses", lambda *a, **k: []), \
             contextlib.redirect_stdout(io.StringIO()):
            return sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, **options), log=log, fail=log)

    def test_a_run_with_shots_fetches_packs_and_numbers_the_records(self):
        write_collection(self.card / "release-metadata.zip", "NSME", zipped=True)
        routes = {route("title", "Super Mario 64 (USA)"): (200, shot_png((200, 30, 30, 255))),
                  route("snap", "Super Mario 64 (USA)"): (200, shot_png((30, 30, 200, 255)))}
        with Server(routes) as server:
            log = Log()
            self.assertEqual(self.run_tool(server, log, shots=True), 0, log.text())
            self.assertIn("2 screenshots of 1 game to fetch", log.text())
            self.assertIn("shots:    2 games have screenshots, 1 different sets", log.text())
            document = card_catalog.load(self.card)
            games = {game["path"]: game for game in document["games"]}
            mario = games["ROMS/Super Mario 64 (USA).z64"]
            self.assertEqual(mario["shots"], 1)
            self.assertEqual(mario["shot_sources"], {"title": provenance.COVER_LIBRETRO,
                                                     "snap": provenance.COVER_LIBRETRO})
            self.assertNotIn("shots", games["ROMS/Hacks/Wave Race Kaizo.z64"])
            self.assertEqual(records(self.card), {"ROMS/Best/Super Mario 64 (USA).z64": 1,
                                                  "ROMS/Super Mario 64 (USA).z64": 1,
                                                  "ROMS/Hacks/Wave Race Kaizo.z64": 0,
                                                  "ROMS/Homebrew/Flappy.z64": 0})
            folder = self.card / card_layout.CARD_FOLDER
            small = (folder / card_layout.SHOT_PACK_NAME).read_bytes()
            self.assertEqual({entry.name for entry in cover_pack.read_index(small)}, {"1.title", "1.snap"})
            width, height, rgb = card_catalog.Shots.open(self.card).pixels(mario, "snap")
            self.assertEqual((width, height), shots.CANVAS)
            self.assertIn(bytes((24, 24, 200)), rgb, "the blue of the fetched snap")

            # The next run remembers the choice, fetches nothing, converts
            # nothing and writes neither pack again.
            server.requests.clear()
            log = Log()
            with mock.patch.object(shots, "convert", side_effect=AssertionError("converted again")):
                self.assertEqual(self.run_tool(server, log), 0, log.text())
            self.assertEqual(server.requests, [])
            self.assertIn("shots.pak is what the card has; not written again", log.text())
            self.assertIn("shots-large.pak is what the card has; not written again", log.text())

            # The owner's own: pending until the next update, then theirs.
            picture(Path(self.temporary.name) / "mine.png", size=(320, 240), color=(240, 240, 20, 255))
            custom_art.save_shot(self.card, mario, "title", Path(self.temporary.name) / "mine.png")
            pending = custom_art.pending_edits(self.card, self.card, card_catalog.load(self.card))
            self.assertEqual(pending["ROMS/Super Mario 64 (USA).z64"].shots, ("title",))
            self.assertIn("ROMS/Best/Super Mario 64 (USA).z64", pending, "the same name, in another folder")
            log = Log()
            self.assertEqual(self.run_tool(server, log), 0, log.text())
            self.assertIn("(2 with your own)", log.text())
            document = card_catalog.load(self.card)
            mario = {game["path"]: game for game in document["games"]}["ROMS/Super Mario 64 (USA).z64"]
            self.assertEqual(mario["shot_sources"]["title"], provenance.COVER_YOURS_ROM)
            self.assertEqual(custom_art.pending_edits(self.card, self.card, document), {})
            removable, _beside = custom_art.edits_of(self.card, self.card, mario)
            self.assertIn(custom_art.art_dir(self.card) / "Super Mario 64 (USA).title.png", removable)
            # Taken out again: the fetched one comes back at the next update.
            self.assertEqual(len(custom_art.remove_shot(self.card, mario, "title")), 1)
            pending = custom_art.pending_edits(self.card, self.card, document)
            self.assertIn("shot_title", pending["ROMS/Super Mario 64 (USA).z64"].removed)

            # Told to stop: nothing more is fetched, and what is there stays.
            log = Log()
            self.assertEqual(self.run_tool(server, log, shots=False), 0, log.text())
            self.assertIn("no longer fetched", log.text())
            self.assertFalse(shots.remembered(self.card))
            self.assertEqual(records(self.card)["ROMS/Super Mario 64 (USA).z64"], 1)

    def test_the_command_line_asks_and_stops(self):
        seen = []
        with mock.patch.object(sleekmenu_prep, "run", lambda options, **_k: seen.append(options.shots) or 0):
            sleekmenu_prep.main(["--card", str(self.card), "--shots"])
            sleekmenu_prep.main(["--card", str(self.card), "--no-shots"])
            sleekmenu_prep.main(["--card", str(self.card)])
        self.assertEqual(seen, [True, False, None])


if __name__ == "__main__":
    unittest.main()
