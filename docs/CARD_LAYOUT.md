# The card

Everything SleekMenu 64 reads or writes on the SD card, and how a game is
matched to its box art and its description. The README has the short version;
this is the reference.

## Layout

```text
/SleekMenu64.z64            the browser                        you copy it
/sleekmenu-prep.pyz         the card-preparation tool          you copy it
/release-metadata.zip       box art and descriptions           fetched by the tool
/ROMS/...                   your games, in any folders          yours
/<any other folder>/...     or anywhere else on the card        yours
                            (or one chosen folder: --roms, or the window's Games folder)

/sleekmenu/art/...          your own pictures and text         yours, or the window's
/sleekmenu/art/hires/...    512-pixel boxes, one per game code  fetched by the tool (--hires)
/sleekmenu/catalog.ebc      titles, genre, publisher, year     written by the tool
/sleekmenu/catalog.json     the same, with every field's source  written by the tool
/sleekmenu/covers.pak       every cover, one file              written by the tool
/sleekmenu/covers-large.pak the same covers at 256x180             written by the tool
/sleekmenu/favorites.txt    one ROM path per line              written by the browser
/sleekmenu/history.txt      the last fifteen launches          written by the browser
/sleekmenu/cheats.txt       which cheats are on, per game      written by the browser
/sleekmenu/cheats/          your own .cht files (optional)     yours
/sleekmenu/art/             your own box art and text (optional)  yours

/ED64/CHEATS/               the Pro menu's cheat pack          the EverDrive's, read only
/ED64/gamedata/             saves                              shared with the EverDrive menu
/ED64/sysdata/registry.dat  which game is loaded, save type    shared with the EverDrive menu
```

Only the ROM is required. Without `catalog.ebc` the browser scans the card
and shows file names; without `covers.pak` it draws a placeholder. The ROMs
must be on the card itself: the catalog records each game's path relative to
the card root, spelled as the card spells it. Both the tool and the browser
skip the folders that hold no games — `ED64`, `sleekmenu`, `menu`,
`metadata`, `System Volume Information`, anything hidden — and the browser's
own `SleekMenu64.z64`. When every game is under one folder, the browser
opens inside it.

## What the browser writes

These, and nothing else:

- `sleekmenu/favorites.txt` when you press C-down on a game
- `sleekmenu/history.txt` when you launch a game
- `sleekmenu/cheats.txt` when you leave the cheats page
- `ED64/gamedata/<game>.<eep|srm|fla>` and `ED64/sysdata/registry.dat` — the
  save and the record the EverDrive menu reads, in its own names and format,
  so a game started from either menu finishes its save in the other

It never creates folders, never renames, moves or deletes a file, and never
touches the network. The prep tool creates the `sleekmenu/` folder and
writes `catalog.ebc` and `covers.pak` into it, and fetches
`release-metadata.zip` to the card root when the card has no collection;
everything else it reads in place.

## Where every field came from

`sleekmenu/catalog.json` is the catalog as the tool built it, kept legible
beside the packed one: the same games and fields, a `roms` key naming the
folder the games were taken from (empty for the whole card) so the next run
scans the same one without being told, plus for each game a
`sources` object naming, for the cover, the title, the description, the
genre, the publisher, the year and the players, which of the four sources
answered — `collection`, `collection (another region's box)`,
`collection (by game code)`, `libretro`, `libretro, modified`, `database`,
`file name`, `yours (this ROM)`, `yours (code NSME)`, `yours`, or `none` —
and `identified`: how the
database knew the dump (`crc`, `serial`, `serial without region`, or
nothing). The window's Catalog tab reads it; so does `make refresh`. The
browser never does: `catalog.ebc` carries the result and nothing about
where it came from. The words are fixed in `tools/provenance.py`.

## Where the games are looked for

The whole card, minus the folders known to hold no games: the browser's
own, the firmware's and any copy of it (`ED64.bk2` holds the firmware's apps
and 64DD IPLs, ROM-shaped files that are not games), `menu/`, `metadata/`,
`System Volume Information`, and anything hidden. The browser's own scan,
for a card with no catalog, uses the same rule (`src/catalog.c`,
`tools/card_layout.py`).

Or one folder, chosen: `--roms ROMS`, or the window's Games folder. Then
only it is walked, the catalog records paths from the card root as always
(`ROMS/...`), so the browser opens inside it, and the report counts and
names the ROM-shaped files elsewhere on the card that were left out. The
choice is kept in `catalog.json` and holds on the next run; `--roms .` or
an empty field is the whole card again. A chosen folder that does not
exist is an error; a remembered one that has gone is a note and the whole
card.

## How a game finds its box

