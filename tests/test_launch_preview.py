# SPDX-License-Identifier: AGPL-3.0-only
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

from PIL import Image

from tools import cover_pack, make_sprite

ROOT = pathlib.Path(__file__).resolve().parents[1]

HOST_CC = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Isrc"]


def strip_comments(source):
    """Blank out C comments, keeping offsets and line numbers intact, so that
    prose explaining a register cannot be mistaken for touching one."""
    out, i, n = [], 0, len(source)
    while i < n:
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append("".join(c if c == "\n" else " " for c in source[i:end]))
            i = end
        elif source.startswith("//", i):
            end = source.find("\n", i)
            end = n if end < 0 else end
            out.append(" " * (end - i))
            i = end
        else:
            out.append(source[i])
            i += 1
    return "".join(out)


# The cheat module leans on the vendored boot code's CIC detector, which is
# pure C and builds on the host as it is.
NFM_BOOT = "third_party/n64flashcartmenu/boot"
CHEATS_SOURCES = ["src/cheats.c", "src/cheat_pack.c", f"{NFM_BOOT}/cic.c"]
CHEATS_FLAGS = [f"-I{NFM_BOOT}"]


def build_and_run(name, sources, extra_flags=(), args=()):
    with tempfile.TemporaryDirectory() as directory:
        binary = pathlib.Path(directory) / name
        subprocess.run(
            HOST_CC + list(extra_flags) + list(sources) + ["-o", str(binary)],
            cwd=ROOT, check=True,
        )
        subprocess.run([str(binary)] + list(args), check=True)


class HostModuleTests(unittest.TestCase):
    def test_host_policy_module(self):
        build_and_run("launch-policy-test",
                      ["src/launch_policy.c", "tests/launch_policy_test.c"])

    def test_host_probe_module(self):
        build_and_run("x7-probe-test",
                      ["src/x7_probe.c", "tests/x7_probe_test.c"])

    def test_host_save_type_module(self):
        build_and_run("save-type-test",
                      ["src/save_type.c", "src/rom_db.c", "tests/save_type_test.c"])

    def test_host_rom_load_module(self):
        build_and_run("rom-load-test",
                      ["src/rom_load.c", "src/x7_save_reg.c", "tests/rom_load_test.c"])

    def test_host_genre_module(self):
        build_and_run("genre-test", ["src/genre.c", "tests/genre_test.c"])

    def test_host_favorites_module(self):
        build_and_run("favorites-test",
                      ["src/favorites.c", "tests/favorites_test.c"])

    def test_host_ui_behaviour(self):
        """The browser itself, driven frame by frame against a stand-in for
        libdragon. Four bugs reached hardware that no source scan could see;
        this is where that stops.

        Run twice, against the same assertions: once reading covers out of a
        loose directory and once out of a pack. The two IO paths are supposed
        to be indistinguishable from the browser's side, and the only way to
        know they are is to hold the behaviour fixed and swap the source."""
        sources = ["tests/ui_host_test.c", "tests/stubs/libdragon_stub.c",
                   "src/ui.c", "src/genre.c", "src/favorites.c", "src/history.c",
                   "src/list_view.c", "src/save_type.c", "src/cover_pack.c",
                   "src/rom_db.c"] + CHEATS_SOURCES
        for packed in (False, True):
            with self.subTest(covers="pack" if packed else "loose"), \
                 tempfile.TemporaryDirectory() as scratch:
                pack = pathlib.Path(scratch) / "covers.pak"
                if packed:
                    pack.write_bytes(cover_pack.build(
                        {"cover.sprite": make_sprite.encode(
                            Image.new("RGBA", (96, 72), (40, 80, 120, 255)))}))
                build_and_run(
                    "ui-test", sources,
                    ["-Itests/stubs"] + CHEATS_FLAGS +
                    [f'-DSM_FAVORITES_PATH="{scratch}/favorites.txt"',
                     f'-DSM_COVERS_DIR="{scratch}/covers"',
                     f'-DSM_COVER_PACK_PATH="{pack}"'],
                )

    def test_host_list_view_module(self):
        build_and_run("list-view-test",
                      ["src/list_view.c", "tests/list_view_test.c"])

    def test_host_save_io_module(self):
        build_and_run("save-io-test",
                      ["src/save_io.c", "tests/save_io_test.c"])

    def test_host_history_module(self):
        build_and_run("history-test", ["src/history.c", "tests/history_test.c"])

    def test_host_registry_module(self):
        build_and_run("ed64-registry-test",
                      ["src/ed64_registry.c", "src/launch_policy.c",
                       "tests/ed64_registry_test.c"])

    def test_host_cheats_module(self):
        """The .cht parser, the engine list, the state file and the hook
        check, against the shape of the Pro firmware's own database. The
        hook check runs against a real cartridge image too when the runner
        names one in SLEEKMENU_TEST_ROM; the suite cannot carry an IPL3."""
        rom = os.environ.get("SLEEKMENU_TEST_ROM")
        build_and_run("cheats-test", CHEATS_SOURCES + ["tests/cheats_test.c"],
                      ["-D_POSIX_C_SOURCE=200809L"] + CHEATS_FLAGS,
                      [rom] if rom else [])

    def test_host_cheat_pack_module(self):
        """Finding a game's file in the Pro's cheat pack: GoodN64 names on
        one side, a No-Intro library and a game code on the other."""
        build_and_run("cheat-pack-test", ["src/cheat_pack.c", "tests/cheat_pack_test.c"],
                      ["-D_POSIX_C_SOURCE=200809L"])

    def test_hook_check_mirrors_the_boot_code(self):
        """The pre-flight check in cheats.c re-implements the test the
        vendored engine makes before patching: the same word of the IPL3 per
        CIC, the same `jr $t1`, the same descrambling for the 6106. The
        numbers are read out of the vendored source so a bump of the boot
        code that moves them fails here rather than on a console."""
        vendored = strip_comments((ROOT / NFM_BOOT / "cheats.c").read_text(encoding="utf-8"))
        ours = strip_comments((ROOT / "src/cheats.c").read_text(encoding="utf-8"))
        theirs = dict(re.findall(r"case (CIC_\w+): patch_offset = (\d+); break;", vendored))
        # 6101 and 7102 share one case label
        theirs["CIC_6101"] = re.search(r"case CIC_6101:\s*case CIC_7102: patch_offset = (\d+)", vendored).group(1)
        theirs["CIC_7102"] = theirs["CIC_6101"]
        mine = dict(re.findall(r"case (CIC_\w+): offset = (\d+); break;", ours))
        mine["CIC_6101"] = re.search(r"case CIC_6101:\s*case CIC_7102: offset = (\d+)", ours).group(1)
        mine["CIC_7102"] = mine["CIC_6101"]
        self.assertEqual(mine, theirs)
        self.assertEqual(set(theirs), {"CIC_5101", "CIC_6101", "CIC_7102", "CIC_x102",
                                       "CIC_x103", "CIC_x105", "CIC_x106"})
        self.assertIn("#define X106_XOR_CONSTANT (0x0260BCD5)", vendored)
        self.assertIn("#define X106_ENC_START (0x13C)", vendored)
        self.assertIn("#define HOOK_X106_XOR_CONSTANT 0x0260BCD5u", ours)
        self.assertIn("#define HOOK_X106_ENC_START 0x13Cu", ours)
        # cic_get_seed(CIC_x106) is 0x85 in the vendored table
        cic = (ROOT / NFM_BOOT / "cic.c").read_text(encoding="utf-8")
        self.assertIn("case CIC_x106: return 0x85;", cic)
        self.assertIn("#define HOOK_X106_SEED 0x85u", ours)
        # I_JR(REG_T1): SPECIAL, rs = 9, funct = 8
        self.assertEqual((9 << 21) | 8, 0x01200008)
        self.assertIn("#define HOOK_JR_T1 0x01200008u", ours)
        # and the launcher will not hand over a list the engine cannot use
        launch = strip_comments((ROOT / "src/launch.c").read_text(encoding="utf-8"))
        self.assertIn("cheats_hook = sm_cheats_hook_check(header, sizeof(header));", launch)
        self.assertIn("cheats_hook == SM_CHEATS_HOOK_OK) {", launch)

    def test_host_pro_fs_module(self):
        """The Pro's sd:/ driver against a fake MCU that enforces the real
        one's rule -- one open file -- and records every command."""
        build_and_run("pro-fs-test", ["src/pro/pro_fs.c", "tests/pro_fs_test.c"],
                      ["-Itests/stubs", "-D_POSIX_C_SOURCE=200809L"])



