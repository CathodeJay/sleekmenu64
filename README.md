<p align="center">
  <img src="docs/banner.png" alt="SleekMenu 64: a game browser for EverDrive-64">
</p>
<p align="center">
  <a href="https://www.buymeacoffee.com/CathodeJay"><img src="https://img.shields.io/badge/-buy_me_a%C2%A0coffee-gray?logo=buy-me-a-coffee" alt="Buy Me A Coffee"></a>
</p>

---

A game browser for the EverDrive-64 X7 and Pro: box art, genres,
descriptions and filters for your N64 library, and the game you pick boots
straight from it. It is an ordinary ROM on the card, started from the
EverDrive's own menu, which stays where it is; saves go to the same
`ED64/gamedata/` folder, so a game carries its save between the two menus.
On an X7 the console can start straight in it.

![The list view, in the Grape theme: the genre tabs across the top, the games on the left, and on the right the selected game's box, year, publisher, genre, region, save type, accessories and size; the buttons and what they do along the bottom](docs/screenshots/list.png)

## Install

You need an EverDrive-64 X7 (OS 3.11) or Pro with your ROMs on the card, in
any folders you like, and a Mac, a Windows PC or a Linux computer. Nothing
to install.

**1. Download two files** from the
[releases page](https://github.com/CathodeJay/sleekmenu64/releases/latest):
`SleekMenu64.z64` and the prep GUI for your computer.

| Your computer | The prep GUI |
|---|---|
| Mac with Apple silicon (M1 and later) | `SleekMenu-Prep-mac-arm64.zip` |
| Mac with an Intel processor | `SleekMenu-Prep-mac-intel.zip` |
| Windows | `SleekMenu-Prep-windows.exe` |
| Linux | `SleekMenu-Prep-linux` |

**2. Copy `SleekMenu64.z64` to the root of the card.**

**3. Open the prep GUI.** On a Mac, unzip it first. It is not code-signed,
so the first launch warns. On macOS 15 and later, open it once, then press
Open Anyway in System Settings → Privacy & Security (earlier macOS:
right-click → Open). On Windows: More info → Run anyway. On Linux:
`chmod +x SleekMenu-Prep-linux` first.

**4. Set up the card.** It is picked for you when it is the only removable
disk. Press **Set up card**: it fetches a box and a description for each of
your games onto the card, then writes the catalog. Up to about 330 MB for a
complete library, once; you can stop and carry on later.

**5. Put the card back in the cart and start `SleekMenu64.z64` from the
EverDrive menu.** Start plays a game,
A shows its details; reset the console to get back to the EverDrive menu.

**Adding games later:** copy them on, open the prep GUI, press **Update
card**. Only what changed is read and only the new games' boxes are
fetched. Until then a new game still shows up and plays, just without its
box.

**Starting the console in SleekMenu:** an X7 can power on straight into
it; see [below](#starting-the-console-in-sleekmenu-x7-only).

**Themes:** the browser comes in six sets of colours: Midnight, Charcoal,
Jungle, Grape, Fire and Ice. Change it on the console (Z, then the THEME
row) or under **Console** on the prep GUI's Card tab.

The prep GUI also shows your card the way the console will, and lets you
give any game your own picture, description or facts; see
[docs/PREP.md](docs/PREP.md).

![The prep GUI's Games tab: the card's games on the left; on the right the selected game's box, its title, genre, publisher, year, players and region in fields, and its description in a box below](docs/screenshots/tool.png)

Descriptions come from the
community-maintained
[n64-flashcart-menu-metadata](https://github.com/n64-tools/n64-flashcart-menu-metadata)
collection, boxes from
[libretro-thumbnails](https://github.com/libretro-thumbnails/Nintendo_-_Nintendo_64)
and, when you ask for them, cheat codes from
[libretro-database](https://github.com/libretro/libretro-database);
SleekMenu ships none of them.

## Using it

| Control | Browsing | A game's details |
|---|---|---|
| D-pad / stick | Move; hold to keep moving, faster the longer you hold | Scroll the description |
| A | Open a folder, or a game's details | The box, full screen |
| B | Parent folder | Back to the list |
| Start | Play | Play |
| C-left / C-right | Previous / next genre tab | — |
| C-up | List, grid or coverflow | Fast or verified load |
| C-down | Favourite | Cheats |
| L / R | Page up / down (coverflow: previous / next letter) | — |
| Z | Filters and theme | Diagnostics |

The bar along the bottom of every screen says what the buttons do there,
each button drawn in its own colour: a blue A, a green B, a red Start, the
yellow C buttons with their arrow.

The first two tabs are your favourites and the last fifteen games you
played. The **grid** shows twelve covers at a time; **coverflow** shows one
face on, with the facts, the start of the description and a strip of
initials under the shelf.

![The grid view, in the Fire theme: twelve box covers, the selected one framed, its title in the bar below](docs/screenshots/grid.png)

![Coverflow, in the Ice theme: the selected box face on with the shelf receding on both sides; under it the title, the facts, the start of the description and a strip of initials](docs/screenshots/coverflow.png)

![The details: the box on the left; the title, year, publisher, genre, region, players, save type, cheats, size and needed accessories beside it; the description below, and the buttons under it](docs/screenshots/detail.png)

## Starting the console in SleekMenu (X7 only)

An EverDrive-64 X7 can power on straight into SleekMenu, without a stop in
the EverDrive menu. The X7's OS starts a file named `autoexec.v64` in the
card's `ED64` folder by itself when there is one, so SleekMenu only has to
be that file. Two ways to put it there:

- **By hand:** copy `SleekMenu64.z64` into the card's `ED64` folder and
  rename the copy `autoexec.v64`. Only the name changes; nothing is
  converted. Do it again when you install a newer SleekMenu.
- **With the prep GUI:** tick **Start the console in SleekMenu** on the
  Card tab and press Update card. It makes the same copy and keeps it up to
  date when you replace `SleekMenu64.z64`.

From then on the console powers on in SleekMenu. A reset inside a game
returns to the EverDrive menu, where `SleekMenu64.z64` is still at the card
root to start again. To go back, delete `ED64/autoexec.v64`, or untick the
box and update. It needs a recent X7 OS; 3.11 has it.

**The EverDrive-64 Pro cannot do this.** Its menu is part of the
cartridge's firmware and has no start-up file, so on a Pro SleekMenu is
always started from the EverDrive menu. More in
[docs/CONSOLE.md](docs/CONSOLE.md#starting-the-console-in-sleekmenu).

## Good to know

- **On the Pro,** let the EverDrive menu boot once after playing before you
  pull the card: that is when the stock menu writes the save out.
- **Hacks** that black-screen on a console because of a stale header
  checksum are fixed as they launch.
- **Cheats** come from the EverDrive-64 Pro's cheat pack in `ED64/CHEATS/`,
  or from libretro when you tick **Fetch cheat codes** on the prep GUI's
  Card tab, and need an Expansion Pak.
- **`.z64` and `.v64`** dumps load; `.n64` ones do not — convert them first.

Everything else about the console — the screens, saves, the clock, 64DD,
cheats in detail — is in [docs/CONSOLE.md](docs/CONSOLE.md).

## More

- [docs/PREP.md](docs/PREP.md) — the prep GUI in full, your own art and
  text, high-resolution boxes, cheat codes, and the command line
- [docs/CONSOLE.md](docs/CONSOLE.md) — using SleekMenu on the console
- [docs/CARD_LAYOUT.md](docs/CARD_LAYOUT.md) — every file on the card
- [docs/DESIGN.md](docs/DESIGN.md) — how it is put together and why
- [CHANGELOG.md](CHANGELOG.md) — what changed in each release

## Building from source

Needs a [libdragon](https://github.com/DragonMinded/libdragon) toolchain.

```sh
make test                                   # host-side tests, no hardware needed
make slim N64_INST=/path/to/libdragon       # build/release/SleekMenu64.z64
make prep                                   # build/release/sleekmenu-prep.pyz
make perf N64_INST=/path/to/libdragon       # the ROM with a frame-time readout
```

`make help` lists the rest.

## Support

SleekMenu 64 is free. If it earned a place on your card and you would like
to support its development, you can
[buy me a coffee](https://buymeacoffee.com/CathodeJay).

## AI

Yes, this project was built with AI tools.

## Licence

AGPL-3.0-only. The boot handoff is vendored from
[N64FlashcartMenu](https://github.com/Polprzewodnikowy/N64FlashcartMenu)
(AGPL), the EverDrive-64 Pro cartridge library from
[krikzz](https://github.com/krikzz/ed64-pro-pub) (MIT) and the interface
font is [Spleen](https://github.com/fcambus/spleen) (BSD-2-Clause); `data/`
is CC BY-SA 4.0 and `src/rom_db.c` is ISC. No box art is included.
[NOTICE.md](NOTICE.md) has the full map.
