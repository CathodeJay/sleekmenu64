# The card

Everything SleekMenu 64 reads or writes on the SD card, and how a game is
matched to its box art and its description. The README has the short version;
this is the reference.

## Layout

```text
/SleekMenu64.z64            the browser                        you copy it
/sleekmenu-prep.pyz         the card-preparation tool          you copy it
/release-metadata.zip       box art and descriptions           you download it
/ROMS/...                   your games, in any folders          yours
/<any other folder>/...     or anywhere else on the card        yours

/sleekmenu/catalog.ebc      titles, genre, publisher, year     written by the tool
/sleekmenu/covers.pak       every cover, one file              written by the tool
/sleekmenu/favorites.txt    one ROM path per line              written by the browser
/sleekmenu/history.txt      the last fifteen launches          written by the browser
/sleekmenu/cheats.txt       which cheats are on, per game      written by the browser
/sleekmenu/cheats/          your own .cht files (optional)     yours

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
writes `catalog.ebc` and `covers.pak` into it; everything else it reads in
place.

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
first it finds and never unpacks a zip:

```text
sleekmenu/release-metadata.zip    or    release-metadata.zip
sleekmenu/metadata/               or    metadata/
menu/metadata/                    the N64FlashcartMenu's own layout
ED64/metadata/                    the EverDrive-64 Pro menu's layout (edmeta)
```

`--metadata PATH` names a zip or folder anywhere else.

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
