#!/usr/bin/env python3
"""F27-G5-R2: keep the captured IF1 descriptor but do not open bulk endpoints.

R1 proved the G5 reset/re-enumeration loop is not caused by the extra
configuration-descriptor callback wrapper.  R2 therefore changes only the
Nintendo vendor-interface bring-up relative to R1: IF1 is still present in the
captured two-interface configuration and is still claimed by the Joy-Con app
class driver, but EP02/EP82 are not opened or armed.  No Nintendo bulk traffic
can occur.  HID IF0, device identity, report descriptors and protocol source
remain otherwise unchanged.
"""
from pathlib import Path

p = Path("OpenPuck/mode_joycon2.cpp")
s = p.read_text(encoding="utf-8")
start_needle = "\tif (itf->bInterfaceNumber == 1 && itf->bInterfaceClass == 0xff) {\n"
end_needle = "\n\treturn 0;\n}\n\nstatic bool driverControl"
start = s.find(start_needle)
if start < 0:
    raise SystemExit("G5-R2 vendor IF1 start anchor missing")
end = s.find(end_needle, start)
if end < 0:
    raise SystemExit("G5-R2 driverOpen end anchor missing")
old = s[start:end]
if old.count("usbd_edpt_open") != 1 or old.count("usbd_edpt_xfer") != 1:
    raise SystemExit("G5-R2 expected exactly one vendor open and one initial OUT arm")
new = r'''\tif (itf->bInterfaceNumber == 1 && itf->bInterfaceClass == 0xff) {
\t\t// G5-R2 enumeration discriminator: claim the captured Nintendo vendor
\t\t// interface descriptor, but deliberately leave its bulk endpoints closed.
\t\t// This isolates endpoint open/arm/xfer runtime from the descriptor shell.
\t\tuint8_t const *p = (uint8_t const *)itf;
\t\tuint8_t const *end = p + maxLen;
\t\tuint16_t used = 0;
\t\tuint8_t endpoints = 0;
\t\twhile (p < end) {
\t\t\tuint16_t remaining = (uint16_t)(end - p);
\t\t\tif (remaining < 2 || p[0] < 2 || p[0] > remaining)
\t\t\t\treturn 0;
\t\t\tuint8_t len = p[0], type = p[1];
\t\t\tif (p != (uint8_t const *)itf &&
\t\t\t    (type == TUSB_DESC_INTERFACE ||
\t\t\t     type == TUSB_DESC_INTERFACE_ASSOCIATION))
\t\t\t\tbreak;
\t\t\tif (type == TUSB_DESC_ENDPOINT)
\t\t\t\tendpoints++;
\t\t\tused += len;
\t\t\tp += len;
\t\t}
\t\tif (endpoints != 2)
\t\t\treturn 0;
\t\tg_jc2VendorEpOut = 0;
\t\tg_jc2VendorEpIn = 0;
\t\treturn used;
\t}'''
s = s[:start] + new + s[end:]
p.write_text(s, encoding="utf-8")
print("F27-G5-R2 retained vendor descriptor but stubbed bulk endpoint bring-up")