class RetiredModuleTests(unittest.TestCase):
    """The hand-rolled X7 register driver and the FAT chain planner are gone.

    libcart (vendored inside libdragon) already owns the SD hardware from
    debug_init_sdfs() onward, and f_read() into a cartridge address already
    reaches cart_card_rd_cart() through libdragon's disk_read_sdram dispatch.
    docs/rejected-approaches.md records why each one was abandoned.
    """

    def test_retired_modules_are_out_of_the_rom_build(self):
        for retired in ("x7_stream.c", "x7_stream.h", "fat_run.c", "fat_run.h",
                        "launch_bootstrap.S", "embedded_covers.c", "embedded_covers.h"):
            self.assertFalse((ROOT / "src" / retired).exists(),
                             f"src/{retired} must not be in the ROM build")

    def test_makefile_builds_every_source_in_src(self):
        makefile = (ROOT / "Makefile.n64").read_text(encoding="utf-8")
        self.assertNotIn("filter-out", makefile)
        self.assertIn("$(shell find src -name '*.c')", makefile)
        # the boot handoff is the only third-party code compiled into the ROM
        self.assertIn("$(NFM_BOOT)/boot.c", makefile)
        self.assertIn("$(NFM_BOOT)/reboot.S", makefile)
        self.assertIn("-include boot_compat.h", makefile)

    def test_no_everdrive_register_access_anywhere_in_the_rom(self):
        """The single invariant that keeps libcart's private state coherent.

        libcart caches the FPGA SD direction latch in a file-static inside
        __edx_sd_mode() that nothing outside cart.c can read or resynchronise,
        and its poll loops have no timeout. A second driver poking the same
        registers desyncs that cache and hangs with no watchdog.
        """
        forbidden = (
            "0x1F800000", "0xBF800000", "EDX_KEY", "EDX_SYS_CFG", "EDX_DMA_ADDR",
            "EDX_DMA_LEN", "EDX_DMA_STA", "EDX_SD_CMD", "EDX_SD_DAT",
            "EDX_SD_STATUS", "EDX_BOOT_CFG", "0xAA55",
        )
        # One sanctioned exception: REG_GAM_CFG is the save-type register, and
        # libcart has no equivalent for it at all. It lives alone in its own
        # module so this invariant still means something.
        sanctioned = {"x7_save_reg.c", "x7_save_reg.h"}
        for path in sorted((ROOT / "src").rglob("*.[ch]")):
            if path.name in sanctioned:
                continue
            source = strip_comments(path.read_text(encoding="utf-8"))
            for token in forbidden + ("REG_GAM_CFG", "0x1F808018"):
                self.assertNotIn(token, source, f"{path.name} touches X7 registers: {token}")

    def test_the_one_sanctioned_register_module_stays_minimal(self):
        source = strip_comments((ROOT / "src/x7_save_reg.c").read_text(encoding="utf-8"))
        writes = re.findall(r"io_write\(([^,]+),", source)
        self.assertEqual(writes, ["SM_X7_REG_GAM_CFG"],
                         "x7_save_reg.c must write exactly one register")
        # Re-locking KEY is what broke the previous canary; never do it again.
        self.assertNotIn("EDX_KEY", source)
        self.assertNotIn("io_write(0x1F808004", source)
        for other in ("SYS_CFG", "DMA_ADDR", "DMA_LEN", "SD_STATUS", "BOOT_CFG"):
            self.assertNotIn(other, source)

    def test_save_register_is_applied_only_at_the_point_of_no_return(self):
        """Reconfiguring backup RAM under a live FatFs mount is unsafe, so the
        one register write must happen only inside the boot handoff, and only
        after interrupts are off."""
        callers = set()
        for path in (ROOT / "src").rglob("*.c"):
            if path.name == "x7_save_reg.c":
                continue
            if "sm_x7_apply_save_type(" in strip_comments(path.read_text(encoding="utf-8")):
                callers.add(path.name)
        # save_io.c is the second sanctioned caller: moving a save to or from
        # the cartridge means telling the cartridge which save device to be,
        # which is the same register. It is allowed only because its two
        # hardware helpers touch no files at all, so an SD transaction can
        # never be in flight across the change -- see the next test.
        self.assertEqual(callers, {"flashcart_x7.c", "save_io.c"})
        # The X7 backend writes it from the hook that sm_rom_boot() runs after
        # interrupts are off, and from nowhere else.
        x7 = strip_comments((ROOT / "src/flashcart_x7.c").read_text(encoding="utf-8"))
        hook = x7.index("static void x7_point_of_no_return(void)")
        hook_end = x7.index("\n}", hook)
        self.assertIn("sm_x7_apply_save_type(", x7[hook:hook_end])
        self.assertEqual(x7.count("sm_x7_apply_save_type("), 1)
        self.assertIn("sm_rom_boot(x7_point_of_no_return, false, cheats)", x7)
        boot = strip_comments((ROOT / "src/rom_boot.c").read_text(encoding="utf-8"))
        self.assertLess(boot.index("disable_interrupts()"),
                        boot.index("at_point_of_no_return()"))

    def test_raw_pi_transfers_are_confined_to_the_save_window(self):
        """libdragon's dma_write() forces its address into 0x1000_0000, the
        cartridge ROM window, so it cannot reach the battery-backed save RAM on
        domain 2 at all. The raw call is the only way there, and it is allowed
        in exactly one place, for exactly that address."""
        for path in (ROOT / "src").rglob("*.c"):
            source = strip_comments(path.read_text(encoding="utf-8"))
            calls = re.findall(r"dma_(?:read|write)_raw_async\(([^;]*?)\)", source)
            if path.name != "save_io.c":
                self.assertEqual(calls, [], f"{path.name} does raw PI transfers")
                continue
            self.assertTrue(calls)
            for call in calls:
                self.assertIn("SM_SAVE_PI_BASE", call)

    def test_save_hardware_helpers_touch_no_files(self):
        """The one thing that makes changing REG_GAM_CFG outside the boot
        handoff safe: nothing between the register write and the transfer can
        be an SD transaction."""
        source = strip_comments((ROOT / "src/save_io.c").read_text(encoding="utf-8"))
        for name in ("sm_save_read_hardware", "sm_save_write_hardware"):
            start = source.index("sm_save_io_result_t " + name)
            end = source.index("\n}", start)
            body = source[start:end]
            for forbidden in ("fopen(", "fread(", "fwrite(", "fclose(",
                              "f_open(", "f_read(", "f_write("):
                self.assertNotIn(forbidden, body, f"{name} touches the card")

    def test_save_transfers_restore_the_pi_timing_they_changed(self):
        """Domain 2 timing belongs to whoever set it. libcart re-reads it on
        every acquire, so leaving ours behind would make it save and restore
        the wrong values for the rest of the session."""
        source = strip_comments((ROOT / "src/save_io.c").read_text(encoding="utf-8"))
        # One definition each, then one restore for every apply.
        self.assertGreaterEqual(source.count("dom2_apply("), 2)
        self.assertEqual(source.count("dom2_apply("), source.count("dom2_restore("),
                         "every dom2_apply needs its own dom2_restore")


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.probe = (ROOT / "src/x7_probe.c").read_text(encoding="utf-8")
        self.header = (ROOT / "src/x7_probe.h").read_text(encoding="utf-8")
        self.launch = (ROOT / "src/launch.c").read_text(encoding="utf-8")

    def test_probe_uses_libcart_not_a_private_driver(self):
        self.assertIn("cart_card_rd_cart(SM_PROBE_CART_PHYS, local.lba, 1u)", self.probe)
        self.assertIn('#include "cart.h"', self.probe)
        self.assertNotIn("cart_card_init(", self.probe)
        self.assertNotIn("cart_card_init(", self.launch)
        self.assertNotIn("cart_exit(", self.probe)

    def test_probe_target_clears_the_running_rom_image(self):
        """Offset 0 is where SleekMenu's own image lives; never write there."""
        self.assertIn("#define SM_PROBE_CART_OFFSET (32u * 1024u * 1024u)", self.header)
        self.assertIn("#define SM_PROBE_CART_PHYS (0x10000000u + SM_PROBE_CART_OFFSET)", self.header)
        for call in re.findall(r"dma_(?:read|write)\([^;]*?,\s*([A-Za-z0-9_]+)\s*,", self.probe):
            self.assertEqual(call, "SM_PROBE_CART_PHYS")

    def test_probe_poisons_the_target_before_each_transfer(self):
        """A transfer that silently does nothing must not read as a pass."""
        # one definition (probe_poison_cart(void)) plus two guarded call sites
        self.assertEqual(self.probe.count("probe_poison_cart()"), 2)
        direct = self.probe.index("cart_card_rd_cart(SM_PROBE_CART_PHYS")
        dispatch = self.probe.index("f_read(file, (void *)(uintptr_t)SM_PROBE_CART_KSEG1")
        poisons = [m.start() for m in re.finditer(r"if \(probe_poison_cart\(\) != 0\)", self.probe)]
        self.assertEqual(len(poisons), 2)
        self.assertLess(poisons[0], direct)
        self.assertLess(direct, poisons[1])
        self.assertLess(poisons[1], dispatch)

    def test_probe_steps_are_ordered_reference_direct_then_dispatch(self):
        reference = self.probe.index("f_read(file, probe_reference")
        lba = self.probe.index("sm_probe_first_lba(", reference)
        direct = self.probe.index("cart_card_rd_cart(SM_PROBE_CART_PHYS", lba)
        compare = self.probe.index("sm_probe_first_difference(probe_reference, probe_readback", direct)
        dispatch = self.probe.index("f_read(file, (void *)(uintptr_t)SM_PROBE_CART_KSEG1", compare)
        self.assertLess(reference, lba)
        self.assertLess(lba, direct)
        self.assertLess(direct, compare)
        self.assertLess(compare, dispatch)

    def test_every_cart_dma_carries_its_own_cache_maintenance(self):
        """dma_read/dma_write go through the uncached alias and do no cache work."""
        self.assertRegex(self.probe,
                         r"data_cache_hit_writeback\(source, SM_PROBE_SECTOR_SIZE\);\s*\n\s*dma_write\(")
        self.assertRegex(self.probe,
                         r"data_cache_hit_writeback_invalidate\(destination, SM_PROBE_SECTOR_SIZE\);\s*\n\s*dma_read\(")
        self.assertIn("data_cache_hit_invalidate(destination, SM_PROBE_SECTOR_SIZE);", self.probe)
        for buffer in ("probe_reference", "probe_readback", "probe_poison"):
            self.assertIn(f"{buffer}[SM_PROBE_SECTOR_SIZE] __attribute__((aligned(16)))", self.probe)

    def test_probe_refuses_to_touch_a_non_x_series_cartridge(self):
        guard = self.probe.index("cart_type != CART_EDX")
        first_write = self.probe.index("probe_poison_cart()", guard)
        self.assertLess(guard, first_write)
        self.assertIn("SM_PROBE_CART_OFFSET + SM_PROBE_SECTOR_SIZE > cart_size", self.probe)


