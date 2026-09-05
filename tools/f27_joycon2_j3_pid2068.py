#!/usr/bin/env python3
"""J3: probe whether Switch 2 treats PID 057E:2068 specially.

Run after the M20 Joy-Con-R chain and J2 full-0x05 transform.  Change both the
physical USB PID and Nintendo factory/vendor logical PID from 2066/2069 to 2068.
No undocumented Charging Grip descriptor/string is invented.
"""
from pathlib import Path

MODE = Path("OpenPuck/mode_switch2_pro.cpp")
JOY = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"J3 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


mode = MODE.read_text(encoding="utf-8")
mode = replace_once(
    mode,
    "static const char J2_BUILD_MARKER[] __attribute__((used)) =\n\t\"F27-J2-JCR-FULL05\";\n",
    "static const char J2_BUILD_MARKER[] __attribute__((used)) =\n\t\"F27-J2-JCR-FULL05\";\n"
    "static const char J3_BUILD_MARKER[] __attribute__((used)) =\n\t\"F27-J3-PID2068-FULL05\";\n",
    "build marker",
)
mode = replace_once(mode, "\tUSBDevice.setID(0x057e, 0x2069);\n", "\tUSBDevice.setID(0x057e, 0x2068);\n", "USB PID")
mode = replace_once(
    mode,
    "\tasm volatile(\"\" : : \"r\"(J2_BUILD_MARKER) : \"memory\");\n",
    "\tasm volatile(\"\" : : \"r\"(J2_BUILD_MARKER) : \"memory\");\n"
    "\tasm volatile(\"\" : : \"r\"(J3_BUILD_MARKER) : \"memory\");\n",
    "retain marker",
)
MODE.write_text(mode, encoding="utf-8")

joy = JOY.read_text(encoding="utf-8")
joy = replace_once(
    joy,
    "#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_R\n\treturn 0x66;\n",
    "#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_R\n\treturn 0x68;\n",
    "logical/factory PID",
)
JOY.write_text(joy, encoding="utf-8")
print("F27-J3 USB + logical PID 057E:2068 full-common-report probe applied")
