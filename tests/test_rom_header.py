# SPDX-License-Identifier: AGPL-3.0-only
import unittest

from tests.rom_fixtures import (N64_MAGIC, SWAP, V64_MAGIC, header_bytes,
                                rom_image, to_n64, to_v64)
from tools import rom_header

# One cartridge, spelled out once: Super Mario 64's real CRC pair and NUS code,
# so a test that says "the product code is NSME" is saying something checkable.
CRC1, CRC2 = 0x635A2BFF, 0x8B022326


def cartridge(**kwargs) -> bytes:
    options = dict(title="SUPER MARIO 64", country="E", game_code="SM")
    options.update(kwargs)
    return rom_image(CRC1, CRC2, **options)


class ByteOrderTests(unittest.TestCase):
    """The same cartridge is dumped three ways, and the same person's shelf
    usually holds all three. If a dump's byte order changed what the header
    said, one game would occupy three rows of the cover database and two of
    them would be wrong."""

    def test_a_byteswapped_v64_dump_reads_the_same_as_its_z64_twin(self):
        image = cartridge()
        native = rom_header.parse(image[:rom_header.HEADER_SIZE])
        swapped = rom_header.parse(to_v64(image)[:rom_header.HEADER_SIZE])
        self.assertEqual(swapped.form, "v64")
        self.assertEqual(swapped.crc_pair, native.crc_pair)
        self.assertEqual(swapped.product_code, native.product_code)
        self.assertEqual(swapped.internal_title, native.internal_title)
        self.assertEqual(swapped.regions, native.regions)

    def test_a_word_swapped_n64_dump_reads_the_same_as_its_z64_twin(self):
        """The .n64 ordering reverses whole words, so the four bytes of the NUS
        code at 0x3B..0x3E straddle a word boundary. Deswapping a word at a
        time and then reading the field is right; reading the field and then
        trying to unpick it is not, and the difference only shows up here."""
        image = cartridge()
        native = rom_header.parse(image[:rom_header.HEADER_SIZE])
        swapped = rom_header.parse(to_n64(image)[:rom_header.HEADER_SIZE])
        self.assertEqual(swapped.form, "n64")
        self.assertEqual(swapped.crc_pair, native.crc_pair)
        self.assertEqual(swapped.product_code, native.product_code)
        self.assertEqual(swapped.internal_title, native.internal_title)
        self.assertEqual(swapped.version, native.version)

    def test_the_byte_order_comes_from_the_magic_and_never_from_the_extension(self):
        """The library this was written for holds 86 byteswapped images named
        .z64. Trusting the extension would misread every one of them, and the
        module is handed bytes precisely so it cannot be told a filename."""
        for form, magic in (("z64", bytes(header_bytes(0, 0)[:4])),
                            ("v64", V64_MAGIC), ("n64", N64_MAGIC)):
            with self.subTest(form=form):
                header = rom_header.parse(SWAP[form](cartridge())[:rom_header.HEADER_SIZE])
                self.assertEqual(header.form, form)
                self.assertEqual(header.crc_pair, f"{CRC1:08X}{CRC2:08X}")
                self.assertEqual(SWAP[form](cartridge())[:4], magic)

    def test_deswapping_a_dump_returns_the_bytes_the_cartridge_holds(self):
        """Deswapping is what makes a .v64 hash to the number No-Intro recorded
        for the .z64. If it were merely self-consistent rather than correct,
        every byteswapped dump in a library would quietly identify as nothing."""
        image = cartridge()
        self.assertEqual(rom_header.deswap(to_v64(image), "v64"), image)
        self.assertEqual(rom_header.deswap(to_n64(image), "n64"), image)
        self.assertEqual(rom_header.deswap(image, "z64"), image)


