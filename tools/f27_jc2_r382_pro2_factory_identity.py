#!/usr/bin/env python3
"""R382: replace only the direct-JCR C0/03 factory identity payload.

Apply after the complete r380 direct-JCR raw-trace composition. USB VID/PID,
descriptors, endpoints, protocol reply, Nintendo bulk handling, trace hooks, and
persistence behavior remain unchanged. The sole intended protocol delta is that
JOYCON2_FACTORY_ID[64] becomes the exact known-working M27 Pro2 factory identity.
"""
from pathlib import Path
import re

P = Path("OpenPuck/mode_joycon2.cpp")
s = P.read_text(encoding="utf-8")

pat = re.compile(
    r"static const uint8_t JOYCON2_FACTORY_ID\[64\] = \{.*?\n\};",
    re.S,
)
m = pat.search(s)
if not m:
    raise SystemExit("R382: JOYCON2_FACTORY_ID[64] not found")

replacement = r'''static const uint8_t JOYCON2_FACTORY_ID[64] = {
	0x01, 0x00, 'H',  'E',  'W',  '7',  '0',  '0',  '0',  '6',  '1',
	'6',  '9',  '7',  '8',  '0',  0x00, 0x00, 0x7e, 0x05, 0x69, 0x20,
	0x01, 0x06, 0x01, 0x23, 0x23, 0x23, 0xa0, 0xa0, 0xa0, 0xe6, 0xe6,
	0xe6, 0x32, 0x32, 0x32, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
};'''

s2, n = pat.subn(replacement, s, count=1)
if n != 1:
    raise SystemExit(f"R382: factory identity replacement count {n}")

# Guard the actual physical personality: this experiment must still enumerate
# as a Joy-Con 2 (R), not as a Pro Controller 2.
for required in (
    "#define JC2_PID 0x2066",
    '#define JC2_PRODUCT "Joy-Con 2 (R)"',
    "#define JC2_NATIVE_REPORT 0x08",
    "USBDevice.setID(0x057e, JC2_PID);",
):
    if required not in s2:
        raise SystemExit("R382: physical JCR guard missing: " + required)

P.write_text(s2, encoding="utf-8")
print("F27 JC2 r382 Pro2 C0/03 factory identity probe applied")
