# Changelog

## 2.0.0

**Upgrading from 1.2:** copy the new `SleekMenu64.z64` over the old one at
the root of the card, download the new prep GUI, and press **Update card**
once. Your catalog, boxes and edits are kept.

### The prep GUI

- One button. **Set up card** the first time and **Update card** after do
  the whole job in one run: read the games, fetch what the card lacks,
  build the catalog and the covers, write them. Four steps show where it
  is; Stop ends it and the next run carries on from there. There is no
  separate download to press first.
- Sharp boxes by default: a 512-pixel box is fetched for every game the
  database knows, and a card keeps them complete as games are added.
- The **Games** tab shows the card as the console will and is where a game
  is changed: its box as the console draws it, and its title, genre,
  publisher, year, players, region and description in fields you type in.
  Only what you change is written; Save puts it on the card at once, and
  Undo my changes brings the original back.
- **Change box…** offers the boxes libretro has for the game, one per
  region, or a picture of your own; a PNG or JPEG can also be dropped
  straight onto the box. One tick applies an edit to every version of the
  game on the card.
- **Fetch cheat codes**, on the Options tab: libretro's cheat file for the
  exact dump of each game, for the many games the EverDrive's cheat pack
  does not cover. Off until you tick it; the card remembers.
- **Start the console in SleekMenu**, on the Options tab for an
  EverDrive-64 X7 card: the console powers on in SleekMenu. A reset inside
  a game returns to the EverDrive menu; untick to go back. The
  EverDrive-64 Pro has no such start-up file, so the switch is not shown
  for its cards.
- The options and the run's report are on tabs of their own, and the
  window reads the card again when you come back to it.
- A **Buy me a coffee** link in the top right corner.

### On the console

- Cheats: a game the EverDrive's cheat pack has no file for, or none for
  the cartridge's region, uses the file the prep GUI fetched for it.

### Fixes

- Boxes were missing for the revisions libretro files as a link to their
  game's box (Castlevania Rev 1 is one of about 130). The link is followed;
  a card that recorded those as missing asks again by itself.
- With one games folder chosen, an edited game went on saying "Edit
  waiting" after it was on the card.
- A description of your own longer than the catalog allows stopped the
  update. It is cut at a word.
- An edit that changed only a game's regions was not shown as yours.
- A collection zip cut short on the card stopped every run; it is fetched
  again.
- The database had eight publishers spelled with a no-break space, and the
  wrong genre for one Super Mario 64 dump.

The command line takes the same choices: `--cheats`, `--no-cheats` and
`--direct-boot on|off`.

## 1.2.0

**Upgrading from 1.1:** copy the new `SleekMenu64.z64` over the old one at
the root of the card. The card does not need preparing again.

- Coverflow glides: the shelf eases from cover to cover instead of
  stepping, a press in the middle of a move turns it instead of restarting
  it, and holding a direction keeps the shelf sliding, faster the longer you
  hold. Holding the D-pad or stick now repeats in every view.
- Coverflow uses the space under the shelf: the genre, year, publisher and
  players on one line, the first two lines of the description, and a strip
  of initials showing where you are and where L and R will jump. A longer
  description creeps up slowly after five seconds on the same game.
- Covers draw faster, and with an Expansion Pak the screen has a third
  buffer, so a slow frame no longer halves the frame rate.
- A cover could stay blank for good after moving twice quickly in the grid
  or coverflow. It now arrives.

## 1.1.0

**Upgrading from 1.0:** copy the new `SleekMenu64.z64` over the old one at
the root of the card, then prepare the card once with the 1.1 prep GUI (or
`sleekmenu-prep.pyz` 1.1). A card prepared by 1.0 still browses, but only
a 1.1 Prepare gives it the box view's covers and the fixes below.

### The prep GUI

- The card is now prepared from a window, one download per system — macOS
  (Apple silicon and Intel), Windows and Linux — with nothing to install.
  Pick the card, press Download the first time to fetch the box-art
  collection onto it, then Prepare.
- The Catalog tab shows the card as the browser will: every game, its box
  as the console draws it, and where each fact came from. Search narrows
  the list; Show narrows it to what you changed, or to what is not in the
  catalog yet.
- Give any game, or every game with one game code, your own picture, text,
  title, genre, publisher, year, players and regions. Save puts it on the
  card straight away; Remove my edit puts the original back.
- High-resolution boxes: an option fetches libretro's 512-pixel boxes for
  the box view; a card that has them keeps them complete from then on.

### Preparing a card

- Games are found wherever they are on the card, or in the one games folder
  you choose, which the card remembers.
- A second Prepare takes seconds: only new or changed files are read.
- The box-art collection is fetched onto a card that lacks it.
- Your own box art and text are taken from files named after the ROM,
  beside it or in `sleekmenu/art/`, or named after the game code; header
  lines in the text set the title, genre, publisher, year, players and
  regions.
- Hacks and homebrew whose header checksum is stale are named in the
  report, and rewritten with `--fix-checksums`.
- ROM-named files with no N64 header are set aside and never listed.
- A game whose file name has an accent (Pokémon) prepared on a Mac was
  listed twice on the console and could not start. Prepare the card once
  with 1.1 to fix it.

### On the console

- Start plays the highlighted game straight from the list, in any view; A
  still opens its details.
- The box view: A on a game's details shows its box full screen.
- Games copied onto the card since the last Prepare are listed and play,
  marked `NOT IN CATALOG` until the next Prepare gives them a box.
- A hack whose header checksum is stale is corrected in cartridge memory at
  launch, so it boots instead of showing a black screen.
- On the X7, a game that keeps time (Animal Forest) gets the cartridge's
  clock at launch.
- The description scrolls on the details card instead of ending in "...".
- File and folder names with accents are drawn without them rather than as
  stray characters.
- The start screen shows the version.

## 1.0.0 — 2026-09-12

The first release: a game browser for the EverDrive-64 X7 and Pro, with
box art, genres, descriptions and filters, started from the EverDrive's own
menu.
