# SPDX-License-Identifier: AGPL-3.0-only
"""The card-preparation tool: the entry point and the archive it ships as.

Two layers. The entry-point tests drive `sleekmenu_prep.main()` in-process
against a small metadata collection written into the card, so they are fast;
nothing here ever touches the network, because the tool never does. The
archive tests build the real .pyz and run it as a subprocess the way a person
does -- from a card, with no arguments -- because the whole point of the
archive is that it works with nothing else installed, and only running it
proves that.
"""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

from tests.rom_fixtures import write_rom
from tools import build_prep, card_layout, coverdb, sleekmenu_prep

ROOT = Path(__file__).resolve().parent.parent
PNG_BYTES = None


def png_bytes() -> bytes:
    global PNG_BYTES
    if PNG_BYTES is None:
        buffer = io.BytesIO()
        Image.new("RGBA", (158, 112), (10, 90, 160, 255)).save(buffer, format="PNG")
        PNG_BYTES = buffer.getvalue()
    return PNG_BYTES


def write_collection(where: Path, *codes: str, zipped: bool = False) -> Path:
    """A collection holding a box and a description for each code, as a
    folder or as the release zip."""
    entries = {}
    for code in codes:
        folder = "metadata/" + "/".join(code)
        entries[f"{folder}/boxart_front.png"] = png_bytes()
        entries[f"{folder}/description.txt"] = f"A description of {code}.".encode()
        entries[f"{folder}/metadata.ini"] = (
            f"[meta]\nname = {code}\nauthor = Someone | A Publisher\n"
            f"release-date = 1998-01-01\nnum-players = 2\n").encode()
    if zipped:
        where.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(where, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        return where
    for name, data in entries.items():
        target = where / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return where / "metadata"


class CardDiscoveryTests(unittest.TestCase):
    def test_from_a_checkout_it_refuses_to_guess(self):
        """`python3 tools/sleekmenu_prep.py` from the repository must not decide
        that tools/ is a card. It says what to do instead."""
        with mock.patch.object(sys, "argv", ["tools/sleekmenu_prep.py"]):
            with self.assertRaises(sleekmenu_prep.PrepError) as caught:
                sleekmenu_prep.find_card(None)
        self.assertIn("--card", str(caught.exception))

    def test_an_explicit_card_must_exist(self):
        with self.assertRaises(sleekmenu_prep.PrepError):
            sleekmenu_prep.find_card(Path("/nonexistent/card"))

    def test_a_pyz_on_the_card_means_the_card_is_where_it_is(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            card.mkdir()
            archive = card / "sleekmenu-prep.pyz"
            archive.write_bytes(b"PK")
            with mock.patch.object(sys, "argv", [str(archive)]):
                self.assertEqual(sleekmenu_prep.find_card(None), card.resolve())

    def test_a_missing_roms_folder_is_made_and_reported(self):
        """A fresh card has no ROMS/ yet. Making it and saying so beats an
        error naming a folder the person has never heard of."""
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch)
            roms, created = sleekmenu_prep.find_roms(card, None)
            self.assertEqual(roms, card / "ROMS")
            self.assertTrue(created)
            self.assertTrue(roms.is_dir())
            roms, created = sleekmenu_prep.find_roms(card, None)
            self.assertFalse(created)

    def test_a_dry_run_does_not_make_folders(self):
        with tempfile.TemporaryDirectory() as scratch:
            with self.assertRaises(sleekmenu_prep.PrepError):
                sleekmenu_prep.find_roms(Path(scratch), None, create=False)
            self.assertFalse((Path(scratch) / "ROMS").exists())

    def test_an_explicit_roms_folder_that_does_not_exist_is_still_an_error(self):
        """That one was typed; guessing what was meant would be worse than
        saying it is not there."""
        with tempfile.TemporaryDirectory() as scratch:
            with self.assertRaises(sleekmenu_prep.PrepError):
                sleekmenu_prep.find_roms(Path(scratch), Path(scratch) / "Games")

    def test_the_card_folders_are_laid_out_once(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch)
            made = sleekmenu_prep.lay_out(card)
            self.assertEqual([m.relative_to(card).as_posix() for m in made], ["sleekmenu"])
            self.assertEqual(sleekmenu_prep.lay_out(card), [])


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name) / "CARD"
        self.roms = self.card / "ROMS"
        self.roms.mkdir(parents=True)
        self.crc = write_rom(self.roms / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")

    def tearDown(self):
        self.temporary.cleanup()

    def run_prep(self, *args):
        """main() with the bundled database replaced by one that knows our ROM."""
        database = {self.crc: coverdb.Entry(crc=self.crc, name="Wave Race 64 (USA)",
                                            serial="NWRE", genre="Racing", year=1996)}
        db_path = self.card / "test-coverdb.csv"
        coverdb.save(db_path, database.values())
        # The tool writes its progress straight to stdout, on purpose, so
        # silencing print() is not enough to keep a test run readable.
        out = io.StringIO()
        with mock.patch.object(sleekmenu_prep, "data_file",
                               lambda name, work: db_path if name == "coverdb.csv"
                               else ROOT / "data" / "genres.csv"), \
             contextlib.redirect_stdout(out), \
             contextlib.redirect_stderr(io.StringIO()):
            code = sleekmenu_prep.main(["--card", str(self.card), *args])
        self.output = out.getvalue()
        return code

    def test_a_collection_zip_beside_the_tool_is_read_in_place(self):
        write_collection(self.card / "release-metadata.zip", "NWRE", zipped=True)
        code = self.run_prep()
        self.assertEqual(code, 0, self.output)
        out = self.card / card_layout.CARD_FOLDER
        self.assertTrue((out / card_layout.CATALOG_NAME).is_file())
        self.assertTrue((out / card_layout.COVER_PACK_NAME).is_file())
        self.assertIn(b"A description of NWRE.", (out / card_layout.CATALOG_NAME).read_bytes())
        # and nothing was unpacked onto the card
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         [card_layout.CATALOG_NAME, card_layout.COVER_PACK_NAME])

    def test_a_collection_unpacked_for_another_menu_is_honoured(self):
        write_collection(self.card / "menu", "NWRE")
        code = self.run_prep()
        self.assertEqual(code, 0, self.output)
        self.assertTrue((self.card / card_layout.CARD_FOLDER / card_layout.COVER_PACK_NAME).is_file())

    def test_an_explicit_collection_anywhere_wins(self):
        elsewhere = write_collection(Path(self.temporary.name) / "elsewhere", "NWRE")
        code = self.run_prep("--metadata", str(elsewhere))
        self.assertEqual(code, 0, self.output)
        self.assertTrue((self.card / card_layout.CARD_FOLDER / card_layout.COVER_PACK_NAME).is_file())

    def test_no_collection_still_writes_a_catalog_and_says_where_to_get_one(self):
        code = self.run_prep()
        self.assertEqual(code, 0, self.output)
        out = self.card / card_layout.CARD_FOLDER
        self.assertTrue((out / card_layout.CATALOG_NAME).is_file())
        self.assertFalse((out / card_layout.COVER_PACK_NAME).exists())
        self.assertIn("release-metadata.zip", self.output)
        self.assertIn("github.com/n64-tools/n64-flashcart-menu-metadata", self.output)

    def test_a_collection_the_library_is_absent_from_is_not_an_error(self):
        write_collection(self.card / "release-metadata.zip", "NZZZ", zipped=True)
        code = self.run_prep()
        self.assertEqual(code, 0, self.output)
        out = self.card / card_layout.CARD_FOLDER
        self.assertTrue((out / card_layout.CATALOG_NAME).is_file())
        self.assertFalse((out / card_layout.COVER_PACK_NAME).exists())

    def test_a_broken_collection_is_reported_not_a_traceback(self):
        (self.card / "release-metadata.zip").write_bytes(b"not a zip at all")
        code = self.run_prep()
        self.assertEqual(code, 1)

    def test_dry_run_writes_nothing_to_the_card(self):
        write_collection(self.card / "release-metadata.zip", "NWRE", zipped=True)
        code = self.run_prep("--dry-run")
        self.assertEqual(code, 0, self.output)
        self.assertFalse((self.card / card_layout.CARD_FOLDER).exists())

    def test_a_fresh_card_gets_its_folders_and_a_message_not_a_catalog(self):
        """No ROMS/ at all: the run lays the card out, tells the person where
        the games go, and stops -- cleanly, exit 0, nothing half-built."""
        shutil.rmtree(self.roms)
        code = self.run_prep()
        self.assertEqual(code, 0)
        self.assertTrue((self.card / "ROMS").is_dir())
        self.assertTrue((self.card / card_layout.CARD_FOLDER).is_dir())
        self.assertFalse((self.card / card_layout.CARD_FOLDER / card_layout.CATALOG_NAME).exists())

    def test_an_empty_roms_folder_is_a_message_not_an_empty_card(self):
        for rom in self.roms.iterdir():
            rom.unlink()
        code = self.run_prep()
        self.assertEqual(code, 0)
        self.assertFalse((self.card / card_layout.CARD_FOLDER / card_layout.CATALOG_NAME).exists())


