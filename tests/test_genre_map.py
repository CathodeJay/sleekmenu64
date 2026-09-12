# SPDX-License-Identifier: AGPL-3.0-only
import tempfile
import unittest
from pathlib import Path

from tests.rom_fixtures import write_rom
from tools import build_metadata, coverdb, genre_map


class GenreMapTests(unittest.TestCase):
    def test_the_shipped_map_folds_libretros_genres_into_a_short_list(self):
        mapping = genre_map.load()
        self.assertTrue(mapping, "data/genres.csv should exist and be readable")
        displayed = set(mapping.values())
        # Twenty-four genres is more than a 168-pixel tab strip can show and
        # more than anyone wants to cycle past to reach Puzzle.
        self.assertLess(len(displayed), len(mapping))
        self.assertLessEqual(len(displayed), 16)
        for expected in ("Action", "Racing", "Sports", "Shooters", "Puzzle"):
            self.assertIn(expected, displayed)

    def test_every_genre_the_reference_library_uses_is_mapped(self):
        """The 24 genres libretro files N64 games under. A new one passing
        through is fine and reported; these are the known set."""
        mapping = genre_map.load()
        known = [
            "Action", "Adventure", "Beat'em Up", "Board", "Casual Game",
            "Compilation", "Educational", "Fighting", "Gambling",
            "Hunting and Fishing", "Lightgun Shooter", "Music / Dancing",
            "Platform", "Puzzle", "Quiz", "Racing", "Role-playing (RPG)",
            "Shoot'em Up", "Shooter", "Simulation", "Sports",
            "Sports with Animals", "Strategy", "Various",
        ]
        self.assertEqual(genre_map.unmapped(mapping, known), [])

    def test_an_unknown_genre_passes_through_and_is_reported(self):
        mapping = {"action": "Action"}
        self.assertEqual(genre_map.apply(mapping, "Roguelike"), "Roguelike")
        self.assertEqual(genre_map.unmapped(mapping, ["Roguelike", "Action"]), ["Roguelike"])

    def test_matching_ignores_case(self):
        self.assertEqual(genre_map.apply({"action": "Action"}, "ACTION"), "Action")

    def test_an_empty_genre_stays_empty(self):
        self.assertEqual(genre_map.apply({"action": "Action"}, ""), "")

    def test_malformed_maps_are_rejected(self):
        for bad in ("source\nAction\n", "source,genre\nAction,\n", "source,genre\n,Action\n",
                    "source,genre\nAction,A\nACTION,B\n"):
            with self.subTest(bad=bad), self.assertRaises(genre_map.GenreMapError):
                genre_map.loads(bad)


class BuildMetadataGenreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.roms = self.root / "ROMS"
        self.roms.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_the_catalog_carries_the_consolidated_genre(self):
        crc = write_rom(self.roms / "Brawler.z64", 0xA1, 0xA2)
        database = self.root / "db.csv"
        coverdb.save(database, [coverdb.Entry(crc=crc, name="Brawler (USA)",
                                              genre="Beat'em Up")])
        document, how = build_metadata.build(self.roms, coverdb_path=database,
                                             genres=genre_map.DEFAULT_PATH)
        self.assertEqual(document["games"][0]["genre"], "Action")
        self.assertEqual(how["genre consolidated"], 1)

    def test_pointing_at_a_missing_map_keeps_libretros_own_genres(self):
        crc = write_rom(self.roms / "Brawler.z64", 0xA1, 0xA2)
        database = self.root / "db.csv"
        coverdb.save(database, [coverdb.Entry(crc=crc, name="Brawler (USA)",
                                              genre="Beat'em Up")])
        document, _ = build_metadata.build(self.roms, coverdb_path=database,
                                           genres=self.root / "absent.csv")
        self.assertEqual(document["games"][0]["genre"], "Beat'em Up")


if __name__ == "__main__":
    unittest.main()
