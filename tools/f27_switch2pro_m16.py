#!/usr/bin/env python3
"""Apply F27-M16 over the accepted M15 dual-session topology probe.

M16 keeps the M15 USB topology unchanged. Session 0 remains the visible
Switch 2 Pro controller. Session 1 remains the otherwise unseen Joy-Con 2 R
function, but now emits a forced native report-0x08 optical-mouse stream from
the right Steam trackpad whenever HID instance 1 is ready. The hidden session
bypasses only its vendor input-enable gate so a hardware FAIL cannot be
explained merely by the Switch never enabling that invisible controller.
"""
from pathlib import Path
import re

PATH = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"F27-M16 {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, repl: str, label: str) -> str:
    out, n = re.subn(pattern, repl, text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"F27-M16 {label}: match count {n}, expected 1")
    return out


src = PATH.read_text(encoding="utf-8")
if "M15_SW2_SESSION_COUNT = 2" not in src:
    raise SystemExit("F27-M16 requires the accepted M15 runtime composition first")
if "F27-M16-HIDDEN-JCR-MOUSE" in src:
    raise SystemExit("F27-M16 already applied")

mouse_block = r'''// F27-M16-HIDDEN-JCR-MOUSE
// Keep M15's dual USB topology unchanged, but feed the right Steam trackpad
// through the otherwise-unseen Joy-Con 2 R HID function. Mouse encoding and
// the stationary carrier follow the hardware-working F27-M3 contract. M16
// deliberately keeps ordinary Joy-Con buttons/stick neutral so all normal
// controller input continues to belong to the visible Pro2 session.
struct M16MousePadState {
	int16_t x;
	int16_t y;
	int32_t remX;
	int32_t remY;
	uint16_t motionTick;
	bool touched;
};

static M16MousePadState g_m16RightMouse;

static int16_t m16ScaledDelta(int32_t *remainder, int32_t delta)
{
	int div = g_mDiv > 0 ? g_mDiv : 64;
	int32_t total = *remainder + delta;
	int32_t value = total / div;
	*remainder = total - value * div;
	if (value > 32767)
		value = 32767;
	else if (value < -32768)
		value = -32768;
	return (int16_t)value;
}

static bool m16PadMouse(bool touch, int16_t x, int16_t y,
			int16_t *dx, int16_t *dy)
{
	*dx = 0;
	*dy = 0;
	if (!touch) {
		g_m16RightMouse.touched = false;
		g_m16RightMouse.remX = g_m16RightMouse.remY = 0;
		return false;
	}
	if (!g_m16RightMouse.touched) {
		g_m16RightMouse.x = x;
		g_m16RightMouse.y = y;
		g_m16RightMouse.remX = g_m16RightMouse.remY = 0;
		g_m16RightMouse.touched = true;
		return true;
	}

	int32_t rawX = (int32_t)x - g_m16RightMouse.x;
	int32_t rawY = (int32_t)y - g_m16RightMouse.y;
	g_m16RightMouse.x = x;
	g_m16RightMouse.y = y;
	*dx = m16ScaledDelta(&g_m16RightMouse.remX, rawX);
	*dy = m16ScaledDelta(&g_m16RightMouse.remY, -rawY);
	return true;
}

static void m16Put16(uint8_t *p, int16_t v)
{
	uint16_t u = (uint16_t)v;
	p[0] = (uint8_t)u;
	p[1] = (uint8_t)(u >> 8);
}

static void m16FlatMouseCarrier(uint8_t out[30])
{
	memset(out, 0, 30);
	g_m16RightMouse.motionTick =
		(uint16_t)((g_m16RightMouse.motionTick + 3u) & 0x0fffu);
	uint16_t timing = (uint16_t)(0x3000u | g_m16RightMouse.motionTick);
	out[0] = (uint8_t)timing;
	out[1] = (uint8_t)(timing >> 8);
	out[3] = 0x0c;
	out[8] = 0x02;
	out[12] = 0x01;
	out[15] = 0x80;
	out[16] = 0x00;
	out[17] = 0x30;
	out[18] = 0xd6;
	out[19] = 0x10;
	out[29] = 0x02;
}

static void sw2BuildJoyconRMouse(uint8_t slot, uint8_t out[63])
{
	memset(out, 0, 63);
	uint32_t buttons = g_in[slot].buttons;
	bool touch = (buttons & TB_RPADT) != 0;
	int16_t dx, dy;
	bool surface = m16PadMouse(touch, g_in[slot].rpx, g_in[slot].rpy,
				   &dx, &dy);

	out[0] = g_sw2Counter8++;
	out[1] = sw2PowerInfo(slot);
	out[4] = 0x07;
	sw2PackStick(out + 5, 0, 0);
	m16Put16(out + 0x09, dx);
	m16Put16(out + 0x0b, dy);
	out[0x0d] = surface ? 0x17 : 0xff;
	out[0x0e] = 0;
	if (surface) {
		uint8_t carrier[30];
		m16FlatMouseCarrier(carrier);
		out[0x0f] = sizeof carrier;
		memcpy(out + 0x10, carrier, sizeof carrier);
	}
}

'''

