# SPDX-License-Identifier: AGPL-3.0-only
import contextlib
import io
import re
import struct
import tempfile
import unittest
from pathlib import Path

from tools import ed64_registry

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "registry"
SAMPLES = {
    "01": FIXTURES / "sample-01.dat",
    "02": FIXTURES / "sample-02.dat",
    "03": FIXTURES / "sample-03.dat",
    "04": FIXTURES / "sample-04.dat",
}


def sample(which: str) -> bytes:
    return SAMPLES[which].read_bytes()


class SampleTests(unittest.TestCase):
    """Every assertion here is against bytes an EverDrive-64 X7 running OS 3.11
    actually wrote. Checking the decoder against our own encoder would prove
    only that we are self-consistent."""

    def test_the_committed_samples_are_all_there_to_be_read(self):
        """These files are committed on purpose and the tests are the reason.
        A missing one has to fail loudly rather than skip."""
        for which, path in SAMPLES.items():
            with self.subTest(sample=which):
                self.assertTrue(path.is_file(), f"{path} is committed on purpose")
                self.assertEqual(len(path.read_bytes()), ed64_registry.SIZE)

    def test_a_record_the_firmware_wrote_verifies(self):
        for which in SAMPLES:
            with self.subTest(sample=which):
                self.assertTrue(ed64_registry.verify(sample(which)))

    def test_the_armed_record_decodes_to_super_mario_64(self):
        """sample-03 is the capture that decoded the format: the first one
        naming a game with real save hardware. Every field offset below was
        read off it, so it is the fixed point the layout rests on."""
        blob = sample("03")
        self.assertEqual(
            ed64_registry.read_str(blob, ed64_registry.PATH_A, ed64_registry.PATH_A_MAX),
            "/ROMS/1 US - N-Z/Super Mario 64 (USA).z64")
        self.assertEqual(blob[1040:1046].decode("latin-1"), "NSME00")
        self.assertEqual(blob[1028:1036].hex().upper(), "635A2BFF8B022326")
        self.assertEqual(ed64_registry.u16(blob, ed64_registry.SAVE_TYPE_AT), 1)
        self.assertEqual(ed64_registry.u16(blob, ed64_registry.CIC_AT), 1)

    def test_the_offsets_the_module_names_are_the_offsets_it_reads(self):
        """The layout was recovered by hand and is the whole reason the file
        can be cooperated with. A constant drifting by four bytes would still
        decode something -- just not the right something."""
        self.assertEqual(
            (ed64_registry.PATH_A, ed64_registry.ROM_CRC_AT, ed64_registry.ID_AT,
             ed64_registry.SAVE_TYPE_AT, ed64_registry.CIC_AT, ed64_registry.CRC_AT),
            (0, 1028, 1040, 1048, 1050, 2252))

    def test_a_browser_build_with_no_save_hardware_reads_as_off(self):
        """sleekmenu.z64 carries a zero CRC pair and NULs where a game code
        would be, and the menu copies exactly that. Reading these two as a
        game with a save would have the firmware writing a file for a ROM that
        has nowhere to put one."""
        for which in ("01", "02"):
            with self.subTest(sample=which):
                blob = sample(which)
                self.assertEqual(blob[1028:1036], b"\0" * 8)
                self.assertEqual(blob[1040:1046].decode("latin-1"), "N???00")
                self.assertEqual(ed64_registry.u16(blob, ed64_registry.SAVE_TYPE_AT), 0)
                self.assertIsNone(ed64_registry.SAVE_EXT[0])

    def test_the_flushed_record_still_names_the_game_it_flushed(self):
        """sample-04 was taken after the firmware wrote the .srm. The record
        is not consumed: the path and the save type both survived, which is
        why anything cooperating with it must skip rewriting unchanged bytes
        rather than re-arming on every boot."""
        blob = sample("04")
        self.assertEqual(
            ed64_registry.read_str(blob, ed64_registry.PATH_A, ed64_registry.PATH_A_MAX),
            "/ROMS/1 US - N-Z/Super Mario 64 (USA).z64")
        self.assertEqual(ed64_registry.u16(blob, ed64_registry.SAVE_TYPE_AT), 3)

    def test_the_current_selection_is_a_different_field_from_the_path(self):
        """The two looked like one field for a while, because right after a
        launch they hold the same string. Booting the menu and touching
        nothing clears the selection and leaves the path -- sample-04."""
        armed, flushed = sample("03"), sample("04")
        self.assertEqual(
            ed64_registry.read_str(armed, ed64_registry.PATH_B, ed64_registry.PATH_B_MAX),
            ed64_registry.read_str(armed, ed64_registry.PATH_A, ed64_registry.PATH_A_MAX))
        self.assertEqual(
            ed64_registry.read_str(flushed, ed64_registry.PATH_B, ed64_registry.PATH_B_MAX), "")

    def test_the_pi_timing_is_the_cartridges_and_not_the_roms(self):
        """Super Mario 64's header says 80 37 12 40 and the registry says
        40 12 07 03 anyway. Copying the ROM's own word in here would be an
        easy and wrong-looking mistake to make."""
        for which in SAMPLES:
            with self.subTest(sample=which):
                blob = sample(which)
                self.assertEqual(blob[ed64_registry.DOM1_AT:ed64_registry.DOM1_AT + 4].hex(),
                                 "40120703")

    def test_a_path_stops_at_its_terminator_not_at_the_end_of_the_field(self):
        """The menu writes a new path over the old one without clearing the
        tail, so the bytes after the NUL are whatever the last game was
        called. Reading the whole field would show that garbage as the path."""
        blob = bytearray(sample("03"))
        blob[0:64] = b"/A.z64\0" + b"leftover of a longer previous path".ljust(57, b"X")
        self.assertEqual(ed64_registry.read_str(bytes(blob), 0, 1024), "/A.z64")

    def test_a_field_with_no_terminator_stops_at_its_cap(self):
        blob = b"A" * 1024 + b"\0" * (ed64_registry.SIZE - 1024)
        self.assertEqual(ed64_registry.read_str(blob, 0, 8), "AAAAAAAA")

    def test_the_save_type_is_big_endian(self):
        """It is a u16 and every id fits in the low byte, so a little-endian
        read gives 256 times the right answer and looks like an unknown type
        rather than a byte-order mistake."""
        blob = bytearray(ed64_registry.SIZE)
        blob[ed64_registry.SAVE_TYPE_AT:ed64_registry.SAVE_TYPE_AT + 2] = b"\x00\x03"
        self.assertEqual(ed64_registry.u16(bytes(blob), ed64_registry.SAVE_TYPE_AT), 3)