By the four-character game code in the ROM's own header (bytes `0x3B`
to `0x3E`). The [n64-flashcart-menu-metadata](https://github.com/n64-tools/n64-flashcart-menu-metadata)
collection files everything under that code, one character per folder:

```text
metadata/N/G/E/E/boxart_front.png     GoldenEye, USA (NGEE)
metadata/N/G/E/E/metadata.ini         publisher, release date, players
metadata/N/G/E/description.txt        the box back, shared by every region
```

The tool looks for a box in this order: the cartridge's own region, the PAL
region for any PAL market, the region-neutral folder, then `E`, `P`, `J`,
then any other region the collection has. Because the code is the
cartridge's, a hack or a translation gets the box of the game it was built
on. A ROM with a blank or unprintable code — most homebrew — gets no box.

The collection can be on the card in any of these forms; the tool takes the
first it finds and never unpacks a zip. A card with none gets the zip
fetched to its root (`--no-download` forbids that; offline, the report says
where to get it):

```text
sleekmenu/release-metadata.zip    or    release-metadata.zip
sleekmenu/metadata/               or    metadata/
menu/metadata/                    the N64FlashcartMenu's own layout
ED64/metadata/                    the EverDrive-64 Pro menu's layout (edmeta)
```

`--metadata PATH` names a zip or folder anywhere else.

**A high-resolution box** comes before the collection and after your own
pictures. `--hires` fetches `Named_Boxarts/<No-Intro name>.png` from
libretro-thumbnails for every game code on the card the database knows,
into `sleekmenu/art/hires/<CODE>.png`, skipping what is there, and records
each in `sleekmenu/art/hires/downloads.json` (address, date, SHA-256).
That manifest is how the tool tells a box it fetched (`libretro`) from one
changed or put there by hand (`libretro, modified`), and the only record it
keeps: downloads write nothing outside `hires/`, so a re-fetch cannot touch
a picture of yours, and a `sleekmenu/art/NSME.png` of yours keeps beating a
fetched `hires/NSME.png`.

**Your own pictures** come before the collection. For `Hacks/Star Road.z64`
the tool looks for `Hacks/Star Road.png` (or `.jpg`) beside the ROM, then
`sleekmenu/art/Star Road.png`, then `sleekmenu/art/<game code>.png`, which
replaces the collection's box for every ROM with that code. A per-ROM
picture becomes a sprite named after a hash of the ROM's path, so two
games of one name in two folders never share one; a code override takes the
collection's sprite name for that code. `Star Road.txt` in either place, or
`NSME.txt` in `sleekmenu/art/`, is the description, and a first line
`Title: ...` the title (`tools/custom_art.py`).

The window's catalog tab writes these same files and no others: Save copies
the chosen picture as it is into `sleekmenu/art/` under the ROM's name or
its code and writes the `.txt` beside it; Remove my edit deletes the files
in `sleekmenu/art/` the selected game uses, never one beside a ROM, which it
only names. The two sizes a picture becomes are made at the next Prepare,
so nothing is stored twice and a better picture later is one file to
replace.

## How a game finds its text

By the CRC pair in the ROM's header, in `data/coverdb.csv` (shipped inside
the tool):

```text
crc,serial,name,genre,publisher,year,players,regions
635A2BFF8B022326,NSME,Super Mario 64 (USA),Platform,Nintendo,1996,1,USA
```

The CRC identifies the dump itself, whatever the file is named. A dump the
database does not know is looked up by its game code next, then by the code
without its region letter (for translations that changed it). When two
different games share a code, neither is used. The collection's
`metadata.ini` fills in what the database leaves blank, and its
`description.txt` supplies the paragraph on the launch card.

## Covers

`tools/make_sprite.py` writes libdragon's sprite format directly from the
collection's PNGs; no toolchain is involved. Covers are fitted, not
stretched, so tall Japanese boxes keep their proportions on the 96x72
thumbnail. Sprites are named after the box's game code, so a game present in
several folders costs one picture. A 3,400-game library comes to about 700
sprites and 10 MB.

The covers go into one `covers.pak` rather than a folder of files because
opening a file by name on a FAT card means walking the folder from the start,
and with long file names that is slow. `--loose-covers` writes the folder
form instead, which is handier when debugging a card.

`covers-large.pak` is the same plan at 256x180 -- the same names, from the
same pictures, one decode for both sizes -- for the box view the browser
opens with A on a game's details. A picture larger than the canvas (a
libretro box, one of yours) is fitted to it; the collection's 158x112 scan
is centred at its own size, never enlarged. About 90 KB a cover, so 700
covers are 64 MB; `--no-large-covers` skips it, and the browser then doubles
the thumbnail in the view and says so. The browser opens the pack beside
the first at startup and reads one sprite when the view opens, freed when
it closes.

## Step by step, from a checkout

The `.pyz` does all of this in one go. The same steps, one at a time:

```sh
make card-art ROMS_ROOT=/Volumes/CARD/ROMS METADATA=release-metadata.zip
make metadata ROMS_ROOT=/Volumes/CARD/ROMS CARD=/Volumes/CARD METADATA=release-metadata.zip
```

Then copy `build/sd/sleekmenu/covers.pak` and `build/catalog.ebc` to
`sleekmenu/` on the card. `CARD` matters: without it the catalog records
paths relative to the ROM folder instead of the card, and every launch fails
unless the library happens to be at the card root.
