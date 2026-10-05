# The card

Everything SleekMenu 64 reads or writes on the SD card, and how a game is
matched to its box art and its description. The README has the short version;
this is the reference.

## Layout

```text
/SleekMenu64.z64            the browser                        you copy it
/sleekmenu-catalog-manager.pyz
                            the tool, for a terminal           you copy it, if you use it
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
/sleekmenu/cheats/libretro/ cheat codes, one file per dump     fetched by the tool (--cheats)
/sleekmenu/theme.txt        the browser's theme, one word      written by the browser or the tool
/sleekmenu/art/             your own box art and text (optional)  yours

/ED64/autoexec.v64          a copy of the browser (X7, optional)  written by the tool (--direct-boot)
/ED64/CHEATS/               the Pro menu's cheat pack          the EverDrive's, read only
/ED64/gamedata/             saves                              shared with the EverDrive menu
/ED64/sysdata/registry.dat  which game is loaded, save type    shared with the EverDrive menu
```

Only the ROM is required. Without `catalog.ebc` the browser scans the card
and shows file names; without `covers.pak` it draws a placeholder. The ROMs
must be on the card itself: the catalog records each game's path relative to
the card root, spelled as the card spells it -- an accented name with its
accents composed, as the card stores it, even on a Mac, which lists them
decomposed. Both the tool and the browser
skip the folders that hold no games — `ED64`, `sleekmenu`, `menu`,
`metadata`, `System Volume Information`, anything hidden — and the browser's
own `SleekMenu64.z64`. When every game is under one folder, the browser
opens inside it.

## What the browser writes

These, and nothing else:

- `sleekmenu/favorites.txt` when you press C-down on a game
- `sleekmenu/history.txt` when you launch a game
- `sleekmenu/cheats.txt` when you leave the cheats page
- `sleekmenu/theme.txt` when you leave the filter page having changed the
  theme
- `ED64/gamedata/<game>.<eep|srm|fla>` and `ED64/sysdata/registry.dat` — the
  save and the record the EverDrive menu reads, in its own names and format,
  so a game started from either menu finishes its save in the other

It never creates folders, never renames, moves or deletes a file, and never
touches the network. The Game Catalog Manager creates the `sleekmenu/`
folder and writes `catalog.ebc` and `covers.pak` into it, and fetches
`release-metadata.zip` to the card root when the card has no collection;
everything else it reads in place. One file of the tool's lives outside
`sleekmenu/`, and only when asked for: `ED64/autoexec.v64`, below.

## The theme

`sleekmenu/theme.txt` holds the id of one of the themes built into the
browser, as its first word: `midnight`, `charcoal`, `jungle`, `grape`,
`fire` or `ice`. The browser reads the file once as it starts, without
regard to case, and uses Midnight when the file is missing, empty, or names
a theme that ROM does not have, so a card prepared by a newer tool still
starts on an older browser. The browser writes the file when the theme is
changed on its filter page, the tool when one is chosen there; a card that
never chose has none.

## Starting in the browser

An EverDrive-64 X7's stock OS starts `ED64/autoexec.v64` by itself at
power-on when the file is there. `--direct-boot on`, or the switch on the
window's Card tab, copies the card's `SleekMenu64.z64` to that name, byte
for byte; `off` removes it. The tool offers this only where it can work and
do no harm (`tools/direct_boot.py`): `ED64/OS64.v64` must be on the card and
carry that file name inside it, which is how an OS with the feature is told
from one without, whatever its version; and an `autoexec.v64` that is not
the browser (its header title says) is another program's and is never
overwritten or removed. A run told nothing leaves the switch where it is,
and copies the browser again when the one at the root has been replaced. A
card for the EverDrive-64 Pro has no `OS64.v64` and no such file.

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
nothing). Each game also carries `file` -- the ROM's size, its modification
time and the 64 header bytes read from it -- and `checksum`, the verdict
of the checksum pass, so the next run opens only the files that changed;
`sprites` names what each sprite was made from (a zip entry's CRC and
size, or a file's size and time, with the converter's format), so a
picture unchanged since is not converted again, and `packs` records the
size and digest of each pack written, so a pack that would come out the
same is not written again. A `set_aside` list names the ROM-shaped files the tool found
in the games folder and refused, with the reason (`not a ROM: no N64
header` -- a 64DD IPL dump, a broken download), so the window can say so
rather than count them as games still to add. The window's Games tab
reads it; so does `make refresh`. The browser never does: `catalog.ebc`
carries the result and nothing about where it came from -- except the
set-asides, which it carries as records with a flag (`SM_FLAG_SET_ASIDE`,
`src/catalog.h`) so that the browser knows those files when it reads a
folder and never lists them. The words are fixed in `tools/provenance.py`.

