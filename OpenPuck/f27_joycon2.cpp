// f27_joycon2.cpp -- F27 Joy-Con 2 mouse-emulation proof of concept.
//
// This module intentionally leaves the proven Switch 2 Pro USB transport in
// place and changes only the logical controller identity/native report stream.
// L/R follow the split-identity path validated by NS-PC-Control: USB still
// enumerates as Pro Controller 2 while factory identity selects Joy-Con 2 and
// the stream uses 0x07/0x08. Both is deliberately experimental: one USB
// session alternates 0x07 and 0x08 to test whether the console demultiplexes
// the two Joy-Con halves before we invest in a dual-interface implementation.
#include "f27_joycon2.h"
#include "config.h"
#include "rf_link.h"
#include "triton.h"
#include <string.h>

namespace {

struct MousePadState {
	int16_t x;
	int16_t y;
	int32_t remX;
	int32_t remY;
	uint16_t motionTick;
	bool touched;
	uint8_t counter;
};

static MousePadState g_left;
static MousePadState g_right;
static bool g_bothRight;

static uint8_t logicalPidLow()
{
#if OPK_F27_JOYCON_TARGET == F27_JOYCON_L
	return 0x67;
#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_R
	return 0x66;
#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_BOTH
	// 0x2068 is SDL's synthetic Joy-Con-pair identity. No physical pair USB
	// personality is known; using it here is an intentional hardware probe.
	return 0x68;
#else
	return 0x69;
#endif
}

static void packStick(uint8_t out[3], int16_t x, int16_t y)
{
	uint16_t sx = (uint16_t)(((int32_t)x + 32768) >> 4);
	uint16_t sy = (uint16_t)(((int32_t)y + 32768) >> 4);
	out[0] = (uint8_t)sx;
	out[1] = (uint8_t)((sx >> 8) | (sy << 4));
	out[2] = (uint8_t)(sy >> 4);
}

static uint8_t powerInfo(uint8_t slot)
{
	uint8_t pct = slot < NSLOT ? g_battery[slot] : 0;
	uint8_t level = pct ? (uint8_t)(((uint16_t)pct * 9u + 50u) / 100u) : 0;
	if (level > 9)
		level = 9;
	return (uint8_t)(level << 2);
}

static int16_t scaledDelta(int32_t *remainder, int32_t delta)
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

static bool padMouse(MousePadState &state, bool touch, int16_t x, int16_t y,
		     int16_t *dx, int16_t *dy)
{
	*dx = 0;
	*dy = 0;
	if (!touch) {
		state.touched = false;
		state.remX = state.remY = 0;
		return false;
	}
	if (!state.touched) {
		state.x = x;
		state.y = y;
		state.remX = state.remY = 0;
		state.touched = true;
		return true;
	}

	int32_t rawX = (int32_t)x - state.x;
	int32_t rawY = (int32_t)y - state.y;
	state.x = x;
	state.y = y;
	*dx = scaledDelta(&state.remX, rawX);
	// Steam pad Y is positive upward; native mouse screen coordinates are
	// positive downward, matching the existing XInput mouse path.
	*dy = scaledDelta(&state.remY, -rawY);
	return true;
}

static void put16(uint8_t *p, int16_t v)
{
	uint16_t u = (uint16_t)v;
	p[0] = (uint8_t)u;
	p[1] = (uint8_t)(u >> 8);
}

static void flatMouseCarrier(MousePadState &state, uint8_t out[30])
{
	memset(out, 0, 30);
	state.motionTick = (uint16_t)((state.motionTick + 3u) & 0x0fffu);
	uint16_t timing = (uint16_t)(0x3000u | state.motionTick);
	out[0] = (uint8_t)timing;
	out[1] = (uint8_t)(timing >> 8);
	out[3] = 0x0c;

	// Identity quaternion, encoded in the hardware-confirmed S2 carrier
	// representation. The omitted component is W; X/Y/Z are zero.
	out[8] = 0x02;
	out[12] = 0x01;
	out[15] = 0x80;

	// +1 g on native S2 X. This is the captured mouse posture produced by
	// feeding -4096 on the Switch-1-style Y axis into the validated remount.
	out[16] = 0x00;
	out[17] = 0x30;
	out[18] = 0xd6;
	out[19] = 0x10;
	out[29] = 0x02;
}

static void rightButtons(uint8_t slot, uint8_t out[2], bool mouse)
{
	uint32_t b = g_in[slot].buttons;
	uint8_t b0 = 0, b1 = 0;
	if (b & TB_R3)
		b0 |= 0x80;
	if (b & TB_VIEW)
		b0 |= 0x40;
	if (g_in[slot].rt >= SW_TRIG_ON || (b & TB_R2))
		b0 |= 0x20;
	if (b & TB_RB)
		b0 |= 0x10;

	uint8_t a = g_abSwap ? 0x01 : 0x02;
	uint8_t bb = g_abSwap ? 0x02 : 0x01;
	uint8_t x = g_abSwap ? 0x04 : 0x08;
	uint8_t y = g_abSwap ? 0x08 : 0x04;
	if (b & TB_A)
		b0 |= a;
	if (b & TB_B)
		b0 |= bb;
	if (b & TB_X)
		b0 |= x;
	if (b & TB_Y)
		b0 |= y;

	if (b & TB_R4)
		b1 |= 0x80; // SL
	if (b & TB_R5)
		b1 |= 0x40; // SR
	if (b & TB_QAM)
		b1 |= 0x10; // C
	if (b & TB_STEAM)
		b1 |= 0x01; // Home
	if (mouse && (b & TB_RPADC))
		b0 |= 0x10; // mouse primary button -> R
	out[0] = b0;
	out[1] = b1;
}

static void leftButtons(uint8_t slot, uint8_t out[2], bool mouse)
{
	uint32_t b = g_in[slot].buttons;
	uint8_t b0 = 0, b1 = 0;
	if (b & TB_L3)
		b0 |= 0x80;
	if (b & TB_MENU)
		b0 |= 0x40;
	if (g_in[slot].lt >= SW_TRIG_ON || (b & TB_L2))
		b0 |= 0x20;
	if (b & TB_LB)
		b0 |= 0x10;
	if (b & TB_DUP)
		b0 |= 0x08;
	if (b & TB_DLF)
		b0 |= 0x04;
	if (b & TB_DRT)
		b0 |= 0x02;
	if (b & TB_DDN)
		b0 |= 0x01;
	if (b & TB_L4)
		b1 |= 0x80; // SL
	if (b & TB_L5)
		b1 |= 0x40; // SR
	if (b & TB_QAM)
		b1 |= 0x01; // Capture
	if (mouse && (b & TB_LPADC))
		b0 |= 0x10; // mouse primary button -> L
	out[0] = b0;
	out[1] = b1;
}

static void buildSide(uint8_t slot, bool right, uint8_t features,
		      uint8_t out[63])
{
	memset(out, 0, 63);
	MousePadState &state = right ? g_right : g_left;
	uint32_t buttons = g_in[slot].buttons;
	bool requestedMouse = (features & 0x10u) != 0;
	bool touch = requestedMouse &&
		     (buttons & (right ? TB_RPADT : TB_LPADT));
	int16_t dx, dy;
	bool surface = padMouse(state, touch,
				 right ? g_in[slot].rpx : g_in[slot].lpx,
				 right ? g_in[slot].rpy : g_in[slot].lpy,
				 &dx, &dy);

	out[0] = state.counter++;
	out[1] = powerInfo(slot);
	if (right)
		rightButtons(slot, out + 2, surface);
	else
		leftButtons(slot, out + 2, surface);
	out[4] = 0x07;
	if (right)
		packStick(out + 5, g_in[slot].rx, g_in[slot].ry);
	else
		packStick(out + 5, g_in[slot].lx, g_in[slot].ly);
	put16(out + 0x09, dx);
	put16(out + 0x0b, dy);
	out[0x0d] = surface ? 0x17 : 0xff;
	out[0x0e] = 0; // NFC state; left has none, right remains idle.

	if (surface && (features & 0x04u)) {
		uint8_t carrier[30];
		flatMouseCarrier(state, carrier);
		out[0x0f] = sizeof carrier;
		memcpy(out + 0x10, carrier, sizeof carrier);
	}
}

} // namespace

