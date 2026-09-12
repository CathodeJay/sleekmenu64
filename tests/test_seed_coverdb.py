# SPDX-License-Identifier: AGPL-3.0-only
import contextlib
import io
import json
import tempfile
import time
import unittest
import zlib
from pathlib import Path

from tests.rom_fixtures import rom_image, write_rom_in
from tools import coverdb, seed_coverdb
from tools.libretro_meta import LibretroMeta

DAT = "Nintendo - Nintendo 64.dat"
# metadat/ folder -> the key libretro writes in each block, and the fact it is.
FOLDERS = (("genre", "genre", "genre"), ("publisher", "publisher", "publisher"),
           ("releaseyear", "releaseyear", "year"), ("maxusers", "users", "players"))


def quiet(*args):
    """A library walk is chatty, and a test run is not the place for it."""


def crc32_of(image: bytes) -> str:
    """What No-Intro recorded: the CRC32 of the big-endian image."""
    return f"{zlib.crc32(image) & 0xFFFFFFFF:08X}"


def game(name, crc32, genre="", publisher="", year=0, players=0, serial=""):
    """One libretro row: the four facts a cartridge cannot answer about itself,
    plus the file CRC32 they are filed under."""
    return dict(name=name, crc32=crc32, genre=genre, publisher=publisher,
                year=year, players=players, serial=serial)


def write_libretro(root: Path, games) -> Path:
    """A libretro-database checkout small enough to read. The real DATs are
    thirteen hundred games long; the shape of a block is all that differs."""
    metadat = root / "metadat"
    for folder, key, fact in FOLDERS:
        folder_path = metadat / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        (folder_path / DAT).write_text("".join(
            f'game (\n\tcomment "{row["name"]}"\n\t{key} "{row[fact]}"\n'
            f'\trom ( crc {row["crc32"]} )\n)\n'
            for row in games if row[fact]), encoding="utf-8")
    serials = metadat / "serial"
    serials.mkdir(parents=True, exist_ok=True)
    (serials / DAT).write_text("".join(
        f'game (\n\tcomment "{row["name"]}"\n\tserial "NUS-{row["serial"]}-USA"\n'
        f'\trom ( crc {row["crc32"]} )\n)\n'
        for row in games if row["serial"]), encoding="utf-8")
    return root


