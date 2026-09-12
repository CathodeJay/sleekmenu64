# registry.dat samples

`ED64/sysdata/registry.dat` files written by an EverDrive-64 X7 running
OS 3.11, captured from a real card. The tests parse these so the reader is
checked against bytes the firmware wrote, not against our own encoder.
`tools/ed64_registry.py` documents the layout.

| file | state of the card |
|---|---|
| sample-01.dat | after booting a SleekMenu build with no save hardware: zero CRC pair, save type OFF |
| sample-02.dat | after the record was rewritten to point at a game that never launched |
| sample-03.dat | after Super Mario 64 (USA) ran and saved: CRC pair, `NSME00`, save type EEP4K |
| sample-04.dat | sample-03 with the save type changed to SRM32K and the CRC resealed, then booted: the firmware wrote a 32 KiB `.srm` |

Samples 01 and 02 name the ROM `EverBrowse`, the project's earlier name;
the bytes are kept as the firmware wrote them.