neutral_pattern = (
    r"static void sw2BuildJoyconRNeutral\(uint8_t slot, uint8_t out\[63\]\)\n"
    r"\{.*?\n\}\n\n(?=static void sw2Build05Neutral)"
)
src = regex_once(src, neutral_pattern, mouse_block, "replace neutral Joy-Con builder")

src = replace_once(
    src,
    "\t\tif (!g_sw2InputEnabled || !tud_hid_n_ready(s))\n"
    "\t\t\tcontinue;\n",
    "\t\tif (!tud_hid_n_ready(s))\n"
    "\t\t\tcontinue;\n"
    "\t\t// The M15 companion never surfaced as a controller, so the host may\n"
    "\t\t// never issue its vendor input-enable command. Force only that hidden\n"
    "\t\t// HID stream active for this discriminator; Pro2 remains host-gated.\n"
    "\t\tif (s != M15_SW2_JOYCON_R && !g_sw2InputEnabled)\n"
    "\t\t\tcontinue;\n",
    "hidden-session input gate",
)

old_jcr = (
    "\t\tif (s == M15_SW2_JOYCON_R) {\n"
    "\t\t\tif (rid == 0x05)\n"
    "\t\t\t\tsw2Build05Neutral((uint8_t)bond, p);\n"
    "\t\t\telse {\n"
    "\t\t\t\trid = 0x08;\n"
    "\t\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);\n"
    "\t\t\t}\n"
    "\t\t} else if (rid == 0x05) {\n"
)
new_jcr = (
    "\t\tif (s == M15_SW2_JOYCON_R) {\n"
    "\t\t\t// Always exercise the hardware-working Joy-Con-R native report\n"
    "\t\t\t// path on the hidden function, independent of any host-selected\n"
    "\t\t\t// report mode for this unregistered companion.\n"
    "\t\t\trid = 0x08;\n"
    "\t\t\tsw2BuildJoyconRMouse((uint8_t)bond, p);\n"
    "\t\t} else if (rid == 0x05) {\n"
)
src = replace_once(src, old_jcr, new_jcr, "hidden Joy-Con report routing")

# M15 also serves control GET_REPORT for HID instance 1. Keep that fallback on
# the same M16 mouse builder so there is no stale neutral-builder reference and
# no second payload definition for the hidden function.
src = replace_once(
    src,
    "sw2BuildJoyconRNeutral((uint8_t)bond, p);",
    "sw2BuildJoyconRMouse((uint8_t)bond, p);",
    "hidden GET_REPORT builder",
)

# The old common-report neutral helper is intentionally left in place. It is
# unreachable for the M16 companion but retaining it keeps the M15 topology
# delta minimal and makes reverting M16 straightforward.
PATH.write_text(src, encoding="utf-8")
print("F27-M16 hidden Joy-Con-R mouse routing probe applied")
