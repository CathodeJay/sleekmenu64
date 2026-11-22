# SPDX-License-Identifier: AGPL-3.0-only
"""Backing up the saves on a card and putting them back (tools/saves.py)."""

import datetime
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools import saves

#: An X7 keeps a file per game in ED64/gamedata/.
X7_TREE = {
    "Super Mario 64 (USA).eep": bytes(range(256)) * 2,
    "Legend of Zelda, The - Ocarina of Time (USA).srm": b"\x5a" * 32768,
    "Paper Mario (USA).fla": os.urandom(131072),
}
#: A Pro keeps a folder per game.
PRO_TREE = {
    "Super Mario 64 (USA)/Super Mario 64 (USA).eep": bytes(range(256)) * 2,
    "Banjo-Kazooie (USA)/Banjo-Kazooie (USA).eep": b"\x01\x02" * 1024,
    "Pokémon Stadium (USA)/Pokémon Stadium (USA).fla": os.urandom(131072),
}
#: When the saves were last written, well before the backup.
PLAYED = time.mktime((2026, 11, 10, 20, 30, 0, 0, 0, -1))


def write_tree(card: Path, tree: dict, when: float = PLAYED) -> None:
    for name, data in tree.items():
        path = saves.folder(card) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (when, when))


def read_tree(card: Path) -> dict:
    root = saves.folder(card)
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


class SavesTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.card = Path(self.scratch.name) / "CARD"
        self.card.mkdir()
        self.zip = Path(self.scratch.name) / saves.file_name(datetime.date(2026, 11, 17))

    def round_trip(self, tree: dict) -> None:
        write_tree(self.card, tree)
        found = saves.find(self.card)
        self.assertEqual(sorted(save.path for save in found), sorted(tree))
        self.assertEqual({save.path: save.size for save in found}, {name: len(data) for name, data in tree.items()})
        self.assertEqual(saves.backup(self.card, self.zip, datetime.datetime(2026, 11, 17, 21, 5, 0)), len(tree))
        self.assertFalse(self.zip.with_name(self.zip.name + ".part").exists())
        with zipfile.ZipFile(self.zip) as archive:
            record = json.loads(archive.read(saves.MANIFEST))
        self.assertEqual(record, {"format": 1, "date": "2026-11-17T21:05:00", "files": len(tree)})
        held = saves.inspect(self.zip)
        self.assertEqual(held.count, len(tree))
        self.assertEqual(held.made, datetime.date(2026, 11, 17))

        # every save gone from the card, then back, with its date
        for path in sorted(saves.folder(self.card).rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        result = saves.restore(self.card, self.zip)
        self.assertEqual(result, saves.Restored(put=len(tree), kept=0, same=0))
        self.assertEqual(read_tree(self.card), tree)
        for name in tree:
            self.assertAlmostEqual((saves.folder(self.card) / name).stat().st_mtime, PLAYED, delta=2)
        self.assertEqual([path for path in saves.folder(self.card).rglob("*.part")], [])

    def test_an_x7_card_goes_to_a_zip_and_back(self):
        self.round_trip(X7_TREE)

    def test_a_pro_card_goes_to_a_zip_and_back(self):
        self.round_trip(PRO_TREE)

    def test_a_restore_onto_a_card_with_no_gamedata_makes_it(self):
        write_tree(self.card, X7_TREE)
        saves.backup(self.card, self.zip)
        other = Path(self.scratch.name) / "OTHER"
        other.mkdir()
        self.assertEqual(saves.restore(other, self.zip).put, len(X7_TREE))
        self.assertEqual(read_tree(other), X7_TREE)

    def test_what_the_systems_leave_beside_the_saves_is_not_backed_up(self):
        write_tree(self.card, {**X7_TREE, "._Paper Mario (USA).fla": b"apple", ".DS_Store": b"finder"})
        self.assertEqual(sorted(save.path for save in saves.find(self.card)), sorted(X7_TREE))

    def test_a_save_that_is_the_same_on_the_card_is_left_alone(self):
        write_tree(self.card, PRO_TREE)
        saves.backup(self.card, self.zip)
        # the same bytes, whatever the date: not rewritten
        later = PLAYED + 86400
        for name in PRO_TREE:
            os.utime(saves.folder(self.card) / name, (later, later))
        self.assertEqual(saves.restore(self.card, self.zip), saves.Restored(put=0, kept=0, same=len(PRO_TREE)))
        for name in PRO_TREE:
            self.assertEqual((saves.folder(self.card) / name).stat().st_mtime, later)

    def test_a_save_that_differs_on_the_card_is_kept_unless_asked_whatever_its_date(self):
        """The cartridge's clock dates a save. A clock that is wrong makes a
        save played since the backup look older, so the dates decide
        nothing: a save that differs is kept unless the owner says
        otherwise, and one missing from the card is put back."""
        write_tree(self.card, X7_TREE)
        saves.backup(self.card, self.zip)
        mario, zelda = "Super Mario 64 (USA).eep", "Legend of Zelda, The - Ocarina of Time (USA).srm"
        missing = "Paper Mario (USA).fla"
        self.assertIn(missing, X7_TREE)
        write_tree(self.card, {mario: b"played since"}, when=PLAYED + 3600)
        write_tree(self.card, {zelda: b"played since, clock behind"}, when=PLAYED - 3600)
        (saves.folder(self.card) / missing).unlink()
        todo = saves.plan(self.card, self.zip)
        self.assertEqual(sorted(todo.changed), sorted([mario, zelda]))
        self.assertEqual(todo.put, [missing])
        self.assertEqual(saves.restore(self.card, self.zip), saves.Restored(put=1, kept=2, same=0))
        self.assertEqual((saves.folder(self.card) / mario).read_bytes(), b"played since")
        self.assertEqual((saves.folder(self.card) / zelda).read_bytes(), b"played since, clock behind")
        self.assertEqual((saves.folder(self.card) / missing).read_bytes(), X7_TREE[missing])
        # and replaced on request
        self.assertEqual(saves.restore(self.card, self.zip, replace_changed=True),
                         saves.Restored(put=2, kept=0, same=1))
        self.assertEqual(read_tree(self.card), X7_TREE)

    def test_nothing_on_the_card_is_deleted(self):
        write_tree(self.card, X7_TREE)
        saves.backup(self.card, self.zip)
        mine = {"Star Fox 64 (USA).eep": b"only on the card", "F-Zero X (USA)/F-Zero X (USA).srm": b"mine too"}
        write_tree(self.card, mine)
        write_tree(self.card, {"Super Mario 64 (USA).eep": b"newer"}, when=PLAYED + 3600)
        saves.restore(self.card, self.zip, replace_changed=True)
        self.assertEqual(read_tree(self.card), {**X7_TREE, **mine})

    def test_a_zip_that_reaches_outside_the_folder_is_refused_and_nothing_is_written(self):
        for bad in ("gamedata/../../escaped.eep", "../escaped.eep", "/escaped.eep", "gamedata/..\\escaped.eep",
                    "C:/escaped.eep"):
            with self.subTest(name=bad):
                with zipfile.ZipFile(self.zip, "w") as archive:
                    archive.writestr(saves.MANIFEST, json.dumps({"format": 1, "date": "2026-11-17", "files": 2}))
                    archive.writestr("gamedata/Fine.eep", b"fine")
                    archive.writestr(bad, b"escaped")
                for call in (lambda: saves.inspect(self.zip), lambda: saves.plan(self.card, self.zip),
                             lambda: saves.restore(self.card, self.zip, True)):
                    with self.assertRaises(saves.SavesError) as raised:
                        call()
                    self.assertEqual(str(raised.exception), "This file isn't a SleekMenu saves backup.")
                self.assertEqual([path for path in Path(self.scratch.name).rglob("*.eep")], [])

    def test_a_file_that_is_not_a_backup_says_so(self):
        cases = {
            "not a zip": lambda path: path.write_bytes(b"PK? no"),
            "a zip of something else": lambda path: zipfile.ZipFile(path, "w").close(),
            "a broken record": lambda path: self.zipped(path, b"{"),
            "a newer format": lambda path: self.zipped(path, json.dumps({"format": 2, "date": "2027-01-01"})),
            "no date": lambda path: self.zipped(path, json.dumps({"format": 1})),
        }
        for what, make in cases.items():
            with self.subTest(what=what):
                path = Path(self.scratch.name) / f"{what}.zip"
                make(path)
                with self.assertRaises(saves.SavesError) as raised:
                    saves.inspect(path)
                self.assertEqual(str(raised.exception), saves.NOT_A_BACKUP)

    @staticmethod
    def zipped(path: Path, record) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(saves.MANIFEST, record)
            archive.writestr("gamedata/Fine.eep", b"fine")

    def test_an_empty_gamedata_has_nothing_to_back_up_and_writes_no_file(self):
        self.assertFalse(saves.has_folder(self.card))
        self.assertEqual(saves.find(self.card), [])
        saves.folder(self.card).mkdir(parents=True)
        self.assertTrue(saves.has_folder(self.card))
        self.assertEqual(saves.find(self.card), [])
        with self.assertRaises(saves.SavesError) as raised:
            saves.backup(self.card, self.zip)
        self.assertEqual(str(raised.exception), "There are no saves on this card yet.")
        self.assertFalse(self.zip.exists())
        self.assertFalse(self.zip.with_name(self.zip.name + ".part").exists())

    def test_a_backup_that_fails_leaves_no_zip_and_an_older_one_stays_whole(self):
        write_tree(self.card, X7_TREE)
        self.zip.write_bytes(b"the last backup")
        with mock.patch.object(zipfile.ZipFile, "write", side_effect=OSError("card pulled out")):
            with self.assertRaises(OSError):
                saves.backup(self.card, self.zip)
        self.assertEqual(self.zip.read_bytes(), b"the last backup")
        self.assertFalse(self.zip.with_name(self.zip.name + ".part").exists())

    def test_a_restore_that_fails_leaves_no_part_file(self):
        write_tree(self.card, X7_TREE)
        saves.backup(self.card, self.zip)
        other = Path(self.scratch.name) / "OTHER"
        with mock.patch.object(saves.os, "replace", side_effect=OSError("card pulled out")):
            with self.assertRaises(OSError):
                saves.restore(other, self.zip)
        self.assertEqual([path for path in other.rglob("*") if path.is_file()], [])

    def test_the_words(self):
        day = datetime.date(2026, 11, 17)
        self.assertEqual(saves.file_name(day), "SleekMenu saves 2026-11-17.zip")
        self.assertEqual(saves.backed_up_line(143, Path("/Users/me") / saves.file_name(day)),
                         "Backed up 143 saves to SleekMenu saves 2026-11-17.zip.")
        self.assertEqual(saves.restore_question(saves.Backup(day, ("x",) * 143)),
                         "This backup holds 143 saves from November 17, 2026. Put them back on the card?")
        self.assertEqual(saves.changed_question(12), "12 saves on the card differ from the backup.")
        self.assertEqual(saves.changed_question(1), "1 save on the card differs from the backup.")
        self.assertEqual(saves.keep_label(12), "Keep the ones on the card")
        self.assertEqual(saves.keep_label(1), "Keep the one on the card")
        self.assertEqual(saves.restored_line(saves.Restored(131, 12, 0)),
                         "Put 131 saves back. 12 saves on the card were kept.")
        self.assertEqual(saves.restored_line(saves.Restored(1, 1, 0)),
                         "Put 1 save back. 1 save on the card was kept.")
        self.assertEqual(saves.restored_line(saves.Restored(5, 0, 3)), "Put 5 saves back.")
        self.assertEqual(saves.spoken_date(datetime.date(2027, 1, 2)), "January 2, 2027")


if __name__ == "__main__":
    unittest.main()
