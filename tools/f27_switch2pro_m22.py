#!/usr/bin/env python3
"""F27-M22: route LEFT Steam trackpad through hidden M21 Joy-Con-R session."""
from pathlib import Path

MODE = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M22 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = MODE.read_text(encoding="utf-8")
if "F27-M21-DUAL-JCR-TOPOLOGY" not in src:
    raise SystemExit("F27-M22 requires the composed M21 dual-Joy-Con topology")
if "F27-M22-HIDDEN-JCR-LEFT-MOUSE" in src:
    raise SystemExit("F27-M22 already applied")

src = replace_once(
    src,
    'static const char M21_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M21-DUAL-JCR-TOPOLOGY";\n',
    'static const char M21_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M21-DUAL-JCR-TOPOLOGY";\n'
    'static const char M22_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M22-HIDDEN-JCR-LEFT-MOUSE";\n',
    "build marker",
)

helper = r'''struct M22HiddenMouseState {
\tint16_t x;
\tint16_t y;
\tint32_t remX;
\tint32_t remY;
\tuint16_t motionTick;
\tbool touched;
\tuint8_t counter;
};

static M22HiddenMouseState g_m22HiddenMouse;

static int16_t m22ScaledDelta(int32_t *remainder, int32_t delta)
{
\tint div = g_mDiv > 0 ? g_mDiv : 64;
\tint32_t total = *remainder + delta;
\tint32_t value = total / div;
\t*remainder = total - value * div;
\tif (value > 32767)
\t\tvalue = 32767;
\telse if (value < -32768)
\t\tvalue = -32768;
\treturn (int16_t)value;
}

static void m22Put16(uint8_t *p, int16_t value)
{
\tuint16_t u = (uint16_t)value;
\tp[0] = (uint8_t)u;
\tp[1] = (uint8_t)(u >> 8);
}

static void m22FlatCarrier(uint8_t out[30])
{
\tmemset(out, 0, 30);
\tg_m22HiddenMouse.motionTick =
\t\t(uint16_t)((g_m22HiddenMouse.motionTick + 3u) & 0x0fffu);
\tuint16_t timing = (uint16_t)(0x3000u | g_m22HiddenMouse.motionTick);
\tout[0] = (uint8_t)timing;
\tout[1] = (uint8_t)(timing >> 8);
\tout[3] = 0x0c;
\tout[8] = 0x02;
\tout[12] = 0x01;
\tout[15] = 0x80;
\tout[16] = 0x00;
\tout[17] = 0x30;
\tout[18] = 0xd6;
\tout[19] = 0x10;
\tout[29] = 0x02;
}

static void m22BuildHiddenLeftMouse(uint8_t slot, uint8_t out[63])
{
\tmemset(out, 0, 63);
\tM22HiddenMouseState &state = g_m22HiddenMouse;
\tbool touch = (g_in[slot].buttons & TB_LPADT) != 0;
\tint16_t dx = 0, dy = 0;
\tif (!touch) {
\t\tstate.touched = false;
\t\tstate.remX = state.remY = 0;
\t} else if (!state.touched) {
\t\tstate.x = g_in[slot].lpx;
\t\tstate.y = g_in[slot].lpy;
\t\tstate.remX = state.remY = 0;
\t\tstate.touched = true;
\t} else {
\t\tint32_t rawX = (int32_t)g_in[slot].lpx - state.x;
\t\tint32_t rawY = (int32_t)g_in[slot].lpy - state.y;
\t\tstate.x = g_in[slot].lpx;
\t\tstate.y = g_in[slot].lpy;
\t\tdx = m22ScaledDelta(&state.remX, rawX);
\t\tdy = m22ScaledDelta(&state.remY, -rawY);
\t}

\tout[0] = state.counter++;
\tout[1] = sw2PowerInfo(slot);
\tout[4] = 0x07;
\tsw2PackStick(out + 5, 0, 0);
\tout[8] = 0x38;
\tm22Put16(out + 0x09, dx);
\tm22Put16(out + 0x0b, dy);
\tout[0x0d] = touch ? 0x17 : 0xff;
\tout[0x0e] = 0;
\tif (touch) {
\t\tuint8_t carrier[30];
\t\tm22FlatCarrier(carrier);
\t\tout[0x0f] = sizeof carrier;
\t\tmemcpy(out + 0x10, carrier, sizeof carrier);
\t}
}

'''
src = replace_once(src, "static void sw2Drain(void)\n{", helper + "static void sw2Drain(void)\n{", "hidden mouse helper")

src = replace_once(
    src,
    "\t\tif (!g_sw2InputEnabled || !tud_hid_n_ready(s))\n\t\t\tcontinue;",
    "\t\t// M22 forces only the unseen companion stream active. Session 0\n"
    "\t\t// retains the console-controlled input-enable state from M20/M21.\n"
    "\t\tif ((s != M15_SW2_JOYCON_R && !g_sw2InputEnabled) ||\n"
    "\t\t    !tud_hid_n_ready(s))\n\t\t\tcontinue;",
    "hidden input-enable bypass",
)

old_hidden_drain = '''\t\tif (s == M15_SW2_JOYCON_R) {
\t\t\tif (rid == 0x05)
\t\t\t\tsw2Build05Neutral((uint8_t)bond, p);
\t\t\telse {
\t\t\t\trid = 0x08;
\t\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);
\t\t\t}
'''
new_hidden_drain = '''\t\tif (s == M15_SW2_JOYCON_R) {
\t\t\t// Force the unseen companion to the hardware-proven Joy-Con-R
\t\t\t// native mouse report regardless of host-selected active report.
\t\t\trid = 0x08;
\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);
'''
src = replace_once(src, old_hidden_drain, new_hidden_drain, "hidden interrupt stream")

old_hidden_get = '''\t} else if (itf == M15_SW2_JOYCON_R) {
\t\tif (reportId == 0x05)
\t\t\tsw2Build05Neutral((uint8_t)bond, p);
\t\telse if (reportId == 0x08 || reportId == 0x09)
\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);
\t\telse
\t\t\treturn 0;
'''
new_hidden_get = '''\t} else if (itf == M15_SW2_JOYCON_R) {
\t\tif (reportId == 0x08 || reportId == 0x09)
\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);
\t\telse if (reportId == 0x05)
\t\t\tsw2Build05Neutral((uint8_t)bond, p);
\t\telse
\t\t\treturn 0;
'''
src = replace_once(src, old_hidden_get, new_hidden_get, "hidden GET_REPORT")

src = replace_once(
    src,
    '\tasm volatile("" : : "r"(M21_BUILD_MARKER) : "memory");\n',
    '\tasm volatile("" : : "r"(M21_BUILD_MARKER) : "memory");\n'
    '\tasm volatile("" : : "r"(M22_BUILD_MARKER) : "memory");\n',
    "retain marker",
)

MODE.write_text(src, encoding="utf-8")
print("F27-M22 hidden Joy-Con-R left-trackpad mouse route applied")
