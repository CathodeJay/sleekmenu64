# SPDX-License-Identifier: AGPL-3.0-only
"""The window over the card-preparation run.

Everything but the widgets is checked without a screen: which disks are
offered as cards, how the fields become a run, and how the run reports
back. The widgets are checked too when this Python has Tk and a display
(CI runs the Linux job under Xvfb); elsewhere those cases are skipped, not
failed, since a Python without Tk is exactly what the command line is for.
"""

import contextlib
import gc
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests.rom_fixtures import write_rom
from tests.test_custom_art import picture
from tests.test_sleekmenu_prep import stay_offline, write_collection
from tools import sleekmenu_gui, sleekmenu_prep


class VolumeTests(unittest.TestCase):
    def test_macos_lists_volumes_but_never_the_boot_disk(self):
        listed = {"/Volumes": ["Macintosh HD", "CARD", ".timemachine"]}
        found = sleekmenu_gui.removable_volumes(
            "darwin", listdir=lambda p: listed.get(p, []),
            is_root=lambda p: p.name == "Macintosh HD")
        self.assertEqual(found, [Path("/Volumes/CARD")])

    def test_linux_lists_the_media_folders(self):
        listed = {"/media": ["jerome"], "/media/jerome": ["CARD", "Backup"],
                  "/run/media": [], "/mnt": ["usb"]}
        found = sleekmenu_gui.removable_volumes("linux", listdir=lambda p: listed.get(p, []))
        self.assertEqual(found, [Path("/media/jerome/Backup"), Path("/media/jerome/CARD"), Path("/mnt/usb")])

    def test_a_missing_folder_is_no_volumes_not_an_error(self):
        def refuse(_path):
            raise OSError("nope")
        self.assertEqual(sleekmenu_gui.removable_volumes("linux", listdir=refuse), [])
        self.assertEqual(sleekmenu_gui.removable_volumes("darwin", listdir=refuse), [])

    def test_windows_asks_the_system_and_survives_not_being_on_windows(self):
        self.assertEqual(sleekmenu_gui.removable_volumes("win32"), [] if sys.platform != "win32"
                         else sleekmenu_gui.removable_volumes("win32"))


class FieldTests(unittest.TestCase):
    def test_the_fields_become_the_runs_options(self):
        options = sleekmenu_gui.options_from("/Volumes/CARD", "", True, False)
        self.assertEqual(options, sleekmenu_prep.Options(card=Path("/Volumes/CARD")))
        options = sleekmenu_gui.options_from("/Volumes/CARD", "  ~/art.zip ", False, True)
        self.assertEqual(options.metadata, Path("  ~/art.zip "))
        self.assertTrue(options.no_checksums and options.fix_checksums)

    def test_a_card_is_described_in_one_line(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch)
            self.assertEqual(sleekmenu_gui.describe_card(card), "no ROMs, box art: none on the card")
            write_rom(card / "Games" / "A.z64", 1, 2)
            (card / "SleekMenu64.z64").write_bytes(b"\x80\x37\x12\x40")
            (card / "release-metadata.zip").write_bytes(b"PK")
            self.assertEqual(sleekmenu_gui.describe_card(card),
                             "1 ROMs, SleekMenu64.z64 present, box art: release-metadata.zip")


class CatalogLineTests(unittest.TestCase):
    def test_the_facts_line_says_what_is_known_and_nothing_else(self):
        game = {"genre": "Racing", "publisher": "Nintendo", "year": 1996, "players": 4, "regions": ["USA"]}
        self.assertEqual(sleekmenu_gui.facts_line(game), "Racing · Nintendo · 1996 · 4 players · USA")
        self.assertEqual(sleekmenu_gui.facts_line({"players": 1}), "1 player")
        self.assertEqual(sleekmenu_gui.facts_line({"year": 0, "players": 0}),
                         "no genre, publisher, year or players known")

    def test_the_edit_panel_says_what_a_save_reaches(self):
        games = [{"code": "NSME"}, {"code": "NSME"}, {"code": "NWRE"}]
        self.assertEqual(sleekmenu_gui.edit_summary(games, games[0], "rom"), "For this ROM only.")
        self.assertEqual(sleekmenu_gui.edit_summary(games, games[0], "code"),
                         "For every game with code NSME: 2 on this card.")
        self.assertIn("only this one", sleekmenu_gui.edit_summary(games, games[2], "code"))

    def test_the_summary_counts_the_games_and_what_was_changed(self):
        document = {"built": "2026-09-19T16:33:58+00:00", "games": [
            {"sources": {"cover": "collection"}}, {"sources": {"cover": "yours (this ROM)"}}]}
        self.assertEqual(sleekmenu_gui.summarize(document),
                         "2 games, built 2026-09-19 16:33; 1 with your own art or text")
        self.assertEqual(sleekmenu_gui.summarize({"games": []}), "0 games")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        stay_offline(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name) / "CARD"
        write_rom(self.card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")

    def tearDown(self):
        self.temporary.cleanup()

    def test_the_run_reports_every_line_and_its_progress(self):
        runner = sleekmenu_gui.Runner(sleekmenu_gui.options_from(str(self.card), "", True, False))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.run_inline(), 0)
        events = runner.drain()
        kinds = [event[0] for event in events]
        self.assertEqual(kinds[-1], "done")
        self.assertEqual(events[-1][1], 0)
        self.assertIn(("progress", "scanning", 1, 1), events)
        logs = [event[1] for event in events if event[0] == "log"]
        self.assertTrue(any(line.startswith("card:") for line in logs))
        self.assertTrue(any("scanned   1 files" in line for line in logs))
        self.assertTrue((self.card / "sleekmenu" / "catalog.ebc").is_file())

    def test_a_bad_card_is_an_error_line_and_a_code_never_a_traceback(self):
        runner = sleekmenu_gui.Runner(sleekmenu_gui.options_from("/nonexistent/card", "", True, False))
        self.assertEqual(runner.run_inline(), 2)
        events = runner.drain()
        self.assertEqual(events[-1], ("done", 2))
        self.assertTrue(any(event[0] == "error" and "not a folder" in event[1] for event in events))

    def test_a_stop_ends_the_run_at_its_next_step_with_nothing_written(self):
        """Stop is a flag the run reads before each step; here it is raised
        before the run starts, so the first step -- scanning -- is where it
        ends, and the card gets no catalog."""
        runner = sleekmenu_gui.Runner(sleekmenu_gui.options_from(str(self.card), "", True, False))
        runner.stop()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.run_inline(), 3)
        events = runner.drain()
        self.assertEqual(events[-1], ("done", 3))
        self.assertTrue(any(event[0] == "error" and "stopped while scanning" in event[1] for event in events))
        self.assertFalse((self.card / "sleekmenu" / "catalog.ebc").exists())


