# SPDX-License-Identifier: AGPL-3.0-only
"""What a game is, read off its name, its folder and the database."""

import unittest

from tools import build_catalog, custom_art, kinds


class ClassifyTests(unittest.TestCase):
    def kind(self, path, identified="crc", disk=False):
        return kinds.classify(path, identified, disk)

    def test_the_database_decides_when_the_name_says_nothing(self):
        self.assertEqual(self.kind("ROMS/Super Mario 64 (USA).z64", "crc"), kinds.RETAIL)
        # built on a retail game: the code is known, the dump is not
        self.assertEqual(self.kind("ROMS/Star Road.z64", "serial"), kinds.HACK)
        # a patch that rewrote the region byte too
        self.assertEqual(self.kind("ROMS/Sin and Punishment.z64", "serial without region"), kinds.TRANSLATION)
        # nothing knows it: a blank or made-up code
        self.assertEqual(self.kind("ROMS/Flappy.z64", ""), kinds.HOMEBREW)
        # a 64DD disk has no header to go by
        self.assertEqual(self.kind("ROMS/F-Zero X Expansion (Japan).ndd", "", disk=True), kinds.RETAIL)

    def test_the_name_wins_over_the_database(self):
        """A hack that never recomputed its header checksum still carries
        the retail CRC pair, so the database 'knows' it: the name is
        believed over that."""
        for name, kind in (("Mother 3 (Hack).z64", kinds.HACK), ("F-Zero X [h1C].z64", kinds.HACK),
                           ("Mario Kart 64 [hack].z64", kinds.HACK), ("Zelda Romhack.z64", kinds.HACK),
                           ("Sin and Punishment [T+Eng].z64", kinds.TRANSLATION),
                           ("Custom Robo (Translated).z64", kinds.TRANSLATION),
                           ("Doubutsu Banchou [T-Eng1.0].z64", kinds.TRANSLATION),
                           ("Flappy (PD).z64", kinds.HOMEBREW), ("Tetris (Homebrew).z64", kinds.HOMEBREW)):
            with self.subTest(name=name):
                self.assertEqual(self.kind("ROMS/" + name, "crc"), kind)

    def test_a_folder_says_what_its_games_are(self):
        self.assertEqual(self.kind("ROMS/Hacks/Star Road.z64", "crc"), kinds.HACK)
        self.assertEqual(self.kind("ROMS/ROM Hacks/Mario/Star Road.z64", "crc"), kinds.HACK)
        self.assertEqual(self.kind("ROMS/Translations/Zelda.z64", "serial"), kinds.TRANSLATION)
        self.assertEqual(self.kind("ROMS/Homebrew/Flappy.z64", "crc"), kinds.HOMEBREW)
        # the nearest folder speaks first
        self.assertEqual(self.kind("Hacks/Translations/Zelda.z64", "serial"), kinds.TRANSLATION)
        # and the file's own name before any folder
        self.assertEqual(self.kind("Hacks/Zelda [T+Eng].z64", "serial"), kinds.TRANSLATION)

    def test_a_real_release_the_database_lacks_is_not_taken_for_a_hack(self):
        self.assertEqual(self.kind("ROMS/Zelda (Beta).z64", "serial"), kinds.RETAIL)
        self.assertEqual(self.kind("ROMS/Mario Kart 64 (USA) (Rev 1).z64", "serial"), kinds.RETAIL)
        self.assertEqual(self.kind("ROMS/Banjo (Proto).z64", "serial"), kinds.RETAIL)
        self.assertEqual(self.kind("ROMS/Doom 64 (v1.1).z64", "serial"), kinds.RETAIL)

    def test_words_that_only_look_like_tags_say_nothing(self):
        self.assertEqual(self.kind("ROMS/Hackers Paradise.z64", "crc"), kinds.RETAIL)
        self.assertEqual(self.kind("ROMS/Hack and Slash/Gauntlet Legends (USA).z64", "crc"), kinds.RETAIL)
        self.assertEqual(self.kind("ROMS/Hack & Slash/Gauntlet Legends (USA).z64", "crc"), kinds.RETAIL)
        self.assertEqual(self.kind("ROMS/Shadowgate 64 (USA).z64", "crc"), kinds.RETAIL)


class StorageTests(unittest.TestCase):
    def test_the_kind_has_bits_of_its_own_in_the_record_flags(self):
        self.assertEqual(kinds.flags(kinds.RETAIL), 0, "an older catalog reads as retail")
        values = [kinds.flags(kind) for kind in kinds.KINDS]
        self.assertEqual(len(set(values)), len(kinds.KINDS))
        for value in values:
            self.assertEqual(value & ~kinds.FLAG_MASK, 0)
            self.assertEqual(value & (build_catalog.FLAG_FAVORITE | build_catalog.FLAG_SET_ASIDE), 0)
        self.assertEqual(kinds.flags(None), 0)

    def test_the_rom_names_the_same_values(self):
        from pathlib import Path
        header = (Path(__file__).resolve().parent.parent / "src" / "catalog.h").read_text(encoding="utf-8")
        self.assertIn(f"SM_KIND_SHIFT = {kinds.FLAG_SHIFT}", header)
        for kind, code in kinds.CODES.items():
            self.assertIn(f"SM_KIND_{kind.upper()} = {code}", header)

    def test_the_catalog_packs_the_kind_and_refuses_one_it_does_not_know(self):
        game = {"title": "Star Road", "path": "Star Road.z64", "kind": "hack"}
        packed = build_catalog.normalize({"schema_version": 1, "games": [game]})
        self.assertEqual(packed[0]["flags"], kinds.flags(kinds.HACK))
        packed = build_catalog.normalize({"schema_version": 1, "games": [dict(game, kind=None, favorite=True)]})
        self.assertEqual(packed[0]["flags"], build_catalog.FLAG_FAVORITE)
        with self.assertRaises(build_catalog.CatalogError):
            build_catalog.normalize({"schema_version": 1, "games": [dict(game, kind="mod")]})


class OwnerTests(unittest.TestCase):
    def test_a_kind_line_in_the_owners_file_is_a_fact_like_any_other(self):
        for written, kind in (("Hack", "hack"), ("hacks", "hack"), ("TRANSLATION", "translation"),
                              ("TL", "translation"), ("Homebrew", "homebrew"), ("HB", "homebrew"),
                              ("Retail", "retail")):
            with self.subTest(written=written):
                self.assertEqual(custom_art.parse_text(f"Kind: {written}\n\nText.")[2], {"kind": kind})
        self.assertEqual(custom_art.parse_text("Kind: mod\n\nText.")[2], {}, "an unknown kind is left unset")
        text = custom_art.format_text("Star Road", "Text.", {"kind": "hack", "genre": "Platforms"})
        self.assertEqual(text, "Title: Star Road\nGenre: Platforms\nKind: Hack\n\nText.\n")
        self.assertEqual(custom_art.parse_text(text)[2], {"genre": "Platforms", "kind": "hack"})


if __name__ == "__main__":
    unittest.main()
