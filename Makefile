# SPDX-License-Identifier: AGPL-3.0-only
PYTHON ?= python3
N64_INST ?=
LIBDRAGON_ROOT ?= third_party/libdragon
BUILD_DIR := build
COVERDB := data/coverdb.csv

.PHONY: all help test card metadata coverdb card-art \
        covers-pak discover-sd check-n64 font-dfs slim clean \
        curate refresh registry rom-db prep release gui

all: help

help:
	@echo "SleekMenu 64"
	@echo ""
	@echo "The release is two files: the ROM and the card-preparation tool."
	@echo "  make prep       Build build/release/sleekmenu-prep.pyz (Python only)"
	@echo "  make release    Build both; needs the libdragon toolchain for the ROM"
	@echo ""
	@echo "  make gui        Open the card-preparation window (needs Tk in this Python)"
	@echo ""
	@echo "Preparing a card from a checkout (the .pyz does this for you on the card):"
	@echo "  make card CARD=/Volumes/CARD ROMS_ROOT=/Volumes/CARD/ROMS [METADATA=release-metadata.zip] [ROM=...]"
	@echo "  make covers-pak COVER_DIR=build/sd/sleekmenu/covers   Pack a covers folder into covers.pak"
	@echo "  make card-art ROMS_ROOT=... METADATA=...   Just convert the boxes to sprites"
	@echo "  make metadata ROMS_ROOT=... [CARD=...] [METADATA=...] [COVER_MAP=...]"
	@echo ""
	@echo "Building the ROM (needs a libdragon toolchain in N64_INST):"
	@echo "  make check-n64  Check for a usable libdragon installation"
	@echo "  make slim       Build build/release/SleekMenu64.z64; art comes from the card"
	@echo ""
	@echo "Maintaining the database:"
	@echo "  make coverdb ROMS_ROOT=... LIBRETRO=... [FILE_CRC=1]"
	@echo "  make curate ARGS='show zelda'          Inspect and correct database rows"
	@echo "  make refresh METADATA_JSON=... [METADATA=...] [CARD=...]  Re-derive genres, add new boxes"
	@echo ""
	@echo "Diagnostics and regeneration (maintainer only):"
	@echo "  make registry FILE=/path/to/registry.dat   Decode an EverDrive registry record"
	@echo "  make rom-db ARES=/path/to/ares            Regenerate src/rom_db.c"
	@echo ""
	@echo "Other:"
	@echo "  make test       Run host-side unit tests"
	@echo "  make discover-sd SD_ROOT=...   Build a catalog from a mounted card"
	@echo "  make font-dfs   Build the embedded font filesystem"
	@echo "  make clean      Remove build/"

test:
	@$(PYTHON) -c "import PIL" 2>/dev/null || { \
		echo ""; \
		echo "Pillow is missing. The test suite reads and writes images, so"; \
		echo "several tests cannot run without it:"; \
		echo ""; \
		echo "    pip install -r requirements-dev.txt"; \
		echo ""; \
		exit 1; \
	}
	$(PYTHON) -m unittest discover -s tests -v

# Everything a card needs, in one pass. This is the supported way in; the
# targets below it exist for when you want one step on its own.
card:
	@if [ -z "$(CARD)" ] || [ -z "$(ROMS_ROOT)" ]; then \
		echo "card requires CARD=/Volumes/CARD ROMS_ROOT=/Volumes/CARD/ROMS [METADATA=...] [ROM=...]"; exit 1; \
	fi
	$(PYTHON) tools/prepare_card.py --card "$(CARD)" --roms "$(ROMS_ROOT)" \
		$(if $(METADATA),--metadata "$(METADATA)",) \
		$(if $(ROM),--rom "$(ROM)",) \
		--coverdb "$(COVERDB)" \
		$(if $(OVERRIDES),--overrides "$(OVERRIDES)",) \
		--work $(BUILD_DIR)/card

# The metadata collection -> sprites the card can read, one per box, named
# by game code. METADATA is release-metadata.zip from the collection's
# releases page, or a folder of it unpacked.
card-art:
	@if [ -z "$(ROMS_ROOT)" ] || [ -z "$(METADATA)" ]; then \
		echo "card-art requires ROMS_ROOT=/path/to/ROMS METADATA=/path/to/release-metadata.zip"; exit 1; \
	fi
	$(PYTHON) tools/pack_covers.py "$(ROMS_ROOT)" --metadata "$(METADATA)" \
		--destination $(BUILD_DIR)/sd/sleekmenu/covers
	$(PYTHON) tools/cover_pack.py $(BUILD_DIR)/sd/sleekmenu/covers \
		--output $(BUILD_DIR)/sd/sleekmenu/covers.pak
	@echo ""
	@echo "Covers:  $(BUILD_DIR)/sd/sleekmenu/covers.pak -> copy to the card as sleekmenu/covers.pak"

