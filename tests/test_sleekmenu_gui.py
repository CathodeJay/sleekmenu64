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
import unittest.mock
from pathlib import Path
from unittest import mock

from tests.rom_fixtures import write_rom
from tests.test_custom_art import picture
from tests.test_sleekmenu_prep import stay_offline, write_collection
from tools import fetch, hires, sleekmenu_gui, sleekmenu_prep


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
    def test_the_choices_become_the_runs_options(self):
        options = sleekmenu_gui.options_from("/Volumes/CARD")
        self.assertEqual(options, sleekmenu_prep.Options(card=Path("/Volumes/CARD"), roms=sleekmenu_prep.WHOLE_CARD,
                                                         hires=True),
                         "an empty games folder is the whole card, said so -- never 'as remembered' -- "
                         "and the boxes are asked for")
        options = sleekmenu_gui.options_from("/Volumes/CARD", "  ~/art.zip ", " ROMS/ ", fix_checksums=True,
                                             offline=True, remembered=True)
        self.assertEqual(options.metadata, Path("  ~/art.zip "))
        self.assertEqual(options.roms, Path("ROMS"))
        self.assertTrue(options.fix_checksums and options.no_download)
        self.assertFalse(options.no_checksums, "hacks are always checked")
        self.assertIsNone(options.hires, "a card that has its boxes keeps them complete, "
                                         "without asking again about the ones libretro lacks")
        self.assertFalse(options.rebuild, "a run keeps what the last one remembered unless told")
        rebuilt = sleekmenu_gui.options_from("/Volumes/CARD", rebuild=True, remembered=True)
        self.assertTrue(rebuilt.rebuild and rebuilt.hires, "from scratch asks for every box again")
        self.assertFalse(options.no_large_covers, "the window always builds the box view's pack")


class CardStatusTests(unittest.TestCase):
    """What the Card tab says about a card, and what its button is called."""

    def test_no_card_and_an_empty_card(self):
        nothing = sleekmenu_gui.card_status(None)
        self.assertEqual(nothing.headline, "Pick your card")
        self.assertFalse(nothing.ready)
        with tempfile.TemporaryDirectory() as scratch:
            empty = sleekmenu_gui.card_status(Path(scratch))
            self.assertEqual(empty.headline, "No games on this card yet")
            self.assertEqual(empty.action, sleekmenu_gui.SET_UP)
            self.assertTrue(empty.ready, "the button makes the folders")

    def test_a_card_that_was_never_set_up_says_what_setting_up_fetches(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch)
            write_rom(card / "Games" / "A.z64", 1, 2)
            status = sleekmenu_gui.card_status(card)
            self.assertEqual((status.headline, status.action), ("Set up this card", sleekmenu_gui.SET_UP))
            self.assertEqual(status.detail, "1 game found on it. Nothing is moved or renamed.")
            self.assertIn("Fetches a box and a description", status.explain)
            self.assertEqual(status.last, "")
            offline = sleekmenu_gui.card_status(card, offline=True)
            self.assertIn("Downloads are off", offline.explain)
            self.assertNotIn("Fetches", offline.explain)
            # the packed catalog of an earlier version, with nothing to read beside it
            (card / "sleekmenu").mkdir()
            (card / "sleekmenu" / "catalog.ebc").write_bytes(b"x")
            earlier = sleekmenu_gui.card_status(card)
            self.assertEqual((earlier.headline, earlier.action), ("Update this card", sleekmenu_gui.UPDATE))
            self.assertIn("earlier version", earlier.detail)

    def test_a_set_up_card_counts_its_games_the_new_ones_and_the_ones_with_no_box(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "A.z64", 1, 2)
            with contextlib.redirect_stdout(io.StringIO()), \
                 unittest.mock.patch.dict(os.environ, {"SLEEKMENU_NO_DOWNLOAD": "1"}):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card, roms=Path("ROMS"))), 0)
            status = sleekmenu_gui.card_status(card)
            self.assertEqual((status.headline, status.action), ("1 game on this card", sleekmenu_gui.UPDATE))
            self.assertEqual(status.detail, "1 has no box.")
            self.assertIn("Nothing new on the card", status.explain)
            self.assertRegex(status.last, r"^Last update: \d{1,2} \w{3} \d{4}, \d\d:\d\d$")
            write_rom(card / "ROMS" / "B.z64", 3, 4)
            write_rom(card / "Other" / "C.z64", 5, 6)     # outside the chosen folder: not counted
            status = sleekmenu_gui.card_status(card)
            self.assertEqual(status.detail, "1 added since the last update. 1 has no box.")
            self.assertEqual(status.explain,
                             "Adds the 1 new game with its box and description, then rewrites the catalog.")
            self.assertEqual(sleekmenu_gui.added_since(card, ["ROMS/A.z64", "ROMS/B.z64", "Other/C.z64"]), 1)
            self.assertTrue(sleekmenu_gui.card_status(card, offline=True).explain.endswith(
                "Downloads are off: only what is already on the card is used."))

    def test_the_last_update_is_said_in_this_computers_time(self):
        self.assertRegex(sleekmenu_gui.when("2026-09-20T02:52:10+00:00"), r"^(19|20) Sep 2026, \d\d:\d\d$")
        self.assertEqual(sleekmenu_gui.when("yesterday"), "")
        self.assertEqual(sleekmenu_gui.when(""), "")


