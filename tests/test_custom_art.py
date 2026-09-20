# SPDX-License-Identifier: AGPL-3.0-only
"""The card owner's own pictures and text, by ROM name or game code."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tests.rom_fixtures import write_rom
from tools import provenance, build_metadata, cover_pack, custom_art, pack_covers, prepare_card
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

    def test_header_lines_set_the_facts_and_bad_values_are_left_unset(self):
        """Any of the facts, in any order, checked the way the catalog
        checks them; the first line that is not a header starts the text,
        so a description that happens to begin with a word and a colon
        survives when no header precedes it... unless the word is one of
        the six, which is the price of a format with no delimiter."""
        (self.roms / "Hacks" / "SM64 Star Road.txt").write_text(
            "Genre: Platforms\nyear: 2011\nPLAYERS: 1\nRegion: us, jpn\nPublisher:  Skelux \n"
            "Title: Star Road\n\nA hack.\n", encoding="utf-8")
        text = custom_art.find_text(custom_art.Index(), self.roms, "Hacks/SM64 Star Road.z64", self.art)
        self.assertEqual(text.title, "Star Road")
        self.assertEqual(text.description, "A hack.")
        self.assertEqual(text.facts, {"genre": "Platforms", "year": 2011, "players": 1,
                                      "regions": ["USA", "JAPAN"], "publisher": "Skelux"})
        (self.roms / "Hacks" / "SM64 Star Road.txt").write_text(
            "Year: soon\nPlayers: 0\nRegions: mars\nGenre:\nNote: the first real line.\n", encoding="utf-8")
        text = custom_art.find_text(custom_art.Index(), self.roms, "Hacks/SM64 Star Road.z64", self.art)
        self.assertEqual(text.facts, {})
        self.assertEqual(text.description, "Note: the first real line.")
        self.assertEqual(custom_art.format_text("T", "D", {"year": 1999, "regions": ["USA"], "players": 0}),
                         "Title: T\nYear: 1999\nRegions: USA\n\nD\n")
        self.assertEqual(custom_art.format_text("", "", {"genre": "Racing"}), "Genre: Racing\n")


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

    def test_the_owners_facts_win_over_the_database_and_are_marked_yours(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            roms = card / "ROMS"
            write_rom(roms / "Game.z64", 1, 2, game_code="GA")
            (card / "sleekmenu" / "art").mkdir(parents=True)
            (card / "sleekmenu" / "art" / "Game.txt").write_text(
                "Genre: Puzzle\nYear: 2001\nPlayers: 2\nRegions: EUROPE\n", encoding="utf-8")
            document, how = build_metadata.build(roms, card, coverdb_path=card / "none.csv")
            game = document["games"][0]
            self.assertEqual((game["genre"], game["year"], game["players"], game["regions"]),
                             ("Puzzle", 2001, 2, ["EUROPE"]))
            self.assertEqual(game["publisher"], "")
            self.assertEqual(game["sources"]["genre"], provenance.YOURS)
            self.assertEqual(game["sources"]["year"], provenance.YOURS)
            self.assertEqual(game["sources"]["players"], provenance.YOURS)
            self.assertEqual(game["sources"]["publisher"], provenance.NONE)
            self.assertEqual(game["description"], "")
            self.assertTrue(provenance.edited(game["sources"]))


if __name__ == "__main__":
    unittest.main()


class EditTests(unittest.TestCase):
    """What the window writes and removes on the catalog tab: the same
    files a person would drop into sleekmenu/art/ by hand."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name)
        self.roms = self.card / "ROMS"
        self.art = self.card / "sleekmenu" / "art"
        # Catalog paths are relative to the card, so the card is the root
        # every lookup is made against.
        write_rom(self.roms / "Hacks" / "Star Road.z64", 1, 2, game_code="SM")
        write_rom(self.roms / "Mario.z64", 3, 4, game_code="SM")
        self.hack = {"path": "ROMS/Hacks/Star Road.z64", "code": "NSME", "title": "Star Road"}
        self.mario = {"path": "ROMS/Mario.z64", "code": "NSME", "title": "Mario"}
        self.source = picture(self.card / "downloads" / "box.JPG")

    def tearDown(self):
        self.temporary.cleanup()

    def test_save_for_this_rom_copies_the_picture_and_writes_the_text(self):
        touched = custom_art.save(self.card, self.hack, self.source, " Super Mario Star Road ",
                                  "A hack.\n\nWith  two paragraphs.")
        self.assertEqual(sorted(p.name for p in touched), ["Star Road.jpg", "Star Road.txt"])
        self.assertEqual((self.art / "Star Road.jpg").read_bytes(), self.source.read_bytes(), "copied as it is")
        self.assertEqual((self.art / "Star Road.txt").read_text(),
                         "Title: Super Mario Star Road\n\nA hack. With two paragraphs.\n")
        found = custom_art.find_art(custom_art.Index(), self.card, "ROMS/Hacks/Star Road.z64", self.art, "NSME")
        self.assertEqual(found.path, self.art / "Star Road.jpg")
        text = custom_art.find_text(custom_art.Index(), self.card, "ROMS/Hacks/Star Road.z64", self.art, "NSME")
        self.assertEqual((text.title, text.description), ("Super Mario Star Road", "A hack. With two paragraphs."))

    def test_save_by_code_reaches_every_rom_with_it_and_text_by_code_is_found(self):
        self.assertEqual(custom_art.sharing_code([self.hack, self.mario], self.hack), 2)
        custom_art.save(self.card, self.mario, None, "", "The one everyone has.", scope=custom_art.SCOPE_CODE)
        self.assertTrue((self.art / "NSME.txt").is_file())
        for rom_path in ("ROMS/Mario.z64", "ROMS/Hacks/Star Road.z64"):
            text = custom_art.find_text(custom_art.Index(), self.card, rom_path, self.art, "NSME")
            self.assertEqual(text.description, "The one everyone has.")
        with self.assertRaises(custom_art.EditError):
            custom_art.save(self.card, {"path": "ROMS/x.z64", "code": ""}, None, "t", "", scope=custom_art.SCOPE_CODE)

    def test_a_new_picture_replaces_one_of_the_other_suffix(self):
        custom_art.save(self.card, self.hack, self.source, "", "")
        png = picture(self.card / "downloads" / "box.png")
        touched = custom_art.save(self.card, self.hack, png, "", "")
        self.assertEqual(sorted(p.name for p in touched), ["Star Road.jpg", "Star Road.png"])
        self.assertFalse((self.art / "Star Road.jpg").exists())
        self.assertTrue((self.art / "Star Road.png").is_file())

    def test_a_file_that_is_not_a_picture_is_refused_and_nothing_is_written(self):
        bad = self.card / "downloads" / "box.png"
        bad.write_bytes(b"not a picture")
        with self.assertRaises(custom_art.EditError):
            custom_art.save(self.card, self.hack, bad, "", "")
        with self.assertRaises(custom_art.EditError):
            custom_art.save(self.card, self.hack, self.card / "downloads" / "box.gif", "", "")
        self.assertFalse(self.art.exists())

    def test_pending_edits_are_what_the_next_prepare_would_change(self):
        """Saved but not yet prepared: the fields that differ from the
        catalog, a picture newer than the catalog, and an owner's field
        whose file has gone. A file the last Prepare already read is not
        pending, however old."""
        import time
        document = {"built": "2026-09-20T00:00:00+00:00", "games": [
            dict(self.hack, genre="Racing", year=1996, players=0, regions=["USA"], description="",
                 sources={"title": "file name", "cover": "collection", "genre": "database",
                          "description": "none", "year": "database", "players": "none", "publisher": "none"}),
            dict(self.mario, title="Mario", description="Own.", genre="", regions=[],
                 sources={"title": "file name", "cover": "yours (this ROM)", "description": "yours",
                          "genre": "yours", "year": "none", "players": "none", "publisher": "none"}),
        ]}
        # Mario's catalog says the owner gave a picture, a text and a genre,
        # and none of those files are on the card: the next Prepare takes
        # them back. The hack has nothing of the owner's yet.
        pending = custom_art.pending_edits(self.card, self.card, document)
        self.assertEqual(set(pending), {"ROMS/Mario.z64"})
        self.assertEqual(pending["ROMS/Mario.z64"].fields, {})
        self.assertEqual(pending["ROMS/Mario.z64"].removed, ("description", "genre", "cover"))
        custom_art.save(self.card, self.hack, self.source, "Star Road DX", "A hack.",
                        facts={"genre": "Platforms", "year": 1996, "regions": ["USA"], "players": 2})
        pending = custom_art.pending_edits(self.card, self.card, document)
        self.assertEqual(set(pending), {"ROMS/Hacks/Star Road.z64", "ROMS/Mario.z64"})
        hack = pending["ROMS/Hacks/Star Road.z64"]
        # the year and the regions already match the catalog: not pending
        self.assertEqual(hack.fields, {"title": "Star Road DX", "description": "A hack.",
                                       "genre": "Platforms", "players": 2})
        self.assertEqual(hack.picture, self.art / "Star Road.jpg")
        self.assertEqual(hack.removed, ())
        # once the catalog carries the edit, and the picture is older than
        # it, nothing is pending
        document["games"][0].update(title="Star Road DX", description="A hack.", genre="Platforms",
                                    players=2, sources={"cover": "yours (this ROM)", "title": "yours"})
        document["built"] = "2100-01-01T00:00:00+00:00"
        (self.art / "Mario.txt").write_text("Own.\n")
        picture(self.art / "Mario.png")
        document["games"][1]["regions"] = []
        pending = custom_art.pending_edits(self.card, self.card, document)
        self.assertNotIn("ROMS/Hacks/Star Road.z64", pending)
        self.assertEqual(pending["ROMS/Mario.z64"].removed, ("genre",))
        self.assertIsNone(pending["ROMS/Mario.z64"].picture)
        time.sleep(0)

    def test_empty_text_removes_the_text_file_and_remove_deletes_only_the_art_folders_files(self):
        custom_art.save(self.card, self.hack, self.source, "T", "D")
        custom_art.save(self.card, self.hack, None, "", "")
        self.assertFalse((self.art / "Star Road.txt").exists(), "cleared fields mean no text of yours")
        self.assertTrue((self.art / "Star Road.jpg").is_file(), "the picture stays")
        beside = picture(self.roms / "Hacks" / "Star Road.png")
        removable, kept = custom_art.edits_of(self.card, self.card, self.hack)
        self.assertEqual(kept, [beside], "beside the ROM wins, and is only named")
        self.assertEqual(removable, [])
        beside.unlink()
        removable, kept = custom_art.edits_of(self.card, self.card, self.hack)
        self.assertEqual(removable, [self.art / "Star Road.jpg"])
        self.assertEqual(custom_art.remove(self.card, self.card, self.hack), [self.art / "Star Road.jpg"])
        self.assertEqual(list(self.art.iterdir()), [])
