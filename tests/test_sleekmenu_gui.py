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
                                                         hires=True, cheats=False),
                         "an empty games folder is the whole card, said so -- never 'as remembered' -- "
                         "the boxes are asked for, and cheats are not unless ticked")
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

    def test_the_two_switches_the_card_remembers_become_the_runs_options(self):
        from_window = sleekmenu_gui.options_from
        self.assertIs(from_window("/c", cheats=True).cheats, True, "ticked on a card that never asked: asked for")
        self.assertIsNone(from_window("/c", cheats=True, cheats_remembered=True).cheats,
                          "ticked on a card that has them: kept complete, absences not asked about again")
        self.assertIs(from_window("/c", cheats=True, cheats_remembered=True, rebuild=True).cheats, True,
                      "from scratch asks again")
        self.assertIs(from_window("/c", cheats=False, cheats_remembered=True).cheats, False,
                      "unticked: the card is told to stop")
        self.assertIsNone(from_window("/c").direct_boot, "a card with no start-up switch is told nothing")
        self.assertIs(from_window("/c", direct_boot=True).direct_boot, True)
        self.assertIs(from_window("/c", direct_boot=False).direct_boot, False)
        self.assertIsNone(from_window("/c").theme, "nothing chosen: the card's theme is left alone")
        self.assertEqual(from_window("/c", theme="jungle").theme, "jungle")


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
        steps.line("cheats:   640 files to fetch from libretro")
        steps.progress("cheats", 12, 640)
        self.assertEqual((steps.current, steps.notes[1]), (1, "12 of 640 cheat files"))
        steps.progress("cheats", 640, 640)
        self.assertEqual(steps.notes[1], "640 cheat files")
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
        self.assertIn("3 cheat files could not be downloaded",
                      line(0, sleekmenu_prep.Outcome(cheats_unreached=3), status))
        self.assertIn("2 boxes and 1 cheat file could not be downloaded",
                      line(0, sleekmenu_prep.Outcome(boxes_unreached=2, cheats_unreached=1), status))
        self.assertEqual(line(0, sleekmenu_prep.Outcome(), status, direct=True),
                         "Done. Eject the card and switch the console on: it starts in SleekMenu.")
        self.assertIn("could not be downloaded", line(0, sleekmenu_prep.Outcome(boxes_unreached=2), status,
                                                      direct=True), "what went wrong comes first")
        self.assertIn("Copy your games onto the card", line(0, sleekmenu_prep.Outcome(), status, games_on_card=False))
        self.assertEqual(line(1, sleekmenu_prep.Outcome(), status), "", "the run's own error line says it")