class SeedFixture(unittest.TestCase):
    """One library, two cartridges, and a libretro checkout that knows both."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.roms = self.root / "ROMS"
        self.roms.mkdir()
        # Super Mario 64's real header CRC pair and NUS code, so the assertions
        # below are checkable against a cartridge somebody actually owns.
        self.mario = rom_image(0x635A2BFF, 0x8B022326, title="SUPER MARIO 64",
                               country="E", game_code="SM")
        self.mario_key = "635A2BFF8B022326"
        self.kart = rom_image(0x3E5055B6, 0x1B5FD8AB, title="MARIOKART64",
                              country="E", game_code="MK", body=b"\xAB\xCD" * 512)
        self.meta = self.libretro(
            # The serials here are deliberately not the ones the headers carry:
            # seed reads the cartridge, and this is how we can tell.
            game("Super Mario 64 (USA)", crc32_of(self.mario), "Platform",
                 "Nintendo", 1996, 1, "ZZZA"),
            game("Mario Kart 64 (USA)", crc32_of(self.kart), "Racing",
                 "Nintendo", 1997, 4, "ZZZB"),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def libretro(self, *games):
        self.libretro_root = write_libretro(self.root / "libretro", games)
        return LibretroMeta.load(self.libretro_root)

    def seed(self, **kwargs):
        options = dict(roms_root=self.roms, meta=self.meta,
                       use_file_crc=False, cache_path=None, deadline=None, log=quiet)
        options.update(kwargs)
        return seed_coverdb.seed(**options)

    def run_main(self, *argv):
        """main() prints a summary; the test wants the file it wrote."""
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = seed_coverdb.main(list(argv))
        return code, out.getvalue()


class FileCrc32Tests(SeedFixture):
    """The single thing in this file that quietly ruins a database if it is
    wrong. One cartridge is dumped as .z64, .v64 and .n64 by three different
    people, and all three have to arrive at the number libretro filed the game
    under -- otherwise two thirds of a real library identifies as nothing and
    the failure looks exactly like a library of unknown games."""

    def test_all_three_byte_orders_of_one_cartridge_hash_to_the_same_number(self):
        expected = crc32_of(self.mario)
        for form in ("z64", "v64", "n64"):
            with self.subTest(form=form):
                path = self.roms / f"dump.{form}"
                write_rom_in(path, form, self.mario)
                self.assertEqual(seed_coverdb.file_crc32(path, form), expected)

    def test_the_hash_of_a_byteswapped_dump_is_not_the_hash_of_its_own_bytes(self):
        """The guard against a deswap that silently stops happening. Without
        it every assertion above still passes if the .v64 and .n64 branches
        are removed and the three files are made byte-identical by accident."""
        for form in ("v64", "n64"):
            with self.subTest(form=form):
                path = self.roms / f"dump.{form}"
                on_disk = write_rom_in(path, form, self.mario)
                self.assertNotEqual(on_disk, self.mario)
                self.assertNotEqual(seed_coverdb.file_crc32(path, form), crc32_of(on_disk))
                self.assertEqual(seed_coverdb.file_crc32(path, form), crc32_of(self.mario))

    def test_two_different_cartridges_do_not_collide(self):
        """A CRC32 that agreed too readily would be worse than none: it would
        file Mario Kart's metadata under Super Mario 64 and look like a match."""
        write_rom_in(self.roms / "a.z64", "z64", self.mario)
        write_rom_in(self.roms / "b.z64", "z64", self.kart)
        self.assertNotEqual(seed_coverdb.file_crc32(self.roms / "a.z64", "z64"),
                            seed_coverdb.file_crc32(self.roms / "b.z64", "z64"))

    def test_a_rom_larger_than_one_read_buffer_is_deswapped_across_the_seam(self):
        """Every real cartridge is bigger than the 1 MB read buffer, and the
        fixtures above are not. A deswap that mishandled a chunk boundary would
        pass every other test here and fail on all 1,300 actual games."""
        big = rom_image(0x11223344, 0x55667788, body=bytes(range(256)) * 4096)
        self.assertGreater(len(big), seed_coverdb.CHUNK)
        for form in ("z64", "v64", "n64"):
            with self.subTest(form=form):
                path = self.roms / f"big.{form}"
                write_rom_in(path, form, big)
                self.assertEqual(seed_coverdb.file_crc32(path, form), crc32_of(big))