class AssetLoadTests(unittest.TestCase):
    """libdragon's asset loader asserts on a missing file rather than returning
    NULL (asset.c: assertf(fd >= 0, "File not found: %s")), so every
    sprite_load() call site has to probe for existence first."""

    def test_every_sprite_load_is_guarded_by_an_existence_check(self):
        for name in ("ui.c", "display.c"):
            source = strip_comments((ROOT / "src" / name).read_text(encoding="utf-8"))
            calls = list(re.finditer(r"\bsprite_load\(", source))
            self.assertTrue(calls, f"no sprite_load call found in {name}")
            for match in calls:
                starts = [m.start() for m in
                          re.finditer(r"(?m)^[A-Za-z_][^;\n]*\)\s*\{$", source[:match.start()])]
                body = source[starts[-1]:match.start()] if starts else source[:match.start()]
                self.assertRegex(
                    body, r"cover_asset_exists\(|dfs_open\(",
                    f"unguarded sprite_load in {name} at offset {match.start()}")

    def test_the_catalog_is_the_only_thing_that_names_a_cover(self):
        """The ROM used to carry a second copy of the cover matcher in C, with
        a 915-entry name-to-sprite table baked in at build time, so that it
        could guess when the catalog said nothing. It produced correct answers
        for exactly one art collection -- the one that generated the table --
        and meaningless sprite numbers for anybody else's. Matching belongs on
        a desktop, where the answer can be reviewed; if a lookup ever reappears
        here, this fails."""
        ui = strip_comments((ROOT / "src/ui.c").read_text(encoding="utf-8"))
        start = ui.index("static sprite_t *load_item_cover")
        body = ui[start:ui.index("\n}", ui.index("sprite_load(", start))]
        self.assertIn("game.cover", body)
        self.assertNotIn("embedded_cover_path", body)
        # One candidate, and it goes through the existence guard, so a missing
        # sprite is never handed to sprite_load().
        self.assertEqual(body.count('SM_COVERS_DIR "/%s"'), 1)
        self.assertEqual(body.count("cover_asset_exists(path)"), 1)

    def test_grid_folders_are_drawn_as_folders(self):
        """A folder item carries the catalog index of the first game inside it.
        The grid rendered that game's title and, when it had one, would have
        rendered its cover -- so four folders looked like four games, each
        misnamed after whatever happened to sort first inside it."""
        ui = strip_comments((ROOT / "src/ui.c").read_text(encoding="utf-8"))
        start = ui.index("static void draw_grid")
        body = ui[start:ui.index("\n}\n", start)]
        self.assertIn("folder_label(", body)
        self.assertIn("draw_folder_tile(", body)
        # and the folder branch stops before anything cover-shaped is drawn
        self.assertLess(body.index("draw_folder_tile("), body.index("slot_sprites[slot]"))

    def test_the_grid_footer_names_the_folder_not_a_game_inside_it(self):
        ui = strip_comments((ROOT / "src/ui.c").read_text(encoding="utf-8"))
        start = ui.index("static const char *footer_hint")
        body = ui[start:ui.index("\n}\n", start)]
        self.assertIn("folder_label(", body)
        self.assertLess(body.index("folder_label("), body.index("game.title"))

    def test_the_card_is_not_read_on_the_frame_the_selection_moves(self):
        """Cover art used to live in the ROM. Reading one off an exFAT card
        with 3,400 entries costs enough that doing it per keypress made
        scrolling crawl, so the reads wait for the selection to settle."""
        ui = strip_comments((ROOT / "src/ui.c").read_text(encoding="utf-8"))
        start = ui.index("void ui_update(")
        body = ui[start:]
        gate = body.index("if (ui->settle) { ui->settle--; return; }")
        # every card read in the library screen sits after the gate
        for call in ("load_slot_step(", "load_selected_cover(", "load_selected_details("):
            self.assertGreater(body.rindex(call), gate, call)
        # and moving the cursor arms it
        self.assertIn("ui->settle = SM_UI_SETTLE_FRAMES;", body)

    def test_scrolling_the_grid_keeps_the_covers_it_already_has(self):
        """Scrolling one row moves four tiles and leaves eight where they are.
        Freeing all twelve and reading all twelve back is three times the work
        for the same picture."""
        ui = strip_comments((ROOT / "src/ui.c").read_text(encoding="utf-8"))
        start = ui.index("static void sync_slots")
        body = ui[start:ui.index("\n}\n", start)]
        self.assertIn("held_index[other] != item", body)
        self.assertIn("ui->slot_pending[slot] = false;", body)
        # only sprites nothing claimed are released
        self.assertIn("if (!taken[other] && held[other]) sprite_free(held[other]);", body)
        # and the fill is one tile per call, not twelve
        step = ui[ui.index("static void load_slot_step"):]
        step = step[:step.index("\n}\n")]
        self.assertIn("return;", step)

    def test_the_favourite_button_writes_a_favourite(self):
        """It used to set a status line saying favourites come from catalog
        metadata, which is true and useless: the catalog is built on a desktop
        and the button is on a controller."""
        ui = strip_comments((ROOT / "src/ui.c").read_text(encoding="utf-8"))
        start = ui.index("if (actions.favorite)")
        body = ui[start:start + 900]
        self.assertIn("sm_favorites_toggle(", body)
        self.assertIn("sm_favorites_save(", body)
        # a failed write is reported rather than silently forgotten
        self.assertIn("Could not write", body)

    def test_the_favourite_filter_reads_the_card_not_the_catalog(self):
        """Otherwise a favourite set on the console would not survive
        rebuilding the catalog with a new art pack."""
        ui = strip_comments((ROOT / "src/ui.c").read_text(encoding="utf-8"))
        start = ui.index("static bool item_matches")
        body = ui[start:ui.index("\n}\n", start)]
        self.assertIn("sm_favorites_contains(", body)
        self.assertIn("game->flags |= SM_FLAG_FAVORITE", body)
        self.assertIn("&= (uint8_t)~SM_FLAG_FAVORITE", body)
        # Every pass that builds the item list consults it: the folder pass,
        # the game pass, and history's own pass. A pass that skipped it would
        # list games the active filter excludes -- and, for the favourites
        # filter, would fall back to the catalog's stale flag.
        for name, passes in (("static void rebuild_history", 1),
                             ("static void rebuild(", 2)):
            body = ui[ui.index(name):]
            body = body[:body.index("\n}\n")]
            self.assertEqual(body.count("item_matches(ui, &game)"), passes,
                             f"{name} must filter every item it lists")

    def test_history_records_the_path_form_the_catalog_uses(self):
        """launch.c holds two forms of the same file and they are not
        interchangeable. `opened_path` is what the loader opened -- "sd:/ROMS/
        ..." -- and sm_save_sync_arm needs exactly that, because it has to name
        the file on the card. History is matched against catalog entries, and
        the catalog stores the card-relative "ROMS/..." form. Recording the
        first meant every lookup missed and the tab stayed empty forever.

        This is a source check because launch.c needs FatFs and cannot be built
        on the host; the matching half is exercised for real in ui_host_test.c.
        """
        source = strip_comments((ROOT / "src/launch.c").read_text(encoding="utf-8"))
        record = re.search(r"sm_history_record\s*\(([^;]*)\)\s*;", source)
        self.assertIsNotNone(record, "launch.c must record the launch")
        self.assertNotIn("opened_path", record.group(1),
                         "history must record `selected`, the catalog's form")
        self.assertIn("selected", record.group(1))

        # And the save arming, right above it, must still use the other one.
        arm = re.search(r"cart->arm_save\s*\(([^;]*)", source)
        self.assertIsNotNone(arm)
        self.assertIn("opened_path", arm.group(1),
                      "the save has to name the file the loader opened")

    def test_the_launch_is_recorded_before_the_handoff(self):
        """The backend's boot does not return, so anything written after it
        never happens. The record has to be on the card before the jump."""
        source = strip_comments((ROOT / "src/launch.c").read_text(encoding="utf-8"))
        self.assertLess(source.index("sm_history_save("), source.index("cart->boot("))
        self.assertLess(source.index("sm_history_record("), source.index("sm_history_save("))

    def test_every_genre_on_the_card_can_be_selected(self):
        """Eight tabs is what the strip can draw. Building only eight meant a
        genre past the eighth existed on the card and could be reached from
        nowhere -- not the strip, and not the filter screen, which cycles the
        same list."""
        genre = strip_comments((ROOT / "src/genre.h").read_text(encoding="utf-8"))
        self.assertIn("SM_GENRE_TABS_VISIBLE 8u", genre)
        maximum = int(re.search(r"SM_GENRE_TABS_MAX (\d+)u", genre).group(1))
        self.assertGreaterEqual(maximum, 24, "a real N64 library has 24 genres")
        ui = strip_comments((ROOT / "src/ui.c").read_text(encoding="utf-8"))
        tabs = ui[ui.index("static void draw_genre_tabs"):]
        tabs = tabs[:tabs.index("\n}\n")]
        self.assertIn("sm_genre_tab_window(", tabs)

    def test_a_cover_is_probed_before_it_is_loaded(self):
        """sprite_load() asserts rather than returning NULL when the file is
        missing, so a catalog naming a cover this card does not have would
        crash the browser instead of drawing an empty frame."""
        source = (ROOT / "src/ui.c").read_text(encoding="utf-8")
        guard = source.index("static bool cover_asset_exists")
        body = source[guard:source.index("static sprite_t *load_item_cover", guard)]
        self.assertIn('fopen(path, "rb")', body)
        self.assertIn("fclose(", body)
        # The guard must run before the load, not after.
        self.assertLess(source.index("cover_asset_exists(path)", guard),
                        source.index("sprite_load(path)", guard))


