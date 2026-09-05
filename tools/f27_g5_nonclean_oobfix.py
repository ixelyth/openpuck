#!/usr/bin/env python3
"""Convert the latest G5 Joy-Con 2 endpoint to the normal OpenPuck composite policy.

Applied after f27_g5_integrate.py and f27_g5_re_refresh.py.  This keeps the
latest Joy-Con identity/HID/vendor/Charging-Grip implementation intact while:
  * fixing the MODE_NAME[13] out-of-bounds bug;
  * exposing normal wake-HID + WebUSB interfaces like HORIPAD;
  * removing the exact 80-byte/two-interface configuration-descriptor wrapper;
  * replacing permanent force-mode with a once-per-build JCR startup marker so
    normal mode changes work after the first boot.
"""
from pathlib import Path
import re


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"G5 nonclean {label}: anchor count {count}, expected 1 in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# The Joy-Con mode is now a normal composite OpenPuck mode.  Keep the exact
# device and HID callbacks, but let TinyUSB emit the full generated config so
# the Joy-Con HID/vendor pair can be followed by wake HID + WebUSB.
p = Path("Makefile")
replace_once(
    p,
    "-Wl,--wrap=tud_descriptor_device_cb -Wl,--wrap=tud_descriptor_configuration_cb -Wl,--wrap=tud_hid_descriptor_report_cb",
    "-Wl,--wrap=tud_descriptor_device_cb -Wl,--wrap=tud_hid_descriptor_report_cb",
    "remove configuration wrapper link flag",
)

p = Path("OpenPuck/mode_joycon2.cpp")
src = p.read_text(encoding="utf-8")
old_top = """// mode_joycon2.cpp -- clean Nintendo Joy-Con 2 USB personality.\n//\n// F27-G5 deliberately starts from upstream OpenPuck rather than the Switch 2 Pro\n// implementation. USB identity/descriptors come from captured Joy-Con 2 L/R\n// descriptors published by ndeadly/switch2_controller_research. Nintendo bulk\n// command framing, controller types, report IDs, feature selection and Charging\n// Grip command 0x08 are cross-checked against novakpetya/linux-switch2 and the\n// current Linux Switch 2 driver carried by martin-bts/hid-switch2-dkms.\n//\n// There are exactly two USB interfaces: IF0 HID interrupt IN/OUT and IF1\n// Nintendo vendor bulk IN/OUT. There is intentionally no Pro2 report 0x09,\n// audio function, WebUSB interface, wake mouse, or Switch2Pro source dependency.\n"""
new_top = """// mode_joycon2.cpp -- Nintendo Joy-Con 2 USB personality.\n//\n// F27-G5 deliberately starts from upstream OpenPuck rather than the Switch 2 Pro\n// implementation. USB identity/descriptors come from captured Joy-Con 2 L/R\n// descriptors published by ndeadly/switch2_controller_research. Nintendo bulk\n// command framing, controller types, report IDs, feature selection and Charging\n// Grip command 0x08 are cross-checked against novakpetya/linux-switch2 and the\n// current Linux Switch 2 driver carried by martin-bts/hid-switch2-dkms.\n//\n// The Joy-Con function itself remains IF0 HID interrupt IN/OUT plus IF1 Nintendo\n// vendor bulk IN/OUT. In this non-clean build the normal OpenPuck wake HID and\n// WebUSB interfaces are appended afterward, matching the proven HORIPAD composite\n// policy. There is still no Pro2 report 0x09, audio function, or Switch2Pro source\n// dependency.\n"""
if src.count(old_top) != 1:
    raise SystemExit("G5 nonclean top-comment anchor mismatch")
src = src.replace(old_top, new_top, 1)

cfg_re = re.compile(
    r'\nextern "C" uint8_t const \*__real_tud_descriptor_configuration_cb\(uint8_t index\);\n'
    r'extern "C" uint8_t const \*__wrap_tud_descriptor_configuration_cb\(uint8_t index\)\n'
    r'\{.*?\n\}\n\n',
    re.S,
)
src, n = cfg_re.subn("\n", src, count=1)
if n != 1:
    raise SystemExit("G5 nonclean configuration-wrapper block anchor mismatch")
p.write_text(src, encoding="utf-8")

p = Path("OpenPuck/OpenPuck.ino")
text = p.read_text(encoding="utf-8")

# Fix the confirmed mode-13 OOB read after USB attach.
old = '\t\t"SINPUT(sdl-native)"\n\t};'
new = '\t\t"SINPUT(sdl-native)",\n\t\t"JOYCON2(jcr/jcl)"\n\t};'
if text.count(old) != 1:
    raise SystemExit("G5 nonclean MODE_NAME anchor mismatch")
