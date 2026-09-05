#!/usr/bin/env python3
"""Apply F27-M14: Switch2Pro common-report 0x05 optical-mouse probe.

M14 is based on the reconciled Switch2Pro source authority. It keeps Nintendo
USB/factory/firmware identity as Switch 2 Pro (057E:2069) and keeps native
report 0x09 as the normal stream. While the right Steam trackpad is touched,
the experiment temporarily emits common report 0x05, which is present in the
real Pro2 HID descriptor, with a synthesized absolute optical block at
payload 0x10..0x17. One off-surface 0x05 release report is emitted before
returning to report 0x09.

The public protocol documents the common-report X/Y fields but not the final
two u16 values. M14 uses an explicit experimental on-surface profile:
quality=0xffff and LOD/state=0x0017; release uses quality=0 and LOD=0xffff.
It also advertises the Joy-Con-style mouse capability value (0x03) in the
feature-info response. These are isolated probe semantics, not production
Switch2Pro behavior.
"""

from pathlib import Path

PATH = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M14 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")

src = replace_once(
    src,
    """static volatile uint32_t g_sw2Counter32 = 0;
static int8_t g_sw2LastRumbleBond = -1;
""",
    """static volatile uint32_t g_sw2Counter32 = 0;

// F27-M14 isolated common-report mouse probe state. The optical position is a
// wrapping accumulator fed by the same Steam-pad delta scaling that proved
// functional in F27-M3, so report 0x05 behaves like an absolute optical sensor
// rather than exposing the bounded Steam pad coordinate directly.
struct Sw2M14MouseState {
\tint16_t padX, padY;
\tint32_t remX, remY;
\tuint16_t opticalX, opticalY;
\tbool touched;
};
static Sw2M14MouseState g_sw2M14Mouse = {
\t0, 0, 0, 0, 0x8000u, 0x8000u, false,
};
static bool g_sw2M14ReleasePending = false;

static int8_t g_sw2LastRumbleBond = -1;
""",
    "probe state",
)

src = replace_once(
    src,
    """\tif (flags & 0x10)
\t\tout[4] = 0x01;
""",
    """\t// F27-M14: advertise the Joy-Con mouse-capability value while retaining
\t// every other Pro2 identity/session field. Public captures report 0x03 for
\t// the Joy-Con optical feature; production Pro2 uses 0x01 here.
\tif (flags & 0x10)
\t\tout[4] = 0x03;
""",
    "feature info",
)

src = replace_once(
    src,
    """static void sw2Build05(uint8_t slot, uint8_t out[63])
{
\tmemset(out, 0, 63);
""",
    """static int16_t sw2M14ScaledDelta(int32_t *remainder, int32_t delta)
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

static bool sw2M14BuildMouse(uint8_t slot, uint8_t out[8])
{
\tconst bool touch = (g_in[slot].buttons & TB_RPADT) != 0;
\tif (!touch) {
\t\tg_sw2M14Mouse.touched = false;
\t\tg_sw2M14Mouse.remX = g_sw2M14Mouse.remY = 0;
\t\tmemset(out, 0, 8);
\t\t// Experimental off-surface profile. The final two common-report u16
\t\t// fields remain undocumented; 0xffff mirrors the proven native
\t\t// report-0x08 off-surface state at the likely LOD position.
\t\tout[6] = 0xff;
\t\tout[7] = 0xff;
\t\treturn false;
\t}

\tif (!g_sw2M14Mouse.touched) {
\t\tg_sw2M14Mouse.padX = g_in[slot].rpx;
\t\tg_sw2M14Mouse.padY = g_in[slot].rpy;
\t\tg_sw2M14Mouse.remX = g_sw2M14Mouse.remY = 0;
\t\tg_sw2M14Mouse.touched = true;
\t} else {
\t\tconst int32_t rawX =
\t\t\t(int32_t)g_in[slot].rpx - g_sw2M14Mouse.padX;
\t\tconst int32_t rawY =
\t\t\t-(int32_t)(g_in[slot].rpy - g_sw2M14Mouse.padY);
\t\tg_sw2M14Mouse.padX = g_in[slot].rpx;
\t\tg_sw2M14Mouse.padY = g_in[slot].rpy;
\t\tconst int16_t dx = sw2M14ScaledDelta(&g_sw2M14Mouse.remX, rawX);
\t\tconst int16_t dy = sw2M14ScaledDelta(&g_sw2M14Mouse.remY, rawY);
\t\tg_sw2M14Mouse.opticalX =
\t\t\t(uint16_t)(g_sw2M14Mouse.opticalX + (uint16_t)dx);
\t\tg_sw2M14Mouse.opticalY =
\t\t\t(uint16_t)(g_sw2M14Mouse.opticalY + (uint16_t)dy);
\t}

\tsw2Put16(out + 0, (int16_t)g_sw2M14Mouse.opticalX);
\tsw2Put16(out + 2, (int16_t)g_sw2M14Mouse.opticalY);
\t// Experimental on-surface profile for the two still-undocumented u16
\t// common-report fields: maximal surface quality, then the hardware-proven
\t// native mouse surface/LOD byte 0x17 widened to u16.
\tout[4] = 0xff;
\tout[5] = 0xff;
\tout[6] = 0x17;
\tout[7] = 0x00;
\treturn true;
}

static void sw2Build05(uint8_t slot, uint8_t out[63])
{
\tmemset(out, 0, 63);
""",
    "mouse helper",
)