def display_available() -> bool:
    if not sleekmenu_gui.available():
        return False
    try:
        import tkinter
        tkinter.Tk().destroy()
    except Exception:  # noqa: BLE001 -- any failure means no usable display
        return False
    return True


@unittest.skipUnless(display_available(), "Tk and a display are needed for the window itself")
class WindowTests(unittest.TestCase):
    def setUp(self):
        stay_offline(self)

    def tearDown(self):
        # A closed window's variables sit in reference cycles until a
        # collection happens to run -- possibly on the next test's worker
        # thread, where Tk refuses them with "main thread is not in main
        # loop". Collect them here, on the thread that made them.
        gc.collect()

    def test_the_window_opens_and_closes(self):
        root = sleekmenu_gui.build(smoke=True)
        root.mainloop()

    def test_the_window_prepares_a_card_end_to_end(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            root = sleekmenu_gui.build(smoke=True, card=str(card))
            root.mainloop()
            self.assertEqual(root.sleekmenu_state["last_code"], 0)
            self.assertTrue((card / "sleekmenu" / "catalog.ebc").is_file())
            # and the catalog tab was reloaded from what the run wrote
            catalog = root.sleekmenu_state["catalog"]
            self.assertIn("ROMS/Wave Race 64 (USA).z64", catalog.games)

    def test_the_catalog_tab_shows_the_card_and_the_box_the_console_draws(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            write_rom(card / "ROMS" / "Hacks" / "Kaizo.z64", 0x33, 0x44, game_code="WR")
            write_collection(card / "release-metadata.zip", "NWRE", zipped=True)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card)), 0)
            root = sleekmenu_gui.build(card=str(card))
            root.update()
            catalog = root.sleekmenu_state["catalog"]
            self.assertTrue(catalog.summary.get().startswith("2 games"))
            self.assertEqual(len(catalog.games), 2)
            rows = catalog.tree.get_children("")
            self.assertEqual(len(rows), 1, "one folder at the root: ROMS/")
            catalog.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            self.assertEqual(catalog.title.get(), "Kaizo")
            self.assertIsNotNone(catalog.photo, "the box, decoded from covers.pak")
            self.assertEqual(catalog.photo.width(), 96 * sleekmenu_gui.BOX_ZOOM)
            self.assertIn("parent game", catalog.notes.get())
            catalog.only_mine.set(True)
            catalog.fill()
            self.assertEqual(catalog.tree.get_children(""), (), "nothing on this card is the owner's")
            root.destroy()

    def test_the_edit_panel_writes_and_removes_the_owners_files(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Hacks" / "Kaizo.z64", 0x33, 0x44, game_code="WR")
            picture(card / "box.png")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card)), 0)
            root = sleekmenu_gui.build(card=str(card))
            root.update()
            catalog = root.sleekmenu_state["catalog"]
            catalog.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            self.assertEqual(str(catalog.remove_button["state"]), "disabled", "nothing of the owner's yet")
            catalog.picture.set(str(card / "box.png"))
            catalog.own_title.set("Kaizo Race")
            catalog.own_text.insert("1.0", "Hard.")
            catalog.save_edit()
            self.assertTrue((card / "sleekmenu" / "art" / "Kaizo.png").is_file())
            self.assertEqual((card / "sleekmenu" / "art" / "Kaizo.txt").read_text(), "Title: Kaizo Race\n\nHard.\n")
            self.assertIn("Press Prepare", catalog.edit_note.get())
            self.assertEqual(str(catalog.remove_button["state"]), "normal")
            catalog.remove_edit()
            self.assertFalse((card / "sleekmenu" / "art" / "Kaizo.png").exists())
            self.assertFalse((card / "sleekmenu" / "art" / "Kaizo.txt").exists())
            self.assertIn("Removed", catalog.edit_note.get())
            catalog.picture.set(str(card / "ROMS" / "Hacks" / "Kaizo.z64"))
            catalog.save_edit()
            self.assertTrue(catalog.edit_note.get().startswith("Not saved"), "a ROM is not a picture")
            root.destroy()


if __name__ == "__main__":
    unittest.main()
