# SPDX-License-Identifier: AGPL-3.0-only
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools import cover_pack, coverdb, refresh_catalog
from tools.metadata_repo import MetadataRepo


def quiet(*args):
    pass


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.collection = self.root / "metadata"
        self.covers = self.root / "covers"
        self.collection.mkdir()
        self.database = self.root / "coverdb.csv"
        self.repo = None

    def tearDown(self):
        if self.repo is not None:
            self.repo.close()
        self.temporary.cleanup()

    def add_box(self, key, description=None, ini=None):
        folder = self.collection / key
        folder.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (158, 112), (30, 90, 150, 255)).save(folder / "boxart_front.png")
        if description:
            (folder / "description.txt").write_text(description, encoding="utf-8")
        if ini:
            (folder / "metadata.ini").write_text(ini, encoding="utf-8")

    def open_collection(self):
        if self.repo is None:
            self.repo = MetadataRepo.open(self.collection)
        return self.repo

    def metadata(self, games):
        path = self.root / "metadata.json"
        path.write_text(json.dumps({"schema_version": 1, "attribution": "", "games": games}),
                        encoding="utf-8")
        return path

    def game(self, path, cover="", crc="", code="", **extra):
        row = {"title": Path(path).stem, "path": path, "cover": cover, "genre": "",
               "publisher": "", "year": 0, "players": 0, "regions": [], "description": ""}
        if crc:
            row["crc"] = crc
        if code:
            row["code"] = code
        row.update(extra)
        return row

    def games_out(self):
        return {g["path"]: g for g in json.loads((self.root / "out.json").read_text())["games"]}


class RefreshCoversTests(Fixture):
    def test_a_newer_collection_reaches_a_card_built_before_it(self):
        self.add_box("N/W/R/E")
        meta = self.metadata([self.game("ROMS/Wave Race 64 (USA).z64", code="NWRE")])
        summary = refresh_catalog.refresh(meta, self.database, self.root / "out.json",
                                         self.open_collection(), self.covers, log=quiet)
        self.assertEqual(summary["collection"]["covers added"], 1)
        self.assertEqual(self.games_out()["ROMS/Wave Race 64 (USA).z64"]["cover"], "NWRE.sprite")
        self.assertTrue((self.covers / "NWRE.sprite").is_file())

    def test_a_japanese_cartridge_does_not_inherit_the_usa_box(self):
        self.add_box("N/W/R/E")
        self.add_box("N/W/R/J")
        meta = self.metadata([self.game("ROMS/Wave Race 64 (Japan).z64", code="NWRJ")])
        refresh_catalog.refresh(meta, self.database, self.root / "out.json",
                                self.open_collection(), self.covers, log=quiet)
        self.assertEqual(self.games_out()["ROMS/Wave Race 64 (Japan).z64"]["cover"], "NWRJ.sprite")

    def test_an_existing_cover_is_never_touched(self):
        self.add_box("N/W/R/E")
        meta = self.metadata([self.game("ROMS/Game.z64", cover="Mine.sprite", code="NWRE")])
        refresh_catalog.refresh(meta, self.database, self.root / "out.json",
                                self.open_collection(), self.covers, log=quiet)
        self.assertEqual(self.games_out()["ROMS/Game.z64"]["cover"], "Mine.sprite")

    def test_a_game_with_no_code_is_left_alone(self):
        """A card built before the code was recorded, or a homebrew with a
        blank header: nothing to look up, nothing to invent."""
        self.add_box("N/W/R/E")
        meta = self.metadata([self.game("ROMS/Old.z64"), self.game("ROMS/Blank.z64", code="")])
        summary = refresh_catalog.refresh(meta, self.database, self.root / "out.json",
                                         self.open_collection(), self.covers, log=quiet)
        self.assertEqual(summary["collection"]["covers added"], 0)

    def test_only_missing_sprites_are_converted(self):
        self.add_box("N/W/R/E")
        self.covers.mkdir()
        (self.covers / "NWRE.sprite").write_bytes(b"already here")
        meta = self.metadata([self.game("ROMS/Game.z64", code="NWRE")])
        summary = refresh_catalog.refresh(meta, self.database, self.root / "out.json",
                                         self.open_collection(), self.covers, log=quiet)
        self.assertNotIn("sprites converted", summary["collection"])
        self.assertEqual((self.covers / "NWRE.sprite").read_bytes(), b"already here")

    def test_descriptions_and_gaps_come_from_the_collection(self):
        self.add_box("N/W/R/E", description="Race on water.\n",
                     ini="[meta]\nauthor = Nintendo EAD | Nintendo\nrelease-date = 1996-09-27\n")
        coverdb.save(self.database, [coverdb.Entry(crc="1" * 16, name="Wave Race 64 (USA)",
                                                   publisher="Nintendo of America")])
        meta = self.metadata([self.game("ROMS/Game.z64", crc="1" * 16, code="NWRE")])
        refresh_catalog.refresh(meta, self.database, self.root / "out.json",
                                self.open_collection(), self.covers, log=quiet)
        game = self.games_out()["ROMS/Game.z64"]
        self.assertEqual(game["description"], "Race on water.")
        # The database row had a publisher and no year: its publisher stands,
        # the collection supplies the year.
        self.assertEqual((game["publisher"], game["year"]), ("Nintendo of America", 1996))

    def test_it_can_rebuild_the_pack_and_the_catalog(self):
        self.add_box("N/W/R/E")
        meta = self.metadata([self.game("ROMS/Game.z64", code="NWRE")])
        pack = self.root / "covers.pak"
        catalog = self.root / "catalog.ebc"
        summary = refresh_catalog.refresh(meta, self.database, self.root / "out.json",
                                         self.open_collection(), self.covers, pack, catalog,
                                         log=quiet)
        self.assertEqual(summary["pack_covers_count"], 1)
        self.assertEqual([e.name for e in cover_pack.read_index(pack.read_bytes())],
                         ["NWRE.sprite"])
        self.assertIn(b"NWRE.sprite", catalog.read_bytes())

    def test_a_pack_needs_somewhere_to_pack_from(self):
        meta = self.metadata([self.game("ROMS/Game.z64", code="NWRE")])
        with self.assertRaisesRegex(refresh_catalog.RefreshError, "--covers"):
            refresh_catalog.refresh(meta, self.database, self.root / "out.json",
                                    pack=self.root / "covers.pak", log=quiet)