text = text.replace(old, new, 1)

# Replace permanent force mode with a once-per-build marker.  First boot of a
# new firmware hash enters Joy-Con directly; after that saveMode()/bootMode and
# persistence behave exactly like main, including switching back to Steam.
old = (
    "\tloadCfg();\n"
    "#if defined(OPK_G5_FORCE_JOYCON2) && OPK_G5_FORCE_JOYCON2\n"
    "\tg_usbMode = MODE_JOYCON2;\n"
    "#endif\n"
    "\tloadBonds();\n"
)
new = (
    "\tloadCfg();\n"
    "#if defined(OPK_G5_START_JOYCON2_ONCE) && OPK_G5_START_JOYCON2_ONCE\n"
    "\t{\n"
    "\t\tstatic const char tagPath[] = \"/jc2mode\";\n"
    "\t\tchar tag[24] = { 0 };\n"
    "\t\tbool startJoyCon2 = true;\n"
    "\t\tFile f(InternalFS);\n"
    "\t\tif (f.open(tagPath, FILE_O_READ)) {\n"
    "\t\t\tint n = f.read((uint8_t *)tag, sizeof tag - 1);\n"
    "\t\t\tif (n > 0)\n"
    "\t\t\t\ttag[n] = 0;\n"
    "\t\t\tf.close();\n"
    "\t\t\tstartJoyCon2 = strncmp(tag, OPK_GIT_HASH, sizeof tag - 1) != 0;\n"
    "\t\t}\n"
    "\t\tif (startJoyCon2) {\n"
    "\t\t\tg_usbMode = MODE_JOYCON2;\n"
    "\t\t\tapplyActiveType();\n"
    "\t\t\tInternalFS.remove(tagPath);\n"
    "\t\t\tFile g(InternalFS);\n"
    "\t\t\tif (g.open(tagPath, FILE_O_WRITE)) {\n"
    "\t\t\t\tg.write((const uint8_t *)OPK_GIT_HASH, strlen(OPK_GIT_HASH));\n"
    "\t\t\t\tg.close();\n"
    "\t\t\t}\n"
    "\t\t}\n"
    "\t}\n"
    "#endif\n"
    "\tloadBonds();\n"
)
if text.count(old) != 1:
    raise SystemExit("G5 nonclean force-mode anchor mismatch")
text = text.replace(old, new, 1)

# Restore the same composite policy used by HORIPAD: controller first, then
# wake HID and WebUSB.  The standard OpenPuck remote-wakeup attribute applies.
old = (
    "\tconst bool psClean = modeIsCleanPS(g_usbMode);\n"
    "\tconst bool joyCon2Clean = g_usbMode == MODE_JOYCON2;\n"
    "\tconst bool dynamic = g_active->dynamicMount();\n"
)
new = (
    "\tconst bool psClean = modeIsCleanPS(g_usbMode);\n"
    "\tconst bool dynamic = g_active->dynamicMount();\n"
)
if text.count(old) != 1:
    raise SystemExit("G5 nonclean clean-flag anchor mismatch")
text = text.replace(old, new, 1)

old = "\t\tif (!puckMode && !keepCdc && !psClean && !joyCon2Clean)\n\t\t\twakeHidBegin();\n"
new = "\t\tif (!puckMode && !keepCdc && !psClean)\n\t\t\twakeHidBegin();\n"
if text.count(old) != 1:
    raise SystemExit("G5 nonclean wake anchor mismatch")
text = text.replace(old, new, 1)

old = "\t\tif (!puckMode && !psClean && !joyCon2Clean)\n\t\t\tusb_web.begin();\n"
new = "\t\tif (!puckMode && !psClean)\n\t\t\tusb_web.begin();\n"
if text.count(old) != 1:
    raise SystemExit("G5 nonclean webusb anchor mismatch")
text = text.replace(old, new, 1)

old = (
    "\t\tUSBDevice.setConfigurationAttribute(joyCon2Clean ? 0xc0 :\n"
    "\t\t\t\t\t\t\t      (psClean ? 0x80 : (0x80 | 0x20)));\n"
    "\t\tif (joyCon2Clean)\n"
    "\t\t\tUSBDevice.setConfigurationMaxPower(500);\n"
)
new = (
    "\t\tUSBDevice.setConfigurationAttribute(psClean ? 0x80 :\n"
    "\t\t\t\t\t\t\t      (0x80 | 0x20));\n"
)
if text.count(old) != 1:
    raise SystemExit("G5 nonclean configuration-attribute anchor mismatch")
text = text.replace(old, new, 1)

p.write_text(text, encoding="utf-8")
print("F27-G5 latest Joy-Con non-clean + mode-table fix applied")
