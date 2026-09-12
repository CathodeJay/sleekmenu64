# SPDX-License-Identifier: AGPL-3.0-only
import tempfile
import unittest
from pathlib import Path

from tools import coverdb, curate


def quiet(*args):
    """Tests are not a place for a change log to be printed."""


class CurateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db = {
            entry.crc: entry for entry in (
                coverdb.Entry(crc="1" * 16, name="Legend of Zelda, The - Ocarina of Time (USA)",
                              genre="Role-playing (RPG)"),
                coverdb.Entry(crc="2" * 16, name="Legend of Zelda, The - Ocarina of Time (Europe)",
                              genre="Role-playing (RPG)"),
                coverdb.Entry(crc="3" * 16, name="Mario Kart 64 (USA)", genre="Sports"),
                coverdb.Entry(crc="4" * 16, name="1080 Snowboarding (Japan, USA) (En,Ja)",
                              genre="Sports", regions=("USA",)),
            )
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_a_substring_selects_every_release_of_a_game(self):
        rows = curate.matching(self.db, "ocarina")
        self.assertEqual(len(rows), 2)

    def test_a_regex_selects_across_localised_titles(self):
        rows = curate.matching(self.db, "re:ocarina|mario kart")
        self.assertEqual(len(rows), 3)

    def test_a_bad_regex_is_reported_rather_than_raised_raw(self):
        with self.assertRaisesRegex(curate.CurateError, "bad regular expression"):
            curate.matching(self.db, "re:[unclosed")

    def test_setting_a_genre_changes_every_matching_release(self):
        """libretro files Ocarina of Time under Role-playing. It is not an RPG,
        and the correction has to reach all eleven releases of it, not the one
        that happens to be highlighted."""
        updated = curate.set_field(self.db, "ocarina", "genre", "Action-Adventure",
                                   dry_run=False, log=quiet)
        self.assertEqual({e.genre for e in curate.matching(updated, "ocarina")},
                         {"Action-Adventure"})
        self.assertEqual(updated["3" * 16].genre, "Sports")   # untouched

    def test_a_dry_run_changes_nothing(self):
        curate.set_field(self.db, "ocarina", "genre", "Action-Adventure", dry_run=True, log=quiet)
        self.assertEqual(self.db["1" * 16].genre, "Role-playing (RPG)")

    def test_a_pattern_matching_nothing_is_an_error_not_a_silent_success(self):
        with self.assertRaisesRegex(curate.CurateError, "nothing matches"):
            curate.set_field(self.db, "Sonic Adventure", "genre", "Action", dry_run=False, log=quiet)


if __name__ == "__main__":
    unittest.main()
