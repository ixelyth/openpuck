#!/usr/bin/env python3
"""Apply F27-M18 dual legacy Switch Pro topology probe.

This is a topology-only discriminator. The build forces MODE_SW_PRO for this
experiment and, whenever one Steam Controller is connected, presents two legacy
Switch Pro HID controller interfaces. USB slot 0 stays live. USB slot 1 has its
own normal Switch-Pro handshake/MAC but its streamed 0x30 input is neutral and
its rumble relay is suppressed. The hardware question is only whether Switch 2
surfaces one or two controller slots behind one USB device address.
"""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"F27-M18 {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)

ino = Path("OpenPuck/OpenPuck.ino")
src = ino.read_text(encoding="utf-8")
if "F27-M18-DUAL-LEGACY-SWPRO" in src:
    raise SystemExit("F27-M18 already applied to OpenPuck.ino")
src = replace_once(
    src,
    "\tloadCfg();\n\tloadBonds();\n",
    "\tloadCfg();\n"
    "\t// F27-M18-DUAL-LEGACY-SWPRO: topology-only hardware probe. Do not\n"
    "\t// persist this override; this experimental binary always boots the\n"
    "\t// legacy Switch Pro personality so the test cannot accidentally run\n"
    "\t// under the saved Switch2Pro mode.\n"
    "\tg_usbMode = MODE_SW_PRO;\n"
    "\tloadBonds();\n",
    "force legacy Switch Pro mode",
)
ino.write_text(src, encoding="utf-8")

path = Path("OpenPuck/mode_switch_pro.cpp")
src = path.read_text(encoding="utf-8")
if "F27-M18-DUAL-LEGACY-SWPRO" in src:
    raise SystemExit("F27-M18 already applied to mode_switch_pro.cpp")

src = replace_once(
    src,
    "static void jcRumble(uint8_t slot, const uint8_t *p, uint16_t pn)\n"
    "{\n"
    "\tif (pn < 9)\n"
    "\t\treturn; // [timer][left rumble x4][right rumble x4]\n",
    "static void jcRumble(uint8_t slot, const uint8_t *p, uint16_t pn)\n"
    "{\n"
    "\t// F27-M18-DUAL-LEGACY-SWPRO: USB slot 1 is a neutral topology\n"
    "\t// companion only. It must never relay rumble into an unrelated bond\n"
    "\t// slot when g_usbToBond[1] is intentionally unmapped.\n"
    "\tif (slot == 1 && g_usbMountCount == 1)\n"
    "\t\treturn;\n"
    "\tif (pn < 9)\n"
    "\t\treturn; // [timer][left rumble x4][right rumble x4]\n",
    "suppress companion rumble",
)

src = replace_once(
    src,
    "void SwitchProController::mountSlots(uint8_t k)\n"
    "{\n"
    "\tfor (uint8_t u = 0; u < k; u++) {\n",
    "void SwitchProController::mountSlots(uint8_t k)\n"
    "{\n"
    "\t// F27-M18-DUAL-LEGACY-SWPRO: when exactly one real Steam Controller\n"
    "\t// is connected, expose TWO independent legacy Pro-controller HIDs.\n"
    "\t// Slot 0 remains live; slot 1 exists only to test whether Switch 2\n"
    "\t// promotes multiple controller interfaces behind one USB address.\n"
    "\tuint8_t mounted = k ? 2 : 0;\n"
    "\tfor (uint8_t u = 0; u < mounted; u++) {\n",
    "force two mounted legacy Pro HIDs",
)

needle = (
    "void SwitchProController::task()\n"
    "{\n"
    "\tfor (uint8_t s = 0; s < g_usbMountCount; s++) {\n"
)
replacement = (
    "static void m18NeutralizeCompanion(uint8_t slot, uint8_t out[63])\n"
    "{\n"
    "\tif (slot != 1 || g_usbMountCount != 1)\n"
    "\t\treturn;\n"
    "\t// Full battery, no buttons, centered sticks, normal vibrator marker,\n"
    "\t// and zero IMU. Handshake/session identity remains the ordinary slot-1\n"
    "\t// legacy Pro path, including its distinct MAC.\n"
    "\tout[1] = 0x80;\n"
    "\tout[2] = out[3] = out[4] = 0;\n"
    "\tjcPackStick(out + 5, 0, 0);\n"
    "\tjcPackStick(out + 8, 0, 0);\n"
    "\tout[11] = 0x09;\n"
    "\tmemset(out + 12, 0, 36);\n"
    "}\n\n"
    "void SwitchProController::task()\n"
    "{\n"
    "\tuint8_t mounted = g_usbMountCount ? 2 : 0;\n"
    "\tfor (uint8_t s = 0; s < mounted; s++) {\n"
)
src = replace_once(src, needle, replacement, "drain/stream both HIDs")

src = replace_once(
    src,
    "\t\tswitchProBuild((uint8_t)s, p);\n"
    "\t\t// Queue the newest state even while the endpoint is busy. usb_tx's bounded drop-oldest policy\n",
    "\t\tswitchProBuild((uint8_t)s, p);\n"
    "\t\tm18NeutralizeCompanion(s, p);\n"
    "\t\t// Queue the newest state even while the endpoint is busy. usb_tx's bounded drop-oldest policy\n",
    "neutral companion stream",
)

path.write_text(src, encoding="utf-8")
print("F27-M18 dual legacy Switch Pro topology probe applied")
