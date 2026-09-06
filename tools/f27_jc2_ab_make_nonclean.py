#!/usr/bin/env python3
"""Transform the common corrected JC2 source into B: non-clean composite.

This is intentionally the only A/B USB-policy delta: the Joy-Con HID/vendor
function stays first and unchanged, while wake HID + WebUSB are appended and
the exact 80-byte/two-interface configuration wrapper is removed.
"""
from pathlib import Path
import re


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"JC2 B {label}: anchor count {count}, expected 1 in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


p = Path("Makefile")
replace_once(
    p,
    "-Wl,--wrap=tud_descriptor_device_cb -Wl,--wrap=tud_descriptor_configuration_cb -Wl,--wrap=tud_hid_descriptor_report_cb",
    "-Wl,--wrap=tud_descriptor_device_cb -Wl,--wrap=tud_hid_descriptor_report_cb",
    "remove configuration wrapper",
)

p = Path("OpenPuck/mode_joycon2.cpp")
src = p.read_text(encoding="utf-8")
cfg_re = re.compile(
    r'\nextern "C" uint8_t const \*__real_tud_descriptor_configuration_cb\(uint8_t index\);\n'
    r'extern "C" uint8_t const \*__wrap_tud_descriptor_configuration_cb\(uint8_t index\)\n'
    r'\{.*?\n\}\n\n',
    re.S,
)
src, n = cfg_re.subn("\n", src, count=1)
if n != 1:
    raise SystemExit("JC2 B configuration-wrapper block anchor mismatch")
src = src.replace('"F27-G5-CLEAN-JCR-GRIP08"', '"F27-JC2-AB-B-NONCLEAN-JCR"')
src = src.replace('"F27-G5-CLEAN-JCL-GRIP08"', '"F27-JC2-AB-B-NONCLEAN-JCL"')
p.write_text(src, encoding="utf-8")

p = Path("OpenPuck/OpenPuck.ino")
text = p.read_text(encoding="utf-8")
replace_pairs = [
    (
        "\tconst bool psClean = modeIsCleanPS(g_usbMode);\n\tconst bool joyCon2Clean = g_usbMode == MODE_JOYCON2;\n\tconst bool dynamic = g_active->dynamicMount();\n",
        "\tconst bool psClean = modeIsCleanPS(g_usbMode);\n\tconst bool dynamic = g_active->dynamicMount();\n",
        "clean flag",
    ),
    (
        "\t\tif (!puckMode && !keepCdc && !psClean && !joyCon2Clean)\n\t\t\twakeHidBegin();\n",
        "\t\tif (!puckMode && !keepCdc && !psClean)\n\t\t\twakeHidBegin();\n",
        "wake HID",
    ),
    (
        "\t\tif (!puckMode && !psClean && !joyCon2Clean)\n\t\t\tusb_web.begin();\n",
        "\t\tif (!puckMode && !psClean)\n\t\t\tusb_web.begin();\n",
        "WebUSB",
    ),
    (
        "\t\tUSBDevice.setConfigurationAttribute(joyCon2Clean ? 0xc0 :\n\t\t\t\t\t\t\t      (psClean ? 0x80 : (0x80 | 0x20)));\n\t\tif (joyCon2Clean)\n\t\t\tUSBDevice.setConfigurationMaxPower(500);\n",
        "\t\tUSBDevice.setConfigurationAttribute(psClean ? 0x80 :\n\t\t\t\t\t\t\t      (0x80 | 0x20));\n",
        "configuration attributes",
    ),
]
for old, new, label in replace_pairs:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"JC2 B {label} anchor count {count}, expected 1")
    text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")
print("F27 JC2 A/B non-clean transform applied")
