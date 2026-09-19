# Design notes

How SleekMenu 64 is put together and why. Nothing here is needed to use it;
the README covers that. [CARD_LAYOUT.md](CARD_LAYOUT.md) describes the card
and the matching of games to art and text in detail.

- [Principles](#principles)
- [Art and metadata](#art-and-metadata)
- [The browser](#the-browser)
- [Launching a game](#launching-a-game)
- [Saves](#saves)
- [Cheats](#cheats)
- [Maintaining the database](#maintaining-the-database)
- [Status](#status)

## Principles

**Nothing is bundled.** The ROM contains a font and nothing else. Box art,
descriptions and the ROMs are yours, on your card, and the console never
touches the network. The only data shipped is `data/coverdb.csv` (titles,
genre, publisher, year, players; CC BY-SA 4.0), which holds no images. The
tool that prepares the card fetches one thing, once: the box-art collection,
from its own releases page onto a card that lacks it (`tools/fetch.py`). It
lands through a `.part` file and is kept only once it opens as a collection
with boxes in it, so an interrupted download never passes for one; three
addresses are tried, since GitHub's `releases/latest/download/` answers only
for a release not marked pre-release. Offline, the report shows the address
and the card gets a catalog without covers; `--no-download` and
`SLEEKMENU_NO_DOWNLOAD=1` forbid the fetch, and the test suite sets the
latter so no test reaches GitHub.

**No dependence on one collection.** `tests/test_portability.py` builds a
card from a library in which not one game appears in the shipped database and
checks the result still works, boxes included.

**One tool, two faces.** The card is prepared by `tools/sleekmenu_prep.run()`,
whether the command line or the window asks: the window
(`tools/sleekmenu_gui.py`, Tkinter) collects five answers and hands them
over, and reports the same lines and progress the terminal prints. Its Stop
button is a flag the run reads before every progress step and between two
pieces of a download (`tools/progress.stoppable()`), so a stop lands between
two files, never inside one, and before the catalog or covers are written;
Ctrl-C on the command line ends the same way. The
downloadable builds are that window frozen with its Python by PyInstaller,
one per platform, built by `.github/workflows/prep-app.yml` on every tag and
proven there by preparing a card from the frozen binary. They are not
code-signed: that is a yearly fee per platform, and the README says what to
click instead.

**The card is the EverDrive's.** The browser writes five files (see
CARD_LAYOUT.md), never creates, renames or deletes anything else, and uses the
EverDrive menu's own save files and records so the two menus can be used
interchangeably.

## Art and metadata

Box art and descriptions come from
[n64-flashcart-menu-metadata](https://github.com/n64-tools/n64-flashcart-menu-metadata),
a public-domain collection filed by the four-character game code in every
cartridge header. It is what the N64FlashcartMenu reads and what the
EverDrive-64 Pro's menu is fed through krikzz's converter, so one download
serves every menu you might run. The zip is read in place — 52 MB and 2,200
files stay one file on the card.

Matching by game code does what a CRC or a file name never could: a hack or a
translation keeps the code of the cartridge it was built on and gets the same
box; a French cartridge with no scan of its own gets the PAL box; a Japanese
one with no Japanese scan gets the USA box rather than an empty frame. On a
real 3,400-game card, 92% of games are boxed exactly and most of the rest from
a neighbouring region.

A picture of the card owner's own, named after the ROM file beside it or in
`sleekmenu/art/`, comes before the collection, and a `.txt` the same way
becomes the description: that is how a hack stops wearing its parent's box
and homebrew gets one at all (`tools/custom_art.py`; CARD_LAYOUT.md has the
rules).

Text comes from `data/coverdb.csv`, keyed by the CRC pair in the ROM header —
what the dump *is*, not what it is named. The game code is used only as a
fallback, because two characters of game id collide for eleven known pairs of
games; those are refused rather than guessed. The collection's `metadata.ini`
and `description.txt` fill in the rest.

Covers are converted by `tools/make_sprite.py`, which writes libdragon's
sprite format itself; `tests/test_make_sprite.py` checks its output byte for
byte against the real `mksprite`. No toolchain anywhere in the art path.

## The browser

On the console the work is split into small modules:

| module | job |
|---|---|
| `display` | 320×240 NTSC or 320×288 PAL, 16-bit, TV-safe margins |
| `input` | controller state mapped to actions |
| `catalog` | bounded parsing and CRC check of the catalog |
| `cover_pack` | binary-searched cover lookup in `covers.pak` |
| `ui` | list, grid and coverflow views, filters, the launch card, the cheats page |
| `launch_policy` | suffix, magic, size and boot-code checks before anything boots |
| `flashcart` / `launch` | one interface over the two cartridges; the X7 backend streams the ROM through libcart, the Pro backend (`src/pro/`) has the cartridge's MCU copy it |
| `x7_rtc` / `x7_save_reg` | the X7's clock and save configuration for the game about to run |
| `save_io` / `save_sync` / `ed64_registry` | saves to and from `ED64/gamedata/`, and the record the EverDrive menu reads |
| `cheats` / `cheat_pack` / `cheats_io` | finding a game's `.cht`, the record of what is on, the list handed to the boot code |

**Three views**, cycled with C-up. The list is for a game you can name. The
grid shows twelve covers for scanning a folder. Coverflow shows one cover
face-on with three receding either side, for when you don't know what you
want yet; it drops the tab strip and page keys, and L/R jump by initial
letter instead. Every step animates over six frames.

**Browsing.** Folders first, then games; B goes up. The games can be in any
folder on the card, and when every one of them is under the same folder the
tree opens inside it and B stops there: a card with its whole library in
`ROMS/` does not start on a list with one entry in it. C-left/right walk the
genre tabs. Z opens the filter (genre, region, players, publisher, year,
favourites, combined with AND). Two flat shortlists sit at the front of the
tab strip: favourites (C-down, kept in `sleekmenu/favorites.txt`) and the
last fifteen launches (`sleekmenu/history.txt`, written at the moment a boot
is committed; replaying a game moves it up rather than adding it twice).

**Reading from the card is deferred.** Art on the card is slower than art
inside a ROM, so nothing is read while the cursor moves: a cover and the
highlighted game's save type are read a tenth of a second after you stop.
The grid keeps the covers already on screen and fills the new row one cover
per frame; coverflow carries six of its seven covers across a step and reads
one. Covers live in a single `covers.pak` because opening a file by name on a
FAT card walks the folder from the start, and with long names that is over
100 KB of reading per picture.

**The box back.** The description on the launch card is rendered whole,
once, into a surface of its own when the card opens, and the card shows a
window of it copied a row at a time: the software renderer has no clipping,
and a row copy is one. Left alone the window waits two seconds, creeps a
pixel every four frames to the end, holds, and starts over; up and down
move it a line and end the automatic scroll for that visit. A bar at the
right edge says how much there is.

**Font.** Spleen 5x8, vendored as its BDF and rasterised at build time. The
video interface's resampling filter stays on: turning it off at 16 bits per
pixel and 320 pixels across trips a hardware bug on NTSC consoles, and
libdragon refuses the combination.

## Launching a game

`launch_prepare` reads the first 4 KiB of the ROM (header plus boot code),
normalises byte order, checks magic, size and the boot code's CRC, resolves
the save type (header override, then the card's `save_db.txt`, then the
built-in table generated from the ares emulator), and looks for cheats. Start
then hands everything to the cartridge backend: the X7 streams the ROM into
its SDRAM through libcart; the Pro asks its MCU to copy the file into
cartridge memory. Either can verify the copy afterwards (C-up on the card
toggles fast/verified).

The jump itself is the boot handoff vendored from N64FlashcartMenu: it
quiesces the RCP, copies the game's own boot code into the RSP's memory,
installs the cheat engine when there is a list, and jumps. That code is AGPL
and the reason the whole project is.

**The checksum.** The retail boot code sums the megabyte after itself and
compares two words of the result with the header; a mismatch is a black
screen before the game's first instruction. Emulators skip the check, so a
hack can ship with stale words, and the EverDrive menu quietly rewrites
them as it loads. After its own load the browser sums the game as it sits in
cartridge memory (`rom_checksum.c`, pure; the megabyte comes through a
reader) and, when the words are stale, writes the right ones into the
header there and reads them back. On the Pro the write goes through the
MCU; on the X7 through the PI, which is the one step not yet seen to take
on hardware — the read-back decides, and a correction that did not take
stops that launch with a message rather than booting into a black screen;
the next Start goes ahead regardless. `tools/n64_checksum.py` is the same
sum on the computer, checked against real cartridges of every boot code;
the prep tool runs it over every dump the database does not know and
rewrites the file only when asked (`--fix-checksums`).

**The clock.** A game that keeps time — Animal Forest and its translations —
is flagged by the same lookup that resolves its save type. On the Pro the
cartridge's MCU is told to serve its own clock and nothing more is needed.
On the X7 the browser does what the stock menu does before such a game:
reads the cartridge's DS1337 over I2C, sets the emulated clock with three
Joybus writes (stop, time, start), and turns the clock on for the game in
the same register write that selects its save memory, at the point of no
return. The clock is off while the browser itself runs, so it is switched on
for the three writes and off again; a clock that does not answer cancels the
launch before the save is armed. The protocol was read out of the stock
OS 3.11 with `tools/trace_x7_rtc.py`, which is where the evidence lives.

**64DD.** On the Pro, `.ndd` images are listed like games. Selected on their
own they boot from the drive's IPL, which the Pro menu keeps in
`ED64/64ddipl/`, chosen by the disk's region; a `.ndd` beside a cartridge
ROM is attached to it as an expansion disk. Not yet run on hardware.

## Saves

Saves are written to `ED64/gamedata/` under the names the EverDrive menu uses,
and both menus read and write `ED64/sysdata/registry.dat`, the record that
says which game is loaded and what save hardware to emulate. The format is
not published; `tools/ed64_registry.py` documents what was worked out from
captures of a real card, and the tests read those captures. On the X7 the save is moved to the card the
next time a menu boots; on the Pro the cartridge handles saves itself and the
stock menu writes them out at its next boot.

## Cheats

The GameShark engine is the vendored boot code's. It hooks a game by
overwriting one instruction of the retail boot code — the `jr $t1` that jumps
to the game — at an offset that depends on the CIC, and boots the game clean,
silently, when that instruction is not where it expects. Before launch the
browser runs the same test on the ROM's first 4 KiB and says so on the card.
Two cases it cannot help: a homebrew or re-signed boot code (libdragon's,
say), and CIC 6101 (Star Fox 64, NTSC), for which the vendored table has the
7102 offset — word 466, where that boot code keeps its jump at word 476. A
one-number fix for upstream; the vendored copy stays byte for byte.

**Finding a game's file.** The Pro menu's pack under `ED64/CHEATS/` is the
older half of libretro's cheat database, byte for byte: 543 files named the
GoodN64 way (`F-Zero X (U).cht`, `Super Mario 64 (J).cht`), while a library
is usually named the No-Intro way (`F-Zero X (USA).z64`). A lookup by exact
name therefore finds almost nothing. Instead the browser lists the folder
once at startup and matches on two things: the names with their tags
stripped, and the region — the file's from its tag, the cartridge's from the
fourth letter of its game code (`NSME` is American, `NSMP` European).

Fifty-nine files carry no tag, most of them named after the header title,
which is the same on every region's cartridge. Their region was settled once
by comparing each file's codes with libretro's region-named files for the
same game (`SUPER MARIO 64.cht` turned out to be the European one,
`GOLDENEYE.cht` the American); the table is in `cheat_pack.c`, and the dozen
that could not be settled are offered flagged as unverified.

Over a 3,400-ROM No-Intro library this finds a region-verified file for just
over half the games, tells about 300 that the pack has the game for another
region only, and leaves about 950 with nothing. The full libretro database
has twice the files; reading a copy dropped on the card would be the next
step.

## Maintaining the database

Inspect and correct rows:

```sh
make curate ARGS="show 'ocarina of time'"
make curate ARGS="set-genre re:'zelda.*ocarina' 'Action-Adventure'"
```

Re-apply every correction, and a newer collection, to a card already built:

```sh
make refresh METADATA_JSON=build/card/metadata.json METADATA=release-metadata.zip CARD=/Volumes/CARD
```

Genres are re-derived from `data/coverdb.csv` and `data/genres.csv` on every
run rather than patched in place, so a correction cannot be lost by rebuilding
from an older artefact. `data/genres.csv` folds libretro's twenty-four genre
strings into the twelve the tab strip shows.

Extend the database from a library of your own, with a checkout of
[libretro-database](https://github.com/libretro/libretro-database):

```sh
make coverdb ROMS_ROOT=/path/to/ROMS LIBRETRO=/path/to/libretro-database
```

`FILE_CRC=1` identifies games by the No-Intro CRC32 of the whole file, which
is exact but reads the entire library; `CRC_CACHE=build/crc-cache.jsonl`
makes it resumable.

## Status

Proven on hardware: the SD transport, a full ROM load verified byte for byte,
the boot handoff, saves in both directions with the stock menu, and the
return to the stock menu — on an EverDrive-64 X7 and an EverDrive-64 Pro.
The X7's clock, with Animal Forest keeping time and reloading its save.

Open:

- Controller Pak (`.mpk`) backup and restore.
- 64DD on hardware.
- The Pro's clock in a game: the MCU is told to serve it; not yet watched.
- The checksum correction on the X7: whether SDRAM takes the PI write. The
  read-back reports it either way.
- Cheats seen to take effect in a game: the page and the matching work on
  hardware; the one in-game test so far used a file for the wrong region.
- Cheats on CIC 6101 cartridges (see above).
- A crisper picture: the VI filter cannot be turned off at this resolution and
  depth, so it is a 32-bit framebuffer or a 640-pixel mode.
- Reading libretro's full cheat database from the card.
