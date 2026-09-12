# SPDX-License-Identifier: AGPL-3.0-only
import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

from tools import build_rom_db


def transcribed_blocks(ids=None) -> str:
    """The multi-line games ares expresses as region/revision branches.

    The generator refuses to run unless the set of these in the source matches
    its own SPECIAL table exactly, so every fixture has to carry them. Their
    bodies are never parsed -- the branches are transcribed in the script --
    so a placeholder is honest here."""
    return "\n".join(f"""  //{rom_id} has region and revision branches
  if(id == "{rom_id}") {{
    if(region_code == 'J') {{eeprom = 2_KiB; rpak = true;}}
    else {{cpak = true;}}
  }}""" for rom_id in (build_rom_db.SPECIAL if ids is None else ids))


def ares_source(*lines, ids=None) -> str:
    """A snippet shaped like mia/medium/nintendo-64.cpp, with whatever
    single-line entries the test is about."""
    return (
        "auto Nintendo64::analyze(vector<u8>& rom) -> string {\n"
        "  string id, region_code;\n"
        + transcribed_blocks(ids) + "\n"
        + "\n".join(lines) + "\n}\n")


def rows_for(entries, rom_id):
    return [entry for entry in entries if entry[0] == rom_id]


class ParseTests(unittest.TestCase):
    """A row that comes out wrong resolves a game to the wrong save hardware,
    which is silent until the console is switched off and the save is gone."""

    def test_a_single_line_entry_becomes_one_row(self):
        entries = build_rom_db.parse(ares_source(
            '  if(id == "NAB") {eeprom = 512; rpak = true;} //Air Boarder 64'))
        self.assertEqual(rows_for(entries, "NAB"),
                         [("NAB", "\\0", 1, 2, 255, "Air Boarder 64")])

    def test_ares_sizes_become_the_ids_the_cartridge_takes(self):
        """The generated numbers go to REG_GAM_CFG verbatim. ares says how big
        the save is; krikzz's id is what the hardware is told."""
        entries = build_rom_db.parse(ares_source(
            '  if(id == "NA1") {eeprom = 512;}',
            '  if(id == "NA2") {eeprom = 2_KiB;}',
            '  if(id == "NA3") {sram = 32_KiB;}',
            '  if(id == "NA4") {sram = 96_KiB;}',
            '  if(id == "NA5") {sram = 128_KiB;}',
            '  if(id == "NA6") {flash = 128_KiB;}'))
        self.assertEqual([(row[0], row[2]) for row in entries if row[0].startswith("NA")],
                         [("NA1", 1), ("NA2", 2), ("NA3", 3), ("NA4", 4),
                          ("NA5", 6), ("NA6", 5)])

    def test_the_accessories_are_collected_into_one_bit_field(self):
        """Four booleans in ares, one byte here. Getting the bits wrong offers
        a Transfer Pak where the game wanted a Rumble Pak."""
        entries = build_rom_db.parse(ares_source(
            '  if(id == "NB1") {cpak = true;}',
            '  if(id == "NB2") {rpak = true;}',
            '  if(id == "NB3") {tpak = true;}',
            '  if(id == "NB4") {rtc = true;}',
            '  if(id == "NB5") {cpak = true; rpak = true; tpak = true; rtc = true;}'))
        self.assertEqual([(row[0], row[3]) for row in entries if row[0].startswith("NB")],
                         [("NB1", 1), ("NB2", 2), ("NB3", 4), ("NB4", 8), ("NB5", 15)])

    def test_a_region_qualified_entry_records_the_region_it_applies_to(self):
        entries = build_rom_db.parse(ares_source(
            "  if(id == \"NFU\" && region_code == 'J') {flash = 128_KiB;} // Conker (Japan)"))
        self.assertEqual(rows_for(entries, "NFU"),
                         [("NFU", "J", 5, 0, 255, "Conker (Japan)")])

    def test_a_save_size_this_table_has_no_id_for_is_not_guessed_at(self):
        """ares can name a size the EverDrive has no setting for. Rounding it
        to the nearest one would arm the wrong save hardware; dropping the row
        resolves the game to no save, which is what the stock firmware does
        for anything it does not know."""
        entries = build_rom_db.parse(ares_source(
            '  if(id == "NZZ") {eeprom = 4_KiB;} // a size this table cannot express'))
        self.assertEqual(rows_for(entries, "NZZ"), [])

    def test_an_entry_with_only_accessories_keeps_them_and_says_no_save(self):
        """Most of the library has a Controller Pak and nothing else. Those
        rows still have to exist -- they are how the browser knows to offer
        the pak -- and their save type is legitimately zero."""
        entries = build_rom_db.parse(ares_source(
            '  if(id == "NRR") {cpak = true; rpak = true;} // Ridge Racer'))
        self.assertEqual(rows_for(entries, "NRR"),
                         [("NRR", "\\0", 0, 3, 255, "Ridge Racer")])

    def test_an_entry_worth_nothing_at_all_is_dropped(self):
        entries = build_rom_db.parse(ares_source('  if(id == "NQQ") {}'))
        self.assertEqual(rows_for(entries, "NQQ"), [])

    def test_a_line_that_is_not_shaped_like_an_entry_is_skipped(self):
        """The parse is a regular expression over C++. Anything that only
        looks like an entry has to miss, not half-match: a three-symbol id
        read out of a four-symbol one would file a real game under a name no
        cartridge has."""
        entries = build_rom_db.parse(ares_source(
            '  if(id == "NABC") {eeprom = 512;}',
            '  if(id == "nab") {eeprom = 512;}',
            '  //if(id == "NCD") {eeprom = 512;}',
            '  if(name == "NEF") {eeprom = 512;}',
            '  if(id != "NGH") {eeprom = 512;}'))
        # Nothing but the transcribed blocks came out of that.
        self.assertEqual({row[0] for row in entries}, set(build_rom_db.SPECIAL))

    def test_the_comment_ares_carries_is_kept_and_bounded(self):
        """The comment is the game's name and the only thing that makes the
        generated table readable in a diff. It also has to fit on a line."""
        entries = build_rom_db.parse(ares_source(
            '  if(id == "NLC") {eeprom = 512;} // ' + "x" * 80))
        self.assertEqual(rows_for(entries, "NLC")[0][5], "x" * 58)

    def test_the_transcribed_branches_are_emitted_as_ares_describes_them(self):
        """Super Mario 64 went missing from the first generated database
        because its entry is a multi-line block the line parser cannot see.
        These rows are the transcription that put it back."""
        entries = build_rom_db.parse(ares_source())
        self.assertEqual(rows_for(entries, "NSM"), [("NSM", "\\0", 1, 0, 255, "special case")])
        self.assertEqual(rows_for(entries, "NK4"),
                         [("NK4", "J", 3, 2, 1, "special case"),
                          ("NK4", "\\0", 2, 2, 255, "special case")])

    def test_a_single_line_entry_for_a_transcribed_game_is_not_a_second_row(self):
        """If ares ever spells one of these on one line as well, the branches
        transcribed here are the more specific answer and the flat one would
        shadow nothing -- but it would still be a duplicate row claiming a
        different save type."""
        entries = build_rom_db.parse(ares_source(
            '  if(id == "NSM") {sram = 32_KiB;} // a flat restatement'))
        self.assertEqual(rows_for(entries, "NSM"), [("NSM", "\\0", 1, 0, 255, "special case")])

    def test_rows_are_ordered_so_the_first_match_in_c_is_the_most_specific(self):
        """The generated lookup returns the first row whose id matches, so the
        order in the file is the priority. A region-agnostic row emitted first
        would answer for every region and the Japanese entry would never be
        reached."""
        entries = build_rom_db.parse(ares_source(
            '  if(id == "NXX") {cpak = true;} // any region',
            "  if(id == \"NXX\" && region_code == 'J') {sram = 32_KiB;} // Japan"))
        self.assertEqual([row[1] for row in rows_for(entries, "NXX")], ["J", "\\0"])

    def test_a_revision_limited_row_comes_before_the_one_that_takes_any(self):
        entries = build_rom_db.parse(ares_source())
        japanese = [row for row in rows_for(entries, "NK4") if row[1] == "J"]
        self.assertEqual(japanese[0][4], 1)
        self.assertLess(entries.index(japanese[0]),
                        entries.index(rows_for(entries, "NK4")[-1]))

    def test_the_same_source_always_produces_the_same_table(self):
        """The output is committed. A parse that reordered between runs would
        put an unreviewable diff in front of whoever regenerates it next."""
        source = ares_source('  if(id == "NAB") {eeprom = 512;}',
                             '  if(id == "NB7") {sram = 32_KiB; cpak = true;}')
        self.assertEqual(build_rom_db.parse(source), build_rom_db.parse(source))
        self.assertEqual([row[0] for row in build_rom_db.parse(source)],
                         sorted(row[0] for row in build_rom_db.parse(source)))

    def test_the_order_of_the_source_does_not_change_the_table(self):
        first = build_rom_db.parse(ares_source('  if(id == "NZA") {eeprom = 512;}',
                                               '  if(id == "NAZ") {sram = 32_KiB;}'))
        second = build_rom_db.parse(ares_source('  if(id == "NAZ") {sram = 32_KiB;}',
                                                '  if(id == "NZA") {eeprom = 512;}'))
        self.assertEqual(first, second)