class IdentificationTests(SeedFixture):
    def test_a_renamed_dump_is_identified_by_what_it_contains(self):
        """The reason --file-crc exists. '0421 - stuff [!]' is what a real card
        holds, and no name matcher will ever get a title out of it."""
        write_rom_in(self.roms / "0421 - stuff [!].z64", "z64", self.mario)
        entries, how, complete = self.seed(use_file_crc=True)
        self.assertTrue(complete)
        self.assertEqual(entries[self.mario_key].name, "Super Mario 64 (USA)")
        self.assertEqual(entries[self.mario_key].genre, "Platform")
        self.assertEqual(how["matched by file crc"], 1)

    def test_a_byteswapped_copy_and_its_z64_twin_produce_one_row_not_two(self):
        """Byteswapped dumps are common enough that a library usually holds
        both. Two rows for one cartridge means a correction made to one of them
        is invisible on whichever copy the card happens to carry."""
        write_rom_in(self.roms / "Super Mario 64 (USA).z64", "z64", self.mario)
        write_rom_in(self.roms / "backup" / "smb64.v64", "v64", self.mario)
        entries, how, _ = self.seed(use_file_crc=True)
        self.assertEqual(list(entries), [self.mario_key])
        self.assertEqual(how["matched by file crc"], 2)

    def test_the_filename_is_only_consulted_when_the_contents_are_unknown(self):
        """A dump libretro has never seen still deserves whatever the title
        says, but the answer is a guess and the counter has to say so."""
        unknown = rom_image(0x99, 0x88, country="E", game_code="MK")
        write_rom_in(self.roms / "Mario Kart 64 (U).z64", "z64", unknown)
        entries, how, _ = self.seed(use_file_crc=True)
        self.assertEqual(entries["0000009900000088"].name, "Mario Kart 64 (USA)")
        self.assertEqual(how["matched by variant"], 1)
        self.assertNotIn("matched by file crc", how)

    def test_a_game_no_database_knows_is_not_filed_at_all(self):
        """A row whose name is just the filename identifies the dump but not
        the game; a placeholder row would only make the database look as if
        it knew something it does not."""
        write_rom_in(self.roms / "Cool Homebrew.z64", "z64", rom_image(0x77, 0x66))
        entries, how, _ = self.seed()
        self.assertEqual(entries, {})
        self.assertEqual(how["unidentified, not filed"], 1)

    def test_include_unidentified_files_it_under_its_filename_on_request(self):
        write_rom_in(self.roms / "Cool Homebrew.z64", "z64", rom_image(0x77, 0x66))
        entries, how, _ = self.seed(include_unidentified=True)
        self.assertEqual(entries["0000007700000066"].name, "Cool Homebrew")
        self.assertNotIn("unidentified, not filed", how)

    def test_a_dump_with_a_blank_header_crc_is_never_filed(self):
        """Homebrew and a few bad dumps leave the pair zeroed. It is not a key:
        filing one would put every such dump in the library on the same row."""
        write_rom_in(self.roms / "Homebrew.z64", "z64", rom_image(0, 0))
        entries, how, _ = self.seed()
        self.assertEqual(entries, {})
        self.assertEqual(how["blank header crc"], 1)

    def test_a_file_that_is_not_a_cartridge_is_counted_and_skipped(self):
        """A ROMS folder collects save files, notes and half-finished
        downloads named .z64. One of them must not stop the walk."""
        (self.roms / "readme.z64").write_bytes(b"not a cartridge, just a note. " * 8)
        write_rom_in(self.roms / "Super Mario 64 (USA).z64", "z64", self.mario)
        entries, how, _ = self.seed()
        self.assertEqual(list(entries), [self.mario_key])
        self.assertEqual(how["not a rom"], 1)

    def test_the_row_is_keyed_on_the_header_pair_and_not_on_the_file_hash(self):
        """The console can compute the header pair from the first 64 bytes it
        already read. It cannot hash 16 MB off a card to look a game up."""
        write_rom_in(self.roms / "Super Mario 64 (USA).z64", "z64", self.mario)
        entries, _, _ = self.seed(use_file_crc=True)
        self.assertEqual(list(entries), [self.mario_key])
        self.assertNotIn(crc32_of(self.mario), entries)

    def test_the_serial_and_the_regions_come_from_the_cartridge_itself(self):
        """Both are in the header, so they are facts rather than lookups. The
        fixture files this game's serial as ZZZA on purpose: if a row ever
        carries that, the cartridge stopped being asked."""
        write_rom_in(self.roms / "junk name.z64", "z64", self.mario)
        entries, _, _ = self.seed(use_file_crc=True)
        self.assertEqual(entries[self.mario_key].serial, "NSME")
        self.assertEqual(entries[self.mario_key].regions, ("USA",))

    def test_a_time_budget_already_spent_stops_before_reading_anything(self):
        """--time-budget exists so a maintainer can seed a huge library in
        sittings. Stopping has to be clean and has to be admitted, because a
        half-built database written out as if it were finished is worse than
        no database at all."""
        write_rom_in(self.roms / "Super Mario 64 (USA).z64", "z64", self.mario)
        said = []
        entries, how, complete = self.seed(deadline=time.monotonic() - 1,
                                           log=said.append)
        self.assertEqual(entries, {})
        self.assertFalse(complete)
        self.assertIn("re-run to continue", said[0])


class DuplicateTests(SeedFixture):
    def copies(self, *folders):
        for folder in folders:
            write_rom_in(self.roms / folder / "Super Mario 64 (USA).z64", "z64", self.mario)

    def test_three_copies_of_one_dump_collapse_to_a_single_row(self):
        """A library that keeps a game in a genre folder and two best-of
        folders is three files and one cartridge. Three rows would be three
        chances to disagree about what the cartridge is."""
        self.copies("Platformers", "Best of", "Nintendo")
        entries, how, _ = self.seed()
        self.assertEqual(list(entries), [self.mario_key])
        self.assertEqual(how["matched by exact"], 3)

