#!/usr/bin/env python3
"""Apply F27-M19 single legacy Switch Pro A/B control.

This is the direct control for M18. It changes no legacy Switch-Pro USB topology:
the binary simply forces MODE_SW_PRO after configuration load. With one Steam
Controller connected, the existing production dynamic-mount path therefore
exposes exactly one legacy Switch Pro HID. The only extra source addition is a
retained build marker with no runtime behavior.
"""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"F27-M19 {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)

ino = Path("OpenPuck/OpenPuck.ino")
src = ino.read_text(encoding="utf-8")
if "F27-M19-SINGLE-LEGACY-SWPRO" in src:
    raise SystemExit("F27-M19 already applied to OpenPuck.ino")
src = replace_once(
    src,
    "\tloadCfg();\n\tloadBonds();\n",
    "\tloadCfg();\n"
    "\t// F27-M19-SINGLE-LEGACY-SWPRO: A/B control for M18. Force the\n"
    "\t// existing production legacy Switch Pro mode without altering its\n"
    "\t// ordinary one-controller dynamic USB topology. This override is\n"
    "\t// experimental and is not persisted.\n"
    "\tg_usbMode = MODE_SW_PRO;\n"
    "\tloadBonds();\n",
    "force legacy Switch Pro mode",
)
ino.write_text(src, encoding="utf-8")

path = Path("OpenPuck/mode_switch_pro.cpp")
src = path.read_text(encoding="utf-8")
if "F27-M19-SINGLE-LEGACY-SWPRO" in src:
    raise SystemExit("F27-M19 already applied to mode_switch_pro.cpp")

src = replace_once(
    src,
    "SwitchProController g_switchPro;\n",
    "SwitchProController g_switchPro;\n"
    "static const char M19_MARKER[] = \"F27-M19-SINGLE-LEGACY-SWPRO\";\n",
    "add binary marker",
)
src = replace_once(
    src,
    "void SwitchProController::beginPool()\n{\n",
    "void SwitchProController::beginPool()\n{\n"
    "\t// Retain the experiment marker in the linked image without changing\n"
    "\t// runtime behavior.\n"
    "\tasm volatile(\"\" : : \"r\"(M19_MARKER) : \"memory\");\n",
    "retain binary marker",
)
path.write_text(src, encoding="utf-8")
print("F27-M19 single legacy Switch Pro A/B probe applied")
