#!/usr/bin/env python3
"""Apply F27-M17 generic USB mouse alongside Switch 2 Pro.

M17 abandons the failed hidden Joy-Con session path. It keeps the reconciled
Switch 2 Pro composite first and unchanged, then appends one standard HID boot
mouse interface after the Nintendo IF0-4 / EP1-3 block. The right Steam
trackpad drives that ordinary USB mouse using the already-proven OpenPuck
XInput mouse glide/scaling model.
"""
from pathlib import Path

PATH = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"F27-M17 {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
if "F27-M17-PRO-GENERIC-HID-MOUSE" in src:
    raise SystemExit("F27-M17 already applied")

anchor = "Switch2ProController g_switch2Pro;\n\n"
insert = r'''Switch2ProController g_switch2Pro;

// F27-M17-PRO-GENERIC-HID-MOUSE
// Keep Nintendo's captured Switch2Pro composite first (IF0-4 / EP1-3), then
// append an ordinary USB boot-mouse HID. This deliberately does not attempt a
// second Nintendo controller identity: M15/M16 showed that a second S2
// function behind the same USB address is neither surfaced nor consumed for
// Joy-Con mouse semantics.
static const uint8_t M17_MOUSE_HID_DESC[] = { TUD_HID_REPORT_DESC_MOUSE() };
static Adafruit_USBD_HID g_m17Mouse;
static volatile const char M17_BUILD_MARKER[] =
	"F27-M17-PRO-GENERIC-HID-MOUSE";

struct M17MouseState {
	int16_t x;
	int16_t y;
	float vx;
	float vy;
	float remX;
	float remY;
	bool touched;
	uint8_t buttons;
};
static M17MouseState g_m17MouseState;

static void m17GenericMouseTask()
{
	if (!g_usbMountCount || !g_m17Mouse.ready())
		return;
	int bond = g_usbToBond[0];
	if (bond < 0 || bond >= NSLOT)
		return;

	uint32_t b = g_in[bond].buttons;
	bool touch = (g_padStick[1] == PS_OFF) && (b & TB_RPADT);
	int16_t rx = g_in[bond].rpx, ry = g_in[bond].rpy;
	if (touch) {
		if (g_m17MouseState.touched) {
			g_m17MouseState.vx += (float)(rx - g_m17MouseState.x);
			g_m17MouseState.vy += (float)(ry - g_m17MouseState.y);
		}
		g_m17MouseState.x = rx;
		g_m17MouseState.y = ry;
	}
	g_m17MouseState.touched = touch;

	int div = g_mDiv > 0 ? g_mDiv : 64;
	float mxf = g_m17MouseState.vx / (float)(div * 10) +
		    g_m17MouseState.remX;
	float myf = -(g_m17MouseState.vy / (float)(div * 10)) +
		    g_m17MouseState.remY;
	int dx = (int)mxf, dy = (int)myf;
	g_m17MouseState.remX = mxf - dx;
	g_m17MouseState.remY = myf - dy;
	if (dx > 127)
		dx = 127;
	else if (dx < -127)
		dx = -127;
	if (dy > 127)
		dy = 127;
	else if (dy < -127)
		dy = -127;

	float friction = g_mFric / 100.0f;
	g_m17MouseState.vx *= friction;
	g_m17MouseState.vy *= friction;
	if (g_m17MouseState.vx > -1.0f && g_m17MouseState.vx < 1.0f)
		g_m17MouseState.vx = 0;
	if (g_m17MouseState.vy > -1.0f && g_m17MouseState.vy < 1.0f)
		g_m17MouseState.vy = 0;

	uint8_t buttons = ((b & TB_RPADC) ? 1u : 0u) |
			  ((b & TB_LPADC) ? 2u : 0u);
	if (!dx && !dy && buttons == g_m17MouseState.buttons)
		return;
	g_m17MouseState.buttons = buttons;

	hid_mouse_report_t report;
	report.buttons = buttons;
	report.x = (int8_t)dx;
	report.y = (int8_t)dy;
	report.wheel = 0;
	report.pan = 0;
	usbTxHid(&g_m17Mouse, 0, &report, sizeof report);
}

'''
src = replace_once(src, anchor, insert, "mouse interface insertion")

old_pool = '''void Switch2ProController::beginPool()\n{\n\tif (!g_sw2DrainRegistered) {\n\t\tusbTxRegisterDrain(sw2Drain);\n\t\tg_sw2DrainRegistered = true;\n\t}\n}\nvoid Switch2ProController::mountSlots(uint8_t k)\n{\n\tif (k)\n\t\tUSBDevice.addInterface(g_sw2Usb);\n}\nvoid Switch2ProController::task()\n{\n\t// Report and vendor transfers are drained by usbTxPump() so endpoint\n\t// submission shares the same priority-inversion protection as other modes.\n}\n'''
new_pool = '''void Switch2ProController::beginPool()\n{\n\t// M17: begin the generic mouse object here, but append its USB interface\n\t// only AFTER the fixed Nintendo composite in mountSlots(). This preserves\n\t// Switch2Pro IF0-4 and EP1-3 exactly.\n\t(void)M17_BUILD_MARKER[0];\n\tg_m17Mouse.setStringDescriptor("OpenPuck Mouse");\n\tg_m17Mouse.setBootProtocol(HID_ITF_PROTOCOL_MOUSE);\n\tg_m17Mouse.setReportDescriptor(M17_MOUSE_HID_DESC,\n\t\t\t\t       sizeof M17_MOUSE_HID_DESC);\n\tg_m17Mouse.setPollInterval(1);\n\tg_m17Mouse.begin();\n\tif (!g_sw2DrainRegistered) {\n\t\tusbTxRegisterDrain(sw2Drain);\n\t\tg_sw2DrainRegistered = true;\n\t}\n}\nvoid Switch2ProController::mountSlots(uint8_t k)\n{\n\tif (k) {\n\t\tUSBDevice.addInterface(g_sw2Usb);\n\t\tUSBDevice.addInterface(g_m17Mouse);\n\t}\n}\nvoid Switch2ProController::task()\n{\n\t// Report and vendor transfers are drained by usbTxPump() so endpoint\n\t// submission shares the same priority-inversion protection as other modes.\n\tm17GenericMouseTask();\n}\n'''
src = replace_once(src, old_pool, new_pool, "controller pool/task")

PATH.write_text(src, encoding="utf-8")
print("F27-M17 generic HID mouse experiment applied")
