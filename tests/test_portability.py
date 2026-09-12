# SPDX-License-Identifier: AGPL-3.0-only
"""Somebody else's ROM library, somebody else's copy of the collection.

Every other test in this suite feeds the pipeline data that data/coverdb.csv
already knows about, which is exactly the condition under which a portability
bug is invisible. The box art used to be compiled into the ROM against one
particular collection, and the resulting sprite index was meaningless to
anyone else's -- see docs/rejected-approaches.md. These tests exist so that
class of regression cannot come back quietly.

The rule they enforce: nothing in this project may require the author's own
library, folder scheme or filenames. A card built from a library the database
has never seen must still be a working card.
"""

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tests.rom_fixtures import write_rom
from tools import cover_pack, coverdb, prepare_card
from tools.metadata_repo import MetadataRepo


class ForeignLibraryTests(unittest.TestCase):
    """A library where not one cartridge appears in data/coverdb.csv."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.card = self.root / "CARD"
        self.roms = self.card / "games"
        self.collection = self.root / "pictures"
        self.roms.mkdir(parents=True)
        self.collection.mkdir()
        # Deliberately empty: the shipped database is not a dependency.
        self.database = self.root / "coverdb.csv"
        self.repo = None

    def tearDown(self):
        if self.repo is not None:
            self.repo.close()
        self.temporary.cleanup()

    def add_box(self, key):
        target = self.collection / key / "boxart_front.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (158, 112), (10, 20, 30, 255)).save(target)

    def prepare(self, with_collection=True, **kwargs):
        if with_collection and self.repo is None:
            self.repo = MetadataRepo.open(self.collection) if any(self.collection.iterdir()) else None
        options = dict(roms=self.roms, card=self.card, repo=self.repo if with_collection else None,
                       database_path=self.database, work=self.root / "work",
                       log=lambda *a: None)
        options.update(kwargs)
        return prepare_card.prepare(**options)

    def test_a_library_the_database_has_never_seen_still_builds_a_card(self):
        """The database is an improvement, not a prerequisite. With no row for
        anything, the browser falls back to filenames and still works."""
        for index, name in enumerate(("Aleph.z64", "Beth.z64", "Gimel.z64")):
            write_rom(self.roms / name, 0xAAAA0000 + index, 0xBBBB0000 + index)
        summary = self.prepare()
        self.assertEqual(summary["database_entries"], 0)
        self.assertTrue((self.card / "sleekmenu" / "catalog.ebc").is_file())
        self.assertEqual(summary.get("games"), 3)

    def test_no_collection_at_all_is_not_an_error(self):
        write_rom(self.roms / "Aleph.z64", 0x01, 0x02)
        summary = self.prepare(with_collection=False)
        self.assertTrue((self.card / "sleekmenu" / "catalog.ebc").is_file())
        self.assertNotIn("covers", summary)

    def test_a_box_is_found_with_no_database_row_at_all(self):
        """The database is for text. A box needs nothing but the four
        characters the cartridge carries, so a library nobody has catalogued
        still gets its covers."""
        write_rom(self.roms / "whatever this is called.z64", 0x11, 0x22, game_code="WR")
        self.add_box("N/W/R/E")
        self.add_box("N/Q/Q/E")
        summary = self.prepare()
        self.assertEqual((summary["database_entries"], summary["covers"]), (0, 1))
        names = [e.name for e in cover_pack.read_index(
            (self.card / "sleekmenu" / "covers.pak").read_bytes())]
        self.assertEqual(names, ["NWRE.sprite"])

    def test_a_collection_with_nothing_for_this_library_leaves_a_usable_card(self):
        write_rom(self.roms / "Aleph.z64", 0x01, 0x02)
        self.add_box("N/Q/Q/E")
        summary = self.prepare()
        self.assertEqual(summary["covers"], 0)
        self.assertTrue((self.card / "sleekmenu" / "catalog.ebc").is_file())

    def test_a_flat_library_with_no_folders_works(self):
        for index in range(4):
            write_rom(self.roms / f"game{index}.z64", index + 1, index + 100)
        self.assertEqual(self.prepare()["games"], 4)

    def test_deeply_nested_and_non_ascii_folder_names_survive_to_the_catalog(self):
        """Folder names are the browser's tabs, and they come from the card,
        not from anything shipped here."""
        deep = self.roms / "Курсы" / "1997" / "sous-dossier"
        write_rom(deep / "jeu.z64", 0x33, 0x44)
        self.prepare()
        payload = (self.card / "sleekmenu" / "catalog.ebc").read_bytes()
        self.assertIn("sous-dossier".encode("utf-8"), payload)


class NoAuthorDefaultsTests(unittest.TestCase):
    """No code path may fall back to one particular person's setup."""

    ROOT = Path(__file__).resolve().parent.parent

    def sources(self):
        for path in sorted((self.ROOT / "tools").glob("*.py")):
            yield path, path.read_text(encoding="utf-8")
        yield (self.ROOT / "Makefile"), (self.ROOT / "Makefile").read_text(encoding="utf-8")

    def test_no_tool_defaults_to_somebody_elses_home_directory(self):
        """Absolute paths into a home directory are how a tool stops being
        portable. Every card, ROM folder and art folder must arrive as an
        argument; a default that points at the machine it was written on
        works exactly once, for one person."""
        forbidden = ("/Users/", "/home/", "/Volumes/Untitled",
                     "C:\\Users", "os.path.expanduser", "Path.home()")
        for path, text in self.sources():
            for token in forbidden:
                self.assertNotIn(token, text, f"{path.name} hardcodes {token}")

    def test_the_only_absolute_paths_in_the_tools_are_documentation(self):
        """`/Volumes/CARD` in a usage string is a worked example. The same
        string in a default= would be a bug, so they are told apart by where
        they sit rather than by what they look like."""
        import ast
        for path, text in self.sources():
            if path.suffix != ".py":
                continue
            for node in ast.walk(ast.parse(text)):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if node.value.startswith(("/Volumes/", "/Users/", "/media/")):
                    self.fail(f"{path.name}:{node.lineno} has an absolute path "
                              f"constant outside a docstring: {node.value!r}")

    def test_the_card_and_the_roms_are_required_arguments(self):
        """`make card` with no arguments must ask, not guess."""
        makefile = (self.ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn('if [ -z "$(CARD)" ] || [ -z "$(ROMS_ROOT)" ]', makefile)

    def test_the_shipped_database_carries_no_filesystem_paths(self):
        """coverdb.csv is keyed on cartridge CRCs. If a path from the machine
        that generated it ever leaked into a row, the file would stop being
        about cartridges and start being about one person's disk."""
        text = (self.ROOT / "data" / "coverdb.csv").read_text(encoding="utf-8")
        for token in ("/Users/", "/Volumes/", "/home/", "C:\\\\"):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()


class CardLayoutTests(unittest.TestCase):
    """The card folder is named once per language, and the two agree.

    These constants used to be independent string literals in five C files and
    three Python ones. Duplication was not the danger -- divergence was: the
    library scan skips the browser's own folder by comparing a directory name
    against this string, so a rename that missed one site would leave the
    browser listing its own catalog and cover pack as games. It is also what
    makes renaming the project a two-line change rather than a hunt.
    """

    ROOT = Path(__file__).resolve().parent.parent

    def header(self):
        return (self.ROOT / "src" / "card_paths.h").read_text(encoding="utf-8")

    def test_the_console_and_the_tooling_agree_on_the_folder_name(self):
        from tools import card_layout
        self.assertIn(f'#define SM_CARD_FOLDER "{card_layout.CARD_FOLDER}"', self.header())
        self.assertIn(f'#define SM_FIRMWARE_FOLDER "{card_layout.FIRMWARE_FOLDER}"',
                      self.header())

    def test_no_source_file_spells_the_folder_name_out_again(self):
        """The name as a *path component*. An asset that merely begins with the
        project name -- sleekmenu-font.sprite, inside the ROM's own
        filesystem -- is a different namespace and not what this guards."""
        import re
        from tools import card_layout
        name = re.escape(card_layout.CARD_FOLDER)
        offender = re.compile(r'"(?:[^"]*/)?' + name + r'(?:/[^"]*)?"', re.IGNORECASE)
        prose = ("#", "*", "//", "/*", chr(34) * 3, chr(39) * 3)
        allowed = {"card_paths.h", "card_layout.py"}
        for path in sorted((self.ROOT / "src").rglob("*.[ch]")) + \
                    sorted((self.ROOT / "tools").glob("*.py")):
            if path.name in allowed:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith(prose):
                    continue
                if offender.search(line):
                    self.fail(f"{path.name}:{number} hardcodes the card folder: "
                              f"{line.strip()}")

    def test_every_on_card_path_is_built_from_the_folder_name(self):
        header = self.header()
        for macro in ("SM_CATALOG_PATH", "SM_COVER_PACK_PATH",
                      "SM_COVERS_DIR", "SM_FAVORITES_PATH", "SM_HISTORY_PATH",
                      "SM_CHEATS_STATE_PATH", "SM_CHEATS_DIR"):
            self.assertRegex(header, rf"#define {macro} SM_CARD_DIR ",
                             f"{macro} must derive from SM_CARD_DIR")

    def test_the_paths_stay_overridable_so_the_host_tests_can_redirect_them(self):
        """tests/ui_host_test.c points them at a temp directory with -D. Without
        the guards that is a redefinition error under -Werror."""
        header = self.header()
        for macro in ("SM_CATALOG_PATH", "SM_COVER_PACK_PATH",
                      "SM_COVERS_DIR", "SM_FAVORITES_PATH", "SM_HISTORY_PATH",
                      "SM_CHEATS_STATE_PATH", "SM_CHEATS_DIR"):
            self.assertIn(f"#ifndef {macro}", header)
