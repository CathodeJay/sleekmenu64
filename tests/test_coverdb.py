# SPDX-License-Identifier: AGPL-3.0-only
import tempfile
import unittest
from pathlib import Path

from tools import coverdb


class CoverDBTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_round_trip_is_byte_stable(self):
        """The file is meant to be edited by hand and reviewed in a diff. If
        writing it back reorders or reformats rows, every contribution turns
        into an unreadable diff and nobody sends a second one."""
        entries = [
            coverdb.Entry(crc="a" * 16, name="Zed (USA)", genre="Racing", year=1997,
                          players=4, regions=("USA",)),
            coverdb.Entry(crc="B" * 16, name="alpha (Japan)", regions=("JAPAN", "USA")),
        ]
        text = coverdb.dumps(entries)
        self.assertEqual(coverdb.dumps(coverdb.loads(text)), text)
        # Sorted by name, case-insensitively, so a human can find a row.
        self.assertLess(text.index("alpha"), text.index("Zed"))

    def test_the_key_is_canonical_however_it_was_written(self):
        lower = coverdb.Entry(crc="abcdef0123456789", name="X")
        upper = coverdb.Entry(crc="ABCDEF0123456789", name="X")
        self.assertEqual(lower.crc, upper.crc)

    def test_regions_are_ordered_and_validated(self):
        self.assertEqual(coverdb.Entry(crc="1" * 16, name="X",
                                       regions=("EUROPE", "USA")).regions, ("USA", "EUROPE"))
        with self.assertRaisesRegex(coverdb.CoverDBError, "unknown region"):
            coverdb.Entry(crc="1" * 16, name="X", regions=("MARS",))

    def test_a_blank_crc_is_not_a_key(self):
        """Homebrew and a few bad dumps leave the CRC pair zeroed. Accepting it
        would file every one of them under the same row."""
        with self.assertRaisesRegex(coverdb.CoverDBError, "all zeroes"):
            coverdb.Entry(crc=coverdb.ZERO_CRC, name="Homebrew")

    def test_malformed_rows_are_rejected_with_a_line_number(self):
        for bad in ("crc,serial,name,art,genre,publisher,year,players,regions\nzz,,X,,,,,,\n",
                    "crc,serial,name,art,genre,publisher,year,players,regions\n" + "1" * 16 + ",,,,,,,,\n",
                    "crc,serial,name,art,genre,publisher,year,players,regions\n" + "1" * 16 + ",,X,,,,,9,\n"):
            with self.subTest(bad=bad), self.assertRaises(coverdb.CoverDBError):
                coverdb.loads(bad)

    def test_duplicate_keys_are_rejected(self):
        text = ("crc,serial,name,art,genre,publisher,year,players,regions\n"
                + "1" * 16 + ",,A,,,,,,\n" + "1" * 16 + ",,B,,,,,,\n")
        with self.assertRaisesRegex(coverdb.CoverDBError, "duplicate crc"):
            coverdb.loads(text)

    def test_merge_fills_gaps_without_overwriting_curated_values(self):
        """A generated row must never quietly undo a correction someone made
        by hand -- that is the whole reason the file is reviewed."""
        curated = {"1" * 16: coverdb.Entry(crc="1" * 16, name="Mario Kart 64 (USA)",
                                           genre="Racing")}
        generated = [coverdb.Entry(crc="1" * 16, name="Mario Kart 64 (USA)",
                                   genre="Sports", publisher="Nintendo", year=1996)]
        merged = coverdb.merge(curated, generated)
        self.assertEqual(merged["1" * 16].genre, "Racing")
        self.assertEqual(merged["1" * 16].publisher, "Nintendo")
        self.assertEqual(merged["1" * 16].year, 1996)

    def test_save_and_load_a_file(self):
        path = self.root / "db.csv"
        coverdb.save(path, [coverdb.Entry(crc="2" * 16, name="Game (USA)")])
        self.assertTrue(path.read_text().startswith(coverdb.SCHEMA_LINE))
        self.assertEqual(list(coverdb.load(path)), ["2" * 16])


if __name__ == "__main__":
    unittest.main()