covers-pak:
	@if [ -z "$(COVER_DIR)" ]; then \
		echo "covers-pak requires COVER_DIR=/path/to/covers"; exit 1; \
	fi
	$(PYTHON) tools/cover_pack.py "$(COVER_DIR)" \
		--output "$(or $(COVER_PAK),$(BUILD_DIR)/sd/sleekmenu/covers.pak)"

# CARD matters more than it looks: catalog paths are recorded relative to it,
# and the browser resolves them as sd:/ROMS/<p> then sd:/<p>. Recording them
# against a ROM folder that is neither leaves every launch failing silently.
metadata:
	@if [ -z "$(ROMS_ROOT)" ]; then \
		echo "metadata requires ROMS_ROOT=/path/to/ROMS [CARD=/Volumes/CARD]"; exit 1; \
	fi
	$(PYTHON) tools/build_metadata.py "$(ROMS_ROOT)" \
		$(if $(CARD),--sd-root "$(CARD)",) \
		--coverdb "$(COVERDB)" \
		$(if $(METADATA),--metadata "$(METADATA)",) \
		$(if $(OVERRIDES),--overrides "$(OVERRIDES)",) \
		$(if $(COVER_MAP),--cover-map "$(COVER_MAP)",) \
		--output "$(or $(METADATA_OUT),$(BUILD_DIR)/metadata.json)"
	$(PYTHON) tools/build_catalog.py "$(or $(METADATA_OUT),$(BUILD_DIR)/metadata.json)" \
		--output $(BUILD_DIR)/catalog.ebc \
		--manifest $(BUILD_DIR)/catalog.manifest.json
	@echo "Copy $(BUILD_DIR)/catalog.ebc to the card as sleekmenu/catalog.ebc"

# Maintainer only. Rebuilds data/coverdb.csv from a real library; FILE_CRC=1
# reads every ROM in full and matches on the No-Intro CRC32, which is exact and
# takes minutes. CRC_CACHE makes a second run cheap.
coverdb:
	@if [ -z "$(ROMS_ROOT)" ] || [ -z "$(LIBRETRO)" ]; then \
		echo "coverdb requires ROMS_ROOT=... LIBRETRO=/path/to/libretro-database"; exit 1; \
	fi
	$(PYTHON) tools/seed_coverdb.py "$(ROMS_ROOT)" --libretro "$(LIBRETRO)" \
		$(if $(FILE_CRC),--file-crc,) \
		$(if $(CRC_CACHE),--crc-cache "$(CRC_CACHE)",) \
		--merge --output "$(COVERDB)"

# The user-facing tool: the whole host toolchain and the database as one
# file that runs from the card. No toolchain needed to build it, so it is also
# what CI builds on every push.
prep:
	$(PYTHON) tools/build_prep.py --output $(BUILD_DIR)/release/sleekmenu-prep.pyz
	@$(PYTHON) $(BUILD_DIR)/release/sleekmenu-prep.pyz --help > /dev/null
	@echo "Release tool: $(BUILD_DIR)/release/sleekmenu-prep.pyz"

# The window, from a checkout. The releases page carries it frozen with its
# Python for people who have neither; .github/workflows/prep-app.yml builds
# those.
gui:
	$(PYTHON) tools/sleekmenu_gui.py

# Everything a GitHub release carries. Nothing else: no art, no metadata --
# the tool builds those on the user's card from the collection they put there.
release: slim prep
	@echo ""
	@echo "Release contents:"
	@ls -la $(BUILD_DIR)/release/SleekMenu64.z64 $(BUILD_DIR)/release/sleekmenu-prep.pyz

# Inspect or correct data/coverdb.csv by hand. Everything curate.py can do is
# reachable through ARGS: show, set-genre.
#     make curate ARGS="show 'ocarina of time'"
#     make curate ARGS="set-genre re:'zelda.*ocarina' 'Action-Adventure'"
curate:
	@if [ -z "$(ARGS)" ]; then \
		echo "curate requires ARGS=..., e.g. ARGS=\"show zelda\""; \
		$(PYTHON) tools/curate.py --help; exit 1; \
	fi
	$(PYTHON) tools/curate.py --db "$(COVERDB)" $(ARGS)