class GenreRefreshTests(Fixture):
    """The regression this exists to prevent: a genre correction applied once
    to a build artefact, then lost the moment anything rebuilt from an older
    copy of that artefact. Ocarina of Time went back to being a role-playing
    game exactly that way."""

    def setUp(self):
        super().setUp()
        self.genres = self.root / "genres.csv"
        self.genres.write_text(
            "# sleekmenu-genres 1\nsource,genre\n"
            "Role-playing (RPG),Role Playing Games\n"
            "Beat'em Up,Action\n"
            "Platform,Platforms\n", encoding="utf-8")

    def run_refresh(self, meta):
        refresh_catalog.refresh(meta, self.database, self.root / "out.json",
                                genres=self.genres, log=quiet)
        return {path: game["genre"] for path, game in self.games_out().items()}

    def test_a_curated_genre_replaces_a_wrong_one(self):
        crc = "1" * 16
        coverdb.save(self.database, [coverdb.Entry(
            crc=crc, name="Legend of Zelda, The - Ocarina of Time (USA)",
            genre="Action-Adventure")])
        meta = self.metadata([self.game("ROMS/Zelda.z64", crc=crc, genre="Role-playing (RPG)")])
        self.assertEqual(self.run_refresh(meta)["ROMS/Zelda.z64"], "Action-Adventure")

    def test_it_is_re_derived_every_run_not_patched_once(self):
        """Running it twice must give the same answer, and running it on its
        own output must not undo the correction."""
        crc = "2" * 16
        coverdb.save(self.database, [coverdb.Entry(crc=crc, name="Game (USA)",
                                                   genre="Action-Adventure")])
        meta = self.metadata([self.game("ROMS/Game (USA).z64", crc=crc, genre="Role-playing (RPG)")])
        first = self.run_refresh(meta)
        second = self.run_refresh(self.root / "out.json")
        self.assertEqual(first, second)
        self.assertEqual(second["ROMS/Game (USA).z64"], "Action-Adventure")

    def test_a_game_the_database_lacks_is_still_consolidated(self):
        coverdb.save(self.database, [coverdb.Entry(crc="3" * 16, name="Other")])
        meta = self.metadata([self.game("ROMS/Homebrew.z64", genre="Beat'em Up")])
        self.assertEqual(self.run_refresh(meta)["ROMS/Homebrew.z64"], "Action")

    def test_a_game_with_no_genre_anywhere_stays_blank(self):
        coverdb.save(self.database, [coverdb.Entry(crc="4" * 16, name="Other")])
        meta = self.metadata([self.game("ROMS/Mystery.z64", genre="")])
        self.assertEqual(self.run_refresh(meta)["ROMS/Mystery.z64"], "")

    def test_the_database_reaches_a_hack_through_its_product_code(self):
        """A patched dump has a CRC the database never saw and the code of
        the cartridge it was built on."""
        coverdb.save(self.database, [coverdb.Entry(
            crc="5" * 16, serial="NKTE", name="Mario Kart 64 (USA)", genre="Racing")])
        meta = self.metadata([self.game("ROMS/MK64 Amped Up.z64", crc="6" * 16, code="NKTE",
                                        genre="Sports")])
        self.assertEqual(self.run_refresh(meta)["ROMS/MK64 Amped Up.z64"], "Racing")


if __name__ == "__main__":
    unittest.main()
