# SPDX-License-Identifier: AGPL-3.0-only
"""The browser's themes: the table the ROM is built with, and the card's
choice of one."""

import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_fetch import Log
from tests.test_sleekmenu_prep import stay_offline
from tools import card_layout, sleekmenu_prep, themes

ROOT = Path(__file__).resolve().parent.parent


def luminance(colour) -> float:
    """Relative luminance, as contrast is measured."""
    def channel(value: int) -> float:
        value = value / 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    red, green, blue = (channel(value) for value in colour)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one, other) -> float:
    lighter, darker = sorted((luminance(one), luminance(other)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class TableTests(unittest.TestCase):
    def test_the_first_theme_is_the_look_the_browser_has_always_had(self):
        self.assertIs(themes.DEFAULT, themes.THEMES[0])
        self.assertEqual((themes.DEFAULT.id, themes.DEFAULT.name), ("midnight", "Midnight"))
        self.assertEqual(themes.DEFAULT.colours["bg"], (8, 12, 20))
        self.assertEqual(themes.DEFAULT.colours["accent"], (245, 230, 160))

    def test_every_theme_has_every_role_and_a_name_of_its_own(self):
        self.assertGreaterEqual(len(themes.THEMES), 4)
        self.assertEqual(len({theme.id for theme in themes.THEMES}), len(themes.THEMES))
        self.assertEqual(len({theme.name for theme in themes.THEMES}), len(themes.THEMES))
        for theme in themes.THEMES:
            with self.subTest(theme=theme.id):
                self.assertRegex(theme.id, r"^[a-z][a-z0-9-]*$")
                self.assertLessEqual(len(theme.id), themes.ID_MAX)
                self.assertEqual(set(theme.colours), set(themes.ROLES))
                for colour in theme.colours.values():
                    self.assertEqual(len(colour), 3)
                    self.assertTrue(all(isinstance(value, int) and 0 <= value <= 255 for value in colour))

    def test_every_theme_can_be_read_on_a_television(self):
        """Text against what it is drawn on, in every theme: the pairs the
        browser actually puts together."""
        pairs = (("text", "bg", 7.0), ("text_body", "bg", 7.0), ("text_soft", "bar", 5.0),
                 ("text_muted", "bg", 4.5), ("text_dim", "bg", 3.0), ("text_bright", "select", 3.5),
                 ("accent", "band", 4.5), ("accent", "bg", 7.0), ("accent_ink", "accent", 7.0),
                 ("text", "band", 4.5))
        for theme in themes.THEMES:
            for fore, back, least in pairs:
                with self.subTest(theme=theme.id, pair=f"{fore} on {back}"):
                    self.assertGreaterEqual(contrast(theme.colours[fore], theme.colours[back]), least)
            # the selection is told from the rows around it
            self.assertGreaterEqual(contrast(theme.colours["select"], theme.colours["bg"]), 1.6, theme.id)

    def test_what_carries_a_meaning_is_the_same_in_every_theme(self):
        for theme in themes.THEMES:
            for role in ("warn", "error", "star"):
                self.assertEqual(theme.colours[role], themes.MIDNIGHT[role], f"{theme.id} {role}")

    def test_the_themes_differ_from_one_another(self):
        seen = {}
        for theme in themes.THEMES:
            key = (theme.colours["bg"], theme.colours["band"], theme.colours["select"], theme.colours["accent"])
            self.assertNotIn(key, seen, f"{theme.id} is {seen.get(key)} under another name")
            seen[key] = theme.id

    def test_a_theme_is_found_by_its_id_whatever_the_case(self):
        self.assertIs(themes.find("jungle"), themes.find(" JUNGLE\n"))
        self.assertEqual(themes.find("jungle").name, "Jungle")
        self.assertIsNone(themes.find("jung"))
        self.assertIsNone(themes.find(""))
        self.assertIsNone(themes.find(None))
        self.assertIs(themes.by_name("Jungle"), themes.find("jungle"))
        self.assertIsNone(themes.by_name("jungle"))


class HeaderTests(unittest.TestCase):
    def test_the_table_in_the_rom_is_the_one_this_file_writes(self):
        """src/theme_table.h is checked in so the ROM builds without
        Python; it must be what tools/themes.py would write today."""
        self.assertEqual((ROOT / "src" / "theme_table.h").read_text(encoding="ascii"), themes.header(),
                         "run: python3 -m tools.themes --header src/theme_table.h")

    def test_the_header_names_every_role_and_every_theme_in_order(self):
        header = themes.header()
        roles = re.findall(r"^    (SM_C_[A-Z_]+),?$", header, re.MULTILINE)
        self.assertEqual(roles, [f"SM_C_{role.upper()}" for role in themes.ROLES] + ["SM_C_COUNT"])
        self.assertEqual(re.findall(r'\{ "([a-z0-9-]+)", "([^"]+)", \{', header),
                         [(theme.id, theme.name) for theme in themes.THEMES])
        self.assertIn(f"#define SM_THEME_COUNT {len(themes.THEMES)}u", header)
        self.assertEqual(header.count("/* bg */"), len(themes.THEMES))

    def test_the_tool_writes_the_header_and_lists_the_themes(self):
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "theme_table.h"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(themes.main(["--header", str(target)]), 0)
                self.assertEqual(target.read_text(encoding="ascii"), themes.header())
                self.assertEqual(themes.main([]), 0)
            for theme in themes.THEMES:
                self.assertIn(theme.name, out.getvalue())

    def test_the_browser_and_the_tool_agree_on_the_file(self):
        header = (ROOT / "src" / "card_paths.h").read_text(encoding="utf-8")
        self.assertIn(f'#define SM_THEME_PATH SM_CARD_DIR "/{card_layout.THEME_FILE}"', header)
        self.assertIn("#ifndef SM_THEME_PATH", header)


class CardTests(unittest.TestCase):
    def setUp(self):
        stay_offline(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name) / "CARD"
        self.card.mkdir()
        self.file = self.card / "sleekmenu" / "theme.txt"

    def tearDown(self):
        self.temporary.cleanup()

    def test_a_card_that_says_nothing_has_the_default(self):
        self.assertEqual(themes.path(self.card), self.file)
        self.assertIs(themes.read(self.card), themes.DEFAULT)
        self.assertIs(themes.read(None), themes.DEFAULT)

    def test_the_file_is_read_as_the_browser_reads_it(self):
        self.file.parent.mkdir()
        for text, wanted in (("jungle\n", "jungle"), ("  GRAPE \r\n", "grape"), ("fire and more\n", "fire"),
                             ("", "midnight"), ("no-such-theme\n", "midnight"), ("\n\nice", "ice")):
            self.file.write_text(text, encoding="ascii", newline="")
            self.assertEqual(themes.read(self.card).id, wanted, repr(text))
        self.file.write_bytes(b"\xff\xfe\x00junk")
        self.assertIs(themes.read(self.card), themes.DEFAULT)

    def test_a_choice_is_one_line_in_the_file(self):
        themes.write(self.card, themes.find("jungle"))
        self.assertEqual(self.file.read_bytes(), b"jungle\n")
        self.assertEqual([p.name for p in self.file.parent.iterdir()], ["theme.txt"])
        self.assertIs(themes.read(self.card), themes.find("jungle"))

    def test_sync_writes_only_what_changes(self):
        log = Log()
        self.assertIs(themes.sync(self.card, None, log), themes.DEFAULT)
        self.assertIs(themes.sync(self.card, "midnight", log), themes.DEFAULT)
        self.assertFalse(self.file.exists(), "choosing the default on a card that never chose writes nothing")
        self.assertEqual(log.text(), "")
        self.assertEqual(themes.sync(self.card, "grape", log).id, "grape")
        self.assertEqual(self.file.read_bytes(), b"grape\n")
        self.assertIn("theme:    Grape", log.text())
        log = Log()
        stamp = self.file.stat().st_mtime_ns
        themes.sync(self.card, "grape", log)
        themes.sync(self.card, None, log)
        self.assertEqual((log.text(), self.file.stat().st_mtime_ns), ("", stamp), "nothing to change")
        themes.sync(self.card, "midnight", log)
        self.assertEqual(self.file.read_bytes(), b"midnight\n", "back to the default is said, not implied")
        with self.assertRaisesRegex(ValueError, "no theme called 'neon'"):
            themes.sync(self.card, "neon", log)

    def test_a_run_puts_the_theme_on_the_card_and_a_dry_run_does_not(self):
        with contextlib.redirect_stdout(io.StringIO()):
            log = Log()
            sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, theme="fire", dry_run=True), log=log, fail=log)
            self.assertFalse(self.file.exists())
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, theme="fire"), log=log, fail=log)
            self.assertEqual(code, 0, log.text())
            self.assertEqual(self.file.read_bytes(), b"fire\n")
            self.assertIn("theme:    Fire", log.text())
            log = Log()
            sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card), log=log, fail=log)
            self.assertEqual(self.file.read_bytes(), b"fire\n", "a run told nothing leaves the card's choice")
            self.assertNotIn("theme:", log.text())

    def test_the_command_line_takes_a_theme_by_its_id(self):
        with mock.patch.object(sleekmenu_prep, "run", return_value=0) as run:
            sleekmenu_prep.main(["--card", str(self.card), "--theme", "ice"])
            self.assertEqual(run.call_args.args[0].theme, "ice")
            sleekmenu_prep.main(["--card", str(self.card)])
            self.assertIsNone(run.call_args.args[0].theme)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            sleekmenu_prep.main(["--card", str(self.card), "--theme", "neon"])

    def test_the_theme_file_is_never_a_game(self):
        from tools import library
        from tests.rom_fixtures import write_rom
        write_rom(self.card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
        themes.write(self.card, themes.find("jungle"))
        self.assertEqual(library.walk(self.card), ["ROMS/Wave Race 64 (USA).z64"])


if __name__ == "__main__":
    unittest.main()
