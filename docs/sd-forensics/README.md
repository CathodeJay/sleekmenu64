# SD forensics

Captures taken from a real EverDrive-64 X7 running OS 3.11, used to work out
the layout of `/ED64/sysdata/registry.dat` — the record the stock firmware writes to
say which ROM is loaded and what save hardware it should emulate. SleekMenu
cooperates with that record rather than replacing it, so the layout had to be
proven rather than guessed.

`src/ed64_registry.c` implements what these samples established, and
`tests/ed64_registry_test.c` parses the `registry.dat` files here so the
parser is checked against bytes the firmware actually wrote rather than
against our own encoder.

| sample | what it captures |
|---|---|
| 01-after-sleekmenu-probe | a browser build with no save hardware; zero CRC pair, save type OFF |
| 02-after-majora | same, after a rewritten record pointed at a game that never launched |
| 03-armed-sm64 | the first record naming a game with a real save — this is the one that decoded the format |
| 04-flushed-srm | the controlled experiment: one byte changed at 1049, CRC resealed, firmware flushed a 32 KiB `.srm` |

`NOTES.md` in samples 03 and 04 carries the findings, including the byte values
that mattered.

## The old name in the samples

Samples 01 and 02 record `/SleekMenu-Probe.z64` and `/sleekmenu.z64` in this
directory's write-up, but the bytes in `registry.dat` say `EverBrowse`. That is
not a mismatch to fix: the project was called EverBrowse 64 when these captures
were taken, and what the firmware wrote is the evidence. Rewriting it would
make the samples agree with the documentation by making them stop being what
came off the card.

## What was removed before publishing

Each sample originally kept every file the firmware had touched. Three kinds
were dropped:

- **`save_db.txt` / `save_db.dat`** — krikzz's own configuration files, shipped
  with EverDrive OS. Not ours to redistribute.
- **`recent.dat`** — a 20 KB dump of one person's ROM library and build history.
  No forensic value the notes do not already carry.
- **`Super Mario 64 (USA).eep` / `.srm`** — game save data. The two facts they
  proved are recorded in the notes: the EEPROM image's `DA` slot magic and
  checksums, and that unused save RAM on this cartridge reads back as `0xAA`
  rather than `0x00` or `0xFF`. That second one was a live bug — the guard
  against overwriting a good save only knew the two obvious fills, and 32 KiB
  of `0xAA` would have sailed through it.

The `registry.dat` files are kept. They are firmware-generated state, they
contain nothing beyond ROM paths and save configuration, and the tests read
them.

## Reproducing

Take a card image before and after the operation you want to understand, then
diff `/ED64/sysdata/registry.dat`. `tools/ed64_registry.py` decodes a record and
prints the fields; it also reseals the CRC-32, which is what made the
one-byte experiment in sample 04 possible.
