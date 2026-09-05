#!/usr/bin/env python3
"""Apply the F27 Joy-Con 2 POC hooks to the isolated Switch2Pro source copy.

The repository branch keeps the reviewed switch2pro source unchanged. Hardware
artifacts run this patch in CI with OPK_F27_JOYCON_TARGET=1/2/3 so the only
experimental delta is explicit and reproducible.
"""
from pathlib import Path

PATH = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27 patch anchor count {count}, expected 1:\n{old}")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")

src = replace_once(
    src,
    '#include "mode_switch2_pro.h"\n',
    '#include "mode_switch2_pro.h"\n#include "f27_joycon2.h"\n',
)
src = replace_once(
    src,
    "static volatile uint8_t g_sw2ActiveReport = 0x09;",
    "static volatile uint8_t g_sw2ActiveReport = F27_JOYCON_DEFAULT_REPORT;",
)
src = replace_once(
    src,
    "static volatile uint8_t g_sw2FeatureMask = 0;",
    "static volatile uint8_t g_sw2FeatureMask = F27_JOYCON_INITIAL_FEATURE_MASK;",
)
src = replace_once(
    src,
    "\tsw2OverlayFlash(address, block, len, 0x00013100, SW2_FACTORY_13100,\n"
    "\t\t\tsizeof SW2_FACTORY_13100);\n}",
    "\tsw2OverlayFlash(address, block, len, 0x00013100, SW2_FACTORY_13100,\n"
    "\t\t\tsizeof SW2_FACTORY_13100);\n"
    "\tf27JoyconPatchFlash(address, block, len);\n}",
)
src = replace_once(
    src,
    "\tif (sub == 0x0a && n >= 9 && (cmd[8] == 0x05 || cmd[8] == 0x09))\n"
    "\t\tg_sw2ActiveReport = cmd[8];",
    "\tif (sub == 0x0a && n >= 9) {\n"
    "\t\tuint8_t report = f27JoyconSelectReport(cmd[8]);\n"
    "\t\tif (report)\n"
    "\t\t\tg_sw2ActiveReport = report;\n"
    "\t}",
)
src = replace_once(
    src,
    "\tuint8_t p[63];\n"
    "\tuint8_t rid = g_sw2ActiveReport;\n"
    "\tif (rid == 0x05)\n"
    "\t\tsw2Build05((uint8_t)bond, p);\n"
    "\telse {\n"
    "\t\trid = 0x09;\n"
    "\t\tsw2Build09((uint8_t)bond, p);\n"
    "\t}\n"
    "\tif (tud_hid_n_report(0, rid, p, sizeof p))",
    "\tuint8_t p[63];\n"
    "\tuint8_t rid = g_sw2ActiveReport;\n"
    "\tif (rid == 0x05) {\n"
    "\t\tsw2Build05((uint8_t)bond, p);\n"
    "\t} else if (!f27JoyconBuildNative((uint8_t)bond, g_sw2Features, &rid, p)) {\n"
    "\t\trid = 0x09;\n"
    "\t\tsw2Build09((uint8_t)bond, p);\n"
    "\t}\n"
    "\tif (tud_hid_n_report(0, rid, p, sizeof p))",
)
src = replace_once(
    src,
    "\tif (identity) {\n"
    "\t\tmemcpy(g_sw2ControlReply, SW2_VENDOR_IDENTITY,\n"
    "\t\t       sizeof SW2_VENDOR_IDENTITY);\n"
    "\t\treturn tud_control_xfer(rhport, request, g_sw2ControlReply,\n",
    "\tif (identity) {\n"
    "\t\tmemcpy(g_sw2ControlReply, SW2_VENDOR_IDENTITY,\n"
    "\t\t       sizeof SW2_VENDOR_IDENTITY);\n"
    "\t\tf27JoyconPatchIdentity(g_sw2ControlReply, sizeof g_sw2ControlReply);\n"
    "\t\treturn tud_control_xfer(rhport, request, g_sw2ControlReply,\n",
)
src = replace_once(
    src,
    "\tg_sw2ActiveReport = 0x09;\n"
    "\tg_sw2Features = 0;\n"
    "\tg_sw2FeatureMask = 0;",
    "\tg_sw2ActiveReport = F27_JOYCON_DEFAULT_REPORT;\n"
    "\tg_sw2Features = 0;\n"
    "\tg_sw2FeatureMask = F27_JOYCON_INITIAL_FEATURE_MASK;",
)
src = replace_once(
    src,
    "\telse if (reportId == 0x09)\n"
    "\t\tsw2Build09((uint8_t)bond, p);\n"
    "\telse\n"
    "\t\treturn 0;",
    "\telse {\n"
    "\t\tuint8_t rid = reportId;\n"
    "\t\tif (!f27JoyconBuildNative((uint8_t)bond, g_sw2Features, &rid, p)) {\n"
    "\t\t\tif (reportId != 0x09)\n"
    "\t\t\t\treturn 0;\n"
    "\t\t\tsw2Build09((uint8_t)bond, p);\n"
    "\t\t}\n"
    "\t}",
)

PATH.write_text(src, encoding="utf-8")
print("F27 Joy-Con 2 POC hooks applied")
