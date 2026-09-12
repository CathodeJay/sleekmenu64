# sample-04-flushed-srm

The controlled experiment that decoded the save-type field, and the one that
turned the layout from a set of correlations into something proven.

sample-03's registry.dat was rewritten with **one byte changed** -- offset 1049,
the low half of the big-endian u16 at 1048, from `01` (EEP4K) to `03` (SRM32K)
-- and its CRC-32 resealed. Nothing else in the 2256 bytes was touched. The card
went back in the console, the stock menu was booted, nothing was launched, and
the console was powered off after five seconds.

The firmware wrote `Super Mario 64 (USA).srm`, 32768 bytes.

That settles four things at once:

- **1048..1049 is the save type**, in krikzz's own numbering -- the same ids
  that go to `REG_GAM_CFG`.
- **The writeback needs nothing else.** Path at offset 0 plus save type is the
  whole record; no launch, no arming step, no second field.
- **`.srm` is the extension and 32768 the length** for SRM32K on the X-series.
- **The record is not consumed.** `registry.dat` after the flush still names
  Super Mario 64 and still says type 3. The firmware will rewrite that file on
  every menu boot until a launch replaces the record, so anything cooperating
  with it should skip writing bytes that have not changed.

It also disproved the "armed flag" reading of byte 1065. What actually changed
across a menu boot was the browser cursor stack at 1064..1071 and the current
selection at 1196 -- both cleared because the menu was left sitting at the root.
The path at offset 0 and the save type both survived untouched.

## The 0xAA discovery

The `Super Mario 64 (USA).srm` the firmware wrote was 512 bytes of real EEPROM
save data followed by 32256 bytes of `0xAA`. The file itself is not kept here
-- see this directory's README -- but that shape is the finding.

Two things follow. The EverDrive backs its emulated EEPROM with the same
battery window it uses for SRAM, at offset 0 -- the game's EEPROM contents came
out of a window the game was never told was SRAM. And **unused save RAM on this
cartridge reads back as `0xAA`**, not `0x00` and not `0xFF`.

That second one was a live bug. SleekMenu refuses to write a blank cartridge
over a save the card already holds, and the guard only knew the two obvious
fills; 32 KiB of `0xAA` would have sailed through it as real data and destroyed
a good save. The guard now rejects any uniformly-filled buffer.

Its EEPROM image (`01 21`, checksum `00A9`) was one star further along than
sample-03's (`01 20`, checksum `00A8`), which is just the save having moved on
between the two captures.
