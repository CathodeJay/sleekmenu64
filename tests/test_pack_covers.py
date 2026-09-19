# SPDX-License-Identifier: AGPL-3.0-only
import io
import tempfile
import unittest
from pathlib import Path

from tools import pack_covers
from tools.metadata_repo import MetadataRepo
from tests.rom_fixtures import write_rom


def png(color, size=(158, 112)):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGBA", size, color).save(out, format="PNG")
    return out.getvalue()


class CoverPackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.roms = self.root / "ROMS"
        self.roms.mkdir()
        meta = self.root / "metadata"
        for key, color in (("N/S/M/E", (255, 0, 0, 255)), ("N/S/M/J", (0, 0, 255, 255)),
                           ("N/F/X", (0, 255, 0, 255))):
            target = meta / key / "boxart_front.png"
            target.parent.mkdir(parents=True)
            target.write_bytes(png(color))
        self.repo = MetadataRepo.open(meta)

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def test_sprites_are_named_after_the_game_code_not_the_rom(self):
        write_rom(self.roms / "Platformers/Super Mario 64 (USA).z64", 1, 2, game_code="SM")
        write_rom(self.roms / "Best of/Super Mario 64 (USA).z64", 1, 2, game_code="SM")
        write_rom(self.roms / "Hacks/SM64 Star Road.z64", 3, 4, game_code="SM")
        planned = pack_covers.plan(self.roms, ["Platformers/Super Mario 64 (USA).z64",
                                               "Best of/Super Mario 64 (USA).z64",
                                               "Hacks/SM64 Star Road.z64"], self.repo)
        # Three ROMs, one box: the hack was built on the same cartridge and
        # carries its code.
        self.assertEqual(set(planned.covers.values()), {"NSME.sprite"})
        self.assertEqual(list(planned.sources), ["NSME.sprite"])

    def test_a_japanese_cartridge_gets_its_own_box(self):
        write_rom(self.roms / "Super Mario 64 (Japan).z64", 5, 6, game_code="SM", country="J")
        planned = pack_covers.plan(self.roms, ["Super Mario 64 (Japan).z64"], self.repo)
        self.assertEqual(planned.covers, {"Super Mario 64 (Japan).z64": "NSMJ.sprite"})

    def test_the_neutral_box_is_named_by_three_characters(self):
        write_rom(self.roms / "Star Fox 64 (USA).z64", 7, 8, game_code="FX")
        planned = pack_covers.plan(self.roms, ["Star Fox 64 (USA).z64"], self.repo)
        self.assertEqual(planned.covers, {"Star Fox 64 (USA).z64": "NFX.sprite"})

    def test_a_rom_the_collection_has_no_box_for_is_listed_not_guessed(self):
        write_rom(self.roms / "Homebrew.z64", 9, 10, game_code="\0\0", country="\0")
        write_rom(self.roms / "Unknown (USA).z64", 11, 12, game_code="QQ")
        (self.roms / "notes.z64").write_bytes(b"not a cartridge")
        planned = pack_covers.plan(self.roms, ["Homebrew.z64", "Unknown (USA).z64", "notes.z64"],
                                   self.repo)
        self.assertEqual(planned.covers, {})
        self.assertEqual(planned.without, ["Homebrew.z64", "Unknown (USA).z64", "notes.z64"])

    def test_conversion_needs_no_external_toolchain(self):
        """Converting art must not require a MIPS cross-compiler. If this
        ever shells out again, the art pipeline stops working for anyone who
        just wants covers."""
        write_rom(self.roms / "Super Mario 64 (USA).z64", 1, 2, game_code="SM")
        planned = pack_covers.plan(self.roms, ["Super Mario 64 (USA).z64"], self.repo)
        written = pack_covers.pack(planned, self.repo, self.root / "covers")
        self.assertEqual(written, 1)
        sprite = (self.root / "covers" / "NSME.sprite").read_bytes()
        self.assertEqual(sprite[:4], (96).to_bytes(2, "big") + (72).to_bytes(2, "big"))

    def test_the_box_views_pack_is_the_same_plan_at_the_large_size(self):
        """One plan, two sizes, one decode: the large sprite carries the
        same name as the small one, so the two packs cannot disagree about
        which picture a game gets. A collection scan is smaller than the
        large canvas and is centred at its own size, never stretched; a
        picture bigger than the canvas -- libretro's, the owner's -- is
        fitted to it."""
        from tools import make_sprite
        from tests.test_custom_art import picture
        write_rom(self.roms / "Super Mario 64 (USA).z64", 1, 2, game_code="SM")
        write_rom(self.roms / "F-Zero X (USA).z64", 3, 4, game_code="FX")
        art = self.root / "sleekmenu" / "art"
        picture(art / "NFXE.png", size=(512, 357), color=(20, 160, 60, 255))
        planned = pack_covers.plan(self.roms, ["Super Mario 64 (USA).z64", "F-Zero X (USA).z64"],
                                   self.repo, art)
        written = pack_covers.pack(planned, self.repo, self.root / "covers",
                                   large_destination=self.root / "covers-large")
        self.assertEqual(written, 2)
        self.assertEqual(sorted(p.name for p in (self.root / "covers-large").iterdir()),
                         sorted(p.name for p in (self.root / "covers").iterdir()))
        # the collection's 158x112 scan, centred on the 256x180 matte at its own size
        width, height, rgb = make_sprite.decode((self.root / "covers-large" / "NSME.sprite").read_bytes())
        self.assertEqual((width, height), make_sprite.LARGE_CANVAS_SIZE)
        def pixel(x, y):
            at = (y * width + x) * 3
            return tuple(rgb[at:at + 3])
        self.assertEqual(pixel(128, 90), (248, 0, 0), "the scan's red at the centre")
        self.assertEqual(pixel(2, 2), tuple(c & ~7 for c in make_sprite.MATTE_RGBA[:3]), "matte at the corner")
        self.assertEqual(pixel(128 - 79 + 1, 90), (248, 0, 0), "the scan's left edge, 79 from centre")
        self.assertEqual(pixel(128 - 79 - 2, 90), tuple(c & ~7 for c in make_sprite.MATTE_RGBA[:3]))
        # the owner's 512-pixel picture fills the large canvas
        width, height, rgb = make_sprite.decode((self.root / "covers-large" / "NFXE.sprite").read_bytes())
        self.assertEqual(pixel(2, 2), (16, 160, 56), "green to the edge: fitted, not centred small")
        # and the small pack is what it always was
        small = (self.root / "covers" / "NFXE.sprite").read_bytes()
        self.assertEqual(small[:4], (96).to_bytes(2, "big") + (72).to_bytes(2, "big"))

    def test_a_dry_run_writes_nothing_and_still_counts(self):
        write_rom(self.roms / "Super Mario 64 (USA).z64", 1, 2, game_code="SM")
        planned = pack_covers.plan(self.roms, ["Super Mario 64 (USA).z64"], self.repo)
        written = pack_covers.pack(planned, self.repo, self.root / "covers", dry_run=True)
        self.assertEqual(written, 1)
        self.assertEqual(list((self.root / "covers").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
