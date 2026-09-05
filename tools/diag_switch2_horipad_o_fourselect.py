#!/usr/bin/env python3
from pathlib import Path

P = Path("OpenPuck/mode_switch_hori.cpp")
s = P.read_text(encoding="utf-8")

start = s.index("static const uint8_t SWITCH_HID_DESC[] = {")
end = s.index("static Adafruit_USBD_HID g_switch[NSLOT];", start)
new_desc = r'''// Exact 123-byte report descriptor from the hardware-positive F16
// Switch 2 HORIPAD O capture (0F0D:0202).
static const uint8_t SWITCH_HID_DESC[] = {
	0x05,0x01,0x09,0x05,0xA1,0x01,0x05,0x09,0x19,0x01,0x29,0x0E,0x15,0x00,0x25,0x01,
	0x35,0x00,0x45,0x01,0x65,0x00,0x55,0x00,0x75,0x01,0x95,0x0E,0x81,0x02,0x95,0x02,
	0x81,0x03,0x05,0x01,0x09,0x39,0x25,0x07,0x46,0x3B,0x01,0x65,0x14,0x75,0x04,0x95,
	0x01,0x81,0x42,0x25,0x01,0x45,0x01,0x65,0x00,0x75,0x01,0x95,0x03,0x81,0x03,0x05,
	0x09,0x09,0x0F,0x95,0x01,0x81,0x02,0x05,0x01,0x09,0x30,0x25,0xFF,0x45,0xFF,0x75,
	0x08,0x81,0x02,0x09,0x31,0x81,0x02,0x09,0x32,0x81,0x02,0x09,0x35,0x81,0x02,0x25,
	0x01,0x45,0x01,0x75,0x01,0x95,0x08,0x81,0x03,0x0A,0x4F,0x48,0x25,0xFF,0x45,0xFF,
	0x75,0x08,0x91,0x02,0x0A,0x4F,0x48,0xB1,0x02,0xC1,0x00
};
static_assert(sizeof SWITCH_HID_DESC == 123,
	      "Switch 2 HORIPAD O descriptor must remain byte-exact");
'''
s = s[:start] + new_desc + s[end:]

builder_start = s.index("static void switchBuildHoripad(")
builder_end = s.index("void SwitchHoriController::begin()", builder_start)
new_builder = r'''static uint16_t codeToSwitch2(uint8_t c, uint16_t fA, uint16_t fB,
			      uint16_t fX, uint16_t fY)
{
	switch (c) {
	case 1: return fA; case 2: return fB; case 3: return fX; case 4: return fY;
	case 5: return 0x10; case 6: return 0x20; case 7: return 0x400; case 8: return 0x800;
	case 9: return 0x100; case 10: return 0x200; case 11: return 0x1000;
	case 18: return 0x2000; case 19: return 0x40; case 20: return 0x80;
	default: return 0;
	}
}
static inline void codeToHat2(uint8_t c, bool &u, bool &d, bool &l, bool &r)
{
	if (c == 12) u = true;
	else if (c == 13) d = true;
	else if (c == 14) l = true;
	else if (c == 15) r = true;
}
static void switchBuildHoripad(uint8_t slot, uint32_t suppressButtons,
			       uint8_t out[8])
{
	uint32_t b = g_in[slot].buttons & ~suppressButtons;
	uint16_t btn = 0;
	bool chat = false;
	bool qam = g_qamMap && (b & TB_QAM);
	if ((b & CHORD_BACK4) == CHORD_BACK4)
		b &= ~(uint32_t)(TB_A | TB_X | TB_Y | TB_DUP | TB_DDN |
				 TB_DLF | TB_DRT);
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
	if (g_in[slot].lt >= SW_TRIG_ON || (b & 0x8000000u)) btn |= 0x40;
	if (g_in[slot].rt >= SW_TRIG_ON || (b & 0x800000u)) btn |= 0x80;
	if (b & TB_MENU) btn |= 0x100;
	if (b & TB_VIEW) btn |= 0x200;
	if (b & TB_L3) btn |= 0x400;
	if (b & TB_R3) btn |= 0x800;
	if (b & TB_STEAM) btn |= 0x1000;
	const uint32_t pmask[4] = { TB_L4, TB_R4, TB_L5, TB_R5 };
	for (uint8_t i = 0; i < 4; i++) {
		if (!(b & pmask[i])) continue;
		btn |= codeToSwitch2(g_back[i], fA, fB, fX, fY);
		chat |= g_back[i] == 21;
	}
	if (qam) {
		btn |= codeToSwitch2(g_qamMap, fA, fB, fX, fY);
		chat |= g_qamMap == 21;
	}
	bool u = b & TB_DUP, d = b & TB_DDN, l = b & TB_DLF, r = b & TB_DRT;
	for (uint8_t i = 0; i < 4; i++)
		if (b & pmask[i]) codeToHat2(g_back[i], u, d, l, r);
	if (qam) codeToHat2(g_qamMap, u, d, l, r);
	uint8_t hat = 8;
	if (u && r) hat = 1;
	else if (r && d) hat = 3;
	else if (d && l) hat = 5;
	else if (l && u) hat = 7;
	else if (u) hat = 0;
	else if (r) hat = 2;
	else if (d) hat = 4;
	else if (l) hat = 6;
	out[0] = (uint8_t)btn;
	out[1] = (uint8_t)(btn >> 8);
	out[2] = (uint8_t)(hat | (chat ? 0x80 : 0));
	out[3] = swStick(g_in[slot].lx, false);
	out[4] = swStick(g_in[slot].ly, true);
	out[5] = swStick(g_in[slot].rx, false);
	out[6] = swStick(g_in[slot].ry, true);
	out[7] = 0;
}

'''
s = s[:builder_start] + new_builder + s[builder_end:]

