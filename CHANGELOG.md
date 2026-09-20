# Changelog

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
