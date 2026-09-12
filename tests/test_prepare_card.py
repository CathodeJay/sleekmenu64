# SPDX-License-Identifier: AGPL-3.0-only
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tests.rom_fixtures import write_rom
from tools import cover_pack, coverdb, prepare_card
from tools.metadata_repo import MetadataRepo


class PrepareCardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.card = self.root / "CARD"
        self.roms = self.card / "ROMS"
        self.collection = self.root / "metadata"
        self.roms.mkdir(parents=True)
        self.collection.mkdir()
        self.database = self.root / "coverdb.csv"
        self.repo = None

    def tearDown(self):
        if self.repo is not None:
            self.repo.close()
        self.temporary.cleanup()

    def add_box(self, key, size=(158, 112)):
        target = self.collection / key / "boxart_front.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", size, (20, 90, 160, 255)).save(target)

    def prepare(self, with_collection=True, **kwargs):
        if with_collection and self.repo is None:
            self.repo = MetadataRepo.open(self.collection)
        options = dict(roms=self.roms, card=self.card, database_path=self.database,
                       repo=self.repo if with_collection else None,
                       work=self.root / "work", log=lambda *a: None)
        options.update(kwargs)
        return prepare_card.prepare(**options)

    def test_end_to_end_writes_a_card_with_no_toolchain(self):
        crc = write_rom(self.roms / "Racing" / "0421 - stuff.z64", 0x11, 0x22, game_code="WR")
        coverdb.save(self.database, [coverdb.Entry(crc=crc, name="Wave Race 64 (USA)",
                                                   genre="Racing", year=1996)])
        self.add_box("N/W/R/E")
        summary = self.prepare()

        catalog = self.card / "sleekmenu" / "catalog.ebc"
        pack = self.card / "sleekmenu" / "covers.pak"
        self.assertTrue(catalog.is_file())
        # One file, not a directory of them: FatFs walks a directory linearly
        # on every open, which is the pause between moving the cursor and the
        # picture appearing.
        self.assertFalse((self.card / "sleekmenu" / "covers").exists())
        entries = cover_pack.read_index(pack.read_bytes())
        self.assertEqual([e.name for e in entries], ["NWRE.sprite"])
        self.assertEqual(entries[0].length, 8 + 96 * 72 * 2 + 128)
        self.assertEqual((summary["games"], summary["covers"], summary["sprites"]), (1, 1, 1))
        self.assertIn(b"NWRE.sprite", catalog.read_bytes())

    def test_loose_covers_are_still_available_for_a_card_being_debugged(self):
        write_rom(self.roms / "Game (USA).z64", 1, 2, game_code="GA")
        self.add_box("N/G/A/E")
        self.prepare(loose_covers=True)
        self.assertTrue((self.card / "sleekmenu" / "covers" / "NGAE.sprite").is_file())
        self.assertFalse((self.card / "sleekmenu" / "covers.pak").exists())

    def test_catalog_paths_are_recorded_against_the_card_not_the_rom_folder(self):
        """The single most damaging thing this pipeline can get wrong: a path
        the browser cannot resolve fails every launch and says nothing."""
        write_rom(self.roms / "Racing" / "Game (USA).z64", 1, 2)
        self.prepare(with_collection=False)
        catalog = (self.card / "sleekmenu" / "catalog.ebc").read_bytes()
        self.assertIn(b"ROMS/Racing/Game (USA).z64", catalog)

    def test_roms_outside_the_card_are_refused_with_a_reason(self):
        outside = self.root / "elsewhere"
        write_rom(outside / "Game (USA).z64", 1, 2)
        with self.assertRaisesRegex(prepare_card.PrepareError, "must be on the card"):
            self.prepare(with_collection=False, roms=outside)

    def test_dry_run_builds_everything_and_writes_nothing(self):
        write_rom(self.roms / "Game (USA).z64", 1, 2, game_code="GA")
        self.add_box("N/G/A/E")
        summary = self.prepare(dry_run=True)
        self.assertEqual((summary["games"], summary["sprites"]), (1, 1))
        self.assertFalse((self.card / "sleekmenu").exists())

    def test_the_rom_image_lands_at_the_card_root(self):
        write_rom(self.roms / "Game (USA).z64", 1, 2)
        image = self.root / "SleekMenu64.z64"
        image.write_bytes(b"\x80\x37\x12\x40" + b"\0" * 60)
        self.prepare(with_collection=False, rom_image=image)
        self.assertTrue((self.card / "SleekMenu64.z64").is_file())

    def test_a_card_with_no_collection_still_gets_a_catalog(self):
        """Metadata is worth having on its own; covers are the optional half."""
        crc = write_rom(self.roms / "Game (USA).z64", 1, 2)
        coverdb.save(self.database, [coverdb.Entry(crc=crc, name="Game (USA)", genre="Puzzle")])
        summary = self.prepare(with_collection=False)
        self.assertNotIn("covers", summary)
        self.assertTrue((self.card / "sleekmenu" / "catalog.ebc").is_file())
        self.assertFalse((self.card / "sleekmenu" / "covers").exists())
        self.assertFalse((self.card / "sleekmenu" / "covers.pak").exists())

    def test_a_collection_with_no_box_for_this_library_leaves_a_usable_card(self):
        write_rom(self.roms / "Game (USA).z64", 1, 2, game_code="GA")
        self.add_box("N/Q/Q/E")
        summary = self.prepare()
        self.assertEqual((summary["covers"], summary["without_art"], summary["sprites"]), (0, 1, 0))
        self.assertTrue((self.card / "sleekmenu" / "catalog.ebc").is_file())
        self.assertFalse((self.card / "sleekmenu" / "covers.pak").exists())

    def test_one_picture_serves_every_copy_of_a_game(self):
        """A library that keeps a game in a genre folder and two best-of
        folders is three ROMs, one cartridge code, one cover."""
        write_rom(self.roms / "Best" / "a.z64", 0x33, 0x44, game_code="KT")
        write_rom(self.roms / "Racing" / "b.z64", 0x33, 0x44, game_code="KT")
        write_rom(self.roms / "Hacks" / "c.z64", 0x55, 0x66, game_code="KT")
        self.add_box("N/K/T/E")
        summary = self.prepare()
        self.assertEqual((summary["games"], summary["covers"], summary["sprites"]), (3, 3, 1))


if __name__ == "__main__":
    unittest.main()
