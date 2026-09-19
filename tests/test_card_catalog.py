# SPDX-License-Identifier: AGPL-3.0-only
"""catalog.json on the card: written by every Prepare, with where each field
came from, and read back to look at the card without scanning it."""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.rom_fixtures import write_rom
from tests.test_custom_art import picture
from tests.test_sleekmenu_prep import write_collection
from tools import card_catalog, make_sprite, provenance, sleekmenu_prep


class CardTests(unittest.TestCase):
    """One card, prepared once for the class: a retail game the collection
    knows, a hack of it with the owner's own picture and text, a homebrew
    nothing knows, and a PAL game the collection has only a USA box for."""

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.card = Path(cls.temporary.name) / "CARD"
        card = cls.card
        write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
        write_rom(card / "ROMS" / "Hacks" / "Wave Race Kaizo.z64", 0x33, 0x44, game_code="WR")
        write_rom(card / "ROMS" / "Homebrew" / "Flappy.z64", 3, 4, game_code="\0\0", country="\0")
        write_rom(card / "ROMS" / "Zelda (Europe).z64", 0x55, 0x66, game_code="ZL", country="P")
        write_collection(card / "release-metadata.zip", "NWRE", "NZLE", zipped=True)
        picture(card / "sleekmenu" / "art" / "Wave Race Kaizo.png")
        (card / "sleekmenu" / "art" / "Wave Race Kaizo.txt").write_text("Title: Kaizo Race\n\nHard.\n")
        with contextlib.redirect_stdout(io.StringIO()), \
             mock.patch.dict(os.environ, {"SLEEKMENU_NO_DOWNLOAD": "1"}):
            cls.code = sleekmenu_prep.run(sleekmenu_prep.Options(card=card))
        cls.document = card_catalog.load(card)
        cls.games = {game["path"]: game for game in cls.document["games"]}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_the_json_is_written_beside_the_catalog_and_stamped(self):
        self.assertEqual(self.code, 0)
        self.assertTrue(card_catalog.path_on(self.card).is_file())
        self.assertIn("built", self.document)
        self.assertEqual(self.document["schema_version"], 1)
        self.assertEqual(len(self.document["games"]), 4)

    def test_every_field_names_its_source(self):
        retail = self.games["ROMS/Wave Race 64 (USA).z64"]["sources"]
        self.assertEqual(retail["cover"], provenance.COVER_COLLECTION)
        self.assertEqual(retail["title"], provenance.TITLE_FILE_NAME)
        self.assertEqual(retail["publisher"], provenance.DATABASE)
        self.assertIn(retail["description"], (provenance.TEXT_COLLECTION, provenance.TEXT_COLLECTION_BY_CODE))
        hack = self.games["ROMS/Hacks/Wave Race Kaizo.z64"]
        self.assertEqual(hack["title"], "Kaizo Race")
        self.assertEqual(hack["sources"]["cover"], provenance.COVER_YOURS_ROM)
        self.assertEqual(hack["sources"]["title"], provenance.YOURS)
        self.assertEqual(hack["sources"]["description"], provenance.YOURS)
        self.assertTrue(provenance.edited(hack["sources"]))
        self.assertFalse(provenance.edited(retail))
        homebrew = self.games["ROMS/Homebrew/Flappy.z64"]
        self.assertEqual(homebrew["identified"], "")
        self.assertEqual(set(homebrew["sources"].values()), {provenance.NONE, provenance.TITLE_FILE_NAME})
        pal = self.games["ROMS/Zelda (Europe).z64"]
        self.assertEqual(pal["sources"]["cover"], provenance.COVER_COLLECTION_REGION)

    def test_the_notes_say_what_a_person_should_know(self):
        self.assertIn("another region's scan",
                      " ".join(provenance.notes(self.games["ROMS/Zelda (Europe).z64"])))
        self.assertIn("placeholder", " ".join(provenance.notes(self.games["ROMS/Homebrew/Flappy.z64"])))
        self.assertIn("The title is yours",
                      " ".join(provenance.notes(self.games["ROMS/Hacks/Wave Race Kaizo.z64"])))

    def test_the_tree_is_the_card_as_the_browser_shows_it(self):
        tree = card_catalog.tree(self.document["games"])
        self.assertEqual(list(tree["folders"]), ["ROMS"])
        roms = tree["folders"]["ROMS"]
        self.assertEqual(list(roms["folders"]), ["Hacks", "Homebrew"])
        self.assertEqual([g["title"] for g in roms["games"]], ["Wave Race 64 (USA)", "Zelda (Europe)"])
        self.assertEqual(card_catalog.count(tree), 4)
        self.assertEqual(card_catalog.count(roms["folders"]["Hacks"]), 1)

    def test_the_box_shown_is_the_sprite_the_console_will_draw(self):
        covers = card_catalog.Covers.open(self.card)
        self.assertIsNotNone(covers)
        width, height, rgb = covers.pixels(self.games["ROMS/Hacks/Wave Race Kaizo.z64"])
        self.assertEqual((width, height), make_sprite.CANVAS_SIZE)
        self.assertEqual(len(rgb), width * height * 3)
        # the owner's picture is red (200, 40, 40); the matte around it is not
        self.assertIn(bytes((200 & ~7, 40 & ~7, 40 & ~7)), rgb)
        self.assertIsNone(covers.pixels(self.games["ROMS/Homebrew/Flappy.z64"]))
        ppm = make_sprite.to_ppm(width, height, rgb)
        self.assertTrue(ppm.startswith(b"P6 96 72 255\n"))

    def test_a_card_without_a_catalog_is_none_and_a_broken_one_is_an_error(self):
        with tempfile.TemporaryDirectory() as scratch:
            self.assertIsNone(card_catalog.load(Path(scratch)))
            broken = card_catalog.path_on(Path(scratch))
            broken.parent.mkdir(parents=True)
            broken.write_text("{not json")
            with self.assertRaises(card_catalog.CatalogJsonError):
                card_catalog.load(Path(scratch))
            self.assertIsNone(card_catalog.Covers.open(Path(scratch)))


class DecodeTests(unittest.TestCase):
    def test_decode_is_the_inverse_of_encode(self):
        from PIL import Image
        image = Image.new("RGBA", (8, 4), (248, 64, 8, 255))
        image.putpixel((0, 0), (0, 248, 0, 255))
        width, height, rgb = make_sprite.decode(make_sprite.encode(image))
        self.assertEqual((width, height), (8, 4))
        self.assertEqual(rgb[:3], bytes((0, 248, 0)))
        self.assertEqual(rgb[3:6], bytes((248, 64, 8)))

    def test_a_non_sprite_is_refused(self):
        with self.assertRaises(make_sprite.SpriteError):
            make_sprite.decode(b"PK\x03\x04")
        with self.assertRaises(make_sprite.SpriteError):
            make_sprite.decode(bytes((0, 8, 0, 4, 0, 0x82, 1, 1)) + bytes(10))


if __name__ == "__main__":
    unittest.main()
