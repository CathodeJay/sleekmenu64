# SPDX-License-Identifier: AGPL-3.0-only
"""The card owner's own pictures and text, by ROM name or game code."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tests.rom_fixtures import write_rom
from tools import build_metadata, cover_pack, custom_art, pack_covers, prepare_card
from tools.metadata_repo import MetadataRepo


def picture(path: Path, size=(300, 200), color=(200, 40, 40, 255)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", size, color)
    if path.suffix.casefold() in (".jpg", ".jpeg"):
        image = image.convert("RGB")
    image.save(path)
    return path


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name)
        self.roms = self.card / "ROMS"
        self.art = self.card / "sleekmenu" / "art"
        write_rom(self.roms / "Hacks" / "SM64 Star Road.z64", 1, 2, game_code="SM")
        write_rom(self.roms / "Homebrew" / "Flappy.z64", 3, 4, game_code="\0\0", country="\0")

    def tearDown(self):
        self.temporary.cleanup()

    def find(self, rom_path, code="NSME"):
        return custom_art.find_art(custom_art.Index(), self.roms, rom_path, self.art, code)

    def test_a_picture_beside_the_rom_wins_over_the_art_folder_and_the_code(self):
        picture(self.art / "NSME.png")
        picture(self.art / "SM64 Star Road.png")
        beside = picture(self.roms / "Hacks" / "SM64 Star Road.png")
        found = self.find("Hacks/SM64 Star Road.z64")
        self.assertEqual(found.path, beside)
        self.assertTrue(found.sprite.startswith("custom-") and found.sprite.endswith(".sprite"))
        beside.unlink()
        self.assertEqual(self.find("Hacks/SM64 Star Road.z64").path, self.art / "SM64 Star Road.png")
        (self.art / "SM64 Star Road.png").unlink()
        by_code = self.find("Hacks/SM64 Star Road.z64")
        self.assertEqual(by_code.path, self.art / "NSME.png")
        self.assertEqual(by_code.sprite, "NSME.sprite", "the collection's own name for the code")
        (self.art / "NSME.png").unlink()
        self.assertIsNone(self.find("Hacks/SM64 Star Road.z64"))

    def test_names_match_whatever_the_case_and_jpeg_is_a_picture_too(self):
        picture(self.roms / "Homebrew" / "FLAPPY.JPG")
        found = self.find("Homebrew/Flappy.z64", code="")
        self.assertIsNotNone(found)
        self.assertEqual(found.path.name, "FLAPPY.JPG")

    def test_two_roms_of_one_name_in_two_folders_get_two_sprites(self):
        self.assertNotEqual(custom_art.per_rom_sprite("A/Game.z64"), custom_art.per_rom_sprite("B/Game.z64"))
        self.assertEqual(custom_art.per_rom_sprite("A/Game.z64"), custom_art.per_rom_sprite("a/game.Z64"))

    def test_text_gives_the_description_and_optionally_the_title(self):
        (self.roms / "Hacks" / "SM64 Star Road.txt").write_text(
            "Title: Super Mario Star Road\n\nA hack with 120 new\n  stars.\n", encoding="utf-8")
        text = custom_art.find_text(custom_art.Index(), self.roms, "Hacks/SM64 Star Road.z64", self.art)
        self.assertEqual(text.title, "Super Mario Star Road")
        self.assertEqual(text.description, "A hack with 120 new stars.")
        (self.art / "Flappy.txt").parent.mkdir(parents=True)
        (self.art / "Flappy.txt").write_text("Just a bird.", encoding="utf-8")
        text = custom_art.find_text(custom_art.Index(), self.roms, "Homebrew/Flappy.z64", self.art)
        self.assertEqual((text.title, text.description), ("", "Just a bird."))
        self.assertIsNone(custom_art.find_text(custom_art.Index(), self.roms, "Hacks/None.z64", self.art))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name)
        self.roms = self.card / "ROMS"
        self.art = self.card / "sleekmenu" / "art"
        collection = self.card / "collection"
        picture(collection / "N/S/M/E/boxart_front.png", size=(158, 112), color=(0, 0, 255, 255))
        self.repo = MetadataRepo.open(collection)

    def tearDown(self):
        self.repo.close()
        self.temporary.cleanup()

    def test_own_art_comes_first_and_a_code_override_replaces_the_collection_box(self):
        write_rom(self.roms / "Super Mario 64 (USA).z64", 1, 2, game_code="SM")
        write_rom(self.roms / "Hacks" / "Star Road.z64", 3, 4, game_code="SM")
        write_rom(self.roms / "Homebrew" / "Flappy.z64", 5, 6, game_code="\0\0", country="\0")
        picture(self.roms / "Hacks" / "Star Road.png")
        picture(self.art / "Flappy.png")
        paths = ["Super Mario 64 (USA).z64", "Hacks/Star Road.z64", "Homebrew/Flappy.z64"]
        planned = pack_covers.plan(self.roms, paths, self.repo, self.art)
        self.assertEqual(planned.covers["Super Mario 64 (USA).z64"], "NSME.sprite")
        self.assertNotEqual(planned.covers["Hacks/Star Road.z64"], "NSME.sprite")
        self.assertIn("Homebrew/Flappy.z64", planned.covers)
        self.assertEqual(planned.without, [])
        self.assertEqual(planned.custom, 2)
        self.assertIsInstance(planned.sources["NSME.sprite"], type(self.repo.art("NSME")))

        # A code override: every ROM with the code, the retail one included,
        # and the collection's box for it is not converted at all.
        picture(self.art / "NSME.png")
        planned = pack_covers.plan(self.roms, paths, self.repo, self.art)
        self.assertEqual(planned.covers["Super Mario 64 (USA).z64"], "NSME.sprite")
        self.assertIsInstance(planned.sources["NSME.sprite"], custom_art.Custom)
        self.assertEqual(planned.custom, 3)

    def test_own_art_needs_no_collection(self):
        write_rom(self.roms / "Homebrew" / "Flappy.z64", 5, 6, game_code="\0\0", country="\0")
        picture(self.roms / "Homebrew" / "Flappy.png")
        planned = pack_covers.plan(self.roms, ["Homebrew/Flappy.z64"], None, None)
        self.assertEqual(len(planned.covers), 1)
        written = pack_covers.pack(planned, None, self.card / "out")
        self.assertEqual(written, 1)
        sprite = next((self.card / "out").glob("custom-*.sprite")).read_bytes()
        self.assertEqual(sprite[:4], (96).to_bytes(2, "big") + (72).to_bytes(2, "big"),
                         "fitted to the card's cover size like a scan")


class CardTests(unittest.TestCase):
    def test_a_card_carries_the_owners_picture_and_text(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            roms = card / "ROMS"
            write_rom(roms / "Homebrew" / "Flappy.z64", 5, 6, game_code="\0\0", country="\0")
            picture(card / "sleekmenu" / "art" / "Flappy.png")
            (roms / "Homebrew" / "Flappy.txt").write_text(
                "Title: Flappy Bird 64\nA bird, some pipes.", encoding="utf-8")
            summary = prepare_card.prepare(roms=roms, card=card, database_path=card / "none.csv",
                                           repo=None, work=Path(scratch) / "work", log=lambda *a: None)
            self.assertEqual(summary["custom_art"], 1)
            catalog = (card / "sleekmenu" / "catalog.ebc").read_bytes()
            self.assertIn(b"Flappy Bird 64", catalog)
            self.assertIn(b"A bird, some pipes.", catalog)
            entries = cover_pack.read_index((card / "sleekmenu" / "covers.pak").read_bytes())
            self.assertEqual(len(entries), 1)
            self.assertTrue(entries[0].name.startswith("custom-"))
            self.assertIn(entries[0].name.encode(), catalog)

    def test_the_metadata_builder_reads_text_only_against_a_card(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            roms = card / "ROMS"
            write_rom(roms / "Game.z64", 1, 2, game_code="GA")
            (roms / "Game.txt").write_text("Own words.", encoding="utf-8")
            document, how = build_metadata.build(roms, card, coverdb_path=card / "none.csv")
            self.assertEqual(document["games"][0]["description"], "Own words.")
            self.assertEqual(how["own text"], 1)


if __name__ == "__main__":
    unittest.main()
