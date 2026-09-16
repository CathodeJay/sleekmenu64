#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Trace the RTC branch of a supplied official X7 OS 3.11 ROM using Unicorn.

Executes the original MIPS launch, RTC conversion, and packet construction
instructions. Hardware and unrelated menu routines are stubbed. This checks
software behaviour; it does not emulate an X7 or validate physical hardware.
No firmware is included or downloaded. Requires the optional unicorn package.
"""
import argparse
import hashlib
import json
from pathlib import Path

OS_SHA256 = "8f7aa92d71d7ad87a644bd19599dfb9aa499be74afbc38b727b0c83074c02c68"
BASE = 0xFFFFFFFF80000000


def trace(rom, rtc, save):
    import unicorn as uc
    from unicorn import mips_const as m

    cpu = uc.Uc(uc.UC_ARCH_MIPS, uc.UC_MODE_MIPS64 | uc.UC_MODE_BIG_ENDIAN)
    cpu.ctl_set_cpu_model(m.UC_CPU_MIPS64_R4000)
    cpu.mem_map(0, 0x800000)
    cpu.mem_write(0x400, rom[0x1000:])
    cpu.mem_write(0x5B300, (0x80060000).to_bytes(4, "big"))
    cpu.mem_write(0x60418, save.to_bytes(2, "big"))
    cpu.mem_write(0x60422, bytes([rtc]))
    cpu.mem_write(0x8218E, b"\x01")  # X7 RTC capability present
    cpu.reg_write(m.UC_MIPS_REG_SP, BASE + 0x700000)
    cpu.reg_write(m.UC_MIPS_REG_RA, BASE + 0x780000)
    cpu.reg_write(m.UC_MIPS_REG_A0, 1)
    events = []
    booted = False

    def reg(register):
        return cpu.reg_read(register)

    def ptr(register):
        return reg(register) & 0x1FFFFFFF

    def return_value(value=0):
        cpu.reg_write(m.UC_MIPS_REG_V0, value)
        cpu.reg_write(m.UC_MIPS_REG_PC, reg(m.UC_MIPS_REG_RA))

    def hook(_cpu, address, _size, _context):
        nonlocal booted
        address &= 0x1FFFFFFF
        # Unrelated menu/UI/save work; all return success. The real launch
        # branch at 0x6B28, time conversion, and packet assembly still run.
        if address in {0x126C0, 0x12898, 0x16B0, 0x6388, 0x64B8, 0x6AA0, 0xB70}:
            return_value()
        elif address in {0x1220, 0x11B8, 0x1190, 0x11E0}:
            events.append({"i2c": {0x1220: "start", 0x11B8: "read_mode",
                                    0x1190: "write_mode", 0x11E0: "stop"}[address]})
            return_value()
        elif address == 0x1148:
            events.append({"i2c_command": reg(m.UC_MIPS_REG_A0) & 255})
            return_value()
        elif address == 0x1058:
            events.append({"i2c_read_bytes": reg(m.UC_MIPS_REG_A1)})
            cpu.mem_write(ptr(m.UC_MIPS_REG_A0), bytes.fromhex("58592304311226") + b"\0" * 9)
            return_value()
        elif address == 0x129B0:
            packet = bytes(cpu.mem_read(ptr(m.UC_MIPS_REG_A0), 64))
            events.append({"joybus": packet.hex()})
            cpu.mem_write(ptr(m.UC_MIPS_REG_A1), bytes(64))
            return_value()
        elif address == 0xAC8:
            events.append({"register": reg(m.UC_MIPS_REG_A0), "value": reg(m.UC_MIPS_REG_A1)})
            return_value()
        elif address == 0x6518:
            booted = True
            cpu.emu_stop()

    cpu.hook_add(uc.UC_HOOK_CODE, hook)
    cpu.emu_start(BASE + 0x6B28, BASE + 0x780000, count=10000)
    expected = {"register": 0x8018, "value": save | (0x1000 if rtc else 0)}
    if not booted or not events or events[-1] != expected:
        raise RuntimeError(f"Unexpected launch result: {booted=}, {events=}")
    if not rtc and events != [expected]:
        raise RuntimeError(f"Non-RTC launch touched clock: {events}")
    return {"rtc": rtc, "save": save, "events": events}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("os_rom", type=Path, help="Official OS 3.11 ED64/OS64.v64")
    args = parser.parse_args()
    rom = args.os_rom.read_bytes()
    if hashlib.sha256(rom).hexdigest() != OS_SHA256:
        parser.error("ROM is not the expected OS 3.11 build; addresses would be invalid")
    for rtc in (False, True):
        for save in range(7):
            print(json.dumps(trace(rom, rtc, save)))


if __name__ == "__main__":
    main()
