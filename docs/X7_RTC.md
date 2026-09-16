# X7 per-game RTC

The X7 backend applies the selected ROM's RTC requirement at launch. Games
without `SM_SAVE_CFG_RTC` receive a plain save-type value in `GAM_CFG`, so
RTC is disabled. Games requesting RTC receive the save type plus `0x1000`.
SleekMenu's own ROM header does not force RTC on.

The existing resolver supplies the requirement from the `ED` developer
header, the first matching `ED64/save_db.txt` record, or the built-in game
database. This is automatic per-game selection; it does not import manual
settings saved in the stock OS's per-ROM configuration files. `AF=51`, for
example, selects FlashRAM plus RTC for Animal Forest.

## Clock preparation

Only a game requesting RTC accesses the clock. Before save preparation,
SleekMenu reads 16 bytes from the battery-backed DS1337 at I2C address
`0x68`, register zero. It converts the date fields to Joybus order, then
sends three cartridge-port commands: stop/unlock RTC block 0, write time
block 2, and start/lock block 0. These initialise the game-facing clock;
the physical DS1337 time is never written.

SleekMenu itself runs with RTC disabled. Before sending the Joybus commands,
it writes `0x1000` to `GAM_CFG` so the cartridge RTC can answer, then writes
zero after the commands, including on failure. The stock OS's RTC diagnostic
uses this same enable/write/disable sequence at `0x8000CAB0..0x8000CACC`.
Save memory has already been flushed, and no save transfer runs during this
temporary configuration. Save preparation and final launch subsequently
select their own save/RTC settings.

I2C waits are bounded. An I2C NACK, timeout, or failed Joybus write cancels
the launch before the save is armed, with the failing step in the message.
The backend attempts to restart the
emulated clock even if a Joybus write fails. After successful preparation,
save transfer proceeds normally. The final handoff writes the complete
save/RTC configuration, explicitly clearing RTC for non-RTC games.

The driver reads the physical clock through the separate I2C registers
`0x1F800018` and `0x1F80001C`. It does not touch libcart's SD state, key, or
timing registers. Temporary and final `GAM_CFG` writes use the existing
register module.

## Evidence from the stock OS

The supported X7 OS is 3.11. Its launch routine uses `GAM_CFG` bit `0x1000`
for RTC; the older [public BIOS header] does not describe this bit. The
old `0x8010` RTC-cache interface is not used by this implementation.

`tools/trace_x7_rtc.py` executes the original OS 3.11 MIPS instructions in
Unicorn with I2C/Joybus and unrelated menu routines stubbed. It checks all
seven save types with RTC off and on. Off produces no clock traffic and
writes exactly the save type. On reads the DS1337, constructs the three
Joybus packets, and writes `save_type | 0x1000`.

The script requires an independently supplied [official OS 3.11 ROM] and
checks its SHA-256 before using fixed addresses. No firmware is included.
To reproduce, with Python and the optional `unicorn` package available:

```sh
python3 tools/trace_x7_rtc.py /path/to/ED64/OS64.v64
```

Relevant OS addresses (virtual addresses, ROM offset = address -
`0x80000400 + 0x1000`):

| Address | Observed operation |
|---|---|
| `0x80006B28` | Game launch and per-game RTC branch |
| `0x80006D20` | Read/initialise RTC, select bit `0x1000` |
| `0x80001D60` | Read and normalise DS1337 fields |
| `0x800013E8` | I2C read transaction |
| `0x80010358` | Construct stop/time/start RTC writes |
| `0x80010270` | Assemble a Joybus write packet |
| `0x80000B90` | Write full configuration to `GAM_CFG` |
| `0x8000CAB0` | Enable RTC before diagnostic Joybus writes |
| `0x8000CAC8` | Disable RTC after the diagnostic |

Host tests exercise the production register and RTC modules, comparing
packets against this trace and checking every save/config combination,
bus failures, cancellation before save preparation, and an RTC launch
followed by a non-RTC launch. The Joybus stub returns a transport error when
`GAM_CFG` has RTC disabled, so omitting the temporary enable fails the test.

## Remaining hardware check

The CPU trace establishes the stock software's behaviour, not electrical
operation of an X7. Validate Animal Forest's clock progression and save
reload through this build, then one ordinary EEPROM game as a check of
the RTC-off handoff. Broad testing of every game with RTC enabled is not
required by this design: ordinary launches receive the same RTC-off
configuration as the stock OS. The Pro backend is unchanged.

[public BIOS header]: https://github.com/krikzz/ed64-x-pub/blob/master/ED64-XIO/inc/bios.h
[official OS 3.11 ROM]: https://krikzz.com/pub/support/everdrive-64/x-series/OS/OS-V3.11.zip
