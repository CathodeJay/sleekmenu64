# SPDX-License-Identifier: AGPL-3.0-only
import unittest

from tools import coverdb, identify, rom_header
from tests.rom_fixtures import header_bytes


def header(crc1, crc2, code="SM", country="E"):
    return rom_header.parse(header_bytes(crc1, crc2, game_code=code, country=country))


class SerialIndexTests(unittest.TestCase):
    """The NUS product code -- NUS-*NSME*-USA -- is shared by every revision
    and language variant of a release, and inherited by every hack built on
    one. It finds the box for a dump the database has never seen."""

    def test_revisions_of_one_release_collapse_to_the_shelf_edition(self):
        entries = [
            coverdb.Entry(crc="1" * 16, name="Star Fox 64 (USA) (Rev 1)", serial="NFXE"),
            coverdb.Entry(crc="2" * 16, name="Star Fox 64 (USA)", serial="NFXE"),
        ]
        self.assertEqual(identify.by_serial(entries)["NFXE"].name, "Star Fox 64 (USA)")

    def test_two_different_games_on_one_serial_are_both_refused(self):
        entries = [
            coverdb.Entry(crc="1" * 16, name="Wave Race 64 (USA)", serial="NZZE"),
            coverdb.Entry(crc="2" * 16, name="Blast Corps (USA)", serial="NZZE"),
        ]
        self.assertEqual(identify.by_serial(entries), {})

    def test_a_region_free_prefix_shared_by_two_games_is_refused(self):
        entries = [
            coverdb.Entry(crc="1" * 16, name="Wave Race 64 (USA)", serial="NWRE"),
            coverdb.Entry(crc="2" * 16, name="Something Else (Japan)", serial="NWRJ"),
        ]
        self.assertEqual(identify.by_serial_prefix(entries), {})

    def test_regional_releases_of_one_game_share_a_prefix(self):
        entries = [
            coverdb.Entry(crc="1" * 16, name="Star Fox 64 (USA)", serial="NFXE"),
            coverdb.Entry(crc="2" * 16, name="Star Fox 64 (Japan)", serial="NFXJ"),
        ]
        chosen = identify.by_serial_prefix(entries)["NFX"]
        self.assertEqual(identify.normalize_name(chosen.name), "star fox 64")

    def test_names_compare_without_their_tags(self):
        self.assertEqual(identify.normalize_name("GoldenEye 007 (Europe) (Rev 1).z64"),
                         "goldeneye 007")
        self.assertEqual(identify.normalize_name("Zelda no Densetsu (Japan) (En,Ja)"),
                         "zelda no densetsu")

    def test_a_prerelease_ranks_below_a_revision_below_the_shelf_copy(self):
        self.assertEqual(identify.release_rank("Game (USA)"), 0)
        self.assertEqual(identify.release_rank("Game (USA) (Rev 2)"), 1)
        self.assertEqual(identify.release_rank("Game (USA) (Kiosk Demo)"), 2)
        self.assertEqual(identify.release_rank("Game (USA) (Beta)"), 3)


class IdentifyTests(unittest.TestCase):
    def test_the_crc_wins_when_it_knows_the_dump(self):
        exact = coverdb.Entry(crc=f"{0x33:08X}{0x44:08X}", name="The Exact Dump (USA)", serial="NSME")
        other = coverdb.Entry(crc="9" * 16, name="Something Else (USA)", serial="NSME")
        index = identify.Index({exact.crc: exact, other.crc: other})
        entry, how = index.identify(header(0x33, 0x44))
        self.assertEqual((entry.name, how), ("The Exact Dump (USA)", "crc"))

    def test_an_unknown_dump_of_a_known_release_is_found_by_serial(self):
        known = coverdb.Entry(crc="1" * 16, name="Super Mario 64 (USA)", serial="NSME")
        entry, how = identify.Index([known]).identify(header(0xDEAD, 0xBEEF))
        self.assertEqual((entry.name, how), ("Super Mario 64 (USA)", "serial"))

    def test_a_translation_that_repatched_the_region_byte_still_matches(self):
        """NJLJ becomes NJLE under an English patch; the box has not changed."""
        known = coverdb.Entry(crc="7" * 16, name="J.League Live 64 (Japan)", serial="NJLJ")
        entry, how = identify.Index([known]).identify(header(0x71, 0x72, code="JL", country="E"))
        self.assertEqual((entry.name, how), ("J.League Live 64 (Japan)", "serial without region"))

    def test_the_exact_serial_is_tried_before_the_region_free_one(self):
        exact = coverdb.Entry(crc="1" * 16, name="Right Game (USA)", serial="NSME")
        other = coverdb.Entry(crc="2" * 16, name="Right Game (Japan)", serial="NSMJ")
        entry, how = identify.Index([exact, other]).identify(header(0x81, 0x82))
        self.assertEqual((entry.name, how), ("Right Game (USA)", "serial"))

    def test_a_header_with_no_usable_code_is_not_matched_by_serial(self):
        known = coverdb.Entry(crc="1" * 16, name="Super Mario 64 (USA)", serial="NSME")
        blank = header(0x55, 0x66, code="\x00\x00", country="\x00")
        self.assertEqual(identify.Index([known]).identify(blank), (None, ""))

    def test_no_header_at_all_is_nothing(self):
        self.assertEqual(identify.Index({}).identify(None), (None, ""))


if __name__ == "__main__":
    unittest.main()
