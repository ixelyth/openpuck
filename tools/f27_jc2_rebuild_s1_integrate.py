#!/usr/bin/env python3
"""Integrate F27 Joy-Con 2 clean-rebuild stage 1 onto current main.

Stage 1 adds one static stock Adafruit HID personality with JCR USB identity.
It intentionally adds no custom TinyUSB app driver, vendor interface, linker
wrapper, native Joy-Con report descriptor, or Nintendo protocol handler.
"""
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"S1 {label}: anchor count {count}, expected 1 in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


p = Path("OpenPuck/config.h")
replace_once(
    p,
    "#define MODE_SINPUT 12\n#define MODE_MAX 12\n",
    "#define MODE_SINPUT 12\n"
    "// F27 clean Joy-Con 2 reconstruction; diagnostic-only, forced by build flag.\n"
    "#define MODE_JOYCON2_REBUILD 13\n"
    "#define MODE_MAX 13\n",
    "mode id",
)
replace_once(
    p,
    "\tcase MODE_SW_HORI:\n\tcase MODE_SW_PRO:\n\t\treturn ET_SWITCH;\n",
    "\tcase MODE_SW_HORI:\n"
    "\tcase MODE_SW_PRO:\n"
    "\tcase MODE_JOYCON2_REBUILD:\n"
    "\t\treturn ET_SWITCH;\n",
    "switch type",
)

p = Path("OpenPuck/controllers.cpp")
replace_once(
    p,
    '#include "mode_xbox_og.h"\n',
    '#include "mode_xbox_og.h"\n#include "mode_joycon2_rebuild.h"\n',
    "controller include",
)
replace_once(
    p,
    "\tcase MODE_SINPUT:\n\t\treturn &g_sinputCtl;\n",
    "\tcase MODE_SINPUT:\n"
    "\t\treturn &g_sinputCtl;\n"
    "\tcase MODE_JOYCON2_REBUILD:\n"
    "\t\treturn &g_joyCon2Rebuild;\n",
    "controller dispatch",
)

p = Path("OpenPuck/OpenPuck.ino")
text = p.read_text(encoding="utf-8")
old = "static const char MODE_SUFFIX[] = { 'X', 'N', 'L', 'P', 'S', 'G',\n\t\t\t\t    'Q', 'D', '3', 'O', 'J', 'I' };"
new = "static const char MODE_SUFFIX[] = { 'X', 'N', 'L', 'P', 'S', 'G',\n\t\t\t\t    'Q', 'D', '3', 'O', 'J', 'I', '2' };"
if text.count(old) != 1:
    raise SystemExit("S1 mode suffix anchor mismatch")
text = text.replace(old, new, 1)
old = "\tloadCfg();\n\tloadBonds();\n"
new = (
    "\tloadCfg();\n"
    "#if defined(OPK_JC2_REBUILD_FORCE) && OPK_JC2_REBUILD_FORCE\n"
    "\tg_usbMode = MODE_JOYCON2_REBUILD;\n"
    "#endif\n"
    "\tloadBonds();\n"
)
if text.count(old) != 1:
    raise SystemExit("S1 force-mode anchor mismatch")
text = text.replace(old, new, 1)
old = "\tconst bool psClean = modeIsCleanPS(g_usbMode);\n\tconst bool dynamic = g_active->dynamicMount();\n"
new = (
    "\tconst bool psClean = modeIsCleanPS(g_usbMode);\n"
    "\tconst bool joyCon2RebuildClean = g_usbMode == MODE_JOYCON2_REBUILD;\n"
    "\tconst bool dynamic = g_active->dynamicMount();\n"
)
if text.count(old) != 1:
    raise SystemExit("S1 clean-mode anchor mismatch")
text = text.replace(old, new, 1)
old = "\t\tif (!puckMode && !keepCdc && !psClean)\n\t\t\twakeHidBegin();\n"
new = "\t\tif (!puckMode && !keepCdc && !psClean && !joyCon2RebuildClean)\n\t\t\twakeHidBegin();\n"
if text.count(old) != 1:
    raise SystemExit("S1 wake anchor mismatch")
text = text.replace(old, new, 1)
old = "\t\tif (!puckMode && !psClean)\n\t\t\tusb_web.begin();\n"
new = "\t\tif (!puckMode && !psClean && !joyCon2RebuildClean)\n\t\t\tusb_web.begin();\n"
if text.count(old) != 1:
    raise SystemExit("S1 webusb anchor mismatch")
text = text.replace(old, new, 1)
old = (
    "\t\tUSBDevice.setConfigurationAttribute(psClean ? 0x80 :\n"
    "\t\t\t\t\t\t\t      (0x80 | 0x20));\n"
)
new = (
    "\t\tUSBDevice.setConfigurationAttribute(joyCon2RebuildClean ? 0x80 :\n"
    "\t\t\t\t\t\t\t      (psClean ? 0x80 : (0x80 | 0x20)));\n"
)
if text.count(old) != 1:
    raise SystemExit("S1 configuration attribute anchor mismatch")
text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

print("F27 Joy-Con 2 clean rebuild S1 integration applied")
