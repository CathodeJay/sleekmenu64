# sample-03-armed-sm64

Captured from the card after: boot the stock menu (OS 3.11) -> launch Super
Mario 64 (USA) -> collect a star in game -> power off.

This is the first snapshot taken while the record refers to a game that
actually has a save, and it is the one that decoded the file. Compare it with
sample-01 and sample-02, both of which refer to an SleekMenu build with no
save hardware at all.

| offset | s01 SleekMenu-Probe | s02 sleekmenu | s03 Super Mario 64 |
|--------|----------------------|----------------|--------------------|
| 1028..1035 ROM CRC pair | zero | zero | `635A2BFF 8B022326` |
| 1040..1045 ROM id       | `N???00` | `N???00` | `NSME00` |
| 1048..1049 save type    | 0 OFF | 0 OFF | 1 EEP4K |
| 1050..1051 CIC          | 3 | 3 | 1 |
| 1064..1071 cursor stack | 2,0,0,0 | 4,0,0,0 | 104,2,1,1 |

The zeros in the first two columns are not the firmware withholding anything:
`sleekmenu.z64`'s own header carries a zero CRC pair and NUL bytes at
0x3C..0x3E, which is exactly what the menu copied. `N???00` is the menu
rendering those NULs as `?`.

The firmware wrote `Super Mario 64 (USA).eep` in the same session, holding a
real save -- `DA` magic on every slot, slot 0's checksum `00A8` against `0085`
for the untouched slots. That file is not kept here; see this directory's
README for what was removed before publishing and why.

## What this overturns

The earlier reading of byte 1065 as an "armed" flag was wrong. 1064..1071 tracks
the browser cursor, and the reason a rewritten registry pointing at Majora's
Mask produced no save file was much simpler: it was copied from an SleekMenu
record, so its save type was 0. The firmware read the path, saw OFF, and had
nothing to write.
