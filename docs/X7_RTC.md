# X7 clock handoff

SleekMenu's ROM header requests RTC support from the stock EverDrive OS.
The intended result is that a game launched through SleekMenu inherits the
clock that the OS initialises when it launches the menu. This handoff is
experimental until the hardware checks below pass.

## Why the menu requests the clock

Animal Forest requires FlashRAM and RTC. SleekMenu resolves its RTC flag
from the game database, `save_db.txt`, or a homebrew header, but the X7
backend does not initialise the RTC when launching a game. It only selects
the save type in `GAM_CFG`. The Pro backend configures RTC separately.

The stock OS cannot see the selected game's header until SleekMenu loads
it, and the stock OS is no longer running at that point. Setting
`N64_ROM_RTC = 1` on the menu ROM asks the OS to initialise the clock before
SleekMenu starts. The menu's load and save paths leave the RTC registers
alone. No I2C clock writes or changes to the battery-backed date/time are
needed in the menu.

The header uses krikzz's [developer override format]: `ED` at offsets
`0x3C..0x3D`, and bit 0 of `0x3F` for RTC. Save type remains off for the menu;
the selected game's save type is applied during launch as usual. RTC is
requested for the menu as a whole, including launches of games that do not
use a clock. Use the supported X7 OS 3.11: krikzz's [OS changelist] records
EEPROM and RTC coexistence support from OS 3.07 onward.

The X7 RTC cache is separate from `GAM_CFG`; libdragon's [X7 clock code]
uses `0x1F808010` for that cache. Adding the RTC flag to `GAM_CFG` would
change the save selection rather than initialise the clock.

## Hardware validation

Host tests and inspecting the compiled ROM header cannot establish that
the X7 clock continues across the boot handoff. On an X7 with OS 3.11:

1. Back up `ED64/gamedata/`. Check the stock OS clock and verify the same
   Animal Forest ROM reports a sensible date/time when started directly.
2. Start this SleekMenu build through the stock OS, then start Animal
   Forest. Compare its date/time with the direct launch. Check that time
   advances after spending a few minutes in the menu before launching.
3. Save, reset to the stock menu, and launch the same ROM again. Confirm
   the save and elapsed time, then repeat after a power cycle.
4. Check an EEPROM game and an SRAM game through SleekMenu, including save
   and reload, because RTC remains enabled during those launches too.
5. If using the stock OS autoexec facility, check that entry path separately;
   it must honour the menu's RTC header just as a manual launch does.

Record the cartridge, OS version, console, ROM identity, launch method,
clock readings, and save results in the PR. Until verified, use the stock
OS for Animal Forest on the X7. This change does not alter the Pro backend.

[developer override format]: https://github.com/krikzz/ed64-x-pub/blob/master/docs/rom_config_database.md
[OS changelist]: https://krikzz.com/pub/support/everdrive-64/x-series/OS/changelist.txt
[X7 clock code]: https://github.com/DragonMinded/libdragon/blob/unstable/src/ed64x.c
