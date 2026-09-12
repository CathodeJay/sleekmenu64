# What goes on the card

SleekMenu 64 is one small ROM plus two folders it reads at runtime. Nothing
here is baked into the binary, so art and metadata can be replaced without
rebuilding anything.

    /SleekMenu64.z64              the browser, about 370 KB
    /release-metadata.zip         the metadata collection, read in place
    /ROMS/...                      your library, in whatever folders you like
    /sleekmenu/catalog.ebc        genre, publisher, year, players, descriptions
    /sleekmenu/covers.pak         box art, 96x72, every picture in one file
    /sleekmenu/favorites.txt      written by the browser; one ROM path a line
    /sleekmenu/history.txt        the last fifteen launches, most recent first
    /sleekmenu/cheats.txt         which cheats are on, one [ROM path] section a game
    /sleekmenu/cheats/            your own .cht files, named after the ROM (optional)
    /ED64/CHEATS/                  the Pro firmware's cheat database, read as it is (listed once at startup)
    /ED64/gamedata/                saves, shared with the stock firmware

Covers ship as a single `covers.pak` rather than a directory of sprites:
FatFs has no directory index, so opening a cover by name walks the directory
from the start, and with names this long that is over 100 KB of walking per
picture. `--loose-covers` writes the old directory form instead, which is
easier to poke at while debugging a card.

The catalog and the covers are both optional. Without a catalog the browser
scans the card and shows titles only; without covers it draws a placeholder.
Neither is an error and neither needs a different build. `favorites.txt` is
written by the browser itself when C-down is pressed -- the catalog's own
favourite flag seeds it the first time and is history afterwards, so a
favourite set on the console survives rebuilding the catalog.

## One command

    cd /Volumes/YOURCARD
    python3 sleekmenu-prep.pyz

With the tool on the card next to ROMS and the collection's zip, that is all
of it: it finds the card by where it is running from, finds every game's box
and description in the collection, and writes `sleekmenu/`. Python 3.9+ and
Pillow; no network, ever. `--metadata PATH` names a zip or folder elsewhere,
`--dry-run` writes nothing. From a checkout, `python3 tools/prepare_card.py
--card ... --roms ... --metadata ...` is the same pipeline.

The ROM folder has to be on the card. The catalog records where each game lives
relative to the card root -- the browser resolves those as `sd:/ROMS/<path>` and
then `sd:/<path>` -- and it cannot reach anything outside the card.

## How a ROM finds its cover

By the four-character game code in its own header, bytes `0x3B..0x3E`, in the
[n64-flashcart-menu-metadata](https://github.com/n64-tools/n64-flashcart-menu-metadata)
collection, which files everything under that code one character per folder:

    metadata/N/G/E/E/boxart_front.png     GoldenEye, USA
    metadata/N/G/E/E/metadata.ini         publisher, release date, players
    metadata/N/G/E/description.txt        the box back, shared by every region

Looked up in this order: the cartridge's own region folder (and the PAL one,
for any PAL market), then the region-neutral three-character folder, then
`E`, `P`, `J`, then whatever other region the collection has. A hack or a
translation keeps the code of the cartridge it was built on and gets the same
box, which no CRC or filename match could manage. A blank or unprintable code
-- most homebrew -- is never looked up.

The tool reads the collection wherever it finds it, in this order:
`sleekmenu/release-metadata.zip`, `release-metadata.zip`,
`sleekmenu/metadata/`, `metadata/`, `menu/metadata/` (the N64FlashcartMenu's
own layout), `ED64/metadata/` (the EverDrive-64 Pro's, as krikzz's edmeta
converter writes it: same files, pictures pre-stretched to double width for
the Pro menu's 640-pixel mode, read back at half width). The zip is read in
place and never unpacked onto the card.

## How a ROM finds its text

By the CRC pair in its own header, via `data/coverdb.csv`:

    crc,serial,name,genre,publisher,year,players,regions
    635A2BFF8B022326,NSME,Super Mario 64 (USA),Platform,Nintendo,1996,1,USA

That key is what the dump *is*, not what somebody named the file, so a ROM
renamed `0421 - stuff [!].z64` still finds its row. A dump the database has
never seen is looked up by `serial` next -- the same product code the boxes
are filed under -- and then by the code without its region letter, for a
translation that rewrote the region byte. Where two different games share a
code neither is used; guessing is worse than a blank.

The collection's `metadata.ini` fills in whatever the database left blank --
publisher, year, players -- and `description.txt` supplies the launch card's
paragraph. Nothing is ever matched by name.

## Art

`tools/make_sprite.py` writes libdragon's sprite container directly from the
collection's bytes, and the test suite checks its output byte-for-byte against
the real `mksprite`, so no toolchain is involved and nothing is unpacked.

Covers are fitted rather than stretched, so portrait Japanese packaging keeps
its proportions on a 96x72 matte. Sprites are named after the **box** -- its
game code, `NSME.sprite` -- not the ROM, so a game kept in a genre folder, two
"best of" folders and a hacks folder points four catalog entries at one file.
On a 3400-game library that is about 700 sprites and 10 MB.

## One step at a time, if you prefer

    make card-art ROMS_ROOT=... METADATA=release-metadata.zip     boxes to sprites
    make metadata ROMS_ROOT=... CARD=... METADATA=release-metadata.zip

`CARD` is not cosmetic: leave it out and catalog paths are recorded against the
ROM folder instead of the card, which resolves for a library at `/ROMS` or at
the card root and silently fails every launch anywhere else.

Copy `build/sd/sleekmenu/covers.pak` to the card as `sleekmenu/covers.pak` and
`build/catalog.ebc` as `sleekmenu/catalog.ebc`.

## Browsing speed

Art on the card is slower to reach than art inside the ROM was, so the browser
does not touch the card while the cursor is moving. A cover and the highlighted
game's save type are read a tenth of a second after you stop; the grid scrolls
a row at a time and keeps the covers already on screen. Holding a direction
costs nothing at all.

## Building the ROM

    make slim N64_INST=/path/to/libdragon-install

About 370 KB, because the only asset inside it is the 5x8 font. Art comes off
the card.
