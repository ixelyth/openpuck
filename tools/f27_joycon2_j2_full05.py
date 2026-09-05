#!/usr/bin/env python3
"""J2: force hardware-positive Joy-Con 2 R onto common report 0x05.

The M20 JCR identity/session remains intact.  Only the periodic report is forced
to common 0x05 so one accepted Nintendo session carries both controller halves.
Mouse and motion payloads are suppressed for this registration/control probe.
"""
from pathlib import Path
import re

MODE = Path("OpenPuck/mode_switch2_pro.cpp")
JOY = Path("OpenPuck/f27_joycon2.cpp")
HDR = Path("OpenPuck/f27_joycon2.h")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"J2 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


mode = MODE.read_text(encoding="utf-8")
mode = replace_once(
    mode,
    "Switch2ProController g_switch2Pro;\n",
    "Switch2ProController g_switch2Pro;\n\n"
    "static const char J2_BUILD_MARKER[] __attribute__((used)) =\n"
    "\t\"F27-J2-JCR-FULL05\";\n",
    "build marker",
)
pattern = re.compile(
    r"\tuint8_t \*m = out \+ 0x2a;\n"
    r".*?"
    r"\tsw2Put16\(m \+ 16, gz\);\n",
    re.S,
)
mode, n = pattern.subn("\tmemset(out + 0x2a, 0, 21);\n", mode, count=1)
if n != 1:
    raise SystemExit(f"J2 motion block: regex count {n}, expected 1")
mode = replace_once(
    mode,
    "\t// Report and vendor transfers are drained by usbTxPump() so endpoint\n",
    "\tasm volatile(\"\" : : \"r\"(J2_BUILD_MARKER) : \"memory\");\n"
    "\t// Report and vendor transfers are drained by usbTxPump() so endpoint\n",
    "retain marker",
)
MODE.write_text(mode, encoding="utf-8")

hdr = HDR.read_text(encoding="utf-8")
hdr = replace_once(
    hdr,
    "#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_R\n#define F27_JOYCON_DEFAULT_REPORT 0x08\n",
    "#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_R\n#define F27_JOYCON_DEFAULT_REPORT 0x05\n",
    "JCR default report",
)
HDR.write_text(hdr, encoding="utf-8")

joy = JOY.read_text(encoding="utf-8")
joy = replace_once(
    joy,
    "#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_R\n\tif (requested == 0x05)\n\t\treturn 0x05;\n\treturn requested == 0x08 || requested == 0x09 ? 0x08 : 0;\n",
    "#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_R\n"
    "\treturn requested == 0x05 || requested == 0x08 || requested == 0x09 ?\n"
    "\t\t       0x05 :\n\t\t       0;\n",
    "force common report",
)
joy = replace_once(joy, "\tbool requestedMouse = true;\n", "\tbool requestedMouse = false;\n", "disable mouse")
JOY.write_text(joy, encoding="utf-8")
print("F27-J2 single-JCR full common-report probe applied")