class RomLoadTests(unittest.TestCase):
    def setUp(self):
        self.load = (ROOT / "src/rom_load.c").read_text(encoding="utf-8")
        self.ui = (ROOT / "src/ui.c").read_text(encoding="utf-8")
        self.launch = (ROOT / "src/launch.c").read_text(encoding="utf-8")

    def test_loader_uses_fatfs_dispatch_not_a_private_driver(self):
        self.assertIn("f_read(file, destination, want, &got)", self.load)
        self.assertIn("SM_LOAD_CART_KSEG1 + offset", self.load)
        self.assertNotIn("cart_card_rd_cart", self.load)
        self.assertNotIn("cart_card_init(", self.load)

    def test_objsize_widening_is_restored_before_verification(self):
        """Widening obj.objsize keeps every transfer sector-aligned, but the
        verify pass must compare only real file bytes."""
        widen = self.load.index("file->obj.objsize = (FSIZE_t)local.padded_bytes;")
        comparison = self.load.index("/* Verification:")
        # The fall-through restore is the last one before the comparison; the
        # earlier ones belong to early exits and are counted below.
        restore = self.load.rfind("file->obj.objsize = real_size;", widen, comparison)
        verify = self.load.index("f_lseek(file, 0)", restore)
        self.assertLess(widen, restore)
        self.assertLess(restore, verify)
        # Inside the widened window every early return has to restore first,
        # so the counts match exactly. Past the fall-through restore objsize is
        # already correct and later returns need nothing.
        window = self.load[widen:restore]
        early_exits = window.count("return local.step;")
        restores = window.count("file->obj.objsize = real_size;")
        self.assertGreater(early_exits, 0)
        self.assertEqual(restores, early_exits)
        # and nothing widens it again on the way to the comparison
        self.assertNotIn("obj.objsize = (FSIZE_t)", self.load[restore:verify])

    def test_cart_image_loss_is_latched_and_respected(self):
        """Both backends overwrite the browser's own image at offset 0, and
        both must say so before the first byte lands, because the latch is
        what stops the UI reading a font out of a ROM that is no longer
        there."""
        flashcart = strip_comments((ROOT / "src/flashcart.c").read_text(encoding="utf-8"))
        self.assertIn("cart_image_intact = false;", flashcart)
        latch = self.load.index("sm_cart_image_overwritten();")
        first_write = self.load.index("f_read(file, destination", latch)
        self.assertLess(latch, first_write, "latch must be set before the first write")
        pro = strip_comments((ROOT / "src/pro/flashcart_pro.c").read_text(encoding="utf-8"))
        latch = pro.index("sm_cart_image_overwritten();")
        first_write = pro.index("copy_to_cart(ADDR_FCI_ROM,", latch)
        self.assertLess(latch, first_write, "the Pro must latch before its first copy")
        # The copy helper is the one place read_fci targets a caller's
        # address; the only other copy into cartridge memory is the read
        # bounce, at the probe's scratch offset, clear of the browser image.
        # The IPL copy lands in the cartridge's IPL area, not at 0, so it does
        # not latch: the browser's image survives a disk-only launch.
        self.assertEqual(pro.count("ed_fs_file_read_fci("), 2)
        self.assertIn("ed_fs_file_read_fci(PRO_SCRATCH_FCI,", pro)
        self.assertIn("#define PRO_SCRATCH_FCI 0x200000u", pro)
        self.assertIn("copy_to_cart(ADDR_FCI_IPL4,", pro)
        # the UI must stop reading rom:/ the moment the image is gone
        guard = self.ui.index("if (!sm_cart_image_intact()) return NULL;")
        self.assertLess(guard, self.ui.index("cover_asset_exists(path)", guard))

    def test_the_probe_never_reaches_the_destructive_path(self):
        """The three-press ladder is gone -- Start now loads and boots in one
        press, because the details screen is already the confirmation. What
        still has to hold is that the diagnostic probe stays diagnostic: it
        must not be able to fall through into the load that overwrites the
        cartridge image."""
        source = strip_comments(self.launch)
        probe_start = source.index("sm_launch_result_t launch_probe(void)")
        probe_end = source.index("\nsm_launch_result_t launch_rom(", probe_start)
        probe_body = source[probe_start:probe_end]
        self.assertIn("cart->probe(opened_path", probe_body)
        for forbidden in ("cart->load_rom(", "cart->boot(", "cart->arm_save("):
            self.assertNotIn(forbidden, probe_body,
                             f"launch_probe() must not call {forbidden}")
        # and the X7's probe, behind that pointer, is the read-only one
        x7 = strip_comments((ROOT / "src/flashcart_x7.c").read_text(encoding="utf-8"))
        x7_probe = x7[x7.index("static bool x7_probe("):]
        x7_probe = x7_probe[:x7_probe.index("\n}")]
        self.assertIn("sm_x7_probe_run(&file, &report)", x7_probe)
        for forbidden in ("sm_rom_load(", "sm_rom_boot(", "sm_save_sync_arm("):
            self.assertNotIn(forbidden, x7_probe)
        # the Pro has no transport probe, and the launcher must cope with that
        self.assertIn("if (!cart->probe) {", probe_body)
        # and the probe is reachable from the UI only as its own action
        ui = strip_comments(self.ui)
        self.assertIn("launch_probe();", ui)

    def test_byteswap_global_is_set_explicitly(self):
        self.assertIn("cart_card_byteswap = 0;", self.load)


