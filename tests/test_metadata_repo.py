# SPDX-License-Identifier: AGPL-3.0-only
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import metadata_repo
from tools.metadata_repo import MetadataRepo

INI = """; Main metadata, in English
[meta]
name = Goldeneye 007 (USA | REVx)
author = Rare | Nintendo
release-date = 1997-08-25
; osi-license =
age-rating = 13
num-players = 4
short-desc = You are Bond, James Bond.
long-desc = description.txt

[boxart]
front = boxart_front.png
"""


def png(color):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGBA", (158, 112), color).save(out, format="PNG")
    return out.getvalue()


def collection(root: Path):
    """A small collection in the layout the release ships."""
    files = {
        "metadata/N/G/E/E/boxart_front.png": png((255, 0, 0, 255)),
        "metadata/N/G/E/E/metadata.ini": INI.encode(),
        "metadata/N/G/E/description.txt": b"You are Bond.\r\nJames Bond.\r\n",
        "metadata/N/G/E/P/boxart_front.png": png((0, 255, 0, 255)),
        "metadata/N/S/M/J/boxart_front.png": png((0, 0, 255, 255)),
        "metadata/N/S/M/boxart_front.png": png((0, 0, 0, 255)),
        "metadata/N/W/R/X/boxart_front.png": png((9, 9, 9, 255)),
        "metadata/N/Z/L/E/metadata.ini": b"[meta]\nshort-desc = Short only.\nnum-players = twelve\n",
    }
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return files


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.files = collection(self.root)
        self.repo = MetadataRepo.open(self.root)

    def tearDown(self):
        self.repo.close()
        self.temporary.cleanup()

    def test_the_cartridges_own_region_folder_is_found_first(self):
        found = self.repo.art("NGEE")
        self.assertEqual(found.key, "N/G/E/E")
        self.assertEqual(self.repo.read(found), self.files["metadata/N/G/E/E/boxart_front.png"])

    def test_every_pal_market_gets_the_pal_box(self):
        # A French cartridge: country F. There is no F folder; P serves it.
        self.assertEqual(self.repo.art("NGEF").key, "N/G/E/P")

    def test_the_three_character_folder_serves_every_region(self):
        self.assertEqual(self.repo.art("NSME").key, "N/S/M")

    def test_a_box_from_another_market_beats_no_box(self):
        # A Japanese cartridge with no J folder falls through to the USA one.
        self.assertEqual(self.repo.art("NGEJ").key, "N/G/E/E")

    def test_a_region_folder_the_order_does_not_name_is_still_tried_last(self):
        self.assertEqual(self.repo.art("NWRE").key, "N/W/R/X")

    def test_a_code_the_collection_lacks_is_none_not_an_error(self):
        self.assertIsNone(self.repo.art("NQQE"))

    def test_lookup_is_case_insensitive_like_the_card(self):
        self.assertEqual(self.repo.art("ngee").key, "N/G/E/E")

    def test_a_code_with_unprintable_characters_is_never_looked_up(self):
        self.assertIsNone(self.repo.art("N??E"))
        self.assertIsNone(self.repo.art(""))
        self.assertIsNone(self.repo.art("N/../E"))

    def test_the_ini_is_read_into_the_catalogs_vocabulary(self):
        info = self.repo.info("NGEE")
        self.assertEqual((info.author, info.year, info.players), ("Rare | Nintendo", 1997, 4))
        self.assertEqual(info.short_description, "You are Bond, James Bond.")

    def test_the_hoisted_description_is_found_from_the_region_folder(self):
        self.assertEqual(self.repo.description("NGEE"), "You are Bond. James Bond.")

    def test_the_short_description_stands_in_for_a_missing_long_one(self):
        self.assertEqual(self.repo.description("NZLE"), "Short only.")

    def test_a_player_count_that_is_not_a_number_is_unknown_not_a_crash(self):
        self.assertEqual(self.repo.info("NZLE").players, 0)

    def test_nothing_is_nothing(self):
        self.assertIsNone(self.repo.info("NSME"))
        self.assertEqual(self.repo.description("NSME"), "")

    def test_art_is_counted_for_the_report(self):
        self.assertEqual(self.repo.art_count(), 5)


class ContainerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.files = collection(self.root / "src")

    def tearDown(self):
        self.temporary.cleanup()

    def zipped(self, prefix=""):
        path = self.root / "release-metadata.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in self.files.items():
                archive.writestr(prefix + name, data)
        return path

    def test_the_release_zip_is_read_in_place(self):
        with MetadataRepo.open(self.zipped()) as repo:
            found = repo.art("NGEE")
            self.assertEqual(repo.read(found), self.files["metadata/N/G/E/E/boxart_front.png"])
            self.assertEqual(repo.description("NGEE"), "You are Bond. James Bond.")

    def test_a_zip_with_a_folder_above_metadata_still_works(self):
        with MetadataRepo.open(self.zipped("release/")) as repo:
            self.assertEqual(repo.art("NGEE").key, "N/G/E/E")

    def test_a_zip_without_the_collection_is_refused_with_a_reason(self):
        path = self.root / "other.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("readme.txt", b"nothing here")
        with self.assertRaises(metadata_repo.RepoError):
            MetadataRepo.open(path)

    def test_a_file_that_is_not_a_zip_is_refused_with_a_reason(self):
        path = self.root / "release-metadata.zip"
        path.write_bytes(b"not a zip")
        with self.assertRaises(metadata_repo.RepoError):
            MetadataRepo.open(path)

    def test_the_metadata_folder_itself_or_its_parent_both_open(self):
        parent = MetadataRepo.open(self.root / "src")
        inner = MetadataRepo.open(self.root / "src" / "metadata")
        self.assertEqual(parent.art("NGEE").path, inner.art("NGEE").path)

    def test_nothing_at_the_path_is_an_error(self):
        with self.assertRaises(metadata_repo.RepoError):
            MetadataRepo.open(self.root / "missing")


class CardSearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_a_bare_card_has_no_collection(self):
        self.assertIsNone(metadata_repo.find_on_card(self.card))

    def test_the_zip_beside_the_tool_is_found(self):
        (self.card / "release-metadata.zip").write_bytes(b"")
        self.assertEqual(metadata_repo.find_on_card(self.card), self.card / "release-metadata.zip")

    def test_the_zip_in_the_browsers_folder_is_preferred(self):
        (self.card / "sleekmenu").mkdir()
        (self.card / "sleekmenu" / "release-metadata.zip").write_bytes(b"")
        (self.card / "release-metadata.zip").write_bytes(b"")
        self.assertEqual(metadata_repo.find_on_card(self.card),
                         self.card / "sleekmenu" / "release-metadata.zip")

    def test_another_menus_folder_is_honoured(self):
        (self.card / "menu" / "metadata").mkdir(parents=True)
        self.assertEqual(metadata_repo.find_on_card(self.card), self.card / "menu" / "metadata")

    def test_the_pros_own_folder_is_found_last_and_read_at_half_width(self):
        """krikzz's edmeta writes the same layout under ED64/metadata with
        every picture stretched to double width for the Pro menu's 640-pixel
        mode. A card prepared for the Pro therefore needs nothing else."""
        collection(self.card / "ED64")
        self.assertEqual(metadata_repo.find_on_card(self.card), self.card / "ED64" / "metadata")
        with MetadataRepo.open(self.card / "ED64" / "metadata") as repo:
            self.assertEqual(repo.width_scale, 0.5)
            self.assertEqual(repo.art("NGEE").key, "N/G/E/E")
        collection(self.card / "menu")
        self.assertEqual(metadata_repo.find_on_card(self.card), self.card / "menu" / "metadata")
        with MetadataRepo.open(self.card / "menu" / "metadata") as repo:
            self.assertEqual(repo.width_scale, 1.0)


class RegionOrderTests(unittest.TestCase):
    def test_a_us_cartridge_owns_only_the_usa_folder(self):
        self.assertEqual(metadata_repo.region_order("NSME"), ["E"])

    def test_a_german_cartridge_owns_its_own_letter_and_the_pal_folder(self):
        self.assertEqual(metadata_repo.region_order("NSMD"), ["D", "P"])
        self.assertEqual(metadata_repo.region_order("NSMP"), ["P"])

    def test_a_japanese_cartridge_owns_only_japan(self):
        self.assertEqual(metadata_repo.region_order("NSMJ"), ["J"])

    def test_the_neutral_file_comes_before_another_markets_box(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collection(root)
            with MetadataRepo.open(root) as repo:
                # NSM has a Japanese box and a neutral one; a US cartridge
                # gets the neutral one, a Japanese one its own.
                self.assertEqual(repo.art("NSME").key, "N/S/M")
                self.assertEqual(repo.art("NSMJ").key, "N/S/M/J")


if __name__ == "__main__":
    unittest.main()