class TranscriptionGuardTests(unittest.TestCase):
    """The multi-line games are the ones a line parser cannot see. The guard
    exists because one of them going quiet is invisible: the table still
    builds, it is just missing Super Mario 64."""

    def test_a_multi_line_game_nobody_transcribed_stops_the_generator(self):
        source = ares_source(ids=list(build_rom_db.SPECIAL) + ["NEW"])
        with self.assertRaises(SystemExit) as raised:
            build_rom_db.parse(source)
        self.assertIn("in source but not transcribed: ['NEW']", str(raised.exception))

    def test_a_transcribed_game_that_left_the_source_stops_it_too(self):
        """A transcription that no longer matches ares is a hand-written claim
        about a game nobody is checking any more."""
        remaining = list(build_rom_db.SPECIAL)[:-1]
        dropped = list(build_rom_db.SPECIAL)[-1]
        with self.assertRaises(SystemExit) as raised:
            build_rom_db.parse(ares_source(ids=remaining))
        self.assertIn(f"transcribed but not in source: ['{dropped}']", str(raised.exception))

    def test_a_source_with_no_multi_line_games_at_all_is_refused(self):
        """Pointing the generator at the wrong file, or at a truncated
        download, must not produce a plausible-looking short table."""
        with self.assertRaises(SystemExit):
            build_rom_db.parse('  if(id == "NAB") {eeprom = 512;}\n')


class EmitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.header = self.root / "rom_db.h"
        self.source = self.root / "rom_db.c"

    def tearDown(self):
        self.temporary.cleanup()

    def emit(self, entries, origin="/path/to/ares/mia/medium/nintendo-64.cpp"):
        build_rom_db.emit(entries, self.header, self.source, origin)
        return self.header.read_text(encoding="utf-8"), self.source.read_text(encoding="utf-8")

    def test_the_generated_table_is_marked_isc_and_not_agpl(self):
        """This table is derived from ares and carries ares's licence. The
        rest of the project is AGPL, and the two files are the only place in
        the tree where that is not true -- so the line has to be there, and it
        has to be the right one."""
        header, source = self.emit([("NAB", "\\0", 1, 2, 255, "Air Boarder 64")])
        for text in (header, source):
            self.assertTrue(text.startswith("/* SPDX-License-Identifier: ISC\n"))
            # ISC requires the copyright and permission notices in all
            # copies, so the tag alone is not enough.
            self.assertIn("ares team, Near et al", text)
            self.assertIn("Permission to use, copy, modify", text)
            self.assertNotIn("AGPL", text)

    def test_both_files_name_where_the_table_came_from(self):
        """Attribution is the condition the table is used under, and the path
        is also how the next person regenerates it."""
        header, source = self.emit([("NAB", "\\0", 1, 2, 255, "")],
                                   origin="/checkouts/ares/mia/medium/nintendo-64.cpp")
        for text in (header, source):
            self.assertIn("/checkouts/ares/mia/medium/nintendo-64.cpp", text)
            self.assertIn("do not edit by hand", text)

    def test_the_count_in_the_header_matches_the_rows_in_the_table(self):
        """The array is declared with the count from the header. Disagreeing
        would read past the end of it on the console."""
        entries = [("NAB", "\\0", 1, 2, 255, ""), ("NB7", "J", 3, 1, 4, ""),
                   ("NCD", "\\0", 0, 8, 255, "")]
        header, source = self.emit(entries)
        self.assertIn(f"#define SM_ROM_DB_COUNT {len(entries)}u", header)
        self.assertEqual(len(re.findall(r"^\s*\{\{'", source, re.M)), len(entries))

    def test_a_row_is_emitted_in_the_order_the_struct_declares(self):
        """The tuple is (id, region, save, feat, rev_max) and the struct is
        id, region, rev_max, save, feat. Emitting the tuple's order would
        compile perfectly and swap every game's save type with its revision
        ceiling."""
        _, source = self.emit([("NK4", "J", 3, 2, 1, "Kirby 64")])
        self.assertIn("{{'N','K','4'}, 'J', 1u, 3u, 2u}, /* Kirby 64 */", source)

    def test_a_region_agnostic_row_emits_a_nul_the_c_compares_against(self):
        """The generated lookup skips the region check when the field is zero.
        A space or a zero digit there would match nothing."""
        _, source = self.emit([("NSM", "\\0", 1, 0, 255, "")])
        self.assertIn("{{'N','S','M'}, '\\0', 255u, 1u, 0u},", source)

    def test_a_row_with_no_comment_gets_no_empty_comment(self):
        _, source = self.emit([("NSM", "\\0", 1, 0, 255, "")])
        self.assertNotIn("/*  */", source)

    def test_the_emitted_table_round_trips_back_to_what_was_parsed(self):
        """The one end-to-end check: what the generator was told is what the
        console will read."""
        entries = build_rom_db.parse(ares_source(
            '  if(id == "NAB") {eeprom = 512; rpak = true;} // Air Boarder 64',
            "  if(id == \"NXX\" && region_code == 'J') {sram = 32_KiB;} // Japan only"))
        _, source = self.emit(entries)
        emitted = re.findall(
            r"\{\{'(.)','(.)','(.)'\}, '(\\0|.)', (\d+)u, (\d+)u, (\d+)u\}", source)
        self.assertEqual(
            [("".join(row[:3]), row[3], int(row[5]), int(row[6]), int(row[4]))
             for row in emitted],
            [(entry[0], entry[1], entry[2], entry[3], entry[4]) for entry in entries])


class MainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def run_tool(self, text):
        source = self.root / "nintendo-64.cpp"
        source.write_text(text, encoding="utf-8")
        header, output = self.root / "rom_db.h", self.root / "rom_db.c"
        argv = sys.argv
        sys.argv = ["build_rom_db.py", "--source", str(source),
                    "--header", str(header), "--output", str(output)]
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                status = build_rom_db.main()
        finally:
            sys.argv = argv
        return status, err.getvalue(), header, output

    def test_a_suspiciously_small_database_is_refused_rather_than_written(self):
        """A source that parsed to almost nothing means the shape of ares
        changed. Writing the result would replace a working table with one
        that resolves the whole library to no save, and nothing on the console
        can tell that from a library of games that genuinely have none."""
        status, err, header, output = self.run_tool(ares_source())
        self.assertEqual(status, 1)
        self.assertIn("suspiciously small database", err)
        self.assertFalse(header.exists())
        self.assertFalse(output.exists())

    def test_a_local_checkout_is_read_from_disk_and_not_from_the_network(self):
        """--source takes a path or a URL. An existing path must never become
        a fetch: regenerating the table is a maintainer's deliberate act on a
        checkout they already have."""
        symbols = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
        entries = [f'  if(id == "N{symbols[index // 32]}{symbols[index % 32]}")'
                   " {eeprom = 512;}" for index in range(400)]
        status, err, header, output = self.run_tool(ares_source(*entries))
        self.assertEqual((status, err), (0, ""))
        self.assertTrue(header.read_text(encoding="utf-8").startswith(
            "/* SPDX-License-Identifier: ISC\n"))
        self.assertIn("SM_ROM_DB_COUNT", header.read_text(encoding="utf-8"))
        self.assertIn("sm_rom_db_lookup", output.read_text(encoding="utf-8"))




class TrailingWhitespaceTests(unittest.TestCase):
    """A trailing space must not delete a game from the save-type table.

    The entry pattern ended `(?:\\s*//\\s*(?P<comment>.*))?$`, which cannot match
    a line that has whitespace after the closing brace and no comment. Such a
    line parsed to nothing, so that cartridge silently resolved to "no save"
    on every card built afterwards. The <300-row floor catches a mass
    disappearance, not one game.
    """

    LINE = '    if(id == "NAB") {eeprom = 512; cpak = true;}'

    def rows_for(self, line):
        """Entries parsed from `line`, less the transcribed SPECIAL rows."""
        entries = build_rom_db.parse(ares_source(line))
        return [row for row in entries if row[0] not in build_rom_db.SPECIAL]

    def test_a_line_with_trailing_whitespace_and_no_comment_still_parses(self):
        self.assertEqual(self.rows_for(self.LINE + "   "), self.rows_for(self.LINE))
        self.assertEqual(len(self.rows_for(self.LINE + "   ")), 1)

    def test_a_trailing_comment_is_still_captured(self):
        rows = self.rows_for(self.LINE + "  // Air Boarder 64")
        self.assertEqual(len(rows), 1)
        self.assertIn("Air Boarder 64", rows[0])

    def test_a_comment_with_trailing_whitespace_is_not_padded(self):
        rows = self.rows_for(self.LINE + " // Air Boarder 64   ")
        self.assertIn("Air Boarder 64", rows[0])
        self.assertNotIn("Air Boarder 64   ", rows[0])


if __name__ == "__main__":
    unittest.main()
