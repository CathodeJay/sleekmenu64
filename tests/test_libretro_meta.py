# SPDX-License-Identifier: AGPL-3.0-only
import tempfile
import unittest
from pathlib import Path

from tools import libretro_meta
from tools.libretro_meta import GameMeta, LibretroMeta


def game(name=None, crc=None, **fields):
    """One clrmamepro block in the shape libretro's metadat DATs use.

    Nothing here is copied from libretro-database: a checkout is a thing the
    card owner points the tools at, and a test that needed one would be a test
    nobody could run."""
    lines = ["game ("]
    if name is not None:
        lines.append(f'\tcomment "{name}"')
    if crc is not None:
        lines.append(f"\trom ( crc {crc} )")
    for key, value in fields.items():
        lines.append(f'\t{key} "{value}"')
    lines.append(")")
    return "\n".join(lines) + "\n"


class DatFixture(unittest.TestCase):
    """A synthetic libretro-database checkout, built per test."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def checkout(self, **folders):
        """folders maps a metadat/ subdirectory to the text of its DAT."""
        for folder, text in folders.items():
            directory = self.root / "metadat" / folder
            directory.mkdir(parents=True, exist_ok=True)
            (directory / libretro_meta.DAT_NAME).write_text(text, encoding="utf-8")
        return LibretroMeta.load(self.root)


class ParsingTests(DatFixture):
    def test_the_four_dats_answer_what_a_cartridge_header_cannot(self):
        """Genre, publisher, year and players are nowhere in a ROM image. If
        this parse is wrong the browser's filter screen offers choices no game
        can match, and nobody can tell it from an empty library."""
        meta = self.checkout(
            genre=game("Mario Kart 64 (USA)", "3E5055B6", genre="Racing"),
            publisher=game("Mario Kart 64 (USA)", "3E5055B6", publisher="Nintendo"),
            releaseyear=game("Mario Kart 64 (USA)", "3E5055B6", releaseyear="1996"),
            maxusers=game("Mario Kart 64 (USA)", "3E5055B6", users="4"),
        )
        self.assertEqual(meta.by_name["Mario Kart 64 (USA)"],
                         GameMeta(genre="Racing", publisher="Nintendo", year=1996, players=4))

    def test_four_separate_files_become_one_row_per_game(self):
        """libretro files each field in its own DAT. A game named the same way
        in all four has to end up as one row, not four partial ones."""
        meta = self.checkout(
            genre=game("A (USA)", "1", genre="Racing") + game("B (USA)", "2", genre="Puzzle"),
            releaseyear=game("A (USA)", "1", releaseyear="1996"),
        )
        self.assertEqual(sorted(meta.by_name), ["A (USA)", "B (USA)"])
        self.assertEqual((meta.by_name["A (USA)"].genre, meta.by_name["A (USA)"].year),
                         ("Racing", 1996))
        self.assertEqual(meta.by_name["B (USA)"].year, 0)

    def test_a_year_and_a_player_count_are_numbers_not_strings(self):
        """The catalog writes both as integers. A string reaching that far
        fails on a desktop, but a year of "1996" sorting next to 1996 in a
        filter list is the kind of thing nobody notices until the card is out."""
        meta = self.checkout(releaseyear=game("A (USA)", "1", releaseyear="1996"),
                             maxusers=game("A (USA)", "1", users="4"))
        self.assertEqual(meta.by_name["A (USA)"].year, 1996)
        self.assertEqual(meta.by_name["A (USA)"].players, 4)

    def test_a_trailing_word_after_the_number_is_ignored(self):
        """"4 players" and "1998-06" both occur. The leading digits are the
        answer; refusing the whole row would lose a field for no reason."""
        meta = self.checkout(releaseyear=game("A (USA)", "1", releaseyear="1998-06"),
                             maxusers=game("A (USA)", "1", users="4 players"))
        self.assertEqual((meta.by_name["A (USA)"].year, meta.by_name["A (USA)"].players),
                         (1998, 4))

    def test_a_checkout_root_and_its_metadat_folder_are_both_accepted(self):
        """Half the time the path someone has to hand is the checkout and half
        the time it is metadat/ itself. Refusing one of them is a support
        question, not a safety feature."""
        text = game("A (USA)", "1", genre="Racing")
        from_root = self.checkout(genre=text)
        from_metadat = LibretroMeta.load(self.root / "metadat")
        self.assertEqual(from_root.by_name, from_metadat.by_name)

    def test_a_path_with_no_metadat_is_reported_rather_than_silently_empty(self):
        """Pointing --libretro at the wrong directory must say so. A silent
        empty parse looks exactly like a library nothing is known about."""
        with self.assertRaisesRegex(FileNotFoundError, "no metadat"):
            LibretroMeta.load(self.root / "not-a-checkout")

    def test_a_dat_one_field_is_missing_does_not_cost_the_others(self):
        """libretro does not carry every field for every system. A checkout
        with no maxusers DAT still has genres worth reading."""
        meta = self.checkout(genre=game("A (USA)", "1", genre="Racing"))
        self.assertEqual(meta.by_name["A (USA)"].genre, "Racing")
        self.assertEqual(meta.counts["maxusers"], 0)
        self.assertEqual(meta.counts["genre"], 1)

    def test_nothing_at_all_is_read_from_a_file_that_is_not_a_dat(self):
        """A proxy error page saved over a DAT is a real way to end up here,
        and it must produce no metadata rather than nonsense metadata."""
        meta = self.checkout(genre="<html><body>404 Not Found</body></html>\n")
        self.assertEqual(meta.by_name, {})
        self.assertEqual(meta.counts["genre"], 0)


class MalformedEntryTests(DatFixture):
    """A partly written row is worse than no row: it is indistinguishable from
    a real one everywhere downstream."""

    def test_a_block_with_no_name_is_skipped_entirely(self):
        meta = self.checkout(genre=game(None, "DEADBEEF", genre="Racing"))
        self.assertEqual(meta.by_name, {})

    def test_a_nameless_block_does_not_leave_its_crc_behind_either(self):
        """The CRC index is what the file-CRC path looks a dump up in. A CRC
        filed without the name it belongs to would answer that lookup with
        nothing attached, which reads as a match."""
        meta = self.checkout(genre=game(None, "DEADBEEF", genre="Racing"))
        self.assertEqual(meta.crc_names, {})
        self.assertIsNone(meta.by_crc32("DEADBEEF"))

    def test_a_dat_entry_with_no_genre_does_not_invent_one(self):
        meta = self.checkout(genre=game("A (USA)", "1"))
        self.assertEqual(meta.by_name, {})
        self.assertEqual(meta.resolve("A (USA)"), ("", None, "none"))

    def test_an_empty_field_is_the_same_as_an_absent_one(self):
        """An empty genre string would reach the card as a genre nobody can
        select and every filter would exclude."""
        meta = self.checkout(genre=game("A (USA)", "1", genre="") +
                                   game("B (USA)", "2", genre="   "))
        self.assertEqual(meta.by_name, {})

    def test_a_year_that_is_not_a_number_leaves_the_year_unset(self):
        meta = self.checkout(genre=game("A (USA)", "1", genre="Racing"),
                             releaseyear=game("A (USA)", "1", releaseyear="unknown"))
        self.assertEqual(meta.by_name["A (USA)"].year, 0)
        self.assertEqual(meta.by_name["A (USA)"].genre, "Racing")

    def test_a_game_whose_only_field_was_unparseable_reads_as_unknown(self):
        """The row exists in the index but holds nothing, and a lookup has to
        say so. Returning an empty row would file the game as identified and
        stop every later attempt to identify it."""
        meta = self.checkout(releaseyear=game("A (USA)", "1", releaseyear="unknown"))
        self.assertEqual(meta.resolve("A (USA)"), ("", None, "none"))
        self.assertEqual(meta.lookup("A (USA)"), (None, "none"))

    def test_a_truncated_final_block_is_dropped_not_half_read(self):
        """An interrupted download leaves the last block without its closing
        paren. Everything before it is still good and must survive."""
        text = (game("A (USA)", "1", genre="Racing")
                + 'game (\n\tcomment "B (USA)"\n\tgenre "Puzzle"')
        meta = self.checkout(genre=text)
        self.assertEqual(sorted(meta.by_name), ["A (USA)"])

    def test_a_block_with_no_crc_still_yields_its_metadata(self):
        """Not every metadat row carries a rom line. Losing the CRC join for
        one game is a downgrade; losing its genre as well would be a bug."""
        meta = self.checkout(genre=game("A (USA)", None, genre="Racing"))
        self.assertEqual(meta.by_name["A (USA)"].genre, "Racing")
        self.assertEqual(meta.crc_names, {})


class NameResolutionTests(DatFixture):
    """Name matching is the fallback for a dump the CRC index has never seen.
    Every rewrite it tries is a rename someone actually made."""

    def dats(self, *names):
        return self.checkout(genre="".join(
            game(name, f"{index + 1:08X}", genre="Shooter")
            for index, name in enumerate(names)))

    def test_an_exact_name_is_reported_as_exact(self):
        meta = self.dats("Star Fox 64 (USA)")
        name, found, kind = meta.resolve("Star Fox 64 (USA)")
        self.assertEqual((name, kind), ("Star Fox 64 (USA)", "exact"))
        self.assertEqual(found.genre, "Shooter")

    def test_a_lettered_revision_matches_the_numbered_rename(self):
        """No-Intro renumbered lettered revisions years ago. Cards assembled
        before that still spell them (Rev A), and it is the same dump."""
        meta = self.dats("Turok 2 - Seeds of Evil (USA) (Rev 1)")
        name, _, kind = meta.resolve("Turok 2 - Seeds of Evil (USA) (Rev A)")
        self.assertEqual((name, kind), ("Turok 2 - Seeds of Evil (USA) (Rev 1)", "variant"))

    def test_a_goodn64_short_region_tag_matches_the_long_one(self):
        meta = self.dats("Star Fox 64 (USA)")
        self.assertEqual(meta.resolve("Star Fox 64 (U)")[0], "Star Fox 64 (USA)")

    def test_the_region_tag_is_peeled_last_of_all(self):
        """A beta of the US release is still the US release. Peeling the
        region first would hand it whichever regional row sorted first, and
        the region is the tag most likely to change the answer."""
        meta = self.dats("Star Fox 64 (USA)", "Star Fox 64")
        self.assertEqual(meta.resolve("Star Fox 64 (USA) (Beta)")[0], "Star Fox 64 (USA)")

    def test_punctuation_and_case_alone_do_not_lose_a_game(self):
        meta = self.dats("Legend of Zelda, The - Ocarina of Time (USA)")
        name, _, kind = meta.resolve("legend of zelda the ocarina of time (usa)")
        self.assertEqual((name, kind), ("Legend of Zelda, The - Ocarina of Time (USA)", "loose"))

    def test_an_unrelated_name_matches_nothing_rather_than_the_nearest_row(self):
        """resolve() has no notion of similarity on purpose. A near miss here
        would be written into the shipped database as fact."""
        meta = self.dats("Star Fox 64 (USA)")
        self.assertEqual(meta.resolve("Star Wars - Rogue Squadron (USA)"), ("", None, "none"))

    def test_lookup_is_resolve_without_the_name(self):
        meta = self.dats("Star Fox 64 (USA)")
        found, kind = meta.lookup("Star Fox 64 (USA)")
        self.assertEqual((found.genre, kind), ("Shooter", "exact"))


class CrcLookupTests(DatFixture):
    def test_a_dump_is_found_by_crc_whatever_the_file_was_renamed_to(self):
        meta = self.checkout(genre=game("Super Mario 64 (USA)", "A03CF036", genre="Platform"))
        name, found = meta.by_crc32("A03CF036")
        self.assertEqual(name, "Super Mario 64 (USA)")
        self.assertEqual(found.genre, "Platform")

    def test_the_crc_is_read_however_it_was_written(self):
        """DATs are inconsistent about case, and a CRC with a leading zero is
        routinely written with it dropped. Both spell the same dump."""
        meta = self.checkout(genre=game("A (USA)", "0e4e2b7a", genre="Racing"))
        self.assertEqual(meta.by_crc32("0E4E2B7A")[0], "A (USA)")
        self.assertEqual(meta.by_crc32("e4e2b7a")[0], "A (USA)")

    def test_an_unknown_crc_is_nothing_rather_than_an_empty_row(self):
        meta = self.checkout(genre=game("A (USA)", "11111111", genre="Racing"))
        self.assertIsNone(meta.by_crc32("22222222"))

    def test_the_first_dat_to_name_a_crc_keeps_it(self):
        """The four DATs disagree about a handful of titles. Whichever answer
        is taken, it has to be the same one on every run: the name chosen here
        is written into the shipped database."""
        meta = self.checkout(
            genre=game("Chosen (USA)", "12345678", genre="Racing"),
            publisher=game("Other Spelling (USA)", "12345678", publisher="Nintendo"))
        self.assertEqual(meta.by_crc32("12345678")[0], "Chosen (USA)")


class SerialJoinTests(DatFixture):
    """The NUS product code is the fallback that finds art for a dump nobody
    has catalogued, so the join that produces it has to hold."""

    GOLDENEYE = {
        "genre": game("GoldenEye 007 (Japan)", "3FEB1B9C", genre="Shooter"),
        "serial": game("007 - GoldenEye (Japan)", "3FEB1B9C", serial="NUS-NGUJ-JPN"),
    }

    def test_a_game_the_two_dats_name_differently_is_joined_on_its_crc(self):
        """The serial DAT calls it "007 - GoldenEye (Japan)" and the genre DAT
        calls it "GoldenEye 007 (Japan)". No normaliser reorders a title, and
        a name-based join drops the game silently -- which is exactly what it
        did. Both DATs carry the No-Intro CRC32 of the same file, so that is
        what the join is on."""
        meta = self.checkout(**self.GOLDENEYE)
        self.assertEqual(meta.serial_for("GoldenEye 007 (Japan)"), "NGUJ")

    def test_the_names_really_do_not_match_by_any_amount_of_normalising(self):
        """The guard on the test above: if these two ever normalised to the
        same string the CRC join would pass for the wrong reason and a
        regression to a name-based join would go unnoticed."""
        meta = self.checkout(**self.GOLDENEYE)
        self.assertNotIn(libretro_meta._loose("GoldenEye 007 (Japan)"), meta.loose_serials)
        self.assertNotIn("GoldenEye 007 (Japan)", meta.serials)

    def test_a_matching_name_is_used_before_the_crc_is_consulted(self):
        """The name is the cheaper and more direct answer where the two DATs
        agree, and the CRC join must not overrule it."""
        meta = self.checkout(
            genre=game("Mario Kart 64 (USA)", "3E5055B6", genre="Racing"),
            serial=game("Mario Kart 64 (USA)", "AAAAAAAA", serial="NUS-NKTE-USA")
                   + game("Something Else (USA)", "3E5055B6", serial="NUS-NXXE-USA"))
        self.assertEqual(meta.serial_for("Mario Kart 64 (USA)"), "NKTE")

    def test_a_name_variant_reaches_the_serial_too(self):
        meta = self.checkout(
            genre=game("Star Fox 64 (USA)", "11111111", genre="Shooter"),
            serial=game("Star Fox 64 (USA)", "11111111", serial="NUS-NFXE-USA"))
        self.assertEqual(meta.serial_for("Star Fox 64 (U)"), "NFXE")

    def test_a_serial_spelled_differently_only_in_punctuation_still_joins(self):
        meta = self.checkout(
            serial=game("Legend of Zelda, The - Ocarina of Time (USA)", "22222222",
                        serial="NUS-NZLE-USA"))
        self.assertEqual(meta.serial_for("legend of zelda the ocarina of time (usa)"), "NZLE")

    def test_the_serial_is_reduced_to_the_four_symbols_a_header_carries(self):
        """Header bytes 0x3B..0x3E give four symbols and nothing else. The
        product code's outer groups are the same for every N64 game and the
        region spelled a second way."""
        meta = self.checkout(serial=game("A (USA)", "1", serial="NUS-NSME-USA"))
        self.assertEqual(meta.serial_for("A (USA)"), "NSME")

    def test_a_serial_already_in_the_short_form_is_taken_as_it_is(self):
        meta = self.checkout(serial=game("A (USA)", "1", serial="NFXE"))
        self.assertEqual(meta.serial_for("A (USA)"), "NFXE")

    def test_a_serial_of_an_unexpected_shape_is_refused_not_truncated(self):
        """A serial that is not four symbols cannot be compared against a ROM
        header. Cutting it down to four would match the wrong cartridges."""
        meta = self.checkout(serial=game("A (USA)", "1", serial="NUS-NSME")
                                    + game("B (USA)", "2", serial="NUS-TOOLONG-USA"))
        self.assertEqual(meta.serial_for("A (USA)"), "")
        self.assertEqual(meta.serial_for("B (USA)"), "")

    def test_a_game_with_no_serial_anywhere_gets_an_empty_string(self):
        meta = self.checkout(genre=game("A (USA)", "1", genre="Racing"))
        self.assertEqual(meta.serial_for("A (USA)"), "")

    def test_a_checkout_with_no_serial_dat_still_loads(self):
        """metadat/serial arrived later than the rest. An older checkout has
        to give up the serial fallback, not the whole catalog."""
        meta = self.checkout(genre=game("A (USA)", "1", genre="Racing"))
        self.assertEqual(meta.serials, {})
        self.assertNotIn("serial", meta.counts)
        self.assertEqual(meta.by_name["A (USA)"].genre, "Racing")


class GameMetaTests(unittest.TestCase):
    def test_a_row_with_nothing_in_it_is_falsy(self):
        """Callers ask "did we learn anything" with a plain truth test, and a
        row that answers yes while holding nothing is filed as identified."""
        self.assertFalse(GameMeta())
        self.assertTrue(GameMeta(genre="Racing"))
        self.assertTrue(GameMeta(year=1996))
        self.assertTrue(GameMeta(players=4))
        self.assertTrue(GameMeta(publisher="Nintendo"))


if __name__ == "__main__":
    unittest.main()


class RomCrcShapeTests(unittest.TestCase):
    """The CRC may sit anywhere inside the rom ( ... ) block.

    libretro-database writes `rom ( crc XXXXXXXX )`, but the wider clrmamepro
    convention is `rom ( name "..." size N crc XXXXXXXX )`. The parser used to
    anchor on `crc` being the first token, so the second shape yielded no CRC
    at all -- and because the CRC join is a fallback, the failure was silent:
    identification quietly degraded to name matching with nothing to show for
    it. Anyone pointing this at a differently-generated DAT would have hit it.
    """

    def test_the_crc_is_found_when_it_is_the_first_token(self):
        self.assertEqual(
            libretro_meta.ROM_CRC.search("rom ( crc 1B5E4B94 )").group(1), "1B5E4B94")

    def test_the_crc_is_found_after_name_and_size(self):
        line = 'rom ( name "Super Mario 64 (USA).z64" size 8388608 crc 1B5E4B94 )'
        self.assertEqual(libretro_meta.ROM_CRC.search(line).group(1), "1B5E4B94")

    def test_a_rom_block_with_no_crc_still_yields_nothing(self):
        line = 'rom ( name "Super Mario 64 (USA).z64" size 8388608 )'
        self.assertIsNone(libretro_meta.ROM_CRC.search(line))

    def test_the_search_does_not_run_past_the_end_of_its_own_block(self):
        """Two adjacent blocks, the first without a CRC. Reading the second
        one's CRC into the first would file one game under another's hash."""
        line = 'rom ( name "a.z64" size 8 ) rom ( name "b.z64" crc DEADBEEF )'
        match = libretro_meta.ROM_CRC.search(line)
        self.assertEqual(match.group(1), "DEADBEEF")
        # The match must begin at the second `rom (`, not reach back over the
        # first block's closing paren and file b's hash under a's name.
        self.assertGreater(match.start(), line.index("a.z64"))
        self.assertLess(match.start(), line.index("b.z64"))

    def test_a_name_containing_parentheses_does_not_hide_the_crc(self):
        """Almost every No-Intro name has a region in brackets. A pattern that
        stops at the first `)` sees `(USA` and gives up before reaching crc."""
        line = 'rom ( name "Super Mario 64 (USA) (Rev 1).z64" size 8 crc A03CF036 )'
        self.assertEqual(libretro_meta.ROM_CRC.search(line).group(1), "A03CF036")