src = replace_once(
    src,
    """\tsw2PackStick(out + 0x0a, lx, ly);
\tsw2PackStick(out + 0x0d, rx, ry);
\tout[0x1f] = 0xd8;
""",
    """\tsw2PackStick(out + 0x0a, lx, ly);
\tsw2PackStick(out + 0x0d, rx, ry);
\t// F27-M14: report 0x05 is common to Pro2 and Joy-Con2. Populate its
\t// documented Joy-Con-only optical block while the Pro2 identity is retained.
\tsw2M14BuildMouse(slot, out + 0x10);
\tout[0x1f] = 0xd8;
""",
    "common report optical block",
)

src = replace_once(
    src,
    """\tuint8_t p[63];
\tuint8_t rid = g_sw2ActiveReport;
\tif (rid == 0x05)
\t\tsw2Build05((uint8_t)bond, p);
\telse {
\t\trid = 0x09;
\t\tsw2Build09((uint8_t)bond, p);
\t}
\tif (tud_hid_n_report(0, rid, p, sizeof p))
\t\tg_sw2LastReportMs = millis();
""",
    """\tuint8_t p[63];
\tconst bool m14Touch = (g_in[bond].buttons & TB_RPADT) != 0;
\tconst bool m14Release = g_sw2M14ReleasePending && !m14Touch;
\tuint8_t rid = g_sw2ActiveReport;
\t// F27-M14: preserve normal Pro2 report 0x09 outside mouse activity. During
\t// right-pad touch, exercise the only documented mouse-bearing report that is
\t// also legal in the Pro2 descriptor: common report 0x05. Emit one explicit
\t// off-surface 0x05 before returning to the host-selected Pro report.
\tif (m14Touch || m14Release)
\t\trid = 0x05;
\tif (rid == 0x05)
\t\tsw2Build05((uint8_t)bond, p);
\telse {
\t\trid = 0x09;
\t\tsw2Build09((uint8_t)bond, p);
\t}
\tif (tud_hid_n_report(0, rid, p, sizeof p)) {
\t\tif (m14Touch)
\t\t\tg_sw2M14ReleasePending = true;
\t\telse if (m14Release)
\t\t\tg_sw2M14ReleasePending = false;
\t\tg_sw2LastReportMs = millis();
\t}
""",
    "drain report switch",
)

src = replace_once(
    src,
    """\tg_sw2FeatureMask = 0;
\tg_sw2LastRumbleBond = -1;
""",
    """\tg_sw2FeatureMask = 0;
\tg_sw2M14Mouse.touched = false;
\tg_sw2M14Mouse.remX = g_sw2M14Mouse.remY = 0;
\tg_sw2M14ReleasePending = false;
\tg_sw2LastRumbleBond = -1;
""",
    "driver reset",
)

PATH.write_text(src, encoding="utf-8")
print("F27-M14 Switch2Pro common-report 0x05 optical probe applied")