class SchemaHistoryTests(unittest.TestCase):
    """The file is meant to be edited by hand and shared in pull requests, so
    it has to be able to read the shape it used to have."""

    V1 = ("crc,name,art,genre,publisher,year,players,regions\n"
          + "A" * 16 + ",Super Mario 64 (USA),,Platform,Nintendo,1996,1,USA\n")

    def test_a_version_1_file_still_loads(self):
        entries = coverdb.loads(self.V1)
        entry = entries["A" * 16]
        self.assertEqual(entry.name, "Super Mario 64 (USA)")
        self.assertEqual(entry.serial, "")
        self.assertEqual(entry.genre, "Platform")

    V2 = ("crc,serial,name,art,genre,publisher,year,players,regions\n"
          + "A" * 16 + ",NSME,Super Mario 64 (USA),Mario 64 art,Platform,Nintendo,1996,1,USA\n")

    def test_a_version_2_file_loads_and_its_art_column_is_dropped(self):
        entry = coverdb.loads(self.V2)["A" * 16]
        self.assertEqual((entry.serial, entry.name, entry.genre), ("NSME", "Super Mario 64 (USA)", "Platform"))
        self.assertFalse(hasattr(entry, "art"))

    def test_it_is_written_back_in_the_current_shape(self):
        for old in (self.V1, self.V2):
            text = coverdb.dumps(coverdb.loads(old))
            self.assertIn("crc,serial,name,genre", text)
            self.assertNotIn("art", text)
            self.assertTrue(text.startswith(coverdb.SCHEMA_LINE))

    def test_a_header_that_is_neither_is_still_refused(self):
        with self.assertRaisesRegex(coverdb.CoverDBError, "header must be"):
            coverdb.loads("crc,name\n1,2\n")


class ShippedDatabaseTests(unittest.TestCase):
    """data/coverdb.csv itself. It is edited by hand and reseeded from
    libretro, and a row that is wrong in a way a rule can state should stop
    here rather than reach a card."""

    PATH = Path(__file__).resolve().parent.parent / "data" / "coverdb.csv"

    @classmethod
    def setUpClass(cls):
        cls.text = cls.PATH.read_text(encoding="utf-8")
        cls.entries = list(coverdb.loads(cls.text).values())

    def test_the_file_is_in_the_form_the_tool_writes(self):
        """So a correction is a one-line diff, whoever makes it and however."""
        self.assertEqual(coverdb.dumps(self.entries), self.text)

    def test_names_genres_and_publishers_are_plain_text(self):
        """A no-break space or a doubled one cannot be seen in the file and
        makes "Bottom Up Interactive" two publishers in the console's filter."""
        for entry in self.entries:
            for field in ("name", "genre", "publisher"):
                value = getattr(entry, field)
                plain = all(ch == " " or (ch.isprintable() and not ch.isspace()) for ch in value)
                self.assertTrue(plain and value == value.strip() and "  " not in value,
                                f"{entry.name}: {field} is {value!r}")

    def test_every_genre_is_one_the_genre_map_knows(self):
        """As libretro spells it or as the browser shows it; anything else is
        a typo that would grow a tab of its own."""
        from tools import genre_map
        mapping = genre_map.load()
        known = set(mapping) | {shown.casefold() for shown in mapping.values()}
        for entry in self.entries:
            if entry.genre:
                self.assertIn(entry.genre.casefold(), known, entry.name)

    def test_years_players_and_game_codes_are_possible(self):
        """The console came out in 1996; the latest dumps in the file are the
        GameCube releases of 2003."""
        import re
        for entry in self.entries:
            self.assertTrue(entry.year == 0 or 1996 <= entry.year <= 2003, f"{entry.name}: year {entry.year}")
            self.assertTrue(0 <= entry.players <= 8, f"{entry.name}: {entry.players} players")
            self.assertRegex(entry.serial, re.compile(r"^([A-Z0-9]{4})?$"), entry.name)

    def test_dumps_of_one_game_agree_on_what_it_is(self):
        """A revision is the same game as its first release: same title and
        game code, so the same genre, publisher and players. The code alone
        is not enough -- both Goemon games carry NGME."""
        games: dict[tuple[str, str], list] = {}
        for entry in self.entries:
            if entry.serial:
                games.setdefault((entry.name.split(" (")[0], entry.serial), []).append(entry)
        for (title, serial), dumps in games.items():
            for field in ("genre", "publisher", "players"):
                values = {getattr(dump, field) for dump in dumps}
                self.assertEqual(len(values), 1, f"{title} [{serial}]: {field} is {sorted(map(str, values))}")