class GamesLineTests(unittest.TestCase):
    """What the Games tab says and writes, without its widgets."""

    def test_a_row_says_the_one_thing_worth_knowing_about_it(self):
        status = sleekmenu_gui.status_of
        whole = {"cover": "NSME.sprite", "genre": "Platform", "sources": {"cover": "libretro"}}
        self.assertEqual(status(whole), "")
        self.assertEqual(status({"genre": "Racing"}), "No box")
        self.assertEqual(status({"cover": "x.sprite"}), "No facts")
        self.assertEqual(status({}), "No box, no facts")
        self.assertEqual(status(dict(whole, sources={"cover": "yours (this ROM)"})), "Changed by me")
        self.assertEqual(status(dict(whole, sources={"genre": "yours"})), "Changed by me")
        self.assertEqual(status(whole, pending=object()), "Edit waiting")
        self.assertEqual(status({"state": sleekmenu_gui.STATE_WAITING}), "New")
        self.assertEqual(status({"state": sleekmenu_gui.STATE_ASIDE}), "Not a ROM")
        self.assertEqual(sleekmenu_gui.lacks({"cover": "x.sprite", "year": 1999}), [],
                         "no description is not something to look at: half the library has none")

    def test_the_show_choices_are_counted_and_listed(self):
        document = {"games": [
            {"path": "A.z64", "cover": "a.sprite", "genre": "Racing", "sources": {"cover": "libretro"}},
            {"path": "B.z64", "genre": "Racing", "sources": {"cover": "none"}},
            {"path": "C.z64", "cover": "c.sprite", "genre": "Racing", "sources": {"cover": "yours (this ROM)"}},
            {"path": "D.z64", "cover": "d.sprite", "genre": "Racing", "sources": {}}]}
        rows = [{"path": "New.z64", "state": sleekmenu_gui.STATE_WAITING},
                {"path": "IPL.z64", "state": sleekmenu_gui.STATE_ASIDE}]
        pending = {"D.z64": object()}
        self.assertEqual(sleekmenu_gui.show_counts(document, rows, pending),
                         {"all": 6, "look": 1, "changed": 2, "new": 1})
        paths = lambda mode: [r["path"] for r in sleekmenu_gui.shown_records(document, rows, pending, mode)]
        self.assertEqual(paths("look"), ["B.z64"])
        self.assertEqual(paths("changed"), ["C.z64", "D.z64"])
        self.assertEqual(paths("new"), ["New.z64"], "a file set aside is not a new game")
        self.assertEqual(sleekmenu_gui.show_counts(None, [], {}), {"all": 0, "look": 0, "changed": 0, "new": 0})

    def test_only_what_the_owner_changed_goes_in_their_file(self):
        """The fields show what the card has. Saving them untouched writes
        nothing; a changed one is written; one that was the owner's stays
        the owner's; an emptied one is left out, and the original returns."""
        from tools import custom_art
        game = {"title": "Kaizo", "genre": "Racing", "publisher": "Nintendo", "year": 1996, "players": 4,
                "regions": ["USA"], "description": "A  race.\n"}
        as_shown = {"title": "Kaizo", "genre": "Racing", "publisher": "Nintendo", "year": 1996, "players": 4,
                    "regions": ["USA"], "description": "A race."}
        values = sleekmenu_gui.edit_values
        self.assertEqual(values(game, None, as_shown), ("", "", {}))
        changed = dict(as_shown, title="Kaizo Race", players=2, regions=["EUROPE", "USA"], description="Hard.")
        self.assertEqual(values(game, None, changed),
                         ("Kaizo Race", "Hard.", {"players": 2, "regions": ["USA", "EUROPE"]}))
        own = custom_art.Text("Kaizo Race", "", {"genre": "Racing"})
        owned_game = dict(game, title="Kaizo Race")
        self.assertEqual(values(owned_game, own, dict(as_shown, title="Kaizo Race")),
                         ("Kaizo Race", "", {"genre": "Racing"}), "theirs already: kept, though nothing changed")
        self.assertEqual(values(owned_game, own, dict(as_shown, title="", genre="")), ("", "", {}),
                         "emptied: left out, so the original comes back")

    def test_the_owners_fields_are_marked(self):
        from tools import custom_art
        game = {"sources": {"title": "yours", "genre": "database", "cover": "yours (code NWRE)"}}
        self.assertEqual(sleekmenu_gui.owned_fields(game, None), {"title", "cover"})
        own = custom_art.Text("", "Hard.", {"regions": ["USA"]})
        self.assertEqual(sleekmenu_gui.owned_fields({"sources": {}}, own), {"description", "regions"})
        pending = custom_art.Pending({"year": 1996}, Path("box.png"), ())
        self.assertEqual(sleekmenu_gui.owned_fields({"sources": {}}, None, pending), {"year", "cover"})
        self.assertEqual(sleekmenu_gui.pending_line(pending), "Changed here, not on the card yet: year, box.")
        self.assertIn("Your title was removed",
                      sleekmenu_gui.pending_line(custom_art.Pending({}, None, ("title",))))

    def test_the_boxes_a_game_could_have_are_one_per_region_its_own_first(self):
        from tools import coverdb
        database = coverdb.load(Path(__file__).resolve().parent.parent / "data" / "coverdb.csv")
        choices = sleekmenu_gui.box_choices(database, {"code": "NSMJ"})
        self.assertEqual([label for label, _names in choices], ["Japan", "USA", "Europe"])
        names = dict(choices)
        self.assertEqual(names["USA"][0], "Super Mario 64 (USA)")
        self.assertEqual(names["Japan"][0], "Super Mario 64 (Japan)", "the release before its revisions")
        self.assertEqual(sleekmenu_gui.box_choices(database, {"code": "NSME"})[0][0], "USA")
        self.assertEqual(sleekmenu_gui.box_choices(database, {"code": ""}), [])
        self.assertEqual(sleekmenu_gui.box_choices(database, {"code": "XXXX"}), [], "homebrew: nothing to offer")
        self.assertEqual(sleekmenu_gui.region_label("D"), "Europe")

    def test_the_notes_under_a_game_say_how_sure_the_tool_is(self):
        notes = sleekmenu_gui.game_notes
        self.assertEqual(notes({"identified": "crc", "sources": {"cover": "libretro"}}), [])
        self.assertIn("Recognised by its game code", notes({"identified": "serial"})[0])
        self.assertIn("Not recognised", notes({"identified": ""})[0])
        self.assertEqual(notes({"identified": "crc", "sources": {"cover": "collection (another region's box)"}}),
                         ["The box is another region's."])

    def test_the_search_looks_at_more_than_the_title(self):
        game = {"title": "Kaizo", "path": "ROMS/Hacks/Kaizo.z64", "publisher": "Nintendo", "year": 1996,
                "code": "NWRE"}
        self.assertTrue(sleekmenu_gui.matches(game, "nintendo 1996"))
        self.assertTrue(sleekmenu_gui.matches(game, "hacks nwre"))
        self.assertFalse(sleekmenu_gui.matches(game, "kaizo 1997"))


