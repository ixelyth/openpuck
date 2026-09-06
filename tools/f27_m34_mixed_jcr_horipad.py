#!/usr/bin/env python3
from pathlib import Path

P = Path("OpenPuck/mode_switch2_pro.cpp")
s = P.read_text(encoding="utf-8")
for x in ("F27-M32-ADA-HID-PARITY", "M32_JCL_HID_DESC[100]", "static Adafruit_USBD_HID g_m32SiblingHid[3]", "M27-M32-ADA-HID-r389-raw"):
    if x not in s:
        raise SystemExit(f"M34 requires {x}")
if "F27-M34-JCR-3HORIPAD" in s:
    raise SystemExit("M34 already applied")

s = s.replace(
    'static const char M32_BUILD_MARKER[] __attribute__((used)) = "F27-M32-ADA-HID-PARITY";',
    'static const char M32_BUILD_MARKER[] __attribute__((used)) = "F27-M32-ADA-HID-PARITY";\n'
    'static const char M34_BUILD_MARKER[] __attribute__((used)) = "F27-M34-JCR-3HORIPAD";', 1)
s = s.replace(
    'asm volatile("" : : "r"(M32_BUILD_MARKER) : "memory");',
    'asm volatile("" : : "r"(M32_BUILD_MARKER) : "memory");\n\tasm volatile("" : : "r"(M34_BUILD_MARKER) : "memory");', 1)

insert = r'''
static const uint8_t M34_HORIPAD_HID_DESC[123] = {
	0x05,0x01,0x09,0x05,0xA1,0x01,0x05,0x09,0x19,0x01,0x29,0x0E,0x15,0x00,0x25,0x01,
	0x35,0x00,0x45,0x01,0x65,0x00,0x55,0x00,0x75,0x01,0x95,0x0E,0x81,0x02,0x95,0x02,
	0x81,0x03,0x05,0x01,0x09,0x39,0x25,0x07,0x46,0x3B,0x01,0x65,0x14,0x75,0x04,0x95,
	0x01,0x81,0x42,0x25,0x01,0x45,0x01,0x65,0x00,0x75,0x01,0x95,0x03,0x81,0x03,0x05,
	0x09,0x09,0x0F,0x95,0x01,0x81,0x02,0x05,0x01,0x09,0x30,0x25,0xFF,0x45,0xFF,0x75,
	0x08,0x81,0x02,0x09,0x31,0x81,0x02,0x09,0x32,0x81,0x02,0x09,0x35,0x81,0x02,0x25,
	0x01,0x45,0x01,0x75,0x01,0x95,0x08,0x81,0x03,0x0A,0x4F,0x48,0x25,0xFF,0x45,0xFF,
	0x75,0x08,0x91,0x02,0x0A,0x4F,0x48,0xB1,0x02,0xC1,0x00
};
static_assert(sizeof M34_HORIPAD_HID_DESC == 123,
	      "M34 HORIPAD descriptor must remain byte-exact");

static uint8_t m34Stick(int16_t v, bool invert)
{
	int32_t x = invert ? -(int32_t)v : (int32_t)v;
	x = (x + 32768) >> 8;
	if (x < 0) x = 0;
	if (x > 255) x = 255;
	return (uint8_t)x;
}

static void m34BuildHoripad(uint8_t bond, uint32_t selectorBit, uint8_t out[8])
{
	uint32_t b = g_in[bond].buttons & ~selectorBit;
	uint16_t btn = 0;
	uint16_t fY = g_abSwap ? 0x08 : 0x01;
	uint16_t fB = g_abSwap ? 0x04 : 0x02;
	uint16_t fA = g_abSwap ? 0x02 : 0x04;
	uint16_t fX = g_abSwap ? 0x01 : 0x08;
	if (b & TB_Y) btn |= fY;
	if (b & TB_B) btn |= fB;
	if (b & TB_A) btn |= fA;
	if (b & TB_X) btn |= fX;
	if (b & TB_LB) btn |= 0x10;
	if (b & TB_RB) btn |= 0x20;
	if (g_in[bond].lt >= SW_TRIG_ON || (b & 0x8000000u)) btn |= 0x40;
	if (g_in[bond].rt >= SW_TRIG_ON || (b & 0x800000u)) btn |= 0x80;
	if (b & TB_MENU) btn |= 0x100;
	if (b & TB_VIEW) btn |= 0x200;
	if (b & TB_L3) btn |= 0x400;
	if (b & TB_R3) btn |= 0x800;
	if (b & TB_STEAM) btn |= 0x1000;
	bool u = b & TB_DUP, d = b & TB_DDN, l = b & TB_DLF, r = b & TB_DRT;
	uint8_t hat = 8;
	if (u && r) hat = 1;
	else if (r && d) hat = 3;
	else if (d && l) hat = 5;
	else if (l && u) hat = 7;
	else if (u) hat = 0;
	else if (r) hat = 2;
	else if (d) hat = 4;
	else if (l) hat = 6;
	out[0] = (uint8_t)btn; out[1] = (uint8_t)(btn >> 8); out[2] = hat;
	out[3] = m34Stick(g_in[bond].lx, false); out[4] = m34Stick(g_in[bond].ly, true);
	out[5] = m34Stick(g_in[bond].rx, false); out[6] = m34Stick(g_in[bond].ry, true); out[7] = 0;
}

'''
anchor = "static constexpr uint8_t M32_HID_COUNT = 4;\n"
if s.count(anchor) != 1:
    raise SystemExit("M34 descriptor anchor mismatch")