class VerificationTests(unittest.TestCase):
    """The CRC is what makes rewriting the file possible at all. A record that
    does not verify is one we would be guessing at 2252 undecoded bytes of."""

    def test_one_flipped_byte_is_reported_as_bad_not_silently_accepted(self):
        """A corrupt record handed back to the firmware is a save written for
        the wrong game, or over the wrong file."""
        good = sample("03")
        for offset in (0, 1, 500, ed64_registry.ROM_CRC_AT, ed64_registry.ID_AT,
                       1049, ed64_registry.CIC_AT, 2251):
            with self.subTest(offset=offset):
                bad = bytearray(good)
                bad[offset] ^= 0x01
                self.assertFalse(ed64_registry.verify(bytes(bad)))

    def test_a_flip_in_the_stored_checksum_itself_is_caught_too(self):
        for offset in range(ed64_registry.CRC_AT, ed64_registry.SIZE):
            with self.subTest(offset=offset):
                bad = bytearray(sample("03"))
                bad[offset] ^= 0x80
                self.assertFalse(ed64_registry.verify(bytes(bad)))

    def test_a_file_of_the_wrong_length_is_refused_rather_than_unpacked(self):
        """A truncated or padded file must answer false, not raise: the caller
        is a menu that has to carry on without the card's cooperation."""
        good = sample("03")
        for blob in (b"", good[:100], good[:-1], good + b"\0"):
            with self.subTest(size=len(blob)):
                self.assertFalse(ed64_registry.verify(blob))

    def test_describe_says_mismatch_rather_than_ok(self):
        """describe() is what a person reads before deciding to trust a card's
        record. It must not print OK next to a checksum that failed."""
        bad = bytearray(sample("03"))
        bad[1049] ^= 0x01
        self.assertIn("MISMATCH", ed64_registry.describe(bytes(bad)))
        self.assertIn("(OK)", ed64_registry.describe(sample("03")))

    def test_the_checksum_covers_everything_ahead_of_it(self):
        blob = sample("03")
        self.assertEqual(struct.unpack(">I", blob[ed64_registry.CRC_AT:])[0],
                         ed64_registry.crc(blob[:ed64_registry.CRC_AT]))


