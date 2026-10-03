# SPDX-License-Identifier: AGPL-3.0-only
"""The X7's start-up switch: what a card says about it, what turning it on
and off writes, and what is left alone."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.rom_fixtures import write_rom
from tests.test_fetch import Log
from tests.test_sleekmenu_prep import stay_offline
from tools import card_layout, direct_boot, sleekmenu_prep


def browser(revision: bytes = b"one") -> bytes:
    """A file with the browser's title where a ROM header carries it."""
    return bytes(0x20) + direct_boot.BROWSER_TITLE + bytes(8) + revision + bytes(256)


def stock_os(with_hook: bool = True) -> bytes:
    return bytes(0x1000) + (b"registry.dat\0" + direct_boot.HOOK + b"\0" if with_hook else b"registry.dat\0")


class CardTests(unittest.TestCase):
    def setUp(self):
        stay_offline(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name) / "CARD"
        self.firmware = self.card / "ED64"
        self.firmware.mkdir(parents=True)
        self.autoexec = self.firmware / "autoexec.v64"
        direct_boot._facts.clear()

    def tearDown(self):
        self.temporary.cleanup()

    def x7(self, hook: bool = True, at_root: bool = True) -> None:
        (self.firmware / "OS64.v64").write_bytes(stock_os(hook))
        if at_root:
            (self.card / card_layout.BROWSER_ROM).write_bytes(browser())

    def test_the_name_looked_for_is_the_one_inside_the_os(self):
        self.assertEqual(direct_boot.HOOK, b"ED64/autoexec.v64")
        self.assertEqual(direct_boot.AUTOEXEC_SHOWN, "ED64/autoexec.v64")

    def test_a_card_says_which_everdrive_it_is_for_and_whether_the_switch_exists(self):
        empty = Path(self.temporary.name) / "EMPTY"
        empty.mkdir()
        self.assertEqual((direct_boot.state(empty).cart, direct_boot.state(empty).available), ("", False))
        self.assertEqual(direct_boot.state(None).available, False)
        bare = direct_boot.state(self.card)
        self.assertEqual((bare.cart, bare.available), ("", False))
        self.assertIn("no EverDrive OS", bare.why)
        (self.firmware / "sysdata").mkdir()
        (self.firmware / "sysdata" / "config.ini").write_text("[state]\n")
        pro = direct_boot.state(self.card)
        self.assertEqual((pro.cart, pro.available, pro.on), (direct_boot.PRO, False, False))
        self.assertIn("Pro has no start-up file", pro.why)

    def test_an_x7_card_has_the_switch_when_its_os_has_the_hook_and_the_browser_is_there(self):
        self.x7(hook=False)
        old = direct_boot.state(self.card)
        self.assertEqual((old.cart, old.available), (direct_boot.X7, False))
        self.assertIn("does not start a file by itself", old.why)
        self.x7(hook=True, at_root=False)
        (self.card / card_layout.BROWSER_ROM).unlink()
        direct_boot._facts.clear()
        missing = direct_boot.state(self.card)
        self.assertFalse(missing.available)
        self.assertIn("SleekMenu64.z64 is not at the card root", missing.why)
        self.x7()
        ready = direct_boot.state(self.card)
        self.assertEqual((ready.cart, ready.available, ready.on, ready.stale), (direct_boot.X7, True, False, False))

    def test_the_card_is_read_however_it_spells_its_names(self):
        self.firmware.rename(self.card / "ed64")
        (self.card / "ed64" / "os64.V64").write_bytes(stock_os())
        (self.card / "sleekmenu64.Z64").write_bytes(browser())
        self.assertTrue(direct_boot.state(self.card).available)
        direct_boot.sync(self.card, True)
        self.assertTrue(direct_boot.state(self.card).on)
        self.assertEqual((self.card / "ed64" / "autoexec.v64").read_bytes(), browser())

    def test_on_is_a_copy_of_the_browser_and_off_removes_it(self):
        self.x7()
        log = Log()
        after = direct_boot.sync(self.card, True, log)
        self.assertTrue(after.on and not after.stale)
        self.assertEqual(self.autoexec.read_bytes(), (self.card / card_layout.BROWSER_ROM).read_bytes())
        self.assertIn("the console now starts in SleekMenu", log.text())
        self.assertEqual(list(self.firmware.glob("*.part")), [])
        log = Log()
        direct_boot.sync(self.card, True, log)
        self.assertEqual(log.lines, [], "already on and current: nothing to do, nothing to say")
        log = Log()
        after = direct_boot.sync(self.card, False, log)
        self.assertFalse(after.on)
        self.assertFalse(self.autoexec.exists())
        self.assertIn("starts in the EverDrive menu again", log.text())
        log = Log()
        direct_boot.sync(self.card, False, log)
        self.assertEqual(log.lines, [])

    def test_a_run_told_nothing_keeps_the_copy_in_step_and_never_turns_it_on(self):
        self.x7()
        log = Log()
        direct_boot.sync(self.card, None, log)
        self.assertFalse(self.autoexec.exists())
        direct_boot.sync(self.card, True)
        (self.card / card_layout.BROWSER_ROM).write_bytes(browser(b"two"))
        self.assertTrue(direct_boot.state(self.card).stale)
        direct_boot.sync(self.card, None, log)
        self.assertEqual(self.autoexec.read_bytes(), browser(b"two"))
        self.assertIn("brought up to date", log.text())
        self.assertFalse(direct_boot.state(self.card).stale)

    def test_another_programs_start_up_file_is_left_alone(self):
        self.x7()
        write_rom(self.autoexec, 1, 2, game_code="XX")
        theirs = self.autoexec.read_bytes()
        found = direct_boot.state(self.card)
        self.assertEqual((found.available, found.on), (False, False))
        self.assertIn("another program", found.why)
        log = Log()
        direct_boot.sync(self.card, True, log)
        self.assertIn("not changed.", log.text())
        direct_boot.sync(self.card, False, log)
        direct_boot.sync(self.card, None, log)
        self.assertEqual(self.autoexec.read_bytes(), theirs)

    def test_the_switch_stays_usable_when_the_browser_at_the_root_is_gone(self):
        self.x7()
        direct_boot.sync(self.card, True)
        (self.card / card_layout.BROWSER_ROM).unlink()
        found = direct_boot.state(self.card)
        self.assertEqual((found.available, found.on, found.stale), (True, True, False))
        direct_boot.sync(self.card, False)
        self.assertFalse(self.autoexec.exists())

    def test_a_run_sets_the_switch_even_on_a_card_with_no_games_and_a_dry_run_does_not(self):
        self.x7()
        with contextlib.redirect_stdout(io.StringIO()):
            log = Log()
            sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, direct_boot=True, dry_run=True),
                               log=log, fail=log)
            self.assertFalse(self.autoexec.exists())
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, direct_boot=True), log=log, fail=log)
            self.assertEqual(code, 0, log.text())
            self.assertTrue(self.autoexec.is_file())
            self.assertIn("boot:     the console now starts in SleekMenu", log.text())
            log = Log()
            sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card), log=log, fail=log)
            self.assertTrue(self.autoexec.is_file(), "a run told nothing leaves the switch where it is")
            self.assertNotIn("boot:", log.text())
            sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, direct_boot=False), log=log, fail=log)
            self.assertFalse(self.autoexec.exists())

    def test_asked_for_on_a_pro_card_the_run_says_why_not_and_goes_on(self):
        (self.firmware / "sysdata").mkdir()
        (self.firmware / "sysdata" / "config.ini").write_text("[state]\n")
        (self.card / card_layout.BROWSER_ROM).write_bytes(browser())
        with contextlib.redirect_stdout(io.StringIO()):
            log = Log()
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, direct_boot=True), log=log, fail=log)
        self.assertEqual(code, 0, log.text())
        self.assertIn("boot:     not changed. The EverDrive-64 Pro has no start-up file", log.text())
        self.assertFalse(self.autoexec.exists())

    def test_the_command_line_takes_on_and_off(self):
        with mock.patch.object(sleekmenu_prep, "run", return_value=0) as run:
            sleekmenu_prep.main(["--card", str(self.card), "--direct-boot", "on"])
            self.assertIs(run.call_args.args[0].direct_boot, True)
            sleekmenu_prep.main(["--card", str(self.card), "--direct-boot", "off"])
            self.assertIs(run.call_args.args[0].direct_boot, False)
            sleekmenu_prep.main(["--card", str(self.card)])
            self.assertIsNone(run.call_args.args[0].direct_boot)

    def test_the_stock_os_file_and_the_start_up_file_are_never_games(self):
        self.x7()
        direct_boot.sync(self.card, True)
        from tools import library
        self.assertEqual(library.walk(self.card), [], "the firmware folder is not scanned, nor is the browser")


if __name__ == "__main__":
    unittest.main()