class CollectionLineTests(unittest.TestCase):
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
            # a file chosen under Downloads is checked, not trusted
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

    def test_the_games_tab_shows_the_card_and_the_box_the_console_draws(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            write_rom(card / "ROMS" / "Hacks" / "Kaizo.z64", 0x33, 0x44, game_code="WR")
            write_rom(card / "ROMS" / "Homebrew" / "Flappy.z64", 3, 4, game_code="\0\0", country="\0")
            write_collection(card / "release-metadata.zip", "NWRE", zipped=True)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card)), 0)
            # a card prepared before catalog.json existed: the packed catalog is there, and said so
            (card / "sleekmenu" / "catalog.json").unlink()
            root = sleekmenu_gui.build(card=str(card))
            root.update()
            games = root.sleekmenu_state["catalog"]
            self.assertIn("earlier version", games.note.get())
            root.destroy()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card)), 0)
            root = sleekmenu_gui.build(card=str(card))
            root.update()
            games = root.sleekmenu_state["catalog"]
            self.assertEqual(games.note.get(), "")
            self.assertEqual(len(games.games), 3)
            self.assertEqual(str(games.show_buttons["all"].cget("text")), "All 3")
            self.assertEqual(str(games.show_buttons["look"].cget("text")), "Needs a look 1")
            self.assertEqual(str(games.show_buttons["changed"].cget("text")), "Changed by me 0")
            rows = games.tree.get_children("")
            self.assertEqual(len(rows), 1, "one folder at the root: ROMS/")
            self.assertEqual(games.tree.set("ROMS/Homebrew/Flappy.z64", "status"), "No box, no facts")
            self.assertEqual(games.tree.set("ROMS/Hacks/Kaizo.z64", "status"), "")
            # nothing selected: nothing to type in
            self.assertEqual(str(games.title_entry.cget("state")), "disabled")
            games.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            # the panel is the game as the console shows it, in fields
            self.assertEqual(games.title.get(), "Kaizo")
            self.assertEqual((games.genre.get(), games.publisher.get(), games.year.get(), games.players.get()),
                             ("Racing", "Nintendo", "1996", "4"))
            self.assertTrue(games.regions["USA"].get())
            self.assertEqual(games.file_name.get(), "Kaizo.z64")
            self.assertEqual(str(games.title_entry.cget("state")), "normal")
            self.assertEqual(str(games.labels["title"].cget("text")), "Title", "nothing here is the owner's")
            self.assertIsNotNone(games.photo, "the box, decoded from covers-large.pak")
            self.assertEqual(games.photo.width(), 256)
            self.assertIn("Recognised by its game code", games.notes.get())
            self.assertEqual(str(games.undo_button.cget("state")), "disabled")
            # two games carry this code: an edit can reach the other one too
            self.assertTrue(games.others_check.winfo_manager())
            self.assertIn("the 1 other version of this game", str(games.others_check.cget("text")))
            self.assertFalse(games.others.get())
            # without the large pack, the thumbnail doubled
            (card / "sleekmenu" / "covers-large.pak").unlink()
            games.reload()
            games.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            self.assertEqual(games.photo.width(), 96 * sleekmenu_gui.BOX_ZOOM)
            # a game with a code of its own has no other version to change
            games.tree.selection_set("ROMS/Homebrew/Flappy.z64")
            root.update()
            self.assertFalse(games.others_check.winfo_manager())
            self.assertEqual(games.box.cget("text"), "NO BOX")
            # the Show choices narrow the list, and so does the search, over more than the title
            games.show.set(sleekmenu_gui.SHOW_LOOK)
            games.fill()
            self.assertTrue(games.tree.exists("ROMS/Homebrew/Flappy.z64"))
            self.assertFalse(games.tree.exists("ROMS/Hacks/Kaizo.z64"))
            games.show.set(sleekmenu_gui.SHOW_CHANGED)
            games.fill()
            self.assertEqual(games.tree.get_children(""), (), "nothing on this card is the owner's")
            games.show.set(sleekmenu_gui.SHOW_ALL)
            games.query.set("kaizo")
            games.fill()
            self.assertEqual(games.shown.get(), "1 of 3")
            self.assertTrue(games.tree.exists("ROMS/Hacks/Kaizo.z64"))
            self.assertFalse(games.tree.exists("ROMS/Wave Race 64 (USA).z64"))
            games.query.set("nintendo 1996")
            games.fill()
            self.assertEqual(games.shown.get(), "2 of 3")
            games.query.set("")
            games.fill()
            self.assertEqual(games.shown.get(), "")
            # a game copied on since, and a file the tool set aside: both
            # rows in their folders, neither editable
            write_rom(card / "ROMS" / "New.z64", 0x55, 0x66, game_code="NW")
            (card / "ROMS" / "Tools" / "IPL.z64").parent.mkdir()
            (card / "ROMS" / "Tools" / "IPL.z64").write_bytes(bytes(64))
            games.reload()
            self.assertEqual(str(games.show_buttons["new"].cget("text")), "New 2")
            self.assertEqual(games.tree.set("ROMS/New.z64", "status"), "New")
            self.assertTrue(games.tree.exists("ROMS/Tools/IPL.z64"), "not updated yet: a newcomer too")
            games.tree.selection_set("ROMS/New.z64")
            root.update()
            self.assertIn("Press Update card", games.notes.get())
            self.assertEqual(str(games.save_button.cget("state")), "disabled")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card)), 0)
            games.reload()
            self.assertEqual(str(games.show_buttons["new"].cget("text")), "New 0")
            self.assertIn("1 file set aside as not a ROM", games.note.get())
            self.assertEqual(games.tree.set("ROMS/Tools/IPL.z64", "status"), "Not a ROM")
            games.tree.selection_set("ROMS/Tools/IPL.z64")
            root.update()
            self.assertIn("Set aside by the tool", games.notes.get())
            self.assertEqual(str(games.save_button.cget("state")), "disabled")
            self.assertEqual(games.tree.set("ROMS/New.z64", "status"), "No box, no facts",
                             "catalogued by the run: a game like any other, and one to look at")
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

    def test_the_options_sit_beside_the_button_and_downloads_can_be_turned_off(self):
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
                notebook = state["notebook"]
                self.assertEqual([notebook.tab(tab, "text") for tab in notebook.tabs()],
                                 ["Card", "Games", "Log"])
                status, options = state["columns"]["card"], state["columns"]["options"]
                self.assertTrue(status.winfo_ismapped() and options.winfo_ismapped(), "both on the Card tab")
                self.assertGreater(options.winfo_rootx(), status.winfo_rootx() + status.winfo_width() - 1,
                                   "the options are a column to the right of the button's")
                self.assertLess(abs(options.winfo_width() - status.winfo_width()), 4, "two halves")
                # cheat codes are a download: turning downloads off greys the
                # box and says why, and keeps its tick for when they are back
                cheats = state["buttons"]["cheats"]
                state["options"]["cheats"].set(True)
                self.assertEqual(str(cheats.cget("state")), "normal")
                state["options"]["offline"].set(True)
                root.update()
                self.assertEqual(str(cheats.cget("state")), "disabled")
                self.assertIn("downloads are off", state["words"]["cheats"].get())
                self.assertTrue(state["options"]["cheats"].get())
                state["options"]["offline"].set(False)
                root.update()
                self.assertEqual(str(cheats.cget("state")), "normal")
                self.assertIn("libretro", state["words"]["cheats"].get())
                state["options"]["cheats"].set(False)
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

    def test_the_button_is_there_only_when_there_is_a_card_to_act_on(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            with mock.patch.object(sleekmenu_gui, "removable_volumes", return_value=[]):
                root = sleekmenu_gui.build(card="")
                root.update()
                state = root.sleekmenu_state
                button = state["buttons"]["action"]
                self.assertEqual(state["words"]["headline"].get(), "Pick your card")
                self.assertFalse(button.winfo_ismapped(), "no card: nothing to set up")
                state["fields"]["card"].set(str(Path(scratch) / "nowhere"))
                root.update()
                self.assertEqual(state["words"]["headline"].get(), "That is not a card")
                self.assertFalse(button.winfo_ismapped())
                state["fields"]["card"].set(str(card))
                root.update()
                self.assertTrue(button.winfo_ismapped())
                self.assertEqual(str(button.cget("text")), "Set up card")
                self.assertEqual(str(button.cget("state")), "normal")
                state["fields"]["card"].set("")
                root.update()
                self.assertFalse(button.winfo_ismapped(), "and gone again with the card")
                root.destroy()

    def test_the_banner_ends_the_row_above_the_tabs_and_opens_the_page(self):
        root = sleekmenu_gui.build(card="")
        root.update()
        banner = root.sleekmenu_state["buttons"]["coffee"]
        self.assertEqual(banner.cget("text"), "Buy me a coffee")
        self.assertEqual(sleekmenu_gui.COFFEE_URL, "https://buymeacoffee.com/CathodeJay")
        self.assertTrue(banner.winfo_ismapped())
        notebook = root.sleekmenu_state["notebook"]
        header = root.sleekmenu_state["header"]
        right = banner.winfo_rootx() + banner.winfo_width() - root.winfo_rootx()
        self.assertGreater(right, root.winfo_width() - 24, "against the right edge")
        self.assertLessEqual(banner.winfo_rooty() + banner.winfo_height(), notebook.winfo_rooty(),
                             "above the tabs, not over them")
        self.assertLessEqual(header.winfo_rooty() + header.winfo_height(), notebook.winfo_rooty())
        # the card is chosen in the same row, to the banner's left
        picker = root.sleekmenu_state["picker"]
        self.assertIs(picker.master, header)
        self.assertLess(picker.winfo_rootx() + picker.winfo_width(), banner.winfo_rootx())
        with mock.patch("webbrowser.open") as opened:
            banner.event_generate("<Button-1>", x=4, y=4)
            root.update()
        opened.assert_called_once_with(sleekmenu_gui.COFFEE_URL)
        for page in ("games", "log"):
            notebook.select(root.sleekmenu_state["pages"][page])
            root.update()
            self.assertTrue(banner.winfo_ismapped(), f"still there on the {page} tab")
            self.assertTrue(picker.winfo_ismapped(), f"and so is the card, on the {page} tab")
        root.destroy()

    def test_the_cheats_box_is_off_until_ticked_and_then_the_card_remembers(self):
        from tests.test_cheat_codes import CHT, FOLDER, route
        from tests.test_fetch import Server
        from tools import cheat_codes
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            mario = next(entry for entry in hires.coverdb.load(sleekmenu_prep.data_file("coverdb.csv", Path(scratch)))
                         .values() if entry.name == "Super Mario 64 (USA)")
            write_rom(card / "ROMS" / "Super Mario 64 (USA).z64",
                      int(mario.crc[:8], 16), int(mario.crc[8:], 16), game_code="SM")
            write_collection(card / "release-metadata.zip", "NSME", zipped=True)
            with mock.patch.dict(os.environ):
                os.environ.pop(fetch.OFFLINE_VARIABLE, None)
                with Server({route("Super Mario 64 (USA)"): (200, CHT)}) as server, \
                     mock.patch.object(cheat_codes, "BASE_URL", server.url(FOLDER)), \
                     mock.patch.object(hires, "BASE_URL", server.url("/Named_Boxarts/")):
                    root = sleekmenu_gui.build(card=str(card))
                    root.update()
                    state = root.sleekmenu_state
                    self.assertFalse(state["options"]["cheats"].get(), "off by default")
                    state["start"]()
                    while state["runner"] is not None:
                        root.update()
                    self.assertFalse(any(".cht" in request for request in server.requests))
                    self.assertFalse(cheat_codes.folder(card).exists())
                    state["options"]["cheats"].set(True)
                    state["start"]()
                    while state["runner"] is not None:
                        root.update()
                    self.assertEqual(state["last_code"], 0)
                    self.assertEqual((cheat_codes.folder(card) / f"{mario.crc}.cht").read_bytes(), CHT)
                    self.assertEqual(state["steps"].notes[1], "1 cheat file")
                    root.destroy()
                    # the card remembers: the box is ticked the next time it is opened
                    root = sleekmenu_gui.build(card=str(card))
                    root.update()
                    state = root.sleekmenu_state
                    self.assertTrue(state["options"]["cheats"].get())
                    state["options"]["cheats"].set(False)
                    state["start"]()
                    while state["runner"] is not None:
                        root.update()
                    self.assertFalse(cheat_codes.remembered(card), "unticked: told to stop")
                    self.assertTrue((cheat_codes.folder(card) / f"{mario.crc}.cht").is_file(), "the files stay")
                    root.destroy()

    def test_the_start_up_switch_is_there_for_an_x7_card_only_and_does_what_it_says(self):
        from tests.test_direct_boot import browser, stock_os
        from tools import direct_boot
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            write_collection(card / "release-metadata.zip", "NWRE", zipped=True)
            (card / "ED64" / "sysdata").mkdir(parents=True)
            (card / "ED64" / "sysdata" / "config.ini").write_text("[state]\n")
            (card / "SleekMenu64.z64").write_bytes(browser())
            root = sleekmenu_gui.build(card=str(card))
            state = root.sleekmenu_state
            root.update()
            self.assertFalse(state["boot_row"].winfo_ismapped(), "a Pro card has no such switch")
            self.assertFalse(state["boot"].available)
            root.destroy()

            (card / "ED64" / "sysdata" / "config.ini").unlink()
            (card / "ED64" / "OS64.v64").write_bytes(stock_os())
            direct_boot._facts.clear()
            root = sleekmenu_gui.build(card=str(card))
            state = root.sleekmenu_state
            root.update()
            self.assertTrue(state["boot_row"].winfo_ismapped())
            self.assertEqual(str(state["buttons"]["boot"].cget("state")), "normal")
            self.assertIn("A reset inside a game returns to the EverDrive menu", state["boot_note"].get())
            self.assertFalse(state["options"]["boot"].get(), "off: the card has no start-up file")
            state["options"]["boot"].set(True)
            state["start"]()
            while state["runner"] is not None:
                root.update()
            self.assertEqual(state["last_code"], 0)
            self.assertEqual((card / "ED64" / "autoexec.v64").read_bytes(), browser())
            self.assertIn("it starts in SleekMenu", state["words"]["result"].get())
            self.assertTrue(state["options"]["boot"].get(), "read back from the card after the run")
            root.destroy()

            # opened again, the switch shows the card as it is; off removes the file
            root = sleekmenu_gui.build(card=str(card))
            root.update()
            state = root.sleekmenu_state
            self.assertTrue(state["options"]["boot"].get())
            state["options"]["boot"].set(False)
            state["start"]()
            while state["runner"] is not None:
                root.update()
            self.assertFalse((card / "ED64" / "autoexec.v64").exists())
            self.assertIn("start SleekMenu64.z64 from the EverDrive menu", state["words"]["result"].get())
            root.destroy()

            # another program's start-up file: the switch is shown, greyed, and says why
            write_rom(card / "ED64" / "autoexec.v64", 1, 2, game_code="XX")
            direct_boot._facts.clear()
            root = sleekmenu_gui.build(card=str(card))
            state = root.sleekmenu_state
            root.update()
            self.assertEqual(str(state["buttons"]["boot"].cget("state")), "disabled")
            self.assertIn("another program", state["boot_note"].get())
            theirs = (card / "ED64" / "autoexec.v64").read_bytes()
            state["start"]()
            while state["runner"] is not None:
                root.update()
            self.assertEqual((card / "ED64" / "autoexec.v64").read_bytes(), theirs)
            root.destroy()

    def test_the_theme_is_read_from_the_card_and_put_on_it_by_the_run(self):
        from tools import themes
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            write_collection(card / "release-metadata.zip", "NWRE", zipped=True)
            root = sleekmenu_gui.build(card=str(card))
            root.update()
            state = root.sleekmenu_state
            theme = state["options"]["theme"]
            self.assertEqual(theme.get(), "Midnight", "a card that never chose shows the default")
            # the swatch beside the name is the theme's own colours
            swatch = state["swatch"]
            fills = [swatch.itemcget(item, "fill") for item in swatch.find_all()]
            self.assertEqual(fills[0], "#%02x%02x%02x" % themes.DEFAULT.colours["bg"])
            self.assertEqual(len(fills), len(sleekmenu_gui.SWATCH_ROLES))
            theme.set("Jungle")
            root.update()
            fills = [swatch.itemcget(item, "fill") for item in swatch.find_all()]
            self.assertEqual(fills[0], "#%02x%02x%02x" % themes.find("jungle").colours["bg"])
            self.assertFalse(themes.path(card).exists(), "nothing is written until the button is pressed")
            state["start"]()
            while state["runner"] is not None:
                root.update()
            self.assertEqual(state["last_code"], 0)
            self.assertEqual(themes.path(card).read_bytes(), b"jungle\n")
            self.assertEqual(theme.get(), "Jungle")
            root.destroy()

            # opened again, the window shows the card's theme
            root = sleekmenu_gui.build(card=str(card))
            root.update()
            self.assertEqual(root.sleekmenu_state["options"]["theme"].get(), "Jungle")
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
        owner's file would change nothing there. Save runs the same run the
        Card tab's button does -- incremental, so seconds -- with the
        choices the card remembers, and the catalog the console reads has
        the edit. A Save while that runs is applied after it; an Undo is
        applied the same way."""
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
            games = state["catalog"]
            # a half-set games folder on the Card tab is not
            # what an edit is applied with: the card's own choice is
            state["fields"]["roms"].set("")
            games.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            games.title.set("Kaizo Race")
            games.genre.set("Platforms")
            games.save_edit()
            self.assertEqual(state["runner"].kind, "apply")
            self.assertIn("Putting it on the card", games.edit_note.get())
            self.assertEqual((card / "sleekmenu" / "art" / "Kaizo.txt").read_text(),
                             "Title: Kaizo Race\nGenre: Platforms\n", "only what was changed")
            # a second game saved while the first is going in (no event
            # loop turn in between: the run is only over once the window
            # has seen it end)
            games.tree.selection_set("ROMS/Wave Race 64 (USA).z64")
            games.on_select()
            games.text.delete("1.0", "end")
            games.text.insert("1.0", "Waves.")
            games.save_edit()
            self.assertEqual(state["apply_pending"], "ROMS/Wave Race 64 (USA).z64")
            while state["runner"] is not None or "apply_pending" in state:
                root.update()
            self.assertEqual(state["last_apply"], 0)
            on_card = {game["path"]: game for game in card_catalog.load(card)["games"]}
            self.assertEqual(on_card["ROMS/Hacks/Kaizo.z64"]["title"], "Kaizo Race")
            self.assertEqual(on_card["ROMS/Hacks/Kaizo.z64"]["genre"], "Platforms")
            self.assertEqual(on_card["ROMS/Wave Race 64 (USA).z64"]["description"], "Waves.")
            self.assertNotIn("Other/Loose.z64", on_card, "applied with the card's games folder")
            self.assertIn(b"Kaizo Race", (card / "sleekmenu" / "catalog.ebc").read_bytes())
            self.assertEqual(games.pending, {})
            self.assertEqual(games.selected()["path"], "ROMS/Wave Race 64 (USA).z64", "the row stays")
            self.assertEqual(games.edit_note.get(), "On the card: SleekMenu shows it the next time it starts.")
            self.assertEqual(str(games.labels["description"].cget("text")), "Description · yours")
            self.assertEqual(str(games.show_buttons["changed"].cget("text")), "Changed by me 2")
            self.assertEqual(games.tree.set("ROMS/Hacks/Kaizo.z64", "status"), "Changed by me")
            # a new box, on this card whose games folder is ROMS: on the
            # card after Save, and not left waiting
            games.tree.selection_set("ROMS/Wave Race 64 (USA).z64")
            root.update()
            games.set_picture(str(picture(Path(scratch) / "box.png")))
            games.save_edit()
            while state["runner"] is not None:
                root.update()
            self.assertEqual(games.pending, {})
            self.assertEqual(games.tree.set("ROMS/Wave Race 64 (USA).z64", "status"), "Changed by me")
            self.assertEqual(str(games.labels["description"].cget("text")), "Description · yours")
            self.assertEqual(games.box.cget("text"), "")
            # and an Undo goes back the same way
            games.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            self.assertEqual(str(games.labels["title"].cget("text")), "Title · yours")
            self.assertEqual(str(games.labels["genre"].cget("text")), "Genre · yours")
            self.assertEqual(str(games.labels["year"].cget("text")), "Year")
            games.remove_edit()
            while state["runner"] is not None:
                root.update()
            on_card = {game["path"]: game for game in card_catalog.load(card)["games"]}
            self.assertEqual(on_card["ROMS/Hacks/Kaizo.z64"]["title"], "Kaizo")
            self.assertEqual(on_card["ROMS/Hacks/Kaizo.z64"]["genre"], "Racing")
            self.assertEqual(games.edit_note.get(), "On the card: SleekMenu shows it the next time it starts.")
            root.destroy()

    def test_the_panel_writes_and_removes_the_owners_files(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Hacks" / "Kaizo.z64", 0x33, 0x44, game_code="WR")
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            picture(card / "box.png")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card)), 0)
            root = sleekmenu_gui.build(card=str(card))
            root.update()
            games = root.sleekmenu_state["catalog"]
            games.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            self.assertEqual(str(games.undo_button["state"]), "disabled", "nothing of the owner's yet")
            # saved as it stands, there is nothing to write
            games.save_edit()
            self.assertIn("Nothing to save", games.edit_note.get())
            self.assertFalse((card / "sleekmenu" / "art").exists())
            games.set_picture(str(card / "box.png"))
            self.assertEqual(games.box.cget("text"), "NOT SAVED YET")
            games.title.set("Kaizo Race")
            games.text.insert("1.0", "Hard.")
            games.players.set("2")
            games.regions["JAPAN"].set(True)
            games.save_edit()
            self.assertTrue((card / "sleekmenu" / "art" / "Kaizo.png").is_file())
            self.assertEqual((card / "sleekmenu" / "art" / "Kaizo.txt").read_text(),
                             "Title: Kaizo Race\nPlayers: 2\nRegions: USA, JAPAN\n\nHard.\n",
                             "the genre, publisher and year were left as the card has them")
            self.assertIn("press the button on the Card tab", games.edit_note.get(), "no collection to apply with")
            self.assertEqual(str(games.undo_button["state"]), "normal")
            # shown at once, as the next update will catalog it: the row,
            # the fields, the marks, and the count of what is waiting
            self.assertEqual(games.tree.item("ROMS/Hacks/Kaizo.z64", "text"), "Kaizo Race")
            self.assertEqual(games.tree.set("ROMS/Hacks/Kaizo.z64", "status"), "Edit waiting")
            self.assertEqual(games.tree.item("ROMS/Hacks/Kaizo.z64", "tags"), ("pending",))
            self.assertEqual((games.title.get(), games.players.get()), ("Kaizo Race", "2"))
            self.assertEqual(str(games.labels["players"].cget("text")), "Players · yours")
            self.assertEqual(str(games.labels["genre"].cget("text")), "Genre")
            self.assertIn("Changed here, not on the card yet: title, players, region, description, box.",
                          games.notes.get())
            self.assertIn("1 edit not on the card yet", games.note.get())
            self.assertEqual(games.box.cget("text"), "NOT ON THE CARD YET")
            # a bad year is refused before anything is written
            games.year.set("soon")
            games.save_edit()
            self.assertTrue(games.edit_note.get().startswith("Not saved: the year"))
            # and once updated, nothing is waiting and the values hold
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card)), 0)
            games.reload()
            self.assertEqual(games.pending, {})
            self.assertEqual(games.note.get(), "")
            self.assertEqual(games.tree.set("ROMS/Hacks/Kaizo.z64", "status"), "Changed by me")
            games.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            self.assertEqual(games.box.cget("text"), "")
            # emptying a field of the owner's gives the original back
            games.players.set("")
            games.save_edit()
            self.assertEqual((card / "sleekmenu" / "art" / "Kaizo.txt").read_text(),
                             "Title: Kaizo Race\nRegions: USA, JAPAN\n\nHard.\n")
            # for every version of the game: the code's file, and this ROM's own out of its way
            games.others.set(True)
            games.genre.set("Platforms")
            games.save_edit()
            self.assertEqual((card / "sleekmenu" / "art" / "NWRE.txt").read_text(),
                             "Title: Kaizo Race\nGenre: Platforms\nRegions: USA, JAPAN\n\nHard.\n")
            self.assertFalse((card / "sleekmenu" / "art" / "Kaizo.txt").exists())
            self.assertTrue((card / "sleekmenu" / "art" / "Kaizo.png").is_file(), "no new picture: the box stays")
            games.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            root.update()
            self.assertTrue(games.others.get(), "the edit is the code's: the box stays ticked")
            games.remove_edit()
            self.assertFalse((card / "sleekmenu" / "art" / "Kaizo.png").exists())
            self.assertFalse((card / "sleekmenu" / "art" / "NWRE.txt").exists())
            self.assertIn("Your changes are removed", games.edit_note.get())
            games.set_picture(str(card / "ROMS" / "Hacks" / "Kaizo.z64"))
            games.save_edit()
            self.assertTrue(games.edit_note.get().startswith("Not saved"), "a ROM is not a picture")
            # a picture dropped on the panel is the same as choosing it; anything else is said
            games.tree.selection_set("ROMS/Hacks/Kaizo.z64")
            games.on_select()
            self.assertFalse(games.dropped([str(card / "ROMS" / "Hacks" / "Kaizo.z64")]))
            self.assertEqual(games.edit_note.get(), "Kaizo.z64 is not a PNG or JPEG.")
            self.assertTrue(games.dropped([str(card / "box.png"), str(card / "other.png")]), "the first one dropped")
            self.assertEqual(games.picture.get(), str(card / "box.png"))
            self.assertEqual(games.box.cget("text"), "NOT SAVED YET")
            games.save_edit()
            self.assertTrue((card / "sleekmenu" / "art" / "Kaizo.png").is_file())
            self.assertFalse(games.dropped([]))
            games.reload()
            self.assertFalse(games.dropped([str(card / "box.png")]), "no game selected to give it to")
            self.assertIn("Select a game", games.edit_note.get())
            root.destroy()

    def test_narrowing_the_list_keeps_what_was_typed_and_a_fixed_game_leaves_needs_a_look(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Homebrew" / "Flappy.z64", 3, 4, game_code="\0\0", country="\0")
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            picture(card / "box.png")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card)), 0)
            root = sleekmenu_gui.build(card=str(card))
            root.update()
            games = root.sleekmenu_state["catalog"]
            flappy = "ROMS/Homebrew/Flappy.z64"
            games.show.set(sleekmenu_gui.SHOW_LOOK)
            games.fill()
            games.tree.selection_set(flappy)
            root.update()
            games.title.set("Flappy Bird")
            games.query.set("flap")
            games.fill()
            root.update()
            self.assertEqual(games.title.get(), "Flappy Bird", "typing in the search does not undo typing in the panel")
            self.assertEqual(games.tree.selection(), (flappy,))
            games.query.set("nothing like it")
            games.fill()
            self.assertEqual(str(games.title_entry.cget("state")), "disabled", "not in the list: not in the panel")
            games.query.set("")
            games.fill()
            games.tree.selection_set(flappy)
            root.update()
            games.set_picture(str(card / "box.png"))
            games.genre.set("Action")
            games.save_edit()
            self.assertEqual(games.tree.set(flappy, "status"), "Edit waiting", "still to look at until it is on the card")
            self.assertEqual(games.genre.get(), "Action")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card)), 0)
            games.applied(flappy, 0)
            self.assertFalse(games.tree.exists(flappy), "it has its box and a genre now")
            self.assertEqual(str(games.title_entry.cget("state")), "disabled")
            self.assertEqual(games.edit_note.get(), "Flappy: On the card: SleekMenu shows it the next time it starts.")
            games.show.set(sleekmenu_gui.SHOW_CHANGED)
            games.fill()
            self.assertEqual(games.tree.set(flappy, "status"), "Changed by me")
            root.destroy()

    def test_change_box_offers_libretros_boxes_by_region_and_the_choice_is_saved_as_the_owners(self):
        from tests.test_fetch import Server
        from tests.test_hires import box_png, route
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            mario = next(entry for entry in sleekmenu_prep.coverdb.load(
                Path(__file__).resolve().parent.parent / "data" / "coverdb.csv").values()
                if entry.name == "Super Mario 64 (USA)")
            write_rom(card / "ROMS" / "Super Mario 64 (USA).z64",
                      int(mario.crc[:8], 16), int(mario.crc[8:], 16), game_code="SM")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card)), 0)
            europe = box_png((200, 30, 30, 255))
            routes = {route("Super Mario 64 (USA)"): (200, box_png()),
                      route("Super Mario 64 (Europe) (En,Fr,De)"): (200, europe)}
            with mock.patch.dict(os.environ):
                os.environ.pop(fetch.OFFLINE_VARIABLE, None)
                root = sleekmenu_gui.build(card=str(card))
                root.update()
                games = root.sleekmenu_state["catalog"]
                games.tree.selection_set("ROMS/Super Mario 64 (USA).z64")
                root.update()
                with Server(routes) as server, \
                     mock.patch.object(hires, "BASE_URL", server.url("/Named_Boxarts/")):
                    games.choose_box()
                    picker = games.picker
                    self.assertEqual(list(picker.tiles), ["current", "USA", "Europe", "Japan"])
                    self.assertEqual(str(picker.use.cget("state")), "disabled", "nothing chosen yet")
                    for _ in range(400):
                        root.update()
                        if str(picker.tiles["Japan"].cget("text")) != "Japan: looking…":
                            break
                        import time
                        time.sleep(0.01)
                self.assertEqual(str(picker.tiles["USA"].cget("text")), "USA")
                self.assertEqual(str(picker.tiles["Europe"].cget("text")), "Europe")
                self.assertEqual(str(picker.tiles["Japan"].cget("text")), "Japan: none")
                self.assertEqual(str(picker.tiles["Japan"].cget("state")), "disabled")
                # a file dropped on the picker that is no picture is said there, and the picker stays
                picker.dropped([str(card / "ROMS" / "Super Mario 64 (USA).z64")])
                self.assertIn("is not a PNG or JPEG", picker.note.get())
                self.assertIsNotNone(games.picker)
                picker.choice.set("Europe")
                self.assertEqual(str(picker.use.cget("state")), "normal")
                picker.confirm()
                self.assertIsNone(games.picker)
                self.assertEqual(games.box.cget("text"), "NOT SAVED YET")
                self.assertIn("Press Save", games.edit_note.get())
                games.save_edit()
            self.assertEqual((card / "sleekmenu" / "art" / "Super Mario 64 (USA).png").read_bytes(), europe)
            self.assertEqual(games.tree.set("ROMS/Super Mario 64 (USA).z64", "status"), "Edit waiting")
            # with downloads off there is only the owner's own picture to choose
            with mock.patch.dict(os.environ, {fetch.OFFLINE_VARIABLE: "1"}):
                games.choose_box()
                self.assertEqual(list(games.picker.tiles), ["current"])
                self.assertIn("Downloads are off", games.picker.note.get())
                # a picture dropped on the picker is taken and closes it
                dropped = picture(Path(scratch) / "dropped.png")
                games.picker.dropped([str(dropped)])
                self.assertIsNone(games.picker)
                self.assertEqual(games.picture.get(), str(dropped))
            root.destroy()


if __name__ == "__main__":
    unittest.main()