class StepTests(unittest.TestCase):
    """A run's reports as the four steps the tab draws."""

    def test_the_passes_and_lines_of_a_run_move_through_the_steps(self):
        steps = sleekmenu_gui.Steps()
        self.assertEqual(steps.current, -1, "nothing to draw before a run")
        steps.start()
        self.assertEqual([steps.state(i) for i in range(4)], ["now", "next", "next", "next"])
        steps.progress("scanning", 3, 10)
        self.assertEqual(steps.notes[0], "3 of 10")
        steps.progress("scanning", 10, 10)
        self.assertEqual(steps.notes[0], "10 files")
        steps.progress("checksums", 1, 2)
        self.assertEqual((steps.current, steps.notes[0]), (0, "10 files"), "still reading the games")
        steps.line("metadata: not on the card; fetching release-metadata.zip")
        self.assertEqual(steps.current, 1)
        steps.progress("fetching", 8, 208)
        self.assertEqual(steps.notes[1], "2 of 52 MB")
        steps.progress("boxes", 212, 716)
        self.assertEqual(steps.notes[1], "212 of 716 boxes")
        self.assertAlmostEqual(steps.fraction, 212 / 716)
        steps.progress("boxes", 716, 716)
        self.assertEqual(steps.notes[1], "716 boxes")
        steps.line("covers:   900 ROMs have a box, 4 do not")
        self.assertEqual((steps.current, steps.fraction), (2, 0.0))
        steps.progress("sprites", 5, 900)
        steps.progress("scanning", 1, 1)
        self.assertEqual(steps.current, 2, "a step is never gone back to")
        steps.line("writing:  the catalog and the covers to /Volumes/CARD/sleekmenu")
        self.assertEqual([steps.state(i) for i in range(4)], ["done", "done", "done", "now"])
        steps.end(0)
        self.assertEqual([steps.state(i) for i in range(4)], ["done"] * 4)

    def test_a_run_that_stopped_stays_where_it_was_and_one_with_nothing_to_do_shows_nothing(self):
        steps = sleekmenu_gui.Steps()
        steps.start()
        steps.progress("scanning", 2, 2)
        steps.progress("boxes", 4, 9)
        steps.end(3)
        self.assertEqual([steps.state(i) for i in range(4)], ["done", "now", "next", "next"])
        steps.start()
        steps.end(0)
        self.assertEqual(steps.current, -1, "a card with no games: nothing was read, fetched or written")

    def test_how_a_run_ended_is_one_sentence(self):
        status = sleekmenu_gui.CardStatus("x", action=sleekmenu_gui.UPDATE, ready=True)
        line = sleekmenu_gui.finished_line
        self.assertTrue(line(0, sleekmenu_prep.Outcome(), status).startswith("Done. Eject the card"))
        self.assertIn("press Update card to carry on", line(3, sleekmenu_prep.Outcome(), status))
        self.assertIn("could not be downloaded. Check the connection",
                      line(0, sleekmenu_prep.Outcome(collection_failed=True), status))
        self.assertIn("2 boxes could not be downloaded", line(0, sleekmenu_prep.Outcome(boxes_unreached=2), status))
        self.assertIn("1 box could", line(0, sleekmenu_prep.Outcome(boxes_unreached=1), status))
        self.assertIn("Copy your games onto the card", line(0, sleekmenu_prep.Outcome(), status, games_on_card=False))
        self.assertEqual(line(1, sleekmenu_prep.Outcome(), status), "", "the run's own error line says it")


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

    def test_the_summary_counts_the_games_the_boxes_and_what_was_changed(self):
        document = {"built": "2026-09-19T16:33:58+00:00", "games": [
            {"sources": {"cover": "collection"}}, {"sources": {"cover": "yours (this ROM)"}},
            {"sources": {"cover": "libretro"}}, {"sources": {"cover": "none"}}]}
        self.assertEqual(sleekmenu_gui.summarize(document),
                         "4 games, built 2026-09-19 16:33; 3 with a box, 1 of them high-resolution; "
                         "1 with your own art or text")
        self.assertEqual(sleekmenu_gui.summarize({"games": []}), "0 games")

    def test_the_tree_cells_are_the_short_forms_of_where_a_field_came_from(self):
        short = sleekmenu_gui.short_cover_source
        self.assertEqual(short("libretro"), "high-res")
        self.assertEqual(short("libretro, modified"), "high-res, edited")
        self.assertEqual(short("yours (this ROM)"), "yours")
        self.assertEqual(short("yours (code NSME)"), "yours")
        self.assertEqual(short("collection (another region's box)"), "other region")
        self.assertEqual(short("collection"), "collection")
        self.assertEqual(short("none"), "none")
        self.assertEqual(sleekmenu_gui.short_text_source("collection (by game code)"), "by code")
        self.assertEqual(sleekmenu_gui.short_text_source("yours"), "yours")

    def test_sizes_are_whole_megabytes_and_one_decimal_under_ten(self):
        self.assertEqual(sleekmenu_gui.megabytes(54_252_321), "52 MB")
        self.assertEqual(sleekmenu_gui.megabytes(1_572_864), "1.5 MB")

    def test_the_collection_line_says_what_a_run_will_read(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            card.mkdir()
            self.assertEqual(sleekmenu_gui.collection_status(None), sleekmenu_gui.CollectionStatus(False, ""))
            with mock.patch.dict(os.environ):
                os.environ.pop(fetch.OFFLINE_VARIABLE, None)
                missing = sleekmenu_gui.collection_status(card)
                chosen_offline = sleekmenu_gui.collection_status(card, offline=True)
            self.assertFalse(missing.ready)
            self.assertTrue(missing.downloadable)
            self.assertIn("it is fetched the first time", missing.line)
            self.assertFalse(chosen_offline.ready or chosen_offline.downloadable, "the owner's own choice")
            with mock.patch.dict(os.environ, {fetch.OFFLINE_VARIABLE: "1"}):
                offline = sleekmenu_gui.collection_status(card)
            self.assertFalse(offline.ready or offline.downloadable)
            self.assertIn("downloads are off", offline.line)
            write_collection(card / "release-metadata.zip", "NWRE", "NZLE", zipped=True)
            present = sleekmenu_gui.collection_status(card)
            self.assertTrue(present.ready)
            self.assertFalse(present.downloadable)
            self.assertIn("2 boxes", present.line)
            self.assertEqual(present.path, card / "release-metadata.zip")
            # a file chosen under Options is checked, not trusted
            junk = Path(scratch) / "junk.zip"
            junk.write_bytes(b"not a zip")
            chosen = sleekmenu_gui.collection_status(card, str(junk))
            self.assertFalse(chosen.ready)
            self.assertTrue(chosen.line.startswith("✗ junk.zip is not the collection"))
            chosen = sleekmenu_gui.collection_status(None, str(card / "release-metadata.zip"))
            self.assertTrue(chosen.ready)
            self.assertEqual(chosen.line, "✓ Using release-metadata.zip: 2 boxes.")
            # the card's own copy, cut short: the next update fetches it again
            (card / "release-metadata.zip").write_bytes(b"PK cut short")
            with mock.patch.dict(os.environ):
                os.environ.pop(fetch.OFFLINE_VARIABLE, None)
                broken = sleekmenu_gui.collection_status(card)
            self.assertFalse(broken.ready)
            self.assertTrue(broken.downloadable)
            self.assertIn("fetched again at the next update", broken.line)

    def test_the_box_view_line_says_what_the_console_will_draw(self):
        self.assertIn("high-resolution", sleekmenu_gui.box_view_line({"sources": {"cover": "libretro"}}))
        self.assertIn("high-resolution", sleekmenu_gui.box_view_line({"sources": {"cover": "libretro, modified"}}))
        self.assertIn("your picture", sleekmenu_gui.box_view_line({"sources": {"cover": "yours (code NSME)"}}))
        self.assertIn("small scan", sleekmenu_gui.box_view_line({"sources": {"cover": "collection"}}))
        self.assertIn("no box", sleekmenu_gui.box_view_line({"sources": {"cover": "none"}}))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        stay_offline(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name) / "CARD"
        write_rom(self.card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")

    def tearDown(self):
        self.temporary.cleanup()

    def test_the_run_reports_every_line_and_its_progress(self):
        runner = sleekmenu_gui.Runner(sleekmenu_gui.options_from(str(self.card)))
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
        runner = sleekmenu_gui.Runner(sleekmenu_gui.options_from("/nonexistent/card"))
        self.assertEqual(runner.run_inline(), 2)
        events = runner.drain()
        self.assertEqual(events[-1], ("done", 2))
        self.assertTrue(any(event[0] == "error" and "not a folder" in event[1] for event in events))

    def test_a_stop_ends_the_run_at_its_next_step_with_nothing_written(self):
        """Stop is a flag the run reads before each step; here it is raised
        before the run starts, so the first step -- scanning -- is where it
        ends, and the card gets no catalog."""
        runner = sleekmenu_gui.Runner(sleekmenu_gui.options_from(str(self.card)))
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
        # Every window a test opens is closed after it, failed or not: Tk's
        # main loop runs while any window of the process is open, so one a
        # failed test left behind would hang every later mainloop().
        self.roots = []
        build = sleekmenu_gui.build

        def recording(*args, **kwargs):
            root = build(*args, **kwargs)
            self.roots.append(root)
            return root
        patch = mock.patch.object(sleekmenu_gui, "build", recording)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        import tkinter
        for root in self.roots:
            try:
                root.destroy()
            except tkinter.TclError:
                pass
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
            write_collection(card / "release-metadata.zip", "NWRE", zipped=True)
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
            # a card prepared before catalog.json existed: the packed catalog is there, and said so
            (card / "sleekmenu" / "catalog.json").unlink()
            root = sleekmenu_gui.build(card=str(card))
            root.update()
            catalog = root.sleekmenu_state["catalog"]
            self.assertIn("earlier version", catalog.summary.get())
            root.destroy()
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
            self.assertIsNotNone(catalog.photo, "the box, decoded from covers-large.pak")
            self.assertEqual(catalog.photo.width(), 256)
            # without the large pack, the thumbnail doubled
            (card / "sleekmenu" / "covers-large.pak").unlink()
            catalog.reload()
            catalog.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            self.assertEqual(catalog.photo.width(), 96 * sleekmenu_gui.BOX_ZOOM)
            self.assertIn("parent game", catalog.notes.get())
            # the tree's cells are the short forms; the pane has the whole phrase
            self.assertEqual(catalog.tree.set("ROMS/Hacks/Kaizo.z64", "cover"), "collection")
            self.assertEqual(catalog.tree.set("ROMS/Hacks/Kaizo.z64", "text"), "by code")
            self.assertIn("Text: collection (by game code)", catalog.sources.get())
            self.assertIn("Kaizo", catalog.edit.cget("text"))
            catalog.show.set(sleekmenu_gui.SHOW_CHANGED)
            catalog.fill()
            self.assertEqual(catalog.tree.get_children(""), (), "nothing on this card is the owner's")
            catalog.show.set(sleekmenu_gui.SHOW_ALL)
            # the search narrows as typed, over more than the title
            catalog.query.set("kaizo")
            catalog.fill()
            self.assertEqual(catalog.shown.get(), "1 of 2")
            self.assertTrue(catalog.tree.exists("ROMS/Hacks/Kaizo.z64"))
            self.assertFalse(catalog.tree.exists("ROMS/Wave Race 64 (USA).z64"))
            catalog.query.set("nintendo 1996")
            catalog.fill()
            self.assertEqual(catalog.shown.get(), "2 of 2")
            catalog.query.set("")
            catalog.fill()
            self.assertEqual(catalog.shown.get(), "")
            # a game copied on since, and a file the tool set aside: both
            # rows in their folders, both counted in the header, neither
            # editable; the set-aside is what Prepare will never add
            self.assertEqual(catalog.waiting.get(), "")
            write_rom(card / "ROMS" / "New.z64", 0x55, 0x66, game_code="NW")
            (card / "ROMS" / "Tools" / "IPL.z64").parent.mkdir()
            (card / "ROMS" / "Tools" / "IPL.z64").write_bytes(bytes(64))
            catalog.reload()
            self.assertIn("2 ROMs on the card are not in it yet", catalog.waiting.get())
            self.assertNotIn("set aside", catalog.waiting.get())
            self.assertTrue(catalog.tree.exists("ROMS/New.z64"))
            self.assertEqual(catalog.tree.set("ROMS/New.z64", "cover"), "not yet")
            self.assertTrue(catalog.tree.exists("ROMS/Tools/IPL.z64"), "not prepared yet: a newcomer too")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card)), 0)
            catalog.reload()
            self.assertIn("1 file set aside as not a ROM", catalog.waiting.get())
            self.assertNotIn("not in it yet", catalog.waiting.get())
            self.assertEqual(catalog.tree.set("ROMS/Tools/IPL.z64", "cover"), "not a ROM")
            catalog.tree.selection_set("ROMS/Tools/IPL.z64")
            root.update()
            self.assertIn("Set aside by the tool", catalog.notes.get())
            self.assertEqual(str(catalog.save_button.cget("state")), "disabled")
            catalog.show.set(sleekmenu_gui.SHOW_WAITING)
            catalog.fill()
            self.assertTrue(catalog.tree.exists("ROMS/Tools/IPL.z64"))
            self.assertFalse(catalog.tree.exists("ROMS/New.z64"), "catalogued by the run")
            root.destroy()

    def test_the_games_folder_field_shows_what_the_card_remembers_and_an_empty_one_is_the_whole_card(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            write_rom(card / "Other" / "Loose.z64", 5, 6)
            write_collection(card / "release-metadata.zip", "NWRE", zipped=True)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card, roms=Path("ROMS"))), 0)
            root = sleekmenu_gui.build(card=str(card))
            root.update()
            state = root.sleekmenu_state
            self.assertEqual(state["catalog"].games.keys(), {"ROMS/Wave Race 64 (USA).z64"})
            self.assertEqual(state["fields"]["roms"].get(), "ROMS", "prefilled from catalog.json")
            state["fields"]["roms"].set("")
            state["start"]()
            while root.sleekmenu_state["runner"] is not None:
                root.update()
            self.assertEqual(root.sleekmenu_state["last_code"], 0)
            self.assertIn("Other/Loose.z64", root.sleekmenu_state["catalog"].games, "the whole card again")
            self.assertEqual(sleekmenu_prep.card_catalog.remembered_roms(card), "")
            root.destroy()

    def test_one_press_on_a_new_card_fetches_what_it_lacks_and_sets_it_up(self):
        """No collection and no boxes on the card: the button is Set up
        card, and one press fetches the collection and a box for the game,
        goes through the four steps and leaves a card the console can read.
        The button is Update card after, and nothing can start while the
        run is going."""
        from tests.test_fetch import Server
        from tests.test_hires import box_png, route
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            mario = next(entry for entry in hires.coverdb.load(sleekmenu_prep.data_file("coverdb.csv", Path(scratch)))
                         .values() if entry.name == "Super Mario 64 (USA)")
            write_rom(card / "ROMS" / "Super Mario 64 (USA).z64",
                      int(mario.crc[:8], 16), int(mario.crc[8:], 16), game_code="SM")
            zipped = write_collection(Path(scratch) / "served.zip", "NSME", zipped=True).read_bytes()
            with mock.patch.dict(os.environ):
                os.environ.pop(fetch.OFFLINE_VARIABLE, None)
                root = sleekmenu_gui.build(card=str(card))
                root.update()
                state = root.sleekmenu_state
                words, buttons = state["words"], state["buttons"]
                self.assertEqual(words["headline"].get(), "Set up this card")
                self.assertEqual(str(buttons["action"].cget("text")), "Set up card")
                self.assertEqual(str(buttons["action"].cget("state")), "normal", "no collection needed first")
                self.assertIn("it is fetched the first time", words["pack"].get())
                routes = {"/release-metadata.zip": (200, zipped), route("Super Mario 64 (USA)"): (200, box_png())}
                with Server(routes) as server, \
                     mock.patch.object(fetch, "release_addresses", lambda: [server.url("/release-metadata.zip")]), \
                     mock.patch.object(hires, "BASE_URL", server.url("/Named_Boxarts/")):
                    state["start"]()
                    self.assertEqual(str(buttons["action"].cget("state")), "disabled", "not while it runs")
                    self.assertEqual(state["steps"].current, 0)
                    while state["runner"] is not None:
                        root.update()
            self.assertEqual(state["last_code"], 0)
            self.assertTrue((card / "release-metadata.zip").is_file())
            self.assertTrue((card / "sleekmenu" / "art" / "hires" / "NSME.png").is_file())
            self.assertTrue((card / "sleekmenu" / "catalog.ebc").is_file())
            self.assertEqual([state["steps"].state(i) for i in range(4)], ["done"] * 4)
            self.assertEqual(state["steps"].notes[1], "1 box")
            self.assertTrue(words["result"].get().startswith("Done. Eject the card"))
            self.assertEqual(words["headline"].get(), "1 game on this card")
            self.assertEqual(words["detail"].get(), "Everything is up to date.")
            self.assertEqual(str(buttons["action"].cget("text")), "Update card")
            self.assertEqual(str(buttons["action"].cget("state")), "normal")
            self.assertTrue(words["last"].get().startswith("Last update: "))
            self.assertTrue(words["pack"].get().startswith("✓ release-metadata.zip is on the card: 1 boxes"))
            self.assertIn("Super Mario 64", state["catalog"].tree.item("ROMS/Super Mario 64 (USA).z64", "text"))
            root.destroy()

    def test_a_download_that_fails_is_said_and_the_card_is_still_written(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            with mock.patch.dict(os.environ):
                os.environ.pop(fetch.OFFLINE_VARIABLE, None)
                root = sleekmenu_gui.build(card=str(card))
                root.update()
                state = root.sleekmenu_state
                with mock.patch.object(fetch, "release_addresses", lambda: ["http://127.0.0.1:9/nothing.zip"]), \
                     mock.patch.object(hires, "BASE_URL", "http://127.0.0.1:9/Named_Boxarts/"):
                    state["start"]()
                    while state["runner"] is not None:
                        root.update()
            self.assertEqual(state["last_code"], 0)
            self.assertTrue(state["outcome"].collection_failed)
            self.assertIn("could not be downloaded. Check the connection and press Update card again",
                          state["words"]["result"].get())
            self.assertTrue((card / "sleekmenu" / "catalog.ebc").is_file())
            root.destroy()

    def test_the_options_are_closed_until_asked_for_and_downloads_can_be_turned_off(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            with mock.patch.dict(os.environ):
                os.environ.pop(fetch.OFFLINE_VARIABLE, None)
                root = sleekmenu_gui.build(card=str(card))
                root.update()
                state = root.sleekmenu_state
                self.assertFalse(state["options"]["offline"].get())
                self.assertIn("Fetches a box", state["words"]["explain"].get())
                state["show"]["options"]()
                state["options"]["offline"].set(True)
                root.update()
                self.assertIn("Downloads are off", state["words"]["explain"].get())
                self.assertIn("downloads are off", state["words"]["pack"].get())
                state["start"]()
                while state["runner"] is not None:
                    root.update()
            self.assertEqual(state["last_code"], 0)
            self.assertFalse((card / "release-metadata.zip").exists(), "nothing was fetched")
            self.assertFalse((card / "sleekmenu" / "art" / "hires").exists())
            self.assertTrue((card / "sleekmenu" / "catalog.ebc").is_file())
            root.destroy()

    def test_a_build_check_never_downloads_and_ends_on_its_own(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            with mock.patch.dict(os.environ):
                os.environ.pop(fetch.OFFLINE_VARIABLE, None)
                root = sleekmenu_gui.build(smoke=True, card=str(card))
                self.assertTrue(root.sleekmenu_state["options"]["offline"].get())
                root.mainloop()
            self.assertEqual(root.sleekmenu_state["last_code"], 0)
            self.assertTrue((card / "sleekmenu" / "catalog.ebc").is_file())
            self.assertFalse((card / "release-metadata.zip").exists())
            # and with no card at all it opens, finds nothing to act on, and closes
            root = sleekmenu_gui.build(smoke=True, card=str(Path(scratch) / "nowhere"))
            root.mainloop()
            self.assertEqual(root.sleekmenu_state["last_code"], 1)

    def test_a_save_is_put_on_the_card_at_once_and_a_second_one_waits_its_turn(self):
        """The console reads only the catalog, so a Save that stopped at the
        owner's file changed nothing there. Now Save runs the same Prepare
        the button does -- incremental, so seconds -- with the choices the
        card remembers, and the catalog the console reads has the edit.
        A Save while that runs is applied after it; a Remove is applied
        the same way."""
        from tools import card_catalog
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Hacks" / "Kaizo.z64", 0x33, 0x44, game_code="WR")
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            write_rom(card / "Other" / "Loose.z64", 5, 6)
            write_collection(card / "release-metadata.zip", "NWRE", zipped=True)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card, roms=Path("ROMS"))), 0)
            root = sleekmenu_gui.build(card=str(card))
            root.update()
            state = root.sleekmenu_state
            catalog = state["catalog"]
            # a half-set games folder under the Card tab's Options is not what an
            # edit is applied with: the card's own choice is
            state["fields"]["roms"].set("")
            catalog.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            catalog.own_title.set("Kaizo Race")
            catalog.own_genre.set("Racing")
            catalog.save_edit()
            self.assertEqual(state["runner"].kind, "apply")
            self.assertIn("Putting it on the card", catalog.edit_note.get())
            # a second game saved while the first is going in (no event
            # loop turn in between: the run is only over once the window
            # has seen it end)
            catalog.tree.selection_set("ROMS/Wave Race 64 (USA).z64")
            catalog.on_select()
            catalog.own_text.insert("1.0", "Waves.")
            catalog.save_edit()
            self.assertEqual(state["apply_pending"], "ROMS/Wave Race 64 (USA).z64")
            while state["runner"] is not None or "apply_pending" in state:
                root.update()
            self.assertEqual(state["last_apply"], 0)
            games = {game["path"]: game for game in card_catalog.load(card)["games"]}
            self.assertEqual(games["ROMS/Hacks/Kaizo.z64"]["title"], "Kaizo Race")
            self.assertEqual(games["ROMS/Hacks/Kaizo.z64"]["genre"], "Racing")
            self.assertEqual(games["ROMS/Wave Race 64 (USA).z64"]["description"], "Waves.")
            self.assertNotIn("Other/Loose.z64", games, "applied with the card's games folder")
            self.assertIn(b"Kaizo Race", (card / "sleekmenu" / "catalog.ebc").read_bytes())
            self.assertEqual(catalog.pending, {})
            self.assertEqual(catalog.selected()["path"], "ROMS/Wave Race 64 (USA).z64", "the row stays")
            self.assertEqual(catalog.edit_note.get(), "On the card: SleekMenu shows it the next time it starts.")
            # and a Remove goes back the same way
            catalog.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            catalog.remove_edit()
            while state["runner"] is not None:
                root.update()
            games = {game["path"]: game for game in card_catalog.load(card)["games"]}
            self.assertEqual(games["ROMS/Hacks/Kaizo.z64"]["title"], "Kaizo")
            self.assertEqual(catalog.edit_note.get(), "On the card: SleekMenu shows it the next time it starts.")
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
            catalog.own_genre.set("Racing")
            catalog.own_year.set("1996")
            catalog.own_players.set("2")
            catalog.own_regions["USA"].set(True)
            catalog.save_edit()
            self.assertTrue((card / "sleekmenu" / "art" / "Kaizo.png").is_file())
            self.assertEqual((card / "sleekmenu" / "art" / "Kaizo.txt").read_text(),
                             "Title: Kaizo Race\nGenre: Racing\nYear: 1996\nPlayers: 2\nRegions: USA\n\nHard.\n")
            self.assertIn("press the button on the Card tab", catalog.edit_note.get())
            self.assertEqual(str(catalog.remove_button["state"]), "normal")
            # shown at once, as the next Prepare will catalog it: the row,
            # the pane, the header's count, and the fields still filled in
            self.assertEqual(catalog.tree.item("ROMS/Hacks/Kaizo.z64", "text"), "Kaizo Race")
            self.assertEqual(catalog.tree.set("ROMS/Hacks/Kaizo.z64", "genre"), "Racing")
            self.assertEqual(catalog.tree.set("ROMS/Hacks/Kaizo.z64", "year"), "1996")
            self.assertEqual(catalog.tree.set("ROMS/Hacks/Kaizo.z64", "cover"), "yours, pending")
            self.assertEqual(catalog.tree.item("ROMS/Hacks/Kaizo.z64", "tags"), ("pending",))
            self.assertEqual(catalog.title.get(), "Kaizo Race")
            self.assertEqual(catalog.facts.get(), "Racing · Nintendo · 1996 · 2 players · USA")
            # the database already had the genre, year and region: not changes
            self.assertIn("Changed here, not in the catalog yet: title, text, players, picture",
                          catalog.notes.get())
            self.assertNotIn("No box", catalog.notes.get())
            self.assertNotIn("No description", catalog.notes.get())
            self.assertIn("1 edit waiting for a Prepare", catalog.summary.get())
            self.assertEqual(catalog.own_genre.get(), "Racing")
            self.assertEqual(catalog.own_year.get(), "1996")
            self.assertTrue(catalog.own_regions["USA"].get())
            self.assertEqual(catalog.box.cget("text"), "PENDING")
            # a bad year is refused before anything is written
            catalog.own_year.set("soon")
            catalog.save_edit()
            self.assertTrue(catalog.edit_note.get().startswith("Not saved: the year"))
            catalog.own_year.set("1996")
            # and once prepared, nothing is pending and the values hold
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card)), 0)
            catalog.reload()
            self.assertEqual(catalog.pending, {})
            self.assertNotIn("waiting", catalog.summary.get())
            self.assertEqual(catalog.tree.set("ROMS/Hacks/Kaizo.z64", "genre"), "Racing")
            self.assertEqual(catalog.tree.set("ROMS/Hacks/Kaizo.z64", "cover"), "yours")
            self.assertEqual(catalog.tree.item("ROMS/Hacks/Kaizo.z64", "tags"), "")
            catalog.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            catalog.remove_edit()
            self.assertFalse((card / "sleekmenu" / "art" / "Kaizo.png").exists())
            self.assertFalse((card / "sleekmenu" / "art" / "Kaizo.txt").exists())
            self.assertIn("Removed", catalog.edit_note.get())
            self.assertIn("file is gone: the next Prepare brings the original back", catalog.notes.get())
            self.assertEqual(catalog.tree.item("ROMS/Hacks/Kaizo.z64", "tags"), ("pending",))
            catalog.picture.set(str(card / "ROMS" / "Hacks" / "Kaizo.z64"))
            catalog.save_edit()
            self.assertTrue(catalog.edit_note.get().startswith("Not saved"), "a ROM is not a picture")
            root.destroy()


if __name__ == "__main__":
    unittest.main()