class CrcCacheTests(SeedFixture):
    """Reading a real library in full is minutes of disk. The cache is what
    makes a second run bearable, and a cache that is trusted when it should not
    be files one game's metadata under another game's key."""

    def cache_line(self, path: Path, crc32: str, mtime: int | None = None) -> str:
        stat = path.stat()
        return json.dumps({"path": str(path), "size": stat.st_size,
                           "mtime": int(stat.st_mtime) if mtime is None else mtime,
                           "crc32": crc32})

    def test_a_cached_crc32_is_used_instead_of_re_reading_the_rom(self):
        """Cached deliberately as the wrong game: if the row comes back as
        Mario Kart, the cache was believed, which is the whole point of it."""
        rom = self.roms / "mystery.z64"
        write_rom_in(rom, "z64", self.mario)
        cache = self.root / "crc.jsonl"
        cache.write_text(self.cache_line(rom, crc32_of(self.kart)) + "\n", encoding="utf-8")
        entries, _, _ = self.seed(use_file_crc=True, cache_path=cache)
        self.assertEqual(entries[self.mario_key].name, "Mario Kart 64 (USA)")

    def test_an_edited_rom_invalidates_its_cache_entry(self):
        """The key carries size and mtime precisely so that a ROM someone
        re-dumped or trimmed is read again rather than answered from a stale
        line -- and the wrong answer would never be noticed."""
        rom = self.roms / "mystery.z64"
        write_rom_in(rom, "z64", self.mario)
        stat = rom.stat()
        cache = self.root / "crc.jsonl"
        cache.write_text(self.cache_line(rom, crc32_of(self.kart),
                                         mtime=int(stat.st_mtime) + 120) + "\n",
                         encoding="utf-8")
        entries, _, _ = self.seed(use_file_crc=True, cache_path=cache)
        self.assertEqual(entries[self.mario_key].name, "Super Mario 64 (USA)")

    def test_a_corrupt_cache_line_is_skipped_rather_than_fatal(self):
        """The file is appended to and flushed as the walk goes, so an
        interrupted run leaves a half-written last line. Losing hours of
        hashing because of it would defeat the reason it is written at all."""
        rom = self.roms / "mystery.z64"
        write_rom_in(rom, "z64", self.mario)
        cache = self.root / "crc.jsonl"
        cache.write_text("\n".join(["not json at all", json.dumps({"path": "no other keys"}),
                                    "", '{"path": "truncated", "size": 1']) + "\n"
                         + self.cache_line(rom, crc32_of(self.kart)) + "\n", encoding="utf-8")
        self.assertEqual(len(seed_coverdb.load_cache(cache)), 1)
        entries, _, _ = self.seed(use_file_crc=True, cache_path=cache)
        self.assertEqual(entries[self.mario_key].name, "Mario Kart 64 (USA)")

    def test_a_missing_cache_file_is_an_empty_cache_and_not_an_error(self):
        self.assertEqual(seed_coverdb.load_cache(self.root / "never-written.jsonl"), {})
        self.assertEqual(seed_coverdb.load_cache(None), {})

    def test_only_unmatched_leaves_a_rom_the_name_already_answered_unread(self):
        """The trade the flag exists to make: hours instead of most of a day,
        at the price of trusting a name match that succeeded. A line in the
        cache is proof the expensive read happened, so an empty cache is proof
        it did not."""
        write_rom_in(self.roms / "Super Mario 64 (USA).z64", "z64", self.mario)
        cheap, how, _ = self.seed(use_file_crc=True, only_unmatched=True,
                                  cache_path=self.root / "cheap.jsonl")
        self.assertEqual(how["matched by exact"], 1)
        self.assertEqual((self.root / "cheap.jsonl").read_text(), "")

        full, how, _ = self.seed(use_file_crc=True, cache_path=self.root / "full.jsonl")
        self.assertEqual(how["matched by file crc"], 1)
        self.assertEqual(len((self.root / "full.jsonl").read_text().splitlines()), 1)
        self.assertEqual(cheap[self.mario_key].name, full[self.mario_key].name)


