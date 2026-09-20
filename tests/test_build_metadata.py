# SPDX-License-Identifier: AGPL-3.0-only
import tempfile
import unittest
from pathlib import Path

from tests.rom_fixtures import write_rom
from tests.test_metadata_repo import collection
from tools import build_metadata, coverdb
from tools.metadata_repo import MetadataRepo


class BuildMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name)
        self.roms = self.card / "N64"
        self.roms.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def build(self, **options):
        base = dict(roms=self.roms, sd_root=None, coverdb_path=self.card / "missing.csv")
        base.update(options)
        return build_metadata.build(**base)

    def test_sd_root_records_paths_the_browser_can_actually_resolve(self):
        """The browser tries sd:/ROMS/<path> and then sd:/<path>. A library at
        sd:/N64 recorded against its own folder yields a bare filename, which
        matches neither, and every launch fails with nothing on screen to
        explain why. Recording against the card root always resolves."""
        write_rom(self.roms / "Game (USA).z64", 1, 2)
        without, _ = self.build()
        self.assertEqual(without["games"][0]["path"], "Game (USA).z64")
        with_root, _ = self.build(sd_root=self.card)
        self.assertEqual(with_root["games"][0]["path"], "N64/Game (USA).z64")

    def test_sd_root_must_contain_the_rom_folder(self):
        write_rom(self.roms / "Game (USA).z64", 1, 2)
        with self.assertRaises(SystemExit):
            self.build(sd_root=self.card / "elsewhere")

    def test_metadata_comes_from_the_database_by_crc(self):
        crc = write_rom(self.roms / "0421 - stuff.z64", 0xAB, 0xCD)
        database = self.card / "db.csv"
        coverdb.save(database, [coverdb.Entry(crc=crc, name="Wave Race 64 (USA)",
                                              genre="Racing", publisher="Nintendo",
                                              year=1996, players=2, regions=("USA",))])
        document, how = self.build(coverdb_path=database)
        game = document["games"][0]
        self.assertEqual((game["genre"], game["publisher"], game["year"], game["players"]),
                         ("Racing", "Nintendo", 1996, 2))
        self.assertEqual(game["regions"], ["USA"])
        self.assertEqual(how["database by crc"], 1)

    def test_a_patched_dump_inherits_its_cartridges_row_by_product_code(self):
        """The 20% of a real card the CRC never found: hacks and translations
        keep the code of the game they were built on."""
        write_rom(self.roms / "Wave Race 64 - Shoreline Hack.z64", 0x99, 0x98, game_code="WR")
        database = self.card / "db.csv"
        coverdb.save(database, [coverdb.Entry(crc="1" * 16, serial="NWRE",
                                              name="Wave Race 64 (USA)", genre="Racing",
                                              publisher="Nintendo", year=1996)])
        document, how = self.build(coverdb_path=database)
        game = document["games"][0]
        self.assertEqual((game["genre"], game["publisher"], game["year"]), ("Racing", "Nintendo", 1996))
        self.assertEqual(how["database by serial"], 1)

    def test_a_game_the_database_lacks_is_left_blank_not_guessed(self):
        write_rom(self.roms / "Some Hack (USA).z64", 3, 4)
        document, _ = self.build()
        game = document["games"][0]
        self.assertEqual((game["genre"], game["publisher"], game["year"], game["players"]),
                         ("", "", 0, 0))
        self.assertEqual(game["description"], "")
        # The header still speaks for itself.
        self.assertEqual(game["regions"], ["USA"])

    def test_the_record_keeps_the_keys_a_refresh_needs(self):
        crc = write_rom(self.roms / "Game (USA).z64", 1, 2, game_code="GE")
        document, _ = self.build()
        self.assertEqual((document["games"][0]["crc"], document["games"][0]["code"]), (crc, "NGEE"))

    def test_covers_may_be_keyed_against_either_root(self):
        write_rom(self.roms / "Game (USA).z64", 1, 2)
        document, _ = self.build(sd_root=self.card, covers={"N64/Game (USA).z64": "NGEE.sprite"})
        self.assertEqual(document["games"][0]["cover"], "NGEE.sprite")
        document, _ = self.build(sd_root=self.card, covers={"Game (USA).z64": "NGEE.sprite"})
        self.assertEqual(document["games"][0]["cover"], "NGEE.sprite")

    def test_the_collection_fills_what_the_database_left_blank_and_never_overrides_it(self):
        write_rom(self.roms / "GoldenEye 007 (USA).z64", 5, 6, game_code="GE")
        crc = write_rom(self.roms / "GoldenEye 007 (USA) (Rev 1).z64", 7, 8, game_code="GE")
        database = self.card / "db.csv"
        coverdb.save(database, [coverdb.Entry(crc=crc, name="GoldenEye 007 (USA)",
                                              publisher="Nintendo of America", year=1997)])
        collection(self.card / "collection")
        with MetadataRepo.open(self.card / "collection") as repo:
            document, how = self.build(coverdb_path=database, repo=repo)
        by_path = {game["path"]: game for game in document["games"]}
        plain = by_path["GoldenEye 007 (USA).z64"]
        revised = by_path["GoldenEye 007 (USA) (Rev 1).z64"]
        # The database had nothing on the plain dump: the collection's
        # publisher (the last name in "Developer | Publisher") and year.
        self.assertEqual((plain["publisher"], plain["year"], plain["players"]),
                         ("Nintendo", 1997, 4))
        # It had the revision: the database's spelling stands.
        self.assertEqual((revised["publisher"], revised["year"]), ("Nintendo of America", 1997))
        self.assertEqual(plain["description"], "You are Bond. James Bond.")
        self.assertEqual(revised["description"], "You are Bond. James Bond.")
        self.assertEqual(how["collection has a description"], 2)
        self.assertIn("n64-flashcart-menu-metadata", document["attribution"])

    def test_a_64dd_disk_image_is_a_game_with_a_name_and_a_region(self):
        """A .ndd has no cartridge header, so nothing identifies it; it is
        still a game the browser should list and, on a Pro, start. The
        region comes from the system area's first word, the way the launcher
        picks the IPL, and from the file name when that word is not a retail
        one."""
        from tools import build_catalog, library
        write_rom(self.roms / "Cart Game (USA).z64", 1, 2)
        (self.roms / "Doshin (Japan).ndd").write_bytes(b"\xe8\x48\xd3\x16" + bytes(60))
        (self.roms / "Homebrew (USA).ndd").write_bytes(bytes(64))
        self.assertEqual(library.walk(self.roms),
                         ["Cart Game (USA).z64", "Doshin (Japan).ndd", "Homebrew (USA).ndd"])
        self.assertTrue(library.is_disk("x/Doshin (Japan).ndd"))
        self.assertFalse(library.is_disk("x/Doshin (Japan).z64"))
        document, how = self.build()
        self.assertEqual(how["64dd disk"], 2)
        self.assertEqual(how["not a rom"], 0)
        by_path = {game["path"]: game for game in document["games"]}
        disk = by_path["Doshin (Japan).ndd"]
        self.assertEqual(disk["title"], "Doshin (Japan)")
        self.assertEqual(disk["regions"], ["JAPAN"])
        self.assertEqual(by_path["Homebrew (USA).ndd"]["regions"], ["USA"])
        self.assertNotIn("crc", disk)
        # and the catalog encoder takes the record as it is
        games = build_catalog.normalize(document)
        self.assertEqual(len(games), 3)
        build_catalog.encode(games)

    def test_a_file_with_no_header_is_set_aside_by_name_and_packed_as_never_listed(self):
        """A 64DD IPL dump or a demo with a broken magic looks like a game
        to a directory walk and is not one. It is named in the document
        with the reason, so the window can say so instead of counting it
        as a game still to add, and packed as a record the browser never
        lists -- so the browser's own read of the folder does not take it
        for a game the catalog missed."""
        from tools import build_catalog
        write_rom(self.roms / "Real Game (USA).z64", 1, 2)
        (self.roms / "Dev Tools").mkdir()
        (self.roms / "Dev Tools" / "64DD IPL (Japan).z64").write_bytes(b"\x00\x00\x00\x00" + bytes(60))
        (self.roms / "Demo.v64").write_bytes(b"junk" * 16)
        document, how = self.build()
        self.assertEqual(how["not a rom"], 2)
        self.assertEqual([game["path"] for game in document["games"]], ["Real Game (USA).z64"])
        self.assertEqual(document["set_aside"], [
            {"path": "Demo.v64", "why": build_metadata.NOT_A_ROM},
            {"path": "Dev Tools/64DD IPL (Japan).z64", "why": build_metadata.NOT_A_ROM},
        ])
        packed = build_catalog.normalize(document)
        self.assertEqual([(g["path"], g["flags"]) for g in packed],
                         [("Demo.v64", build_catalog.FLAG_SET_ASIDE),
                          ("Dev Tools/64DD IPL (Japan).z64", build_catalog.FLAG_SET_ASIDE),
                          ("Real Game (USA).z64", 0)])
        self.assertEqual(packed[1]["title"], "64DD IPL (Japan)")
        with self.assertRaises(build_catalog.CatalogError):
            build_catalog.normalize({"schema_version": 1, "games": document["games"],
                                     "set_aside": [{"path": "Real Game (USA).z64", "why": "x"}]})

    def test_attribution_names_only_what_was_used(self):
        write_rom(self.roms / "Game (USA).z64", 1, 2)
        document, _ = self.build()
        self.assertNotIn("n64-flashcart-menu-metadata", document["attribution"])


if __name__ == "__main__":
    unittest.main()