class HeaderFieldTests(unittest.TestCase):
    def test_the_crc_pair_is_crc1_then_crc2_and_the_order_is_the_key(self):
        """The pair is the cover database's primary key. Transposing the two
        words still yields sixteen plausible hex digits, so nothing would raise
        -- every row would simply stop matching, on every card, silently."""
        header = rom_header.parse(cartridge()[:rom_header.HEADER_SIZE])
        self.assertEqual(header.crc1, CRC1)
        self.assertEqual(header.crc2, CRC2)
        self.assertEqual(header.crc_pair, "635A2BFF8B022326")
        transposed = rom_header.parse(rom_image(CRC2, CRC1)[:rom_header.HEADER_SIZE])
        self.assertNotEqual(transposed.crc_pair, header.crc_pair)

    def test_the_product_code_is_the_four_bytes_of_the_nus_number(self):
        """NUS-NSME-USA: media letter, two-character game code, region letter,
        taken from 0x3B..0x3E. It is the fallback that finds art for a dump the
        database has never seen, so an off-by-one here loses art quietly."""
        header = rom_header.parse(cartridge()[:rom_header.HEADER_SIZE])
        self.assertEqual(header.product_code, "NSME")
        self.assertEqual(header.game_code, "SM")
        self.assertEqual(header.country, "E")

    def test_every_revision_of_a_release_shares_one_product_code(self):
        """That sharing is the whole reason the serial column exists: an
        unknown revision of a known release still finds the shelf edition's
        cover. Folding the revision byte into the code would defeat it."""
        first = rom_header.parse(rom_image(0x11, 0x22, country="E", game_code="SM",
                                           version=0)[:rom_header.HEADER_SIZE])
        later = rom_header.parse(rom_image(0x33, 0x44, country="E", game_code="SM",
                                           version=3)[:rom_header.HEADER_SIZE])
        self.assertEqual(first.product_code, later.product_code)
        self.assertNotEqual(first.crc_pair, later.crc_pair)

    def test_the_revision_byte_is_read_and_kept_where_the_menu_shows_it(self):
        """0x3F is the revision. The stock firmware's six-symbol id appends it
        as two hex digits, and that string is what a registry record is
        compared against -- 'NSME03' and 'NSME3' are not the same record."""
        header = rom_header.parse(cartridge(version=3)[:rom_header.HEADER_SIZE])
        self.assertEqual(header.version, 3)
        self.assertEqual(header.rom_id, "NSME03")
        self.assertEqual(header.rom_id[:4], header.product_code)

    def test_the_internal_title_drops_its_padding_and_its_control_bytes(self):
        """The title is drawn on a 320-pixel screen. A stray 0x01 left in by a
        dumper renders as a box or eats the rest of the line, and the twenty
        bytes are space- or NUL-padded depending on who built the cartridge."""
        raw = bytearray(cartridge())
        raw[0x20:0x34] = b"\x01SUPER MARIO 64\x00\x00\x00\x00\x00"
        self.assertEqual(rom_header.parse(bytes(raw)).internal_title, "SUPER MARIO 64")

    def test_a_homebrew_header_with_no_id_reports_none_rather_than_mojibake(self):
        """Homebrew and hacks leave the id bytes zero. A product code of four
        NULs would be a key -- shared by every homebrew ever built -- so the
        module returns nothing at all and lets the caller stop looking."""
        raw = bytearray(cartridge())
        raw[0x3B:0x3F] = b"\0\0\0\0"
        header = rom_header.parse(bytes(raw))
        self.assertEqual(header.product_code, "")
        self.assertEqual(header.rom_id, "????00")
        self.assertEqual(header.country, "")

    def test_one_unprintable_byte_is_enough_to_withdraw_the_product_code(self):
        """A translation patch that rewrites the region byte to something
        unprintable leaves three good characters and one bad one. Three
        characters of NUS code is not an identity, so the answer is nothing."""
        raw = bytearray(cartridge())
        raw[0x3E] = 0x00
        header = rom_header.parse(bytes(raw))
        self.assertEqual(header.product_code, "")
        self.assertEqual(header.game_code, "SM")