class MergeTests(SeedFixture):
    """data/coverdb.csv is reviewed and corrected by hand and then re-seeded
    from a bigger library. A re-seed that undid the corrections would make the
    review pointless, and nobody would notice until a card was built."""

    def setUp(self):
        super().setUp()
        self.output = self.root / "coverdb.csv"
        write_rom_in(self.roms / "Super Mario 64 (USA).z64", "z64", self.mario)

    def curated(self, *entries):
        coverdb.save(self.output, entries)

    def test_a_re_seed_cannot_clobber_a_curated_row(self):
        self.curated(coverdb.Entry(crc=self.mario_key, name="Super Mario 64 (USA)",
                                   publisher="The Curator", genre="Platformer"))
        code, _ = self.run_main(str(self.roms), "--libretro", str(self.libretro_root),
                                "--merge", "--output", str(self.output))
        row = coverdb.load(self.output)[self.mario_key]
        self.assertEqual(code, 0)
        self.assertEqual(row.publisher, "The Curator")
        self.assertEqual(row.genre, "Platformer")   # not libretro's "Platform"

    def test_a_re_seed_still_fills_the_blanks_the_curator_left(self):
        """Refusing to overwrite is only half of it: a merge that also refused
        to add would freeze the file at whatever the first pass produced."""
        self.curated(coverdb.Entry(crc=self.mario_key, name="Super Mario 64 (USA)",
                                   genre="Platformer"))
        self.run_main(str(self.roms), "--libretro", str(self.libretro_root),
                      "--merge", "--output", str(self.output))
        row = coverdb.load(self.output)[self.mario_key]
        self.assertEqual((row.publisher, row.year, row.players), ("Nintendo", 1996, 1))
        self.assertEqual(row.serial, "NSME")

    def test_a_merge_keeps_rows_for_cartridges_this_library_lacks(self):
        """The shipped database is the union of what several people own. A
        maintainer re-seeding from their own shelf must not delete everyone
        else's rows just by not owning those games."""
        self.curated(coverdb.Entry(crc="A" * 16, name="A Game Nobody Here Owns",
                                   genre="Puzzle"))
        self.run_main(str(self.roms), "--libretro", str(self.libretro_root),
                      "--merge", "--output", str(self.output))
        self.assertEqual(sorted(coverdb.load(self.output)), sorted(["A" * 16, self.mario_key]))

    def test_without_merge_the_whole_file_is_replaced(self):
        """Which is why every documented invocation passes --merge. Pinned here
        so the footgun is a decision somebody made rather than a surprise."""
        self.curated(coverdb.Entry(crc=self.mario_key, name="Super Mario 64 (USA)",
                                   publisher="The Curator", genre="Platformer"),
                     coverdb.Entry(crc="A" * 16, name="A Game Nobody Here Owns"))
        self.run_main(str(self.roms), "--libretro", str(self.libretro_root),
                      "--output", str(self.output))
        database = coverdb.load(self.output)
        self.assertEqual(list(database), [self.mario_key])
        self.assertEqual(database[self.mario_key].publisher, "Nintendo")
        self.assertEqual(database[self.mario_key].genre, "Platform")

    def test_fill_serials_adds_what_is_missing_and_rewrites_nothing_else(self):
        """It exists for when the library is not to hand, so it reads no ROMs
        at all -- and a serial already in the file was either read off a
        cartridge or typed by a person, and outranks a lookup by name."""
        self.curated(coverdb.Entry(crc="1" * 16, name="Super Mario 64 (USA)"),
                     coverdb.Entry(crc="2" * 16, name="Super Mario 64 (USA)", serial="NSMJ"),
                     coverdb.Entry(crc="3" * 16, name="Something Nobody Filed (USA)"))
        code, report = self.run_main(str(self.roms), "--libretro", str(self.libretro_root),
                                     "--fill-serials", "--output", str(self.output))
        database = coverdb.load(self.output)
        self.assertEqual(code, 0)
        self.assertEqual(database["1" * 16].serial, "ZZZA")   # from libretro, by name
        self.assertEqual(database["2" * 16].serial, "NSMJ")   # untouched
        self.assertEqual(database["3" * 16].serial, "")       # nothing to say
        self.assertIn("1 serials added", report)

    def test_running_out_of_time_is_reported_in_the_exit_status(self):
        """A make target that treated an interrupted seed as success would
        commit a half-built database. The status is the only thing make sees."""
        code, report = self.run_main(str(self.roms), "--libretro", str(self.libretro_root),
                                     "--time-budget=-1", "--output", str(self.output))
        self.assertEqual(code, 2)
        self.assertIn("INCOMPLETE", report)


if __name__ == "__main__":
    unittest.main()
