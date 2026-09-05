#!/usr/bin/env python3
"""Integrate the clean F27-G5 Joy-Con 2 mode onto current upstream main.

This script intentionally patches only generic OpenPuck mode/USB plumbing. The
Joy-Con implementation itself lives in mode_joycon2.cpp and has no dependency
on mode_switch2_pro.cpp or any Switch2Pro branch.
"""
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"G5 {label}: anchor count {count}, expected 1 in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Mode number and controller type.
p = Path("OpenPuck/config.h")
replace_once(
    p,
    "#define MODE_SINPUT 12\n#define MODE_MAX 12\n",
    "#define MODE_SINPUT 12\n"
    "// F27-G5 clean Joy-Con 2 diagnostic. Exact 2066/2067 USB personality; no Pro2 composite.\n"
    "#define MODE_JOYCON2 13\n"
    "#define MODE_MAX 13\n",
    "mode id",
)
replace_once(
    p,
    "\tcase MODE_SW_HORI:\n\tcase MODE_SW_PRO:\n\t\treturn ET_SWITCH;\n",
    "\tcase MODE_SW_HORI:\n"
    "\tcase MODE_SW_PRO:\n"
    "\tcase MODE_JOYCON2:\n"
    "\t\treturn ET_SWITCH;\n",
    "switch type",
)

# Controller dispatch.
p = Path("OpenPuck/controllers.cpp")
replace_once(
    p,
    '#include "mode_xbox_og.h"\n',
    '#include "mode_xbox_og.h"\n#include "mode_joycon2.h"\n',
    "controller include",
)
replace_once(
    p,
    "\tcase MODE_SINPUT:\n\t\treturn &g_sinputCtl;\n",
    "\tcase MODE_SINPUT:\n"
    "\t\treturn &g_sinputCtl;\n"
    "\tcase MODE_JOYCON2:\n"
    "\t\treturn &g_joyCon2;\n",
    "controller dispatch",
)

# Register the custom two-interface Joy-Con class driver.
p = Path("OpenPuck/usb_app_drivers.h")
replace_once(
    p,
    "const usbd_class_driver_t *xboxOgClassDriver(void);\n",
    "const usbd_class_driver_t *xboxOgClassDriver(void);\n"
    "const usbd_class_driver_t *joyCon2ClassDriver(void);\n",
    "driver declaration",
)
p = Path("OpenPuck/usb_app_drivers.cpp")
replace_once(
    p,
    "\t\t*xboxOgClassDriver(),\n",
    "\t\t*xboxOgClassDriver(),\n\t\t*joyCon2ClassDriver(),\n",
    "driver registry",
)

# Device/config/HID wrappers required to present captured descriptors exactly.
p = Path("Makefile")
replace_once(
    p,
    "OPENPUCK_LINK_FLAGS ?= -Wl,--wrap=tud_vendor_control_xfer_cb\n",
    "OPENPUCK_LINK_FLAGS ?= -Wl,--wrap=tud_vendor_control_xfer_cb "
    "-Wl,--wrap=tud_descriptor_device_cb "
    "-Wl,--wrap=tud_descriptor_configuration_cb "
    "-Wl,--wrap=tud_hid_descriptor_report_cb "
    "-Wl,--wrap=tud_hid_get_report_cb "
    "-Wl,--wrap=tud_hid_set_report_cb\n",
    "link wrappers",
)

# Give the Joy-Con device-level Nintendo requests first refusal. Joy-Con mode
# omits WebUSB, but the Adafruit callback still owns the global symbol.
p = Path("OpenPuck/webusb_config.cpp")
replace_once(
    p,
    "bool xboxOgVendorControlXfer(uint8_t rhport, uint8_t stage,\n"
    "\t\t\t     const tusb_control_request_t *request);\n",
    "bool xboxOgVendorControlXfer(uint8_t rhport, uint8_t stage,\n"
    "\t\t\t     const tusb_control_request_t *request);\n"
    "bool joyCon2VendorControlXfer(uint8_t rhport, uint8_t stage,\n"
    "\t\t\t      const tusb_control_request_t *request);\n",
    "vendor declaration",
)
replace_once(
    p,
    "\tif (g_usbMode == MODE_XBOX_OG &&\n"
    "\t    xboxOgVendorControlXfer(rhport, stage, request))\n"
    "\t\treturn true;\n"
    "\treturn __real_tud_vendor_control_xfer_cb(rhport, stage, request);\n",
    "\tif (g_usbMode == MODE_JOYCON2 &&\n"
    "\t    joyCon2VendorControlXfer(rhport, stage, request))\n"
    "\t\treturn true;\n"
    "\tif (g_usbMode == MODE_XBOX_OG &&\n"
    "\t    xboxOgVendorControlXfer(rhport, stage, request))\n"
    "\t\treturn true;\n"
    "\treturn __real_tud_vendor_control_xfer_cb(rhport, stage, request);\n",
    "vendor routing",
)