## Where the games are looked for

The whole card, minus the folders known to hold no games: the browser's
own, the firmware's and any copy of it (`ED64.bk2` holds the firmware's apps
and 64DD IPLs, ROM-shaped files that are not games), `menu/`, `metadata/`,
`System Volume Information`, and anything hidden. The browser's own scans
use the same rule (`src/folder_scan.c`, `tools/card_layout.py`): the
whole card at boot when there is no catalog, and otherwise the folder being
browsed, read for the games the catalog does not have yet. Those are listed
by file name and play; the next run of the tool gives them their box and
facts. The window's Card tab counts them as "added since the last update".

Or one folder, chosen: `--roms ROMS`, or Where the games are on the
window's Card tab. Then
only it is walked, the catalog records paths from the card root as always
(`ROMS/...`), so the browser opens inside it, and the report counts and
names the ROM-shaped files elsewhere on the card that were left out. The
choice is kept in `catalog.json` and holds on the next run; `--roms .` or
`/` there is the whole card again. A chosen folder that does not
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
each in `sleekmenu/art/hires/downloads.json` (address, date, SHA-256). A
revision that libretro files as a link to its game's box gets that box,
and a name with no picture behind it gives way to the code's next name.
That manifest is how the tool tells a box it fetched (`libretro`) from one
changed or put there by hand (`libretro, modified`), and the only record it
keeps: downloads write nothing outside `hires/`, so a re-fetch cannot touch
a picture of yours, and a `sleekmenu/art/NSME.png` of yours keeps beating a
fetched `hires/NSME.png`. It also lists the codes libretro had no box for
(`missing`, with the date), so a run that keeps the set complete does not
ask about them again; `--hires` asked explicitly does. A card whose
manifest exists keeps its boxes complete on every run: the games added
since get theirs without the choice being repeated.

**Your own pictures** come before the collection. For `Hacks/Star Road.z64`
the tool looks for `Hacks/Star Road.png` (or `.jpg`) beside the ROM, then
`sleekmenu/art/Star Road.png`, then `sleekmenu/art/<game code>.png`, which
replaces the collection's box for every ROM with that code. A per-ROM
picture becomes a sprite named after a hash of the ROM's path, so two
games of one name in two folders never share one; a code override takes the
collection's sprite name for that code. `Star Road.txt` in either place, or
`NSME.txt` in `sleekmenu/art/`, is the description, and a first line
`Title: ...` the title (`tools/custom_art.py`).

The window's Games tab writes these same files and no others: Save copies
the chosen picture as it is into `sleekmenu/art/` under the ROM's name or
its code and writes the `.txt` beside it; Undo my changes deletes the files
in `sleekmenu/art/` the selected game uses, never one beside a ROM, which it
only names. The two sizes a picture becomes are made at the next update,
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

Your own text wins over both: `<ROM name>.txt` beside the ROM or in
`sleekmenu/art/`, or `<CODE>.txt` there. Header lines at the top --
`Title:`, `Genre:`, `Publisher:`, `Year:`, `Players:`, `Regions:` -- each
set that one field, checked the way the catalog checks it (a year in
1970..2100, players 1..8, regions from USA, Japan and Europe under the
usual spellings), and the first line that is not a header starts the
description. The window's Games tab writes this same file
(`tools/custom_art.py`), and reads it back to show the edit as the next
update will catalog it.

## How a game finds its cheats

In this order, the first that has a file:

```text
sleekmenu/cheats/Star Road.cht              yours: named like the ROM file
ED64/CHEATS/Super Mario 64 (U).cht          the EverDrive's pack, when its file's region tag
                                            agrees with the cartridge
sleekmenu/cheats/libretro/635A2BFF8B022326.cht   fetched: the dump's own
ED64/CHEATS/Some Game.cht                   the pack again, when it can only guess: a file with
                                            no region tag, the Europe file for a French cartridge
```

A fetched file is named by the two checksum words in the ROM's header
(0x10 to 0x17), sixteen hex digits, which is the key `data/coverdb.csv`
knows a dump by: `--cheats` fetches
`cht/Nintendo - Nintendo 64/<No-Intro name>.cht` from libretro-database for
every ROM on the card whose checksum the database has, skipping what is
there, and records each in `sleekmenu/cheats/libretro/downloads.json`
(name, address, date, SHA-256) with the dumps libretro had no file for and
whether the card still wants them (`tools/cheat_codes.py`). A hack has
another checksum and gets none. The browser reads the first 96 KB of a
file and its first 256 codes; libretro's per-dump files run from a few
codes to thousands, which is why the pack's shorter list is preferred
where the pack is sure of the game.

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
