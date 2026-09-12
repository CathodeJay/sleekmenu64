# Design notes

The long version of what the README keeps short: where the art and the text
metadata come from and how a game is matched to them, how the database is
maintained, how the browser is put together, and what is still open. Nothing
here is needed to use SleekMenu 64.

## Your own library, the shared collection

This is the part that is easy to get wrong, so it is worth being explicit: **no
part of this project depends on one particular ROM collection or art pack.**
`tests/test_portability.py` enforces that — it builds a card from a library
where not one cartridge appears in the shipped database and asserts the result
still works, boxes included.

### Where the art and descriptions come from

[n64-flashcart-menu-metadata](https://github.com/n64-tools/n64-flashcart-menu-metadata)
is a public-domain collection of box art, descriptions and release details,
filed by the four-character game code every cartridge carries in its header:
GoldenEye USA is `NGEE`, so its box is `metadata/N/G/E/E/boxart_front.png`.
It is the collection the N64FlashcartMenu reads, and the one the EverDrive-64
Pro's own menu is fed through krikzz's converter, so one download serves every
menu you might run.

Download `release-metadata.zip` from its
[releases page](https://github.com/n64-tools/n64-flashcart-menu-metadata/releases)
and put it on the card next to the tool (or in `sleekmenu/`). It is read in
place: 52 MB and 2,200 files stay one file on the card. A card that already
holds the collection unpacked for the N64FlashcartMenu (`menu/metadata/`), or
converted for the EverDrive-64 Pro's own menu by krikzz's edmeta
(`ED64/metadata/`), is read as it is — the Pro's copies are pre-stretched to
double width for its 640-pixel mode and are read at half width — and
`--metadata` points at a copy anywhere else.

Matching by game code is what a CRC or a filename never managed. A hack, a
translation or a fixed dump keeps the code of the cartridge it was built on and
gets the same box; a French cartridge with no box of its own gets the PAL one,
a Japanese cartridge with no Japanese scan gets the USA box rather than an
empty frame. On a real 3,371-game card that is 92% of games boxed exactly, most
of the rest boxed from a neighbouring region, and no guessing anywhere.

The collection also carries a `description.txt` — the first paragraph of the
box back — and a `metadata.ini` with publisher, release date and player count
for a growing share of games. The description goes on the launch card; the
rest fills in whatever `data/coverdb.csv` does not already say.

Be clear about what this is: the pictures are the publishers'. This project
distributes none of them, and the tool downloads nothing; you fetch the
collection yourself, once. Want a box the collection lacks? Add it to a folder
copy under the game's code and the tool picks it up; better still, send it
upstream.

Conversion is done by `tools/make_sprite.py`, which writes libdragon's sprite
container directly; `tests/test_make_sprite.py` checks its output byte-for-byte
against sprites from the real `mksprite`, so there is no toolchain anywhere in
the art path. Covers are fitted, not stretched: portrait Japanese packaging
keeps its proportions on a 96×72 matte. One sprite per box, named by game
code, so three copies of a game in three folders cost one picture.

### How the text metadata is matched

`data/coverdb.csv` maps a cartridge to its genre, publisher, year and player
count. The key is the CRC pair in the ROM's **own header** — what the dump
*is*, rather than what somebody named the file — so a game renamed
`0421 - stuff [!].z64` still gets its row.

```
crc,serial,name,genre,publisher,year,players,regions
635A2BFF8B022326,NSME,Super Mario 64 (USA),Platform,Nintendo,1996,1,USA
```

`serial` is the same NUS product code the collection files boxes under. It is
a weaker key — two characters of game code was never much room, and eleven
genuine collisions exist in the wild — so it is used only after the CRC, for
the patched dumps the CRC cannot know, and colliding codes are refused rather
than guessed. A cartridge nothing knows is left blank rather than guessed at:
the browser shows its filename and simply cannot filter it by year.

## Maintaining the database

Inspect and correct rows:

```sh
make curate ARGS="show 'ocarina of time'"
make curate ARGS="set-genre re:'zelda.*ocarina' 'Action-Adventure'"
```

Re-apply every correction, and a newer collection, to a card you have already
built, without re-reading the library:

```sh
make refresh METADATA_JSON=build/card/metadata.json METADATA=release-metadata.zip CARD=/Volumes/CARD
```

Genres are re-derived from `data/coverdb.csv` and `data/genres.csv` on **every**
run rather than patched in place. That is deliberate: a fix applied once to a
build artefact is lost the moment anything rebuilds from an older copy, which
is exactly how Ocarina of Time went back to being a role-playing game.
`data/genres.csv` consolidates libretro's twenty-four genre strings into the
twelve the tab strip shows.

To extend the database from a library of your own:

```sh
make coverdb ROMS_ROOT=/path/to/ROMS LIBRETRO=/path/to/libretro-database
```

Add `FILE_CRC=1` to identify games by the No-Intro CRC32 of the whole file,
which is exact and indifferent to renaming — and which reads the entire
library, so budget minutes rather than seconds. `CRC_CACHE=build/crc-cache.jsonl`
makes it resumable, and `--only-unmatched` restricts the expensive read to the
games a name match could not identify.

The libretro DATs are not vendored here. Point `LIBRETRO` at your own checkout
of [libretro-database](https://github.com/libretro/libretro-database).

## How it works

The host tooling validates the metadata, normalises paths and regions, sorts by
case-folded ROM path, interns strings and writes a checksum-protected catalog.
On the console, responsibilities are split into narrow modules:

| module | job |
|---|---|
| `display` | 320×240 NTSC or 320×288 PAL, integer-pixel, TV-safe |
| `input` | controller state mapped to semantic actions |
| `catalog` | bounded parsing and CRC validation of the host catalog |
| `cover_pack` | binary-searched cover lookup, one file open per picture |
| `ui` | list and grid views, paging, filters, launch detail |
| `launch_policy` | suffix, magic, size and IPL3 CRC gates before anything boots |
| `flashcart` / `launch` | the cartridge behind one interface: the X7 backend streams the ROM into SDRAM through libcart (`rom_load`), the Pro backend (`src/pro/`) has the cartridge's MCU copy it; either can verify, and both report progress for the bar |
| `save_io` / `save_sync` / `ed64_registry` | moves save memory to and from `ED64/gamedata/` and writes the record the stock firmware reads |
| `cheats` / `cheat_pack` / `cheats_io` | finds a game's `.cht` in the firmware's pack by name and region, reads it, keeps the record of what is on, builds the list the boot code's GameShark engine takes, and checks ahead of time that the engine can hook the game's boot code |

**Saves interoperate with the stock menu.** Saves are written to
`ED64/gamedata/` under the same names the firmware uses, and both menus read
and write the same `ED64/sysdata/registry.dat`, so a game started from one
finishes its save in the other. That format is undocumented; how it was worked
out is in [docs/sd-forensics/](docs/sd-forensics/).

**Three views**, cycled with C-up. The **list** is for finding a game you can
name. The **grid** puts twelve covers on screen for scanning a folder. **Coverflow**
turns the shelf side on, one cover face on in the middle with three receding
either side — for when you don't know what you want yet. Every step slides:
covers move, turn and resize between their old and new places over six frames,
entering and leaving past the edges of the screen rather than appearing in the
middle of it. Coverflow gives up the tab strip and the page keys: L and R jump
to the next initial instead, which crosses a three-thousand-game library in
about as many presses as there are letters.

**Browsing.** Each view lists folders first, then games in the current folder;
B goes to the parent. C-left and C-right walk the genre tab strip, which shows
eight codes at a time and scrolls with the selection, so every genre on the
card is reachable. Z opens the combined genre, region, players, publisher, year
and favourites filter, combined with AND.

**Two shortlists** sit at the front of the strip, both flat — they ignore
whatever folder you were standing in, because a shortlist that only showed the
matches in one folder would not be one. **Favourites** are set with C-down and
live in `sleekmenu/favorites.txt`. **History** is the last fifteen games you
launched, most recent first, written to `sleekmenu/history.txt` at the moment
a boot is committed. Replaying a game moves it up rather than adding it twice,
so the list stays fifteen things you are actually playing.

**Cheats** are the Pro firmware's own database, `ED64/CHEATS/<game>.cht`
in libretro's text form, read as it is; a file of your own under
`sleekmenu/cheats/`, named after the ROM file, is looked at first. The
pack is the older half of libretro's cheat database, byte for byte: 543
files named the GoodN64 way, `F-Zero X (U).cht`, `Super Mario 64 (J).cht`,
while a library is usually named the No-Intro way, `F-Zero X (USA).z64`.
A lookup by exact name therefore finds almost nothing, so the browser
lists the folder once at startup (543 names, under a second on the Pro's
MCU) and matches a game to its file by the names with their tags stripped
and by region: the file's from its tag, the cartridge's from the fourth
letter of its game code (`NSME` is American, `NSMP` European). Fifty-nine
files carry no tag -- most named after the header title, which is the
same on every region's cartridge -- and their region was settled once by
matching their codes against libretro's region-named files (`SUPER MARIO
64.cht` is the European one, `GOLDENEYE.cht` the American); the table is
in `cheat_pack.c`, and the dozen that could not be settled are handed over
flagged. Over a 3,400-ROM No-Intro library this finds a region-verified
file for just over half the games, tells 300 or so that the pack has the
game for another region only, and leaves 950 with nothing -- the pack is
what it is; the full libretro database has twice the files, and reading
one dropped on the card would be the next step. The engine itself is the
vendored boot code's: it hooks the game by overwriting the `jr $t1` that
ends the retail IPL3, at an offset that depends on the CIC, and boots the
game clean when that instruction is not where it expects. The browser
runs the same test on the ROM's first 4 KiB before launch and says so on
the card, because the engine says nothing. Two cases it cannot help with:
a homebrew or re-signed IPL3 (libdragon's, say), and CIC 6101 -- Star Fox
64 in NTSC -- for which the vendored table has the 7102 offset (word 466)
where that boot code keeps its jump at word 476, so those two cartridges
boot without cheats until the fix lands upstream.

**Covers come off the card**, which is slower than reading them from inside the
ROM, so nothing touches the card while the selection is moving: a cover and the
highlighted game's save type are read a tenth of a second after you stop. The
grid scrolls a row at a time, keeps the eight covers that stay on screen, and
fills the four new ones one per frame. Coverflow works the same way: stepping
one cover along carries six of the seven across and reads exactly one. All covers live in a single `covers.pak`
because FatFs has no directory index — opening a cover by name walks the
directory from the start, and with long filenames that is over 100 KB of
walking, per picture.

## What you supply, and what nothing fetches

You supply the ROMs and the metadata collection. Nothing here bundles,
downloads or redistributes either; neither the console nor the prep tool ever
touches the network.

The prep tool carries one thing: `data/coverdb.csv`, which holds titles,
genre, publisher, year and player counts derived from libretro-database. It
holds no images and no ROM data, and it is CC BY-SA 4.0 (`data/LICENSE`).

The release itself — the ROM and the prep tool — contains no art and no
per-card metadata. Both are built onto your card, from your library and the
collection you put there, when you run the tool. A card image or a build you
pass on to somebody else carries whatever you put on it; the box scans on it
are the publishers', whatever licence the collection's files carry.

## Status

Proven on hardware, in this order: the SD-to-SDRAM transport, a full ROM load
verified byte-for-byte, the boot handoff, cartridge saves in both directions
with the stock firmware, and a return to the stock menu afterwards.

Still open:

- Controller Pak (`.mpk`) backup and restore, and telling the games that save
  only to a pak that they need one.
- Cheats on CIC 6101 cartridges (Star Fox 64, NTSC): the vendored engine
  looks for its hook one word off for that CIC. A one-number fix for
  upstream N64FlashcartMenu; the vendored copy stays byte-for-byte until
  then.
- Save type and accessory support in the catalog record, so the filter screen
  can offer those rows instead of leaving them out.
- Soak tests over a full library, PAL capture review, malformed-media cases.

[docs/catalog-format.md](docs/catalog-format.md) has the exact binary contract.