bool f27JoyconEnabled()
{
	return OPK_F27_JOYCON_TARGET != F27_JOYCON_OFF;
}

uint8_t f27JoyconTarget()
{
	return OPK_F27_JOYCON_TARGET;
}

uint8_t f27JoyconSelectReport(uint8_t requested)
{
#if OPK_F27_JOYCON_TARGET == F27_JOYCON_L
	if (requested == 0x05)
		return 0x05;
	return requested == 0x07 || requested == 0x09 ? 0x07 : 0;
#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_R
	if (requested == 0x05)
		return 0x05;
	return requested == 0x08 || requested == 0x09 ? 0x08 : 0;
#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_BOTH
	if (requested == 0x05)
		return 0x05;
	return requested == 0x07 || requested == 0x08 || requested == 0x09 ?
		       0x09 :
		       0;
#else
	return requested == 0x05 || requested == 0x09 ? requested : 0;
#endif
}

void f27JoyconPatchIdentity(uint8_t *data, uint16_t len)
{
	if (!f27JoyconEnabled() || !data || len < 22)
		return;
	data[20] = logicalPidLow();
	data[21] = 0x20;
}

void f27JoyconPatchFlash(uint32_t address, uint8_t *data, uint8_t len)
{
	if (!f27JoyconEnabled() || !data)
		return;
	const uint32_t pid = 0x00013014u;
	if (address <= pid && pid < address + len)
		data[pid - address] = logicalPidLow();
	if (address <= pid + 1u && pid + 1u < address + len)
		data[pid + 1u - address] = 0x20;
}

bool f27JoyconBuildNative(uint8_t slot, uint8_t features, uint8_t *reportId,
			  uint8_t out[63])
{
	if (!f27JoyconEnabled() || !reportId || !out || slot >= NSLOT)
		return false;

#if OPK_F27_JOYCON_TARGET == F27_JOYCON_L
	*reportId = 0x07;
	buildSide(slot, false, features, out);
#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_R
	*reportId = 0x08;
	buildSide(slot, true, features, out);
#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_BOTH
	g_bothRight = !g_bothRight;
	*reportId = g_bothRight ? 0x08 : 0x07;
	buildSide(slot, g_bothRight, features, out);
#else
	return false;
#endif
	return true;
}
