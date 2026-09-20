# SPDX-License-Identifier: AGPL-3.0-only
"""The card-preparation tool: the entry point and the archive it ships as.

Two layers. The entry-point tests drive `sleekmenu_prep.main()` in-process
against a small metadata collection written into the card, so they are fast.
The archive tests build the real .pyz and run it as a subprocess the way a
person does -- from a card, with no arguments -- because the whole point of
the archive is that it works with nothing else installed, and only running
it proves that.

Nothing here touches the network: every run is told to stay offline through
the environment, the way CI is. What the tool does on a card that lacks the
collection, and how it fetches one, is tests/test_fetch.py, against a server
in the test process.
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
from tools import build_prep, card_catalog, card_layout, coverdb, custom_art, fetch, library, sleekmenu_prep

ROOT = Path(__file__).resolve().parent.parent
PNG_BYTES = None
OFFLINE = {fetch.OFFLINE_VARIABLE: "1"}


def stay_offline(test: unittest.TestCase) -> None:
    """The tool told, for the length of one test, never to fetch."""
    patch = mock.patch.dict(os.environ, OFFLINE)
    patch.start()
    test.addCleanup(patch.stop)


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

    def test_a_card_with_no_games_gets_a_roms_folder_and_says_so(self):
        """A fresh card has nothing on it. Making ROMS/ and saying so beats
        an error naming a folder the person has never heard of."""
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch)
            found = sleekmenu_prep.find_library(card, None)
            self.assertEqual(found.created, card / "ROMS")
            self.assertTrue(found.created.is_dir())
            self.assertEqual(found.rom_paths, [])
            found = sleekmenu_prep.find_library(card, None)
            self.assertIsNone(found.created, "made once, then it is just an empty folder")

    def test_a_dry_run_does_not_make_folders(self):
        with tempfile.TemporaryDirectory() as scratch:
            found = sleekmenu_prep.find_library(Path(scratch), None, create=False)
            self.assertIsNone(found.created)
            self.assertFalse((Path(scratch) / "ROMS").exists())

    def test_an_explicit_roms_folder_that_does_not_exist_is_still_an_error(self):
        """That one was typed; guessing what was meant would be worse than
        saying it is not there."""
        with tempfile.TemporaryDirectory() as scratch:
            with self.assertRaises(sleekmenu_prep.PrepError):
                sleekmenu_prep.find_library(Path(scratch), Path(scratch) / "Games")

    def test_games_are_found_wherever_they_are_on_the_card(self):
        """Nothing is assumed about `ROMS`: a folder of any name, several
        folders, and files loose at the root are all the library, recorded
        relative to the card so every launch resolves."""
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch)
            write_rom(card / "Games" / "Alpha.z64", 1, 2)
            write_rom(card / "Hacks" / "Beta.z64", 3, 4)
            write_rom(card / "Loose.z64", 5, 6)
            found = sleekmenu_prep.find_library(card, None)
            self.assertEqual(found.root, card)
            self.assertEqual(found.rom_paths, ["Games/Alpha.z64", "Hacks/Beta.z64", "Loose.z64"])
            self.assertIsNone(found.created)
            self.assertEqual(sleekmenu_prep.describe_library(found),
                             "1 at the card root, 1 in Games/, 1 in Hacks/")

    def test_the_browsers_own_files_and_the_systems_are_never_games(self):
        """SleekMenu64.z64 sits at the card root and is a .z64; the
        N64FlashcartMenu's folder holds a .n64; macOS leaves a `._` twin
        beside every file it copies; the firmware folder holds saves. None
        of them is a game."""
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch)
            write_rom(card / "ROMS" / "Alpha.z64", 1, 2)
            (card / card_layout.BROWSER_ROM).write_bytes(b"\x80\x37\x12\x40" + bytes(60))
            (card / "ROMS" / "._Alpha.z64").write_bytes(b"\x00\x05\x16\x07")
            write_rom(card / "menu" / "sc64menu.n64", 7, 8)
            write_rom(card / "ED64" / "OS64.v64", 9, 10)
            write_rom(card / "System Volume Information" / "x.z64", 11, 12)
            write_rom(card / ".Trashes" / "y.z64", 13, 14)
            found = sleekmenu_prep.find_library(card, None)
            self.assertEqual(found.rom_paths, ["ROMS/Alpha.z64"])

    def test_a_folder_is_recorded_as_the_card_spells_it(self):
        """`--roms ROMS` on a card whose folder is `roms`: the catalog must say
        `roms`, or the browser shows a folder the card does not have. Only
        a case-insensitive file system can stage this, so the spelling
        helper is checked directly."""
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch)
            write_rom(card / "roms" / "Alpha.z64", 1, 2)
            spelled = library.spelled_on_disk(card, card / "roms")
            self.assertEqual(spelled.name, "roms")
            found = sleekmenu_prep.find_library(card, None)
            self.assertEqual(found.rom_paths, ["roms/Alpha.z64"])
            with mock.patch("os.listdir", lambda path: ["roms", "other"]):
                self.assertEqual(library.spelled_on_disk(card, card / "ROMS").name, "roms")
                self.assertEqual(library.spelled_on_disk(card, card / "ROMS" / "US").name, "US")

    def test_the_card_folders_are_laid_out_once(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch)
            made = sleekmenu_prep.lay_out(card)
            self.assertEqual([m.relative_to(card).as_posix() for m in made], ["sleekmenu"])
            self.assertEqual(sleekmenu_prep.lay_out(card), [])


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        stay_offline(self)
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
                         [card_layout.CATALOG_NAME, card_layout.CATALOG_JSON_NAME,
                          card_layout.COVER_PACK_LARGE_NAME, card_layout.COVER_PACK_NAME])
        self.assertIn("large:    1 covers for the box view", self.output)
        # --no-large-covers leaves the box view's pack out of the run (and,
        # as with everything else, never deletes the one already there)
        (out / card_layout.COVER_PACK_LARGE_NAME).unlink()
        code = self.run_prep("--no-large-covers")
        self.assertEqual(code, 0, self.output)
        self.assertTrue((out / card_layout.COVER_PACK_NAME).is_file())
        self.assertFalse((out / card_layout.COVER_PACK_LARGE_NAME).exists())
        self.assertNotIn("large:", self.output)

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
        self.assertIn("anywhere on the card", self.output)

    def test_a_hack_with_a_stale_checksum_is_named_and_fixed_only_on_request(self):
        """A dump the database does not know is summed the way the boot
        code sums it. A mismatch is reported with the file's name; the file
        is rewritten only with --fix-checksums, and a dump the database
        knows is never read a megabyte deep."""
        from tests.test_n64_checksum import synthetic, with_boot_code
        image = with_boot_code(synthetic(), 6102)
        image[0x10:0x18] = bytes(8)
        hack = self.roms / "Hacks" / "Wave Race 64 - Shoreline (hack).z64"
        hack.parent.mkdir()
        hack.write_bytes(bytes(image))
        code = self.run_prep()
        self.assertEqual(code, 0, self.output)
        self.assertIn("1 with a header that does not match", self.output)
        self.assertIn("BAD     ROMS/Hacks/Wave Race 64 - Shoreline (hack).z64", self.output)
        self.assertIn("--fix-checksums", self.output)
        self.assertEqual(hack.read_bytes()[0x10:0x18], bytes(8), "not touched")

        code = self.run_prep("--fix-checksums", "--dry-run")
        self.assertEqual(code, 0, self.output)
        self.assertEqual(hack.read_bytes()[0x10:0x18], bytes(8), "a dry run writes nothing")

        code = self.run_prep("--fix-checksums")
        self.assertEqual(code, 0, self.output)
        self.assertIn("fixed   ROMS/Hacks/Wave Race 64 - Shoreline (hack).z64", self.output)
        self.assertNotEqual(hack.read_bytes()[0x10:0x18], bytes(8))
        self.assertEqual(hack.read_bytes()[0x18:], bytes(image[0x18:]))

        code = self.run_prep()
        self.assertIn("0 with a header that does not match", self.output)
        code = self.run_prep("--no-checksums")
        self.assertNotIn("checksum:", self.output)

    def test_a_second_run_reads_nothing_it_remembers_and_writes_no_pack_it_need_not(self):
        """The catalog carries every header, every checksum verdict, what
        each sprite was made from and what each pack came to. A second run
        over an unchanged card opens no ROM, converts no picture and writes
        no pack; a new ROM is read and only it; a changed picture is
        converted and only it; --rebuild does everything again."""
        from tests.test_n64_checksum import synthetic, with_boot_code
        from tools import headers
        write_collection(self.card / "release-metadata.zip", "NWRE", zipped=True)
        hack = self.roms / "Hacks" / "Shoreline.z64"
        hack.parent.mkdir()
        hack.write_bytes(bytes(with_boot_code(synthetic(), 6102)))
        png_path = self.card / "sleekmenu" / "art" / "Shoreline.png"
        png_path.parent.mkdir(parents=True)
        png_path.write_bytes(png_bytes())
        out = self.card / card_layout.CARD_FOLDER
        self.assertEqual(self.run_prep(), 0, self.output)
        self.assertIn("2 converted", self.output)
        first = card_catalog.load(self.card)
        games = {game["path"]: game for game in first["games"]}
        self.assertIn("header", games["ROMS/Wave Race 64 (USA).z64"]["file"])
        self.assertEqual(games["ROMS/Hacks/Shoreline.z64"]["checksum"], {"known": True, "matches": False})
        self.assertEqual(set(first["sprites"]), {"NWRE.sprite", custom_art.per_rom_sprite("ROMS/Hacks/Shoreline.z64")})
        self.assertEqual(set(first["packs"]), {card_layout.COVER_PACK_NAME, card_layout.COVER_PACK_LARGE_NAME})
        stamp = (out / card_layout.COVER_PACK_LARGE_NAME).stat().st_mtime_ns

        # unchanged: nothing opened, nothing converted, nothing written
        headers.clear()
        self.assertEqual(self.run_prep(), 0, self.output)
        self.assertIn("2 unchanged since the last run, 0 read", self.output)
        self.assertIn("1 unchanged since the last run, not read again", self.output)
        self.assertIn("0 converted, 2 kept from the last run", self.output)
        self.assertIn(f"{card_layout.COVER_PACK_LARGE_NAME} is what the card has; not written again", self.output)
        self.assertEqual((out / card_layout.COVER_PACK_LARGE_NAME).stat().st_mtime_ns, stamp)
        self.assertEqual(headers.opened, 0)

        # a game added: it alone is read; the packs change and are written
        write_rom(self.roms / "Zelda.z64", 0x33, 0x44, game_code="ZL")
        headers.clear()
        self.assertEqual(self.run_prep(), 0, self.output)
        self.assertIn("2 unchanged since the last run, 1 read", self.output)
        self.assertEqual(headers.opened, 1)
        self.assertIn("0 converted, 2 kept from the last run", self.output)
        self.assertIn(f"{card_layout.COVER_PACK_LARGE_NAME} is what the card has; not written again", self.output)

        # the owner's picture replaced, with an old date: it alone is
        # converted, and the packs are written
        from tests.test_custom_art import picture
        picture(png_path, color=(20, 200, 40, 255))
        os.utime(png_path, (0, 0))
        headers.clear()
        self.assertEqual(self.run_prep(), 0, self.output)
        self.assertIn("1 converted, 1 kept from the last run", self.output)
        self.assertNotIn("not written again", self.output)
        self.assertNotEqual((out / card_layout.COVER_PACK_LARGE_NAME).stat().st_mtime_ns, stamp)

        # --rebuild: as if there were no catalog
        headers.clear()
        self.assertEqual(self.run_prep("--rebuild"), 0, self.output)
        self.assertNotIn("unchanged since the last run", self.output)
        self.assertIn("2 converted", self.output)
        self.assertEqual(headers.opened, 3)

    def test_a_chosen_folder_is_scanned_alone_and_remembered_until_the_whole_card_is_asked_for(self):
        """--roms ROMS: only ROMS/ is catalogued, what is elsewhere is
        counted and named, and the choice holds on the next plain run --
        the archive is run from the card with no arguments. `--roms .` is
        the whole card again, and forgets."""
        write_rom(self.card / "Other" / "Loose.z64", 5, 6)
        code = self.run_prep("--roms", "roms")           # typed in the wrong case, on purpose
        self.assertEqual(code, 0, self.output)
        self.assertIn("under ROMS/ (chosen)", self.output)
        self.assertIn("1 ROM-shaped file elsewhere on the card left out: Other/Loose.z64", self.output)
        catalog = (self.card / card_layout.CARD_FOLDER / card_layout.CATALOG_NAME).read_bytes()
        self.assertIn(b"ROMS/Wave Race 64 (USA).z64", catalog)
        self.assertNotIn(b"Other/Loose.z64", catalog)
        self.assertEqual(card_catalog.remembered_roms(self.card), "ROMS")

        code = self.run_prep()
        self.assertEqual(code, 0, self.output)
        self.assertIn("under ROMS/ (remembered)", self.output)
        self.assertIn("--roms .", self.output)
        catalog = (self.card / card_layout.CARD_FOLDER / card_layout.CATALOG_NAME).read_bytes()
        self.assertNotIn(b"Other/Loose.z64", catalog)

        code = self.run_prep("--roms", ".")
        self.assertEqual(code, 0, self.output)
        self.assertIn("(whole card)", self.output)
        catalog = (self.card / card_layout.CARD_FOLDER / card_layout.CATALOG_NAME).read_bytes()
        self.assertIn(b"Other/Loose.z64", catalog)
        self.assertEqual(card_catalog.remembered_roms(self.card), "")
        code = self.run_prep()
        self.assertNotIn("remembered", self.output)

        # a remembered folder that has since gone is a note, not an error
        self.run_prep("--roms", "Other")
        shutil.rmtree(self.card / "Other")
        code = self.run_prep()
        self.assertEqual(code, 0, self.output)
        self.assertIn("chosen last time is gone", self.output)
        self.assertEqual(self.run_prep("--roms", "/somewhere/else"), 2, "outside the card: an error")

    def test_a_copy_of_the_firmware_folder_is_not_a_games_folder(self):
        """ED64.bk2 -- a backup of the firmware folder -- holds the
        firmware's apps and 64DD IPLs, ROM-shaped files with real headers,
        and a whole-card scan used to catalogue them."""
        write_rom(self.card / "ED64.bk2" / "edapp" / "nes" / "app.n64", 7, 8, game_code="ED")
        write_rom(self.card / "ED64" / "OS64.v64", 9, 10)
        code = self.run_prep()
        self.assertEqual(code, 0, self.output)
        catalog = (self.card / card_layout.CARD_FOLDER / card_layout.CATALOG_NAME).read_bytes()
        self.assertNotIn(b"ED64.bk2", catalog)
        self.assertNotIn(b"OS64", catalog)
        self.assertEqual(library.outside(self.card, "ROMS"), [])

    def test_a_library_in_a_folder_of_its_own_name_is_catalogued_where_it_is(self):
        """The comment that started this: games in `Games/` and no `ROMS`
        at all. The catalog records `Games/...`, which the browser resolves
        as sd:/Games/..., and no ROMS/ is made."""
        shutil.rmtree(self.roms)
        crc = write_rom(self.card / "Games" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
        self.assertEqual(crc, self.crc)
        code = self.run_prep()
        self.assertEqual(code, 0, self.output)
        catalog = (self.card / card_layout.CARD_FOLDER / card_layout.CATALOG_NAME).read_bytes()
        self.assertIn(b"Games/Wave Race 64 (USA).z64", catalog)
        self.assertFalse((self.card / "ROMS").exists())
        self.assertIn("1 in Games/", self.output)


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
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"} | OFFLINE
            result = subprocess.run([sys.executable, str(copy)], cwd=card,
                                    capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            catalog = card / card_layout.CARD_FOLDER / card_layout.CATALOG_NAME
            self.assertTrue(catalog.is_file())
            self.assertIn(entry.genre.encode("utf-8"), catalog.read_bytes())
            self.assertIn("1 with genre", result.stdout)


if __name__ == "__main__":
    unittest.main()