class SafetyGateTests(unittest.TestCase):
    # Writing to the card was forbidden outright while the SD transport was
    # still being proved. It is allowed now, but only from the two modules that
    # exist to write, and only to the two paths the stock firmware owns -- so a
    # bug elsewhere still cannot put a byte on the user's card.
    # favorites.c joins them because a favourite you cannot set is not a
    # feature: it writes one small text file of ROM paths, and nothing else.
    # history.c is the same shape and the same size -- fifteen ROM paths,
    # written once at launch. Adding a name here is meant to be a decision
    # somebody makes on purpose, which is the point of the list.
    # cheats_io.c writes the record of which cheats are on -- one small text
    # file under the browser's folder, in the same spirit as favourites.
    SD_WRITERS = {"save_io.c", "ed64_registry.c", "favorites.c", "history.c", "cheats_io.c"}

    def test_only_the_save_modules_write_to_the_card(self):
        for path in sorted((ROOT / "src").rglob("*.c")):
            source = strip_comments(path.read_text(encoding="utf-8"))
            modes = set(re.findall(r'fopen\s*\([^,]+,\s*"([^"]+)"', source))
            if path.name in self.SD_WRITERS:
                self.assertTrue(modes <= {"rb", "wb"}, f"{path.name}: {modes}")
                continue
            self.assertTrue(modes <= {"rb"}, f"{path.name} opens the card for writing")
            self.assertNotIn("fwrite(", source)

    def test_no_module_deletes_renames_or_creates_directories(self):
        """Nothing on the card is ever removed or moved. A save that goes wrong
        must leave the user's files where they were."""
        source = "\n".join(strip_comments(p.read_text(encoding="utf-8"))
                           for p in (ROOT / "src").rglob("*.c"))
        # Matched as calls, not as substrings: a set operation named
        # sm_favorites_remove() deletes nothing from anybody's card, and a
        # check that cannot tell the two apart is a check nobody can trust.
        for forbidden in ("remove", "rename", "unlink", "mkdir",
                          "f_unlink", "f_mkdir", "f_rename"):
            found = re.search(r"\b" + forbidden + r"\s*\(", source)
            self.assertIsNone(found, f"{forbidden}() must never be called on the card")
        # Still nothing hand-rolls libcart's SD or save-RAM access.
        self.assertNotIn("cart_card_wr", source)
        self.assertNotIn("cart_rom_wr", source)
        self.assertNotIn("SAV_CFG", source)

    def test_the_registry_records_the_path_that_was_opened(self):
        """A catalog stores paths relative to the ROMS root. The record has to
        name the file on the card, so it is built from what the loader
        resolved and opened -- never from the catalog's shorthand."""
        sync = strip_comments((ROOT / "src/save_sync.c").read_text(encoding="utf-8"))
        self.assertIn("sm_registry_path_for_launch(", sync)
        self.assertNotIn("sm_registry_normalise_path(", sync,
                         "save_sync must not normalise a catalog path directly")
        launch = strip_comments((ROOT / "src/launch.c").read_text(encoding="utf-8"))
        # the armed record is built from the resolved path, not `selected`
        arm = launch.index("cart->arm_save(")
        self.assertIn("opened_path", launch[arm:arm + 120])
        self.assertIn("snprintf(opened_path", launch)
        # and the X7 backend passes that path straight through to the registry
        x7 = strip_comments((ROOT / "src/flashcart_x7.c").read_text(encoding="utf-8"))
        self.assertIn("sm_save_sync_arm(sd_path, header, type, report)", x7)

    def test_save_and_pak_come_from_the_cartridge_not_the_catalog(self):
        """The catalog has no save-type or accessory field, so the panel reads
        the highlighted ROM's own header. A hack no database has heard of still
        shows the right save type this way."""
        ui = strip_comments((ROOT / "src/ui.c").read_text(encoding="utf-8"))
        start = ui.index("static void load_selected_details")
        body = ui[start:ui.index("\n}", start)]
        self.assertIn("sm_rom_db_lookup(", body)
        self.assertIn("sm_rom_header_normalise(", body)
        self.assertIn('fopen(paths.primary, "rb")', body)
        # and the panel shows what that produced, not a catalog field
        self.assertIn("ui->selected_details_loaded", ui)
        self.assertIn("sm_save_type_name(ui->selected_save)", ui)

    def test_the_filter_screen_offers_only_what_it_can_filter(self):
        """Filtering on save type would mean opening every ROM on the card.
        Drawing a control that cannot work is worse than leaving it out."""
        ui = strip_comments((ROOT / "src/ui.c").read_text(encoding="utf-8"))
        start = ui.index("static void draw_filters")
        # stop at the next function, not at ui_draw -- other screens between
        # them legitimately mention SAVE.
        body = ui[start:ui.index("\nstatic ", start + 10)]
        for offered in ('"GENRE"', '"REGION"', '"PLAYERS"', '"PUBLISHER"',
                        '"YEAR"', '"FAVORITES"'):
            self.assertIn(offered, body)
        for absent in ('"SAVE"', '"PAK"'):
            self.assertNotIn(absent, body, "the filter cannot narrow on this")

    def test_only_the_selected_row_scrolls(self):
        """Fifteen rows of drifting text would be unreadable and would force a
        redraw every frame."""
        ui = strip_comments((ROOT / "src/ui.c").read_text(encoding="utf-8"))
        start = ui.index("static void draw_row_title")
        body = ui[start:ui.index("\n}", ui.index("marquee", start))]
        self.assertIn("if (!selected || length <= room)", body)

    def test_the_card_paths_written_are_the_firmwares_own(self):
        save_io = strip_comments((ROOT / "src/save_io.c").read_text(encoding="utf-8"))
        registry = strip_comments((ROOT / "src/ed64_registry.h").read_text(encoding="utf-8"))
        header = strip_comments((ROOT / "src/save_io.h").read_text(encoding="utf-8"))
        self.assertIn('#define SM_GAMEDATA_DIR "ED64/gamedata"', header)
        self.assertIn('#define SM_REGISTRY_PATH "sd:/ED64/sysdata/registry.dat"', registry)
        # Every write target is built from that one directory constant.
        for match in re.findall(r'fopen\s*\(([^,]+),\s*"wb"', save_io + registry):
            self.assertTrue("path" in match or "SM_REGISTRY_PATH" in match, match)
        self.assertIn("SM_SAVE_SD_PREFIX SM_GAMEDATA_DIR", save_io)

    def test_save_database_is_read_only(self):
        launch = (ROOT / "src/launch.c").read_text(encoding="utf-8")
        self.assertIn('fopen(SM_SAVE_DB_PATH, "rb")', launch)
        self.assertIn('#define SM_SAVE_DB_PATH "sd:/ED64/save_db.txt"', launch)

    def test_fatfs_is_opened_read_only(self):
        source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.c"))
        for match in re.findall(r"f_open\([^;]*?,\s*([^)]+)\)", source):
            self.assertNotIn("FA_WRITE", match)
            self.assertNotIn("FA_CREATE", match)

    def test_boot_is_reachable_only_from_a_successful_load(self):
        """Verification is optional now, but a load that reported anything
        other than SM_LOAD_OK must still never reach the handoff -- booting a
        half-written image is a hang, not an error message."""
        source = strip_comments((ROOT / "src/launch.c").read_text(encoding="utf-8"))
        load = source.index("loaded = cart->load_rom(")
        gate = source.index("if (loaded != SM_FLASHCART_LOAD_OK) {", load)
        # the gate returns; it does not fall through
        gate_end = source.index("\n    }", gate)
        self.assertIn("return last_result;", source[gate:gate_end])
        boot = source.index("cart->boot(", gate)
        self.assertLess(gate, boot)
        # and the save is on the cartridge before the jump, never after
        arm = source.index("cart->arm_save(", gate)
        self.assertLess(arm, boot)
        self.assertNotIn("cart_exit(", source)
        self.assertNotIn("debug_close_sdfs(", source)
        # The X7 backend reports OK for exactly one load outcome, SM_LOAD_OK;
        # every other step maps to something the gate refuses.
        x7 = strip_comments((ROOT / "src/flashcart_x7.c").read_text(encoding="utf-8"))
        self.assertEqual(x7.count("return SM_FLASHCART_LOAD_OK;"), 1)
        self.assertIn("case SM_LOAD_OK: return SM_FLASHCART_LOAD_OK;", x7)

    def test_boot_tears_down_in_the_right_order(self):
        boot = strip_comments((ROOT / "src/rom_boot.c").read_text(encoding="utf-8"))
        order = ["joypad_close()", "display_close()", "disable_interrupts()",
                 "at_point_of_no_return()", "boot(&params)"]
        positions = [boot.index(token) for token in order]
        self.assertEqual(positions, sorted(positions), "teardown order is wrong")
        self.assertIn("params.cheat_list = (uint32_t *)cheats;", boot)
        self.assertIn("params.detect_cic_seed = true;", boot)

    def test_probe_path_has_no_writes_saves_or_boot(self):
        source = ((ROOT / "src/x7_probe.c").read_text(encoding="utf-8")
                  + (ROOT / "src/launch.c").read_text(encoding="utf-8"))
        for forbidden in ("cart_card_wr", "f_write(", "SAV_CFG", "GAME_CFG",
                          "launch_bootstrap(", "cart_exit("):
            self.assertNotIn(forbidden, source)

    def test_launch_status_fits_the_ui_buffer(self):
        launch = (ROOT / "src/launch.c").read_text(encoding="utf-8")
        self.assertIn("static char status[128]", launch)
        probe = (ROOT / "src/x7_probe.c").read_text(encoding="utf-8")
        for literal in re.findall(r'snprintf\(out, out_size,\s*\n?\s*"([^"]+)"', probe):
            self.assertLess(len(literal), 100, literal)

    def test_rom_format_is_decided_by_the_header_not_the_filename(self):
        launch = strip_comments((ROOT / "src/launch.c").read_text(encoding="utf-8"))
        detect = launch.index("sm_rom_format_detect(header")
        normalise = launch.index("sm_rom_header_normalise(header", detect)
        validate = launch.index("launch_validate(", normalise)
        self.assertLess(detect, normalise)
        self.assertLess(normalise, validate)
        # word-swapped .n64 has no hardware path and must be refused
        self.assertIn("SM_LAUNCH_WORD_SWAPPED", launch)
        self.assertNotIn("launch_suffix_is_z64", launch)

    def test_generated_database_is_reproducible(self):
        """rom_db.c is generated; the generator must refuse to silently drop
        entries, which is how Super Mario 64 went missing the first time."""
        gen = (ROOT / "tools/build_rom_db.py").read_text(encoding="utf-8")
        self.assertIn("ares multi-line entries changed", gen)
        self.assertIn("refusing to write a suspiciously small database", gen)
        db = (ROOT / "src/rom_db.c").read_text(encoding="utf-8")
        self.assertIn("GENERATED by tools/build_rom_db.py", db)
        self.assertIn("'N','S','M'", db)   # Super Mario 64
        self.assertGreater(db.count("},"), 350)

    def test_transfer_chunks_are_the_ones_the_hardware_was_proven_with(self):
        """The X7 streams 128 KiB at a time through FatFs; the Pro asks its
        MCU for a megabyte at a time. Both figures were measured on the
        cartridges, and a bigger number is not a free speed-up: the X7's is
        bounded by libcart's transfer and the Pro's by how often the launch
        card gets to redraw."""
        self.assertIn("#define SM_LOAD_CHUNK (128u * 1024u)",
                      (ROOT / "src/rom_load.h").read_text(encoding="utf-8"))
        self.assertIn("#define PRO_LOAD_CHUNK (1024u * 1024u)",
                      (ROOT / "src/pro/flashcart_pro.c").read_text(encoding="utf-8"))