class RewriteTests(unittest.TestCase):
    """The reseal is the operation that proved the format. sample-04 is what
    came back from the card after exactly this was done to sample-03."""

    def test_changing_the_save_type_touches_that_byte_and_the_checksum_only(self):
        """The controlled experiment: one byte at 1049, from 1 (EEP4K) to
        3 (SRM32K), CRC resealed, nothing else in the 2256 touched. The
        firmware answered with a 32768 byte .srm. Anything that quietly
        rewrote a neighbouring field would have made that proof worthless --
        and would clobber menu settings we never decoded."""
        before = sample("03")
        after = ed64_registry.rewrite(before, save_type=3)
        changed = [i for i in range(ed64_registry.SIZE) if before[i] != after[i]]
        self.assertEqual(changed, [1049, 2252, 2253, 2254, 2255])
        self.assertEqual(ed64_registry.u16(after, ed64_registry.SAVE_TYPE_AT), 3)

    def test_a_resealed_record_verifies_again(self):
        """If it did not, the firmware would reject it and the card would be
        no worse off -- but every save SleekMenu arms would go missing."""
        after = ed64_registry.rewrite(sample("03"), save_type=3)
        self.assertTrue(ed64_registry.verify(after))

    def test_the_reseal_reproduces_what_the_card_was_given(self):
        """The bytes that went back on the card, checked against the capture
        taken afterwards. The firmware also cleared the browser cursor and the
        current selection on the next boot, so only the fields the experiment
        set are compared."""
        after = ed64_registry.rewrite(sample("03"), save_type=3)
        flushed = sample("04")
        self.assertEqual(after[ed64_registry.SAVE_TYPE_AT:ed64_registry.SAVE_TYPE_AT + 2],
                         flushed[ed64_registry.SAVE_TYPE_AT:ed64_registry.SAVE_TYPE_AT + 2])
        self.assertEqual(after[ed64_registry.PATH_A:ed64_registry.PATH_A + 1024],
                         flushed[ed64_registry.PATH_A:ed64_registry.PATH_A + 1024])
        self.assertEqual(after[ed64_registry.ID_AT:ed64_registry.ID_AT + ed64_registry.ID_LEN],
                         flushed[ed64_registry.ID_AT:ed64_registry.ID_AT + ed64_registry.ID_LEN])
        self.assertEqual(after[ed64_registry.ROM_CRC_AT:ed64_registry.ROM_CRC_AT + 8],
                         flushed[ed64_registry.ROM_CRC_AT:ed64_registry.ROM_CRC_AT + 8])

    def test_a_reseal_that_changes_nothing_is_byte_identical(self):
        """Rewriting a file whose bytes have not changed is the one thing the
        record's not-being-consumed makes tempting, and re-arming on every
        menu boot is how a save gets written twice."""
        for which in SAMPLES:
            with self.subTest(sample=which):
                blob = sample(which)
                self.assertEqual(ed64_registry.rewrite(blob), blob)

    def test_every_documented_save_type_survives_a_round_trip(self):
        for identifier in sorted(ed64_registry.SAVE_TYPES):
            with self.subTest(save_type=identifier):
                after = ed64_registry.rewrite(sample("03"), save_type=identifier)
                self.assertTrue(ed64_registry.verify(after))
                self.assertEqual(ed64_registry.u16(after, ed64_registry.SAVE_TYPE_AT),
                                 identifier)

    def test_an_id_the_firmware_does_not_know_is_refused(self):
        """The value goes straight to REG_GAM_CFG. An id krikzz never defined
        is not a bigger save, it is undefined cartridge behaviour."""
        for identifier in (-1, 7, 256):
            with self.subTest(save_type=identifier):
                with self.assertRaisesRegex(ValueError, "save type must be"):
                    ed64_registry.rewrite(sample("03"), save_type=identifier)

    def test_rewriting_the_path_clears_the_tail_of_the_one_it_replaces(self):
        """The firmware leaves the old path's tail in place. We do not, so a
        diff of two cards shows what changed rather than what is left over."""
        after = ed64_registry.rewrite(sample("03"), path="/A.z64")
        self.assertEqual(ed64_registry.read_str(after, ed64_registry.PATH_A, 1024), "/A.z64")
        self.assertEqual(after[6:ed64_registry.PATH_A_MAX], b"\0" * (1024 - 6))
        self.assertEqual(ed64_registry.read_str(after, ed64_registry.PATH_B,
                                                ed64_registry.PATH_B_MAX), "/A.z64")
        self.assertTrue(ed64_registry.verify(after))

    def test_a_path_too_long_for_the_short_field_is_refused(self):
        """Both fields get the same string. Writing 1000 bytes into the 256
        byte one would run over the ROM id and the save type."""
        with self.assertRaisesRegex(ValueError, "short field"):
            ed64_registry.rewrite(sample("03"), path="/ROMS/" + "x" * 300 + ".z64")

    def test_a_path_that_exactly_fills_the_short_field_is_still_refused(self):
        """255 characters plus a terminator is the most that fits. Accepting
        256 would leave the field unterminated and the read would run on into
        whatever follows."""
        with self.assertRaisesRegex(ValueError, "short field"):
            ed64_registry.rewrite(sample("03"), path="/" + "x" * 255)

    def test_a_rom_id_that_is_not_six_symbols_is_refused(self):
        """The field is fixed width. A short id would leave the tail of the
        previous game's id behind it and name a cartridge that is not there."""
        for identifier in ("NSME0", "NSME000", ""):
            with self.subTest(rom_id=identifier):
                with self.assertRaisesRegex(ValueError, "exactly 6"):
                    ed64_registry.rewrite(sample("03"), rom_id=identifier)

    def test_a_rom_crc_that_is_not_the_eight_header_bytes_is_refused(self):
        for value in (b"", b"\x01\x02", b"\x00" * 9):
            with self.subTest(length=len(value)):
                with self.assertRaisesRegex(ValueError, "8 header bytes"):
                    ed64_registry.rewrite(sample("03"), rom_crc=value)

    def test_pointing_the_record_at_another_game_leaves_the_rest_alone(self):
        """The file also holds menu settings and browser position that were
        never decoded. Four fields are ours to write; the other 2200 bytes are
        the user's."""
        before = sample("01")
        after = ed64_registry.rewrite(
            before, path="/ROMS/Wave Race 64 (USA).z64", rom_id="NWRE00",
            save_type=1, rom_crc=bytes.fromhex("07F0AC7F1E3F4D3C"))
        self.assertTrue(ed64_registry.verify(after))
        untouched = [(1052, 1064), (1072, 1196), (2223, 2252)]
        for start, end in untouched:
            with self.subTest(span=(start, end)):
                self.assertEqual(after[start:end], before[start:end])
        self.assertEqual(after[ed64_registry.DOM1_AT:ed64_registry.DOM1_AT + 4],
                         before[ed64_registry.DOM1_AT:ed64_registry.DOM1_AT + 4])
        self.assertEqual(ed64_registry.u16(after, ed64_registry.CIC_AT),
                         ed64_registry.u16(before, ed64_registry.CIC_AT))

    def test_the_original_blob_is_never_modified_in_place(self):
        """The caller holds the bytes it read off the card and compares them
        against the result to decide whether a write is needed at all."""
        before = sample("03")
        copy = bytes(before)
        ed64_registry.rewrite(before, save_type=6, path="/X.z64", rom_id="NXXE00")
        self.assertEqual(before, copy)


