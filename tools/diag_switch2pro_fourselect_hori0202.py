#!/usr/bin/env python3
from pathlib import Path

p = Path("OpenPuck/mode_switch2_pro.cpp")
s = p.read_text(encoding="utf-8")
old = "\tUSBDevice.setID(0x057e, 0x2069);\n"
new = "\tUSBDevice.setID(0x0f0d, 0x0202);\n"
if s.count(old) != 1:
    raise SystemExit(f"expected exactly one Switch2Pro VID/PID anchor, found {s.count(old)}")
s = s.replace(old, new, 1)

# Deliberately preserve the complete Switch2Pro protocol/report contract. Only
# the device VID/PID changes for this classification discriminator.
for required in (
    'USBDevice.setManufacturerDescriptor("Nintendo");',
    'USBDevice.setProductDescriptor("Switch 2 Pro Controller");',
    'USBDevice.setSerialDescriptor("00");',
    'static const uint8_t SWITCH2_PRO_HID_DESC[]',
    'static const uint8_t SW2_VENDOR_IDENTITY[64]',
):
    if required not in s:
        raise SystemExit(f"missing preserved Switch2Pro contract: {required}")
if "USBDevice.setID(0x057e, 0x2069);" in s:
    raise SystemExit("Nintendo VID/PID unexpectedly remains")
if "USBDevice.setID(0x0f0d, 0x0202);" not in s:
    raise SystemExit("HORI 0F0D:0202 VID/PID did not land")

p.write_text(s, encoding="utf-8")
print("Switch2Pro FourSelect HORI 0F0D:0202 identity transform applied")
