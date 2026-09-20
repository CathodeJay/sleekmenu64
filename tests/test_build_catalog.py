# SPDX-License-Identifier: AGPL-3.0-only
import json
import struct
import subprocess
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from tools import build_catalog


def game(path="USA/Action/Test.z64", **changes):
    value = {
        "title": "Test Game", "path": path, "genre": "Action",
        "regions": ["USA"], "players": 1, "publisher": "Indie",
        "year": 2026,
    }
    value.update(changes)
    return value


class CatalogBuilderTests(unittest.TestCase):
    def test_binary_header_offsets_crc_and_flags(self):
        games = build_catalog.normalize({"schema_version": 1, "games": [game(favorite=True)]})
        data = build_catalog.encode(games)
        header = build_catalog.HEADER.unpack_from(data)
        magic, version, header_size, count, records_at, strings_at, strings_size, crc, flags = header
        self.assertEqual((magic, version, header_size, count, records_at, flags),
                         (b"EBC1", 2, 32, 1, 32, 0))
        self.assertEqual(strings_at, 32 + build_catalog.RECORD.size)
        self.assertEqual(strings_at + strings_size, len(data))
        self.assertEqual(crc, zlib.crc32(data[header_size:]))
        record = build_catalog.RECORD.unpack_from(data, records_at)
        self.assertEqual(record[6:], (2026, 1, 1, 1))

    def test_output_is_deterministic_and_sorted_by_path(self):
        document = {"schema_version": 1, "games": [game("Z/Game.z64"), game("a/Game.z64")]}
        first = build_catalog.encode(build_catalog.normalize(document))
        second = build_catalog.encode(build_catalog.normalize(document))
        self.assertEqual(first, second)
        fields = build_catalog.HEADER.unpack_from(first)
        first_path_offset = build_catalog.RECORD.unpack_from(first, fields[4])[1]
        start = fields[5] + first_path_offset
        self.assertEqual(first[start:first.index(b"\0", start)], b"a/Game.z64")

    def test_build_writes_manifest_matching_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, manifest = root / "input.json", root / "out.ebc", root / "out.json"
            source.write_text(json.dumps({"schema_version": 1, "games": [game()]}), encoding="utf-8")
            build_catalog.build(source, output, manifest)
            details = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(details["game_count"], 1)
            self.assertEqual(details["size_bytes"], output.stat().st_size)
            self.assertEqual(details["record_size"], 32)

    def test_a_description_travels_in_the_string_table_as_console_text(self):
        games = build_catalog.normalize({"schema_version": 1, "games": [
            game(description="You are Bond\u2026 James Bond\u2122 \u2014 \u201cshaken\u201d, caf\u00e9!")]})
        self.assertEqual(games[0]["description"], 'You are Bond... James Bond - "shaken", cafe!')
        data = build_catalog.encode(games)
        self.assertIn(b'"shaken", cafe!\0', data)

    def test_a_missing_description_is_an_empty_string_not_an_error(self):
        games = build_catalog.normalize({"schema_version": 1, "games": [game()]})
        self.assertEqual(games[0]["description"], "")
        record = build_catalog.RECORD.unpack_from(build_catalog.encode(games), 32)
        self.assertEqual(record[5], 0)   # the shared empty string at offset 0

    def test_a_description_past_the_limit_is_refused(self):
        with self.assertRaisesRegex(build_catalog.CatalogError, "longer than"):
            build_catalog.normalize({"schema_version": 1, "games": [game(description="x" * 2001)]})

    def test_titles_and_publishers_are_console_text_too(self):
        games = build_catalog.normalize({"schema_version": 1, "games": [
            game(title="Pok\u00e9mon Stadium", publisher="Nintendo\u2122")]})
        self.assertEqual((games[0]["title"], games[0]["publisher"]), ("Pokemon Stadium", "Nintendo"))

    def test_rejects_duplicate_case_insensitive_paths(self):
        with self.assertRaisesRegex(build_catalog.CatalogError, "duplicate ROM path"):
            build_catalog.normalize({"schema_version": 1, "games": [game(), game("usa/action/TEST.Z64")]})

    def test_rejects_traversal_and_invalid_values(self):
        bad = [
            game("../secret.z64"), game(players=9), game(players=-1), game(regions=["MARS"]),
            game(year="2026"), game(year=1969), game(path="USA/readme.txt"),
            game(regions="USA"), game(title=""),
        ]
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(build_catalog.CatalogError):
                    build_catalog.normalize({"schema_version": 1, "games": [value]})

    def test_accepts_more_players_than_the_console_has_ports(self):
        """Micro Machines 64 Turbo seats eight by sharing pads. The number is
        real; the browser filters on "at least", so keeping it makes the game
        findable under every count up to eight."""
        games = build_catalog.normalize({"schema_version": 1, "games": [game(players=8)]})
        self.assertEqual(games[0]["players"], 8)

    def test_accepts_a_rom_no_database_has_ever_catalogued(self):
        """Hacks, homebrew and translations have no genre, publisher, year or
        players anywhere, and a header that names no market. Refusing them
        would only force the builder to invent values."""
        unknown = game(genre="", publisher="", year=0, players=0, regions=[])
        games = build_catalog.normalize({"schema_version": 1, "games": [unknown]})
        self.assertEqual(len(games), 1)
        entry = games[0]
        self.assertEqual((entry["genre"], entry["publisher"]), ("", ""))
        self.assertEqual((entry["year"], entry["players"], entry["region_mask"]), (0, 0, 0))
        # and the title still has to be there -- it is the only thing the
        # browser can show for such a ROM
        with self.assertRaises(build_catalog.CatalogError):
            build_catalog.normalize({"schema_version": 1, "games": [game(title="")]})


class ConsoleReaderTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]
    # strdup is POSIX, not C11; the console's newlib declares it by default
    # and a strict host libc wants asking.
    HOST_CC = ["cc", "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Wextra", "-Werror",
               "-Isrc", "-Itests/stubs"]

    def test_the_console_reader_agrees_with_the_builder(self):
        """The contract that matters: Python writes it, C reads it."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "metadata.json"
            source.write_text(json.dumps({"schema_version": 1, "games": [
                {"title": "GoldenEye 007 (USA)", "path": "ROMS/GoldenEye 007 (USA).z64",
                 "cover": "NGEE.sprite", "publisher": "Nintendo\u2122", "genre": "Shooters",
                 "year": 1997, "players": 4, "regions": ["USA"], "favorite": True,
                 "description": "You are Bond. James Bond."},
                {"title": "Homebrew", "path": "ROMS/Homebrew.z64", "regions": []},
            ], "set_aside": [{"path": "ROMS/Tools/IPL.z64", "why": "not a ROM: no N64 header"}]}),
                encoding="utf-8")
            good = root / "catalog.ebc"
            build_catalog.build(source, good, root / "manifest.json")
            # The same bytes stamped as format 1: the reader must refuse them.
            data = bytearray(good.read_bytes())
            struct.pack_into("<H", data, 4, 1)
            older = root / "older.ebc"
            older.write_bytes(data)
            junk = root / "junk.ebc"
            junk.write_bytes(b"not a catalog" * 8)
            binary = root / "catalog-test"
            subprocess.run(self.HOST_CC + ["src/catalog.c", "src/folder_scan.c",
                                           "tests/stubs/libdragon_stub.c",
                                           "tests/catalog_test.c", "-o", str(binary)],
                           cwd=self.ROOT, check=True)
            subprocess.run([str(binary), str(good), str(older), str(junk)], check=True)


if __name__ == "__main__":
    unittest.main()