class SaveTableTests(unittest.TestCase):
    """The ids are krikzz's and go verbatim to REG_GAM_CFG, so the three
    tables and the C header have to agree about all seven of them."""

    def test_every_id_has_an_extension_and_a_length(self):
        self.assertEqual(set(ed64_registry.SAVE_TYPES), set(ed64_registry.SAVE_EXT))
        self.assertEqual(set(ed64_registry.SAVE_TYPES), set(ed64_registry.SAVE_BYTES))

    def test_off_is_the_only_id_that_writes_nothing(self):
        for identifier, extension in ed64_registry.SAVE_EXT.items():
            with self.subTest(save_type=identifier):
                self.assertEqual(extension is None, identifier == 0)
                self.assertEqual(ed64_registry.SAVE_BYTES[identifier] == 0, identifier == 0)

    def test_the_proven_pair_is_what_the_card_actually_wrote(self):
        """SRM32K wrote "Super Mario 64 (USA).srm" at 32768 bytes and EEP4K
        wrote a 512 byte .eep. Both were measured, not inferred."""
        self.assertEqual((ed64_registry.SAVE_EXT[3], ed64_registry.SAVE_BYTES[3]),
                         (".srm", 32768))
        self.assertEqual((ed64_registry.SAVE_EXT[1], ed64_registry.SAVE_BYTES[1]),
                         (".eep", 512))

    def test_the_ids_match_the_ones_the_n64_side_uses(self):
        """src/save_type.h says the same values are a hardware contract. The
        two tables drifting apart would arm one save type and write another."""
        header = (ROOT / "src" / "save_type.h").read_text(encoding="utf-8")
        block = re.search(r"typedef enum \{(.*?)\} sm_save_type_t;", header, re.S)
        self.assertIsNotNone(block, "src/save_type.h should declare sm_save_type_t")
        from_c = {int(value): name
                  for name, value in re.findall(r"SM_SAVE_(\w+)\s*=\s*(\d+)", block.group(1))}
        self.assertEqual(from_c, ed64_registry.SAVE_TYPES)

    def test_the_record_geometry_matches_the_n64_side(self):
        header = (ROOT / "src" / "ed64_registry.h").read_text(encoding="utf-8")
        self.assertIn(f"#define SM_REGISTRY_SIZE {ed64_registry.SIZE}u", header)
        self.assertIn(f"#define SM_REGISTRY_PATH_MAX {ed64_registry.PATH_B_MAX}u", header)


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def run_tool(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = ed64_registry.main([str(a) for a in arguments])
        return status, out.getvalue(), err.getvalue()

    def write(self, name, blob):
        path = self.root / name
        path.write_bytes(blob)
        return path

    def test_a_record_that_does_not_verify_is_refused(self):
        """The one guard that matters. Rewriting a record we cannot check is
        rewriting 2252 bytes of somebody's menu settings on a guess."""
        bad = bytearray(sample("03"))
        bad[1049] ^= 0x01
        status, _, err = self.run_tool(self.write("bad.dat", bytes(bad)))
        self.assertEqual(status, 1)
        self.assertIn("refusing", err)

    def test_a_file_of_the_wrong_size_is_refused_before_anything_else(self):
        status, _, err = self.run_tool(self.write("short.dat", sample("03")[:100]))
        self.assertEqual(status, 1)
        self.assertIn("expected 2256 bytes", err)

    def test_decoding_a_good_record_reports_its_fields(self):
        status, out, _ = self.run_tool(SAMPLES["03"])
        self.assertEqual(status, 0)
        self.assertIn("Super Mario 64 (USA).z64", out)
        self.assertIn("NSME00", out)
        self.assertIn("save type 1 EEP4K -> .eep (512 bytes)", out)
        self.assertIn("(OK)", out)

    def test_setting_the_save_type_writes_a_record_that_verifies(self):
        output = self.root / "out.dat"
        status, out, _ = self.run_tool(SAMPLES["03"], "--set-save-type", 3,
                                       "--output", output)
        self.assertEqual(status, 0)
        written = output.read_bytes()
        self.assertTrue(ed64_registry.verify(written))
        self.assertEqual([i for i in range(ed64_registry.SIZE)
                          if written[i] != sample("03")[i]],
                         [1049, 2252, 2253, 2254, 2255])
        self.assertIn("--- after ---", out)

    def test_nothing_is_written_when_no_edit_was_asked_for(self):
        """The tool is pointed at a card. Decoding a record must never be a
        write, and it never edits in place even when it does write."""
        output = self.root / "out.dat"
        status, _, _ = self.run_tool(SAMPLES["03"], "--output", output)
        self.assertEqual(status, 0)
        self.assertFalse(output.exists())
        self.assertEqual(SAMPLES["03"].read_bytes(), sample("03"))


if __name__ == "__main__":
    unittest.main()
