#!/usr/bin/env python3
from pathlib import Path

P = Path("OpenPuck/mode_switch2_pro.cpp")
s = P.read_text(encoding="utf-8")
for x in (
    "F27-M32-ADA-HID-PARITY",
    "M32_JCR_HID_DESC[100]",
    "static Adafruit_USBD_HID g_m32SiblingHid[3]",
    "M27-M32-ADA-HID-r389-raw",
):
    if x not in s:
        raise SystemExit(f"M35 requires {x}")
if "F27-M35-FOUR-JCR" in s:
    raise SystemExit("M35 already applied")

s = s.replace(
    'static const char M32_BUILD_MARKER[] __attribute__((used)) = "F27-M32-ADA-HID-PARITY";',
    'static const char M32_BUILD_MARKER[] __attribute__((used)) = "F27-M32-ADA-HID-PARITY";\n'
    'static const char M35_BUILD_MARKER[] __attribute__((used)) = "F27-M35-FOUR-JCR";',
    1,
)
s = s.replace(
    'asm volatile("" : : "r"(M32_BUILD_MARKER) : "memory");',
    'asm volatile("" : : "r"(M32_BUILD_MARKER) : "memory");\n\t'
    'asm volatile("" : : "r"(M35_BUILD_MARKER) : "memory");',
    1,
)

old_begin = '''\t\t\tconst uint8_t *desc = (i == 1) ? M32_JCR_HID_DESC : M32_JCL_HID_DESC;\n\t\t\tg_m32SiblingHid[i].setReportDescriptor(desc, 100);'''
new_begin = '''\t\t\tg_m32SiblingHid[i].setReportDescriptor(M32_JCR_HID_DESC, 100);'''
if s.count(old_begin) != 1:
    raise SystemExit("M35 sibling descriptor anchor mismatch")
s = s.replace(old_begin, new_begin, 1)

old_rid = '''static uint8_t m32NativeRid(uint8_t hid)\n{\n\treturn (hid & 1u) ? 0x07 : 0x08;\n}'''
new_rid = '''static uint8_t m32NativeRid(uint8_t hid)\n{\n\t(void)hid;\n\treturn 0x08;\n}'''
if s.count(old_rid) != 1:
    raise SystemExit("M35 rid anchor mismatch")
s = s.replace(old_rid, new_rid, 1)

start = s.index("static bool m32BuildNative(uint8_t hid, uint8_t bond, bool active,")
end = s.index("\nstatic void m32TraceHidEvent", start)
new_builder = r'''static bool m32BuildNative(uint8_t hid, uint8_t bond, bool active,
			   uint8_t out[63])
{
	(void)hid;
	uint8_t rid = 0;
	g_sw2SessionCtx = M15_SW2_PRO;
	bool ok = m29BuildSession0Native(bond,
					g_sw2Sessions[M15_SW2_PRO].features, &rid, out);
	g_sw2SessionCtx = M15_SW2_PRO;
	if (!ok)
		return false;
	out[3] &= 0x3f;
	if (!active) {
		uint8_t counter = out[0], power = out[1];
		memset(out + 2, 0, 61);
		out[0] = counter;
		out[1] = power;
		out[4] = 0x07;
		sw2PackStick(out + 5, 0, 0);
		out[0x0d] = 0xff;
		out[0x0e] = 0;
		out[0x0f] = 0;
	}
	return true;
}
'''
s = s[:start] + new_builder + s[end:]

# All four selector paths are JCRs. The existing M32 sender already emits all
# four paths through HID0 plus three real Adafruit_USBD_HID siblings.
s = s.replace("M27-M32-ADA-HID-r389-raw", "M27-M35-FOUR-JCR-r392-raw")
s = s.replace("0x39334D52UL", "0x32334D52UL")
s = s.replace("r.e ? 'L' : 'R'", "'R'")

P.write_text(s, encoding="utf-8")
print("F27-M35 r392 four JCR discriminator applied")