def check_manifest(test, vendor, at_least):
    import hashlib
    manifest = (vendor / "MANIFEST.sha256").read_text(encoding="utf-8")
    entries = [line.split(None, 1) for line in manifest.splitlines() if line.strip()]
    test.assertGreaterEqual(len(entries), at_least)
    for digest, name in entries:
        path = vendor / name.strip()
        test.assertTrue(path.exists(), f"missing vendored file {name}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        test.assertEqual(actual, digest, f"{name} has been modified")


class VendoredBootTests(unittest.TestCase):
    """The boot handoff is vendored from N64FlashcartMenu, unmodified."""

    VENDOR = ROOT / "third_party/n64flashcartmenu"

    def test_vendored_tree_is_byte_for_byte_upstream(self):
        check_manifest(self, self.VENDOR, 11)

    def test_licence_is_carried_and_flagged(self):
        licence = (self.VENDOR / "LICENSE.md").read_text(encoding="utf-8")
        self.assertIn("GNU AFFERO GENERAL PUBLIC LICENSE", licence)
        vendored = (self.VENDOR / "VENDORED.md").read_text(encoding="utf-8")
        self.assertIn("AGPL-3.0", vendored)
        self.assertIn("6407ab15f6c19d1bf9ded5104c1c8b3c36471379", vendored)

    def test_compat_shim_matches_libdragon_preview_values(self):
        """boot.c needs three C0_STATUS bits that trunk libdragon lacks. The
        values must match preview's cop0.h exactly, or the redefinition would
        be a hard error rather than a legal identical one."""
        compat = (ROOT / "src/boot_compat.h").read_text(encoding="utf-8")
        for name, value in (("C0_STATUS_FR", "0x04000000"),
                            ("C0_STATUS_CU0", "0x10000000"),
                            ("C0_STATUS_CU1", "0x20000000")):
            self.assertRegex(compat, rf"#ifndef {name}\s*\n#define {name} {value}\b")


class VendoredProLibraryTests(unittest.TestCase):
    """krikzz's Pro reference library is vendored unmodified too."""

    VENDOR = ROOT / "third_party/ed64pro"

    def test_vendored_tree_is_byte_for_byte_upstream(self):
        check_manifest(self, self.VENDOR, 9)

    def test_licence_is_carried_and_flagged(self):
        licence = (self.VENDOR / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", licence)
        vendored = (self.VENDOR / "VENDORED.md").read_text(encoding="utf-8")
        self.assertIn("5d7e96905331a841f97f8c51e0b0cba878e72fe3", vendored)

    def test_the_type_macros_stay_inside_the_pro_backend(self):
        """types.h defines u32 and friends as bare macros. Nothing outside the
        Pro backend may include everdrive.h, or every u32 in the tree turns
        into unsigned long behind its author's back."""
        for path in (ROOT / "src").rglob("*.[ch]"):
            if "pro" in path.parts[-2:][0] or path.parent.name.startswith("pro"):
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("everdrive.h", text, f"{path} includes the Pro library")
            self.assertNotIn("appmain.h", text, f"{path} includes the Pro library")


class VendoredFontTests(unittest.TestCase):
    """The interface font is Spleen 5x8, vendored as its BDF, unmodified."""

    VENDOR = ROOT / "third_party/spleen"

    def test_vendored_tree_is_byte_for_byte_upstream(self):
        check_manifest(self, self.VENDOR, 2)

    def test_licence_is_carried_and_flagged(self):
        licence = (self.VENDOR / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Redistribution and use in source and binary forms", licence)
        self.assertIn("Frederic Cambus", licence)
        vendored = (self.VENDOR / "VENDORED.md").read_text(encoding="utf-8")
        self.assertIn("BSD-2-Clause", vendored)
        self.assertIn("0493c34e22791824767c618fed42c434b477662c", vendored)
        notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
        self.assertIn("`third_party/spleen/` | BSD-2-Clause", notice)


class FlashcartInterfaceTests(unittest.TestCase):
    """One ROM, two cartridges. The launcher talks to sm_flashcart_t and the
    two backends do what the hardware needs; these checks hold each side to
    what was proven on the real carts."""

    def source(self, name):
        return strip_comments((ROOT / "src" / name).read_text(encoding="utf-8"))

    def test_the_launcher_knows_no_cartridge(self):
        """launch.c reached FatFs, libcart and the X7 modules directly before
        the Pro existed. Now every byte moves through the interface, so a
        third cartridge is a third backend and not a third launcher."""
        launch = self.source("launch.c")
        for forbidden in ("f_open(", "f_read(", "cart_type", "sm_rom_load(", "sm_rom_boot(",
                          "sm_save_sync_arm(", "sm_x7_probe_run(", "sm_x7_apply_save_type(",
                          "ed_fs_", "ed_dev_"):
            self.assertNotIn(forbidden, launch, f"launch.c reaches past the interface: {forbidden}")
        for needed in ("cart->load_rom(", "cart->arm_save(", "cart->boot(", "cart->probe",
                       "sm_flashcart()->max_rom_bytes()"):
            self.assertIn(needed, launch)
        main = self.source("main.c")
        self.assertIn("sm_flashcart_detect()", main)
        self.assertIn("cart->init(", main)
        self.assertIn("cart->save_sync_flush(", main)
        self.assertNotIn("debug_init_sdfs(", main)

    def test_detection_reads_the_pro_before_probing_the_x7(self):
        """libcart's X-series probe writes a key to an address the Pro maps
        as backup RAM. Reading the Pro's id register is harmless on any
        cart, so it goes first, and it is only ever a read."""
        flashcart = self.source("flashcart.c")
        self.assertLess(flashcart.index("sm_flashcart_pro_present()"),
                        flashcart.index("&sm_flashcart_x7"))
        pro = self.source("pro/flashcart_pro.c")
        present = pro[pro.index("bool sm_flashcart_pro_present(void)"):]
        present = present[:present.index("\n}")]
        self.assertIn("ed_get_cart_id()", present)
        self.assertIn("DEVID_ED64PRO", present)
        for forbidden in ("ed_check_status", "ed_fifo", "ed_dev_", "ed_fs_", "ed_init_hw"):
            self.assertNotIn(forbidden, present, "detection must not talk to the MCU")

    def test_the_pro_backend_follows_the_probe_order(self):
        """probe/pro_probe.c booted two games on a real Pro doing these things
        in this order; the backend keeps to it. Stop the firmware's game
        mapping before the card is touched, name the paths and set the
        configuration with the device stopped, start it again only in the
        boot, and reset the byteswap setting whichever way a load ends."""
        pro = self.source("pro/flashcart_pro.c")
        init = pro[pro.index("static bool pro_init("):pro.index("static void pro_flush(")]
        self.assertLess(init.index("ed_fifo_flush()"), init.index("ed_init_hw()"))
        self.assertLess(init.index("ed_init_hw()"), init.index("ed_fs_init()"))
        self.assertLess(init.index("ed_fs_init()"), init.index('attach_filesystem("sd:/"'))
        arm = pro[pro.index("static bool pro_arm("):pro.index("static bool pro_attach_disk(")]
        stop = arm.index("ed_dev_stop(0)")
        self.assertLess(stop, arm.index("DEV_PATH_GPAK"))
        self.assertLess(arm.index("DEV_PATH_GPAK"), arm.index("DEV_PATH_GDATA"))
        self.assertLess(arm.index("DEV_PATH_GDATA"), arm.index("DEV_PATH_BRM"))
        self.assertLess(arm.index("DEV_PATH_BRM"), arm.index("ed_dev_set_cfg(&cfg)"))
        self.assertNotIn("ed_dev_start()", arm)
        boot = pro[pro.index("static bool pro_boot("):pro.index("const sm_flashcart_t sm_flashcart_pro")]
        self.assertLess(boot.index("ed_dev_start()"), boot.index("sm_rom_boot(NULL, from_disk, cheats)"))
        # a disk boot is refused, with the device stopped again, unless the
        # IPL is readable where the boot code will look for it
        self.assertLess(boot.index("pi_rd(header_back, ADDR_PI_DDIPL"), boot.index("sm_rom_boot(NULL, from_disk, cheats)"))
        self.assertLess(boot.index("ed_dev_stop(0)"), boot.index("sm_rom_boot(NULL, from_disk, cheats)"))
        load = pro[pro.index("static sm_flashcart_load_t pro_load("):pro.index("static u32 bram_type_of(")]
        self.assertEqual(load.count("set_swap("), 2, "swap is set before the copy and reset after")
        self.assertIn("set_swap(byteswap);", load)
        self.assertIn("set_swap(false);", load)
        self.assertEqual(pro.count("ed_dev_wr_swap("), 1, "the swap command has one home")
        # every piece of a copy is positioned explicitly first
        copy = pro[pro.index("static u8 copy_to_cart("):pro.index("static sm_flashcart_load_t pro_load(")]
        self.assertLess(copy.index("ed_fs_file_set_ptr((u32)offset)"), copy.index("ed_fs_file_read_fci("))
        # the disk: attached after the ROM's configuration, with the drive on
        attach = pro[pro.index("static bool pro_attach_disk("):pro.index("static bool pro_boot(")]
        self.assertLess(attach.index("copy_to_cart(ADDR_FCI_IPL4,"), attach.index("DEV_ROM_IPL"))
        self.assertLess(attach.index("DEV_PATH_DISK"), attach.index("armed_cfg.dd_en = 1"))
        self.assertLess(attach.index("armed_cfg.dd_en = 1"), attach.index("ed_dev_set_cfg(&armed_cfg)"))
        self.assertNotIn("ed_dev_start()", attach)
        # and the file-size question is asked with commands the probe ran
        info = pro[pro.index("static int mcu_file_info("):pro.index("typedef struct {")]
        self.assertNotIn("ed_fs_file_info(", info)
        self.assertIn("ed_fs_file_available()", info)
        self.assertIn("sm_pro_fs_release_mcu();", load)
        self.assertLess(load.index("sm_pro_fs_release_mcu();"), load.index("ed_fs_file_open("))
        # the Pro's stock firmware does the save flush, and the backend says so
        self.assertIn(".probe = NULL", pro)
        self.assertNotIn("sm_save_sync_flush(", pro)

    def test_the_pro_names_saves_the_way_its_firmware_does(self):
        """Read back from the firmware by the probe: the game is /ROMS/x.z64,
        its folder ed64/gamedata/x.z64, its save bram.<ext> inside it."""
        pro = self.source("pro/flashcart_pro.c")
        paths = pro[pro.index("static bool pro_paths("):pro.index("static bool pro_arm(")]
        self.assertIn('"/%s"', paths)
        self.assertIn('"ed64/gamedata/%s"', paths)
        self.assertIn('"%s/bram%s"', paths)
        self.assertIn("sm_save_extension(type)", paths)
        # and the save type goes across as the firmware's own enum, explicitly
        self.assertIn("case SM_SAVE_SRM128K: return DEV_BRM_SRM128K;", pro)
        self.assertIn("cfg.brm_size = (u32)sm_save_bytes(type);", pro)

    def test_cheats_reach_the_boot_code_and_nothing_else(self):
        """The GameShark list is built by the launcher from the set the
        player toggled, handed to the cart's boot, and passed straight into
        the vendored engine. Disks get none: the engine patches a cartridge
        IPL3, which the 64DD IPL is not."""
        launch = self.source("launch.c")
        self.assertIn("sm_cheats_build_list(&cheats, cheat_words,", launch)
        self.assertIn("if (!selected_disk && cheats_available && launch_cheats_possible() &&", launch)
        self.assertIn("bool launch_cheats_possible(void) { return is_memory_expanded(); }", launch)
        self.assertLess(launch.index("sm_cheats_build_list("), launch.index("cart->boot("))
        self.assertIn("cheats_available = sm_cheats_load(selected, header, sizeof(header), &cheat_pack, &cheats, &cheats_source);", launch)
        # the player's own folder answers before the firmware's pack, and the
        # pack is asked by name and region, never by a guessed file name
        io = self.source("cheats_io.c")
        self.assertLess(io.index("try_file(SM_CHEATS_DIR, by_file"),
                        io.index("sm_cheat_pack_find(pack, rom_path, header, header_length)"))
        self.assertLess(io.index("sm_cheat_pack_find("), io.index("try_file(SM_FIRMWARE_CHEATS_DIR, match.name"))
        self.assertNotIn("by_title", io)
        # the pack is listed once, at startup, not at the first launch card
        main = self.source("main.c")
        self.assertIn("launch_read_cheat_pack();", main)
        self.assertIn('dir_findfirst(SM_FIRMWARE_CHEATS_DIR, &entry)', io)
        for backend in ("flashcart_x7.c", "pro/flashcart_pro.c"):
            self.assertIn("cheats)", self.source(backend))
        boot = self.source("rom_boot.c")
        self.assertIn("params.cheat_list = (uint32_t *)cheats;", boot)
        # the record of what is on is one file under the browser's folder
        io = self.source("cheats_io.c")
        self.assertIn('fopen(SM_CHEATS_STATE_PATH, "wb")', io)
        self.assertNotIn('fopen(SM_FIRMWARE_CHEATS_DIR', io.replace('"rb"', ''))
        header = (ROOT / "src/card_paths.h").read_text(encoding="utf-8")
        self.assertIn('#define SM_FIRMWARE_CHEATS_DIR SM_SD_ROOT SM_FIRMWARE_FOLDER "/CHEATS"', header)

    def test_the_pro_library_is_confined_to_the_pro_backend(self):
        """The vendored library reaches the cartridge's registers directly;
        the register-access invariant above is kept by never compiling it
        into anything but the backend and the probe."""
        makefile = (ROOT / "Makefile.n64").read_text(encoding="utf-8")
        self.assertIn("$(BUILD_DIR)/src/pro/%.o: CFLAGS += -I$(EDIO)", makefile)
        self.assertIn("$(EDIO)/everdrive.c $(EDIO)/n64.c", makefile)
        self.assertIn("$(BUILD_DIR)/$(EDIO)/%.o: CFLAGS += -Wno-error -w", makefile)
        for path in (ROOT / "src").rglob("*.[ch]"):
            text = path.read_text(encoding="utf-8")
            if path.parent.name == "pro":
                continue
            self.assertNotIn("ed_fs_", text, f"{path} calls the Pro library")
            self.assertNotIn("ed_dev_", text, f"{path} calls the Pro library")


if __name__ == "__main__":
    unittest.main()
