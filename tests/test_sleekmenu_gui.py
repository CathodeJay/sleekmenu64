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
from tools import fetch, sleekmenu_gui, sleekmenu_prep


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
        self.assertEqual(options, sleekmenu_prep.Options(card=Path("/Volumes/CARD"), roms=sleekmenu_prep.WHOLE_CARD,
                                                         hires=False),
                         "an empty games folder is the whole card and an unticked box is no fetch, "
                         "said so -- never 'as remembered'")
        options = sleekmenu_gui.options_from("/Volumes/CARD", "  ~/art.zip ", False, True, hires=True,
                                             roms=" ROMS/ ")
        self.assertEqual(options.metadata, Path("  ~/art.zip "))
        self.assertEqual(options.roms, Path("ROMS"))
        self.assertTrue(options.no_checksums and options.fix_checksums and options.hires)
        self.assertFalse(options.rebuild, "a run keeps what the last one remembered unless told")
        self.assertTrue(sleekmenu_gui.options_from("/Volumes/CARD", "", True, False, rebuild=True).rebuild)
        self.assertFalse(options.no_large_covers, "the window always builds the box view's pack")

    def test_a_card_is_described_in_one_line(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch)
            self.assertEqual(sleekmenu_gui.describe_card(card), "no ROMs")
            write_rom(card / "Games" / "A.z64", 1, 2)
            (card / "SleekMenu64.z64").write_bytes(b"\x80\x37\x12\x40")
            (card / "release-metadata.zip").write_bytes(b"PK")
            self.assertEqual(sleekmenu_gui.describe_card(card),
                             "1 ROMs, SleekMenu64.z64 present")

    def test_the_card_line_counts_the_games_added_since_the_last_prepare(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "A.z64", 1, 2)
            self.assertIsNone(sleekmenu_gui.added_since(card, ["ROMS/A.z64"]), "no catalog to compare with")
            with contextlib.redirect_stdout(io.StringIO()), \
                 unittest.mock.patch.dict(os.environ, {"SLEEKMENU_NO_DOWNLOAD": "1"}):
                self.assertEqual(sleekmenu_prep.run(sleekmenu_prep.Options(card=card, roms=Path("ROMS"))), 0)
            self.assertNotIn("added since", sleekmenu_gui.describe_card(card))
            write_rom(card / "ROMS" / "B.z64", 3, 4)
            write_rom(card / "Other" / "C.z64", 5, 6)     # outside the chosen folder: not counted
            self.assertIn("1 added since the last Prepare", sleekmenu_gui.describe_card(card))


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

    def test_the_collection_line_says_whether_prepare_can_go(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            card.mkdir()
            self.assertEqual(sleekmenu_gui.collection_status(None), sleekmenu_gui.CollectionStatus(False, ""))
            with mock.patch.dict(os.environ):
                os.environ.pop(fetch.OFFLINE_VARIABLE, None)
                missing = sleekmenu_gui.collection_status(card)
            self.assertFalse(missing.ready)
            self.assertTrue(missing.downloadable)
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
            # a file chosen in the field is checked, not trusted
            junk = Path(scratch) / "junk.zip"
            junk.write_bytes(b"not a zip")
            chosen = sleekmenu_gui.collection_status(card, str(junk))
            self.assertFalse(chosen.ready)
            self.assertTrue(chosen.line.startswith("✗ junk.zip is not the collection"))
            chosen = sleekmenu_gui.collection_status(None, str(card / "release-metadata.zip"))
            self.assertTrue(chosen.ready)
            self.assertEqual(chosen.line, "✓ Using release-metadata.zip: 2 boxes.")

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

    def test_without_a_collection_prepare_waits_and_download_fetches_it(self):
        """No collection on the card: Prepare is off and says why, Download
        is on. Download puts the zip on the card, the line under the field
        turns to a tick with the box count, and Prepare comes on."""
        from tests.test_fetch import Server
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            zipped = write_collection(Path(scratch) / "served.zip", "NWRE", zipped=True).read_bytes()
            with mock.patch.dict(os.environ):
                os.environ.pop(fetch.OFFLINE_VARIABLE, None)
                root = sleekmenu_gui.build(card=str(card))
                root.update()
                state = root.sleekmenu_state
                buttons = state["buttons"]
                self.assertEqual(str(buttons["prepare"].cget("state")), "disabled")
                self.assertEqual(str(buttons["download"].cget("state")), "normal")
                self.assertIn("Download the collection first", state["why"].get())
                self.assertTrue(state["note"].get().startswith("✗ Not on the card: press Download"))
                state["start"]()
                self.assertIsNone(state["runner"], "Prepare refuses without a collection")
                with Server({"/release-metadata.zip": (200, zipped)}) as server, \
                     mock.patch.object(fetch, "release_addresses",
                                       lambda: [server.url("/release-metadata.zip")]):
                    state["download"]()
                    self.assertEqual(str(buttons["prepare"].cget("state")), "disabled", "not while fetching")
                    self.assertEqual(str(buttons["download"].cget("state")), "disabled")
                    while state["runner"] is not None:
                        root.update()
            self.assertEqual(state["last_download"], 0)
            self.assertTrue((card / "release-metadata.zip").is_file())
            self.assertEqual(state["note"].get(),
                             f"✓ release-metadata.zip is on the card: 1 boxes, "
                             f"{sleekmenu_gui.megabytes((card / 'release-metadata.zip').stat().st_size)}. "
                             "Ready to prepare.")
            self.assertEqual(str(buttons["prepare"].cget("state")), "normal")
            self.assertEqual(str(buttons["download"].cget("state")), "disabled", "nothing left to download")
            self.assertEqual(state["why"].get(), "")
            root.destroy()

    def test_a_build_check_on_a_card_with_no_collection_ends_rather_than_waits(self):
        with tempfile.TemporaryDirectory() as scratch:
            card = Path(scratch) / "CARD"
            write_rom(card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
            root = sleekmenu_gui.build(smoke=True, card=str(card))
            root.mainloop()
            self.assertEqual(root.sleekmenu_state["last_code"], 1)
            self.assertFalse((card / "sleekmenu").exists())

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
            # a half-edited games folder on the Prepare tab is not what an
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
            self.assertIn("press Prepare", catalog.edit_note.get())
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