s = s.replace("USBDevice.setID(0x0F0D, 0x0092);", "USBDevice.setID(0x0F0D, 0x0202);")
s = s.replace('USBDevice.setProductDescriptor("POKKEN CONTROLLER");',
              'USBDevice.setProductDescriptor("HORIPAD O");')

old_mount = '''void SwitchHoriController::mountSlots(uint8_t k)\n{\n\tfor (uint8_t u = 0; u < k; u++)\n\t\tUSBDevice.addInterface(g_switch[u]);\n}\n'''
new_mount = '''void SwitchHoriController::mountSlots(uint8_t k)\n{\n\t(void)k;\n\tfor (uint8_t u = 0; u < maxSlots(); u++)\n\t\tUSBDevice.addInterface(g_switch[u]);\n}\n'''
if old_mount not in s:
    raise SystemExit("mountSlots anchor mismatch")
s = s.replace(old_mount, new_mount, 1)

task_start = s.index("void SwitchHoriController::task()")
new_task = r'''void SwitchHoriController::task()
{
	int bond = -1;
	for (uint8_t u = 0; u < g_usbMountCount; u++) {
		if (g_usbToBond[u] >= 0) {
			bond = g_usbToBond[u];
			break;
		}
	}
	static const uint32_t selector[NSLOT] = { TB_L4, TB_R4, TB_L5, TB_R5 };
	int selected = -1;
	uint32_t suppress = 0;
	if (bond >= 0) {
		uint32_t buttons = g_in[bond].buttons;
		for (uint8_t u = 0; u < NSLOT; u++) {
			if (!(buttons & selector[u])) continue;
			if (selected >= 0) {
				selected = -1;
				suppress = 0;
				break;
			}
			selected = (int)u;
			suppress = selector[u];
		}
	}
	const uint8_t neutral[8] = { 0x00, 0x00, 0x08, 0x80, 0x80, 0x80, 0x80, 0x00 };
	uint8_t active[8];
	if (selected >= 0)
		switchBuildHoripad((uint8_t)bond, suppress, active);
	for (uint8_t u = 0; u < maxSlots(); u++) {
		if (!g_switch[u].ready()) continue;
		if (millis() - g_swLastMs[u] < USB_STREAM_MS) continue;
		g_swLastMs[u] = millis();
		const uint8_t *p = selected == (int)u ? active : neutral;
		usbTxHid(&g_switch[u], 0, p, 8);
	}
}
'''
s = s[:task_start] + new_task + "\n"
P.write_text(s, encoding="utf-8")

out = P.read_text(encoding="utf-8")
for check in (
    "USBDevice.setID(0x0F0D, 0x0202);",
    'USBDevice.setProductDescriptor("HORIPAD O");',
    "sizeof SWITCH_HID_DESC == 123",
    "TB_L4, TB_R4, TB_L5, TB_R5",
):
    if check not in out:
        raise SystemExit(f"missing expected contract: {check}")
print("Switch 2 HORIPAD O FourSelect transform applied")
