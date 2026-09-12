# SleekMenu 64

A game browser for the EverDrive-64. It is an ordinary N64 ROM that you start
from the EverDrive's own menu: it shows your library with box art, genres,
descriptions and filters, and boots the game you pick. The EverDrive's menu
stays where it is — SleekMenu sits beside it on the card, and a reset or a
power cycle brings the stock menu back.

Works on the EverDrive-64 X7 and the EverDrive-64 Pro with one and the same
ROM. Saves go to the same `ED64/gamedata/` folder the stock menu uses, so a
game started from either menu carries its save into the other.

```
┌──────────────────────────────────────────┐
│ ALL  FAV  HIS  ACT  ADV  PLT  RPG  RAC ▸ │
├──────────────────────────────────────────┤
│  ▸ Racing/                               │
│  ▸ RPG/                                  │
│    Blast Corps (USA)             Action  │
│  ▶ Super Mario 64 (USA)       Platforms  │
│    Wave Race 64 (USA)            Racing  │
└──────────────────────────────────────────┘
```

## What you need

- An EverDrive-64 X7 (OS 3.11) or an EverDrive-64 Pro, with your ROMs in a
  `ROMS` folder on the card, in any sub-folders you like.
- A computer with Python 3.9 or newer and [Pillow](https://python-pillow.org/)
  (`pip install Pillow`) to prepare the card. No compiler, no toolchain.

## Install

**1. Get the two release files** from this project's releases page:

- `SleekMenu64.z64` — the browser
- `sleekmenu-prep.pyz` — the tool that builds the catalog and the covers

**2. Get the box art and descriptions.** Download `release-metadata.zip` from
the [n64-flashcart-menu-metadata releases](https://github.com/n64-tools/n64-flashcart-menu-metadata/releases).
It is a public-domain collection of box scans and descriptions for every
cartridge, shared with other N64 menus. SleekMenu ships none of it and never
downloads anything itself.

**3. Copy the three files to the root of the card**, next to `ROMS`:

```text
/SleekMenu64.z64
/sleekmenu-prep.pyz
/release-metadata.zip
/ROMS/...
```

**4. Run the tool from the card.** It takes no arguments; running it from the
card is how it knows where the card is.

```sh
cd /Volumes/CARD          # or wherever the card is mounted
python3 sleekmenu-prep.pyz
```

It reads every ROM, matches each one to its box and description, and writes
`sleekmenu/catalog.ebc` and `sleekmenu/covers.pak` beside itself. A card of
three thousand games takes under a minute. Run it again whenever you add
games.

**5. Eject the card, put it in the cart, and start `SleekMenu64.z64` from the
EverDrive menu.** Press A on a game for its details, Start to play. To get
back to the EverDrive menu, reset the console.

What the tool writes, and what it leaves alone:

```text
/sleekmenu/catalog.ebc     titles, genre, publisher, year, descriptions
/sleekmenu/covers.pak      every cover in one file
/sleekmenu/favorites.txt   written by the browser as you star games
/sleekmenu/history.txt     the last fifteen games you launched
/sleekmenu/cheats.txt      which cheats are on, per game
/ED64/gamedata/            saves, shared with the EverDrive menu — never touched
```

Both the catalog and the covers are optional: with no catalog the browser
scans the card and shows filenames, with no covers it draws a placeholder.
The tool never moves, renames or deletes anything on the card.

## Controls

| Control | Browsing | Launch details |
|---|---|---|
| D-pad / stick | Move | — |
| A | Open a folder, or a game's details | — |
| B | Parent folder | Back to the list |
| Start | — | Play |
| C-left / C-right | Previous / next genre tab | — |
| C-up | List, grid or coverflow view | Fast or verified load |
| C-down | Favourite | Cheats |
| L / R | Page up / down | — |
| Z | Filters (genre, region, players, publisher, year, favourites) | Diagnostics |

The first two tabs, **FAV** and **HIS**, are your favourites and the last
fifteen games you played.

## Good to know

- **Saves.** Written to `ED64/gamedata/` under the EverDrive's own file names.
  On the X7 the save is moved to the card the next time a menu boots. On the
  Pro the cartridge handles saves itself and the stock menu writes them out
  at its next boot — so after playing from SleekMenu, let the EverDrive menu
  boot once before pulling the card.
- **ROM formats.** `.z64` and `.v64` (byteswapped) dumps load; `.n64`
  word-swapped dumps are listed but refused, convert them to `.z64`. Size
  limit: 64 MiB on the X7, 126 MiB on the Pro.
- **64DD on the Pro.** `.ndd` disk images are listed like games. Selected on
  their own they boot from the drive's IPL, which the Pro's menu keeps in
  `ED64/64ddipl/`; a `.ndd` in the same folder as a cartridge ROM is attached
  to that ROM as its expansion disk. Experimental: not yet run on hardware.
- **Not done yet.** Controller Pak (`.mpk`) backup and restore.

## Cheats

GameShark codes, from the cheat pack the EverDrive-64 Pro's menu ships in
`ED64/CHEATS/` (one `.cht` file per game). If that folder is on your card,
there is nothing to set up.

**To use them:** open a game's details, press C-down, tick the codes you
want, press B. Your choices are remembered per game in
`sleekmenu/cheats.txt`. Cheats need an Expansion Pak.

**Which file a game gets.** The pack names its files with short region tags
— `F-Zero X (U).cht`, `F-Zero X (E).cht` — while ROMs are usually named
`F-Zero X (USA).z64`. SleekMenu matches on the game's name and on the
region written inside the ROM, so a USA cartridge gets the `(U)` file and
never European codes. The cheats page shows the file it picked, and warns
when it had to guess.

**When there is nothing to tick:**

- *"Cheat pack has this game for Europe, Japan; yours is USA"* — the pack
  has no file for your region. Codes from another region point at the wrong
  memory addresses and do nothing, so they are not offered.
- *"Not in the cheat pack"* — the pack has files for some 540 games, most
  of the well-known ones, far from all.
- *"WILL NOT RUN"* in red on the card — the console has no Expansion Pak, or
  the game's boot code is not the retail one (hacks, homebrew). The cheats
  page says which.

**Your own codes.** Put a `.cht` file in `sleekmenu/cheats/`, named exactly
like the ROM file (`Super Mario 64 (USA).cht` for `Super Mario 64 (USA).z64`).
It is used instead of the pack. The format is the pack's own; a cheat made
of several lines of code joins them with `;`:

```text
cheats = 2
cheat0_desc = "Infinite Lives"
cheat0_code = "8033B21D 0064"
cheat1_desc = "99 Coins"
cheat1_code = "8133B218 0063"
```

## Building from source

Needs a [libdragon](https://github.com/DragonMinded/libdragon) toolchain.

```sh
make test                                   # host-side tests, no hardware needed
make slim N64_INST=/path/to/libdragon       # build/release/SleekMenu64.z64
make prep                                   # build/release/sleekmenu-prep.pyz
```

`make help` lists the rest. More detail, for the curious:

- [docs/DESIGN.md](docs/DESIGN.md) — how art and metadata are matched, how the
  database is maintained, how the browser works
- [docs/CARD_LAYOUT.md](docs/CARD_LAYOUT.md) — everything on the card, and the
  step-by-step form of the prep tool
- [docs/catalog-format.md](docs/catalog-format.md) — the catalog's binary
  format
- [docs/rejected-approaches.md](docs/rejected-approaches.md) — what was tried
  and dropped, and why
- [docs/sd-forensics/](docs/sd-forensics/) — how the EverDrive's save
  registry format was worked out

## Licence

AGPL-3.0-only. The boot handoff is vendored from
[N64FlashcartMenu](https://github.com/Polprzewodnikowy/N64FlashcartMenu)
(AGPL), the EverDrive-64 Pro cartridge library from
[krikzz](https://github.com/krikzz/ed64-pro-pub) (MIT) and the interface
font is [Spleen](https://github.com/fcambus/spleen) (BSD-2-Clause); `data/`
is CC BY-SA 4.0 and `src/rom_db.c` is ISC. No box art is included.
[NOTICE.md](NOTICE.md) has the full map.