class MalformedInputTests(unittest.TestCase):
    """seed_coverdb and build_metadata hand this module whatever the first 64
    bytes of a file happen to be. Anything that is not a cartridge has to come
    back as 'not a cartridge' -- an exception stops a library walk dead, and a
    confident wrong answer files junk under a real game's key."""

    def test_a_file_too_short_to_hold_a_header_is_not_identified(self):
        for length in (0, 1, 4, rom_header.HEADER_SIZE - 1):
            with self.subTest(length=length):
                self.assertIsNone(rom_header.parse(cartridge()[:length]))

    def test_bytes_that_are_not_an_n64_image_are_refused_rather_than_misread(self):
        for name, data in (
            ("png", b"\x89PNG\r\n\x1a\n" + bytes(200)),
            ("text", b"This is a readme, not a cartridge. " * 8),
            ("zeroes", bytes(256)),
            ("magic in the wrong place", bytes(8) + header_bytes(1, 2)),
        ):
            with self.subTest(name=name):
                self.assertIsNone(rom_header.parse(data))

    def test_junk_behind_the_first_64_bytes_cannot_change_the_answer(self):
        """A ROM is megabytes; the header is 64 bytes and the reader is only
        ever given those. Nothing further into the file may reach the fields."""
        short = rom_header.parse(cartridge()[:rom_header.HEADER_SIZE])
        long = rom_header.parse(header_bytes(CRC1, CRC2, title="SUPER MARIO 64",
                                             country="E", game_code="SM") + b"\xff" * 4096)
        self.assertEqual(long.crc_pair, short.crc_pair)
        self.assertEqual(long.internal_title, short.internal_title)

    def test_a_dump_with_a_zeroed_crc_pair_identifies_nothing(self):
        """A few homebrew builds and bad dumps leave the CRC pair blank. It
        parses -- there is nothing malformed about it -- but it is not a key,
        and every caller has to be able to see that for itself."""
        header = rom_header.parse(rom_image(0, 0)[:rom_header.HEADER_SIZE])
        self.assertIsNotNone(header)
        self.assertEqual(header.crc_pair, "0" * 16)


class RegionTests(unittest.TestCase):
    def test_the_cartridge_answers_first_and_the_filename_cannot_override_it(self):
        """Files get renamed and mislabelled; the country byte is what the
        cartridge was manufactured with. A Japanese cartridge in a file somebody
        tagged (USA) is a Japanese cartridge, and filtering by region has to
        agree with what actually boots."""
        header = rom_header.parse(cartridge(country="J")[:rom_header.HEADER_SIZE])
        self.assertEqual(rom_header.regions_for(header, "Game (USA).z64"), ["JAPAN"])

    def test_a_dual_market_cartridge_reports_both_markets(self):
        """'A' shipped for both NTSC markets. Recording one of them would hide
        the game from a filter it genuinely belongs in."""
        header = rom_header.parse(cartridge(country="A")[:rom_header.HEADER_SIZE])
        self.assertEqual(rom_header.regions_for(header, "Game.z64"), ["USA", "JAPAN"])

    def test_a_blank_country_byte_falls_back_to_the_filename(self):
        """Homebrew and romhacks usually leave the byte zero. The filename is
        the only thing left that knows, and it is asked only then."""
        raw = bytearray(cartridge())
        raw[0x3E] = 0
        header = rom_header.parse(bytes(raw))
        self.assertEqual(rom_header.regions_for(header, "Some Hack (USA).z64"), ["USA"])
        self.assertEqual(rom_header.regions_for(header, "Some Hack.z64"), [])

    def test_a_market_with_no_bucket_records_nothing_rather_than_guessing(self):
        """A Korean cartridge is not a US one. The header answered, and the
        answer was a market the catalog has no filter for, so the filename is
        never consulted -- inventing USA from a tag would be worse than blank."""
        header = rom_header.parse(cartridge(country="K")[:rom_header.HEADER_SIZE])
        self.assertEqual(header.regions, ())
        self.assertEqual(rom_header.regions_for(header, "Game (USA).z64"), [])

    def test_a_file_that_is_not_a_cartridge_still_gets_a_region_from_its_name(self):
        """build_metadata calls this for every file it walked, including the
        ones parse() refused. It must not require a header to exist."""
        self.assertEqual(rom_header.regions_for(None, "Game (Europe).z64"), ["EUROPE"])
        self.assertEqual(rom_header.regions_for(None, "Game.z64"), [])


if __name__ == "__main__":
    unittest.main()