# Keep the physical Joy-Con descriptor clean: no wake mouse or WebUSB. The G5
# hardware artifact forces this mode at boot so persisted mode state cannot
# accidentally make the discriminator enumerate as another personality.
p = Path("OpenPuck/OpenPuck.ino")
text = p.read_text(encoding="utf-8")
old = "static const char MODE_SUFFIX[] = { 'X', 'N', 'L', 'P', 'S', 'G',\n\t\t\t\t    'Q', 'D', '3', 'O', 'J', 'I' };"
new = "static const char MODE_SUFFIX[] = { 'X', 'N', 'L', 'P', 'S', 'G',\n\t\t\t\t    'Q', 'D', '3', 'O', 'J', 'I', '2' };"
if text.count(old) != 1:
    raise SystemExit("G5 mode suffix anchor mismatch")
text = text.replace(old, new, 1)
old = "\tloadCfg();\n\tloadBonds();\n"
new = (
    "\tloadCfg();\n"
    "#if defined(OPK_G5_FORCE_JOYCON2) && OPK_G5_FORCE_JOYCON2\n"
    "\tg_usbMode = MODE_JOYCON2;\n"
    "#endif\n"
    "\tloadBonds();\n"
)
if text.count(old) != 1:
    raise SystemExit("G5 force-mode anchor mismatch")
text = text.replace(old, new, 1)
old = "\tconst bool psClean = modeIsCleanPS(g_usbMode);\n\tconst bool dynamic = g_active->dynamicMount();\n"
new = (
    "\tconst bool psClean = modeIsCleanPS(g_usbMode);\n"
    "\tconst bool joyCon2Clean = g_usbMode == MODE_JOYCON2;\n"
    "\tconst bool dynamic = g_active->dynamicMount();\n"
)
if text.count(old) != 1:
    raise SystemExit("G5 clean-mode anchor mismatch")
text = text.replace(old, new, 1)
old = "\t\tif (!puckMode && !keepCdc && !psClean)\n\t\t\twakeHidBegin();\n"
new = "\t\tif (!puckMode && !keepCdc && !psClean && !joyCon2Clean)\n\t\t\twakeHidBegin();\n"
if text.count(old) != 1:
    raise SystemExit("G5 wake anchor mismatch")
text = text.replace(old, new, 1)
old = "\t\tif (!puckMode && !psClean)\n\t\t\tusb_web.begin();\n"
new = "\t\tif (!puckMode && !psClean && !joyCon2Clean)\n\t\t\tusb_web.begin();\n"
if text.count(old) != 1:
    raise SystemExit("G5 webusb anchor mismatch")
text = text.replace(old, new, 1)
old = (
    "\t\tUSBDevice.setConfigurationAttribute(psClean ? 0x80 :\n"
    "\t\t\t\t\t\t\t      (0x80 | 0x20));\n"
)
new = (
    "\t\tUSBDevice.setConfigurationAttribute(joyCon2Clean ? 0xc0 :\n"
    "\t\t\t\t\t\t\t      (psClean ? 0x80 : (0x80 | 0x20)));\n"
    "\t\tif (joyCon2Clean)\n"
    "\t\t\tUSBDevice.setConfigurationMaxPower(500);\n"
)
if text.count(old) != 1:
    raise SystemExit("G5 config attribute anchor mismatch")
text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

print("F27-G5 clean Joy-Con 2 integration applied")