class ArchiveTests(unittest.TestCase):
    """The .pyz itself. Built once for the class; several seconds otherwise."""

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.archive = Path(cls.temporary.name) / "sleekmenu-prep.pyz"
        build_prep.build(cls.archive)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_it_carries_the_database_and_its_licence_but_not_the_tests(self):
        names = build_prep.contents(self.archive)
        self.assertIn("sleekmenu_data/coverdb.csv", names)
        self.assertIn("sleekmenu_data/genres.csv", names)
        self.assertIn("sleekmenu_data/LICENSE", names)
        self.assertIn("tools/sleekmenu_prep.py", names)
        self.assertFalse(any(n.startswith("tests/") for n in names))
        self.assertNotIn("tools/build_prep.py", names, "the builder does not ship in what it builds")
        # and no pictures, ever
        self.assertFalse(any(n.endswith((".png", ".jpg", ".sprite")) for n in names))

    def test_it_is_small(self):
        """Half of it is the database. If this doubles, something image-shaped
        got in."""
        self.assertLess(self.archive.stat().st_size, 300 * 1024)

    def test_it_is_reproducible(self):
        again = Path(self.temporary.name) / "again.pyz"
        build_prep.build(again)
        self.assertEqual(self.archive.read_bytes(), again.read_bytes())

    def test_it_runs_with_no_checkout_anywhere_near_it(self):
        """The reason it exists. From an empty directory, with the repository
        nowhere on the path, --help must work -- which means every import
        inside the archive resolved."""
        with tempfile.TemporaryDirectory() as elsewhere:
            copy = Path(elsewhere) / "sleekmenu-prep.pyz"
            shutil.copy2(self.archive, copy)
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            result = subprocess.run([sys.executable, str(copy), "--help"], cwd=elsewhere,
                                    capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Prepare an SD card", result.stdout)

    def test_from_a_card_with_no_arguments_it_finds_the_card_and_uses_its_own_database(self):
        """The whole promise, end to end, offline: copy the archive next to
        ROMS/, run it, get a card. The bundled database identifies the
        cartridge -- a real CRC from data/coverdb.csv -- so the catalog carries
        a genre the ROM's filename never mentioned."""
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            (card / "ROMS").mkdir(parents=True)
            copy = card / "sleekmenu-prep.pyz"
            shutil.copy2(self.archive, copy)
            # a cartridge the bundled database knows
            database = coverdb.load(ROOT / "data" / "coverdb.csv")
            crc, entry = next((c, e) for c, e in database.items()
                              if e.genre and e.name == "Super Mario 64 (USA)")
            write_rom(card / "ROMS" / "mario.z64", int(crc[:8], 16), int(crc[8:], 16))
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            result = subprocess.run([sys.executable, str(copy)], cwd=card,
                                    capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            catalog = card / card_layout.CARD_FOLDER / card_layout.CATALOG_NAME
            self.assertTrue(catalog.is_file())
            self.assertIn(entry.genre.encode("utf-8"), catalog.read_bytes())
            self.assertIn("1 with genre", result.stdout)


if __name__ == "__main__":
    unittest.main()
