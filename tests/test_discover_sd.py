# SPDX-License-Identifier: AGPL-3.0-only
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from tools import build_catalog, discover_sd


class DiscoverSdTests(unittest.TestCase):
    def test_scans_recursively_excludes_system_dirs_and_infers_titles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ROMs" / "Racing").mkdir(parents=True)
            (root / "ROMs" / "Racing" / "Wave_Race-64.z64").write_bytes(b"")
            (root / "ED64").mkdir()
            (root / "ED64" / "menu.n64").write_bytes(b"")
            (root / "sleekmenu").mkdir()
            (root / "sleekmenu" / "browser.z64").write_bytes(b"")
            document = discover_sd.scan(root)
            self.assertEqual(len(document["games"]), 1)
            self.assertEqual(document["games"][0]["path"], "ROMs/Racing/Wave_Race-64.z64")
            self.assertEqual(document["games"][0]["title"], "Wave Race 64")

    def test_metadata_merges_by_casefolded_normalized_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Games").mkdir()
            (root / "Games" / "homebrew.v64").write_bytes(b"")
            metadata = root / "meta.json"
            metadata.write_text(json.dumps({"games": [{
                "path": "games\\HOMEBREW.V64", "title": "My Homebrew", "year": 2024,
                "publisher": "Me", "genre": "Puzzle", "regions": ["USA"], "players": 2,
            }]}), encoding="utf-8")
            game = discover_sd.scan(root, metadata)["games"][0]
            self.assertEqual((game["title"], game["publisher"], game["players"]),
                             ("My Homebrew", "Me", 2))

    def test_generates_input_and_invokes_deterministic_builder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "demo.n64").write_bytes(b"")
            generated = root / "out" / "input.json"
            catalog = root / "out" / "catalog.ebc"
            manifest = root / "out" / "manifest.json"
            discover_sd.discover_and_build(root, None, generated, catalog, manifest)
            self.assertTrue(catalog.read_bytes().startswith(build_catalog.MAGIC))
            self.assertEqual(json.loads(manifest.read_text())["game_count"], 1)
            first = catalog.read_bytes()
            discover_sd.discover_and_build(root, None, generated, catalog, manifest)
            self.assertEqual(catalog.read_bytes(), first)

    def test_optional_cover_map_adds_normalized_sprite_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Games").mkdir()
            (root / "Games" / "Test.z64").write_bytes(b"")
            covers = root / "covers.json"
            covers.write_text(json.dumps({"schema_version": 1, "covers": {
                "games\\TEST.Z64": "Games\\Test.sprite",
            }}), encoding="utf-8")
            game = discover_sd.scan(root, cover_map_path=covers)["games"][0]
            self.assertEqual(game["cover"], "Games/Test.sprite")

    def test_accepts_tested_cap_and_rejects_one_more(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            at_cap = [f"game-{index:04d}.z64" for index in range(discover_sd.MAX_GAMES)]
            with mock.patch.object(discover_sd.os, "walk", return_value=[(str(root), [], at_cap)]):
                self.assertEqual(len(discover_sd.scan(root)["games"]), discover_sd.MAX_GAMES)
            over_cap = at_cap + ["one-too-many.z64"]
            with mock.patch.object(discover_sd.os, "walk", return_value=[(str(root), [], over_cap)]):
                with self.assertRaisesRegex(build_catalog.CatalogError, "8192-game"):
                    discover_sd.scan(root)


if __name__ == "__main__":
    unittest.main()