s = s.replace(anchor, insert + anchor, 1)
old = '''\t\t\tconst uint8_t *desc = (i == 1) ? M32_JCR_HID_DESC : M32_JCL_HID_DESC;\n\t\t\tg_m32SiblingHid[i].setReportDescriptor(desc, 100);'''
new = '''\t\t\tg_m32SiblingHid[i].setReportDescriptor(M34_HORIPAD_HID_DESC,\n\t\t\t\t\t\t\t   sizeof M34_HORIPAD_HID_DESC);'''
if s.count(old) != 1:
    raise SystemExit("M34 sibling descriptor anchor mismatch")
s = s.replace(old, new, 1)

start = s.index("\tuint8_t selected = m32SelectedMask((uint8_t)bond);")
end = s.index("\tg_sw2SessionCtx = M15_SW2_PRO;\n\tm27TraceService();", start)
loop = r'''\tuint8_t selected = m32SelectedMask((uint8_t)bond);
	static const uint32_t selectorBits[4] = { TB_L4, TB_R4, TB_L5, TB_R5 };
	for (uint8_t hid = 0; hid < M32_HID_COUNT; hid++) {
		uint8_t rid = hid == 0 ? 0x08 : 0x00;
		bool ready = hid == 0 ? tud_hid_n_ready(0) : g_m32SiblingHid[hid - 1u].ready();
		m32TraceHidEvent(hid, ready ? 2 : 1, ready, rid, selected);
		if (!g_sw2Sessions[M15_SW2_PRO].inputEnabled || !ready) continue;
		if ((uint32_t)(millis() - g_m32LastReportMs[hid]) < USB_STREAM_MS) continue;
		bool active = (selected & (uint8_t)(1u << hid)) != 0;
		if (hid == 0) {
			uint8_t p[63];
			if (!m32BuildNative(0, (uint8_t)bond, active, p)) continue;
			if (!tud_hid_n_report(0, 0x08, p, sizeof p)) continue;
		} else {
			uint8_t p[8] = { 0x00,0x00,0x08,0x80,0x80,0x80,0x80,0x00 };
			if (active) m34BuildHoripad((uint8_t)bond, selectorBits[hid], p);
			usbTxHid(&g_m32SiblingHid[hid - 1u], 0, p, sizeof p);
		}
		g_m32LastReportMs[hid] = millis();
		m32TraceHidEvent(hid, 3, true, rid, selected);
	}
'''
s = s[:start] + loop + s[end:]
s = s.replace("M27-M32-ADA-HID-r389-raw", "M27-M34-JCR-3HORI-r391-raw")
s = s.replace("0x39334D52UL", "0x31334D52UL")
s = s.replace("r.e ? 'L' : 'R'", "r.a == 0 ? 'R' : 'H'")
P.write_text(s, encoding="utf-8")
print("F27-M34 r391 JCR + 3 HORIPAD applied")