# Re-derive an existing metadata.json against the current data/ files. Genres
# are recomputed from coverdb.csv + genres.csv every run rather than patched in
# place, so a curated correction cannot be silently reverted by a stale build
# artefact. Boxes are additive: nothing already matched is dropped.
refresh:
	@if [ -z "$(METADATA_JSON)" ]; then \
		echo "refresh requires METADATA_JSON=/path/to/sleekmenu/catalog.json [METADATA=release-metadata.zip]"; exit 1; \
	fi
	$(PYTHON) tools/refresh_catalog.py "$(METADATA_JSON)" \
		--coverdb "$(COVERDB)" \
		--genres data/genres.csv \
		$(if $(METADATA),--collection "$(METADATA)",) \
		$(if $(CARD),--covers "$(CARD)/sleekmenu/covers",) \
		--output "$(METADATA_JSON)"

# Decode one /ED64/sysdata/registry.dat. Prints every field the format is known to
# carry; tools/ed64_registry.py documents the layout.
registry:
	@if [ -z "$(FILE)" ]; then \
		echo "registry requires FILE=/path/to/registry.dat"; exit 1; \
	fi
	$(PYTHON) tools/ed64_registry.py "$(FILE)"

# Maintainer only. Regenerates src/rom_db.c from the save-type table in the
# ares emulator (ISC). Needs an ares checkout; see NOTICE.md.
rom-db:
	@if [ -z "$(ARES)" ]; then \
		echo "rom-db requires ARES=/path/to/ares"; exit 1; \
	fi
	$(PYTHON) tools/build_rom_db.py \
		--source "$(ARES)/mia/medium/nintendo-64.cpp" \
		--header src/rom_db.h --output src/rom_db.c

discover-sd:
	@if [ -z "$(SD_ROOT)" ]; then \
		echo "discover-sd requires SD_ROOT=/path/to/mounted/sd"; exit 1; \
	fi
	$(PYTHON) tools/discover_sd.py "$(SD_ROOT)" $(if $(METADATA),--metadata "$(METADATA)",) \
		$(if $(COVER_MAP),--cover-map "$(COVER_MAP)",)

check-n64:
	@if [ -z "$(N64_INST)" ]; then \
		echo "N64 build unavailable: set N64_INST to an installed libdragon toolchain."; \
		exit 1; \
	fi
	@if [ ! -f "$(N64_INST)/include/n64.mk" ]; then \
		echo "N64 build unavailable: $(N64_INST)/include/n64.mk was not found."; \
		exit 1; \
	fi
	@if [ ! -f "$(LIBDRAGON_ROOT)/n64.mk" ]; then \
		echo "libdragon checkout unavailable: $(LIBDRAGON_ROOT)/n64.mk was not found."; \
		exit 1; \
	fi
	@echo "libdragon toolchain found at $(N64_INST)"
	@echo "libdragon checkout found at $(LIBDRAGON_ROOT)"

N64_INST_AUTO := $(if $(N64_INST),$(N64_INST),$(CURDIR)/.toolchain)
FONT_SOURCE := third_party/spleen/spleen-5x8.bdf
FONT_BUILD := $(BUILD_DIR)/font
FONT_DFS := $(FONT_BUILD)/sleekmenu-font.dfs

# The font is the only thing that has to ship inside the ROM: there is no
# screen without it. Box art does not: it comes off the card, matched once on
# a desktop against data/coverdb.csv, so the ROM stays small and the build
# depends on no art collection. The font itself is Spleen 5x8 (BSD-2-Clause),
# vendored as its BDF and rasterised here.
font-dfs:
	@if [ ! -x "$(N64_INST_AUTO)/bin/mkdfs" ]; then \
		echo ""; \
		echo "No libdragon toolchain at $(N64_INST_AUTO)."; \
		echo "Building the ROM needs one; preparing a card does not."; \
		echo "Set N64_INST to your libdragon install:"; \
		echo "    make slim N64_INST=/path/to/libdragon"; \
		echo ""; \
		exit 1; \
	fi
	rm -rf $(FONT_BUILD)/filesystem
	mkdir -p $(FONT_BUILD)/filesystem
	$(PYTHON) tools/build_compact_font.py --source "$(FONT_SOURCE)" \
		--filesystem "$(FONT_BUILD)/filesystem" --work "$(FONT_BUILD)/work"
	"$(N64_INST_AUTO)/bin/mkdfs" "$(FONT_DFS)" "$(FONT_BUILD)/filesystem"

slim: font-dfs
	$(MAKE) -B -f Makefile.n64 N64_INST="$(N64_INST_AUTO)" LIBDRAGON_ROOT="$(LIBDRAGON_ROOT)" \
		DFS_IMAGE="$(FONT_DFS)"
	mkdir -p $(BUILD_DIR)/release
	cp sleekmenu.z64 $(BUILD_DIR)/release/SleekMenu64.z64
	@echo "Release: $(BUILD_DIR)/release/SleekMenu64.z64 (art comes from the card)"

clean:
	rm -rf $(BUILD_DIR)
