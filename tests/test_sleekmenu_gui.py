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
from tests.test_sleekmenu_prep import stay_offline
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


if __name__ == "__main__":
    unittest.main()
