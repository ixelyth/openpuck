#!/usr/bin/env python3
"""F27-M27: replace only M25 session1 test payload with coherent proven JCR/M3 machinery."""

from pathlib import Path

MODE = Path("OpenPuck/mode_switch2_pro.cpp")
JOY = Path("OpenPuck/f27_joycon2.cpp")
HDR = Path("OpenPuck/f27_joycon2.h")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M27 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


mode = MODE.read_text(encoding="utf-8")
joy = JOY.read_text(encoding="utf-8")
hdr = HDR.read_text(encoding="utf-8")

if "F27-M22-HIDDEN-JCR-LEFT-MOUSE" not in mode:
    raise SystemExit("F27-M27 requires the composed M22 dual-R probe")
if "F27-M25-IDENTITY-SWAP-JCR" not in mode:
    raise SystemExit("F27-M27 requires the hardware-positive M25 composition")
for forbidden in (
    "F27-M23-JCR-JCL-LEFT-MOUSE",
    "F27-M24-ROLE-SWAP-JCR",
    "F27-M26-INPUT-PAYLOAD-SWAP-JCR",
    "F27-M27-PROVEN-SESSION1-LEFT-JCR",
):
    if forbidden in mode:
        raise SystemExit(f"F27-M27 forbidden/already-applied marker present: {forbidden}")

mode = replace_once(
    mode,
    'static const char M25_BUILD_MARKER[] __attribute__((used)) =\n'
    '\t"F27-M25-IDENTITY-SWAP-JCR";\n',
    'static const char M25_BUILD_MARKER[] __attribute__((used)) =\n'
    '\t"F27-M25-IDENTITY-SWAP-JCR";\n'
    'static const char M27_BUILD_MARKER[] __attribute__((used)) =\n'
    '\t"F27-M27-PROVEN-SESSION1-LEFT-JCR";\n',
    "build marker",
)

# Add independent session1 mouse state without modifying the existing g_left/g_right
# state used by the hardware-proven session0 native builder.
joy = replace_once(
    joy,
    "static MousePadState g_left;\nstatic MousePadState g_right;\nstatic bool g_bothRight;\n",
    "static MousePadState g_left;\nstatic MousePadState g_right;\n"
    "static MousePadState g_m27Session1Left;\nstatic bool g_bothRight;\n",
    "independent session1 mouse state",
)

# This is the M3-proven Joy-Con-R report layout/carrier/button/stick path, with
# only the mouse coordinates/touch source changed from the right Steam pad to
# the left Steam pad. The existing buildSide()/f27JoyconBuildNative() path is
# left textually untouched for session0.
anchor = "\n} // namespace\n\nbool f27JoyconEnabled()\n"
helper = r'''
static void m27BuildSession1Left(uint8_t slot, uint8_t out[63])
{
	memset(out, 0, 63);
	MousePadState &state = g_m27Session1Left;
	uint32_t buttons = g_in[slot].buttons;
	bool touch = (buttons & TB_LPADT) != 0;
	int16_t dx, dy;
	bool surface = padMouse(state, touch, g_in[slot].lpx, g_in[slot].lpy,
				 &dx, &dy);

	out[0] = state.counter++;
	out[1] = powerInfo(slot);
	rightButtons(slot, out + 2, surface);
	out[4] = 0x07;
	out[8] = 0x38;
	packStick(out + 5, g_in[slot].rx, g_in[slot].ry);
	put16(out + 0x09, dx);
	put16(out + 0x0b, dy);
	out[0x0d] = surface ? 0x17 : 0xff;
	out[0x0e] = 0;
	if (surface) {
		uint8_t carrier[30];
		flatMouseCarrier(state, carrier);
		out[0x0f] = sizeof carrier;
		memcpy(out + 0x10, carrier, sizeof carrier);
	}
}
'''
joy = replace_once(
    joy,
    anchor,
    "\n" + helper + "\n} // namespace\n\nbool f27JoyconEnabled()\n",
    "coherent session1 left-pad builder",
)

# Export a dedicated M27 session1 entry point. It deliberately does not alter
# f27JoyconBuildNative(), so the hardware-positive session0 implementation is
# preserved verbatim.
export_anchor = r'''bool f27JoyconBuildNative(uint8_t slot, uint8_t features, uint8_t *reportId,
			  uint8_t out[63])
{
'''
if export_anchor not in joy:
    raise SystemExit("F27-M27 native builder function anchor missing")

append_anchor = "\n\treturn true;\n}\n"
last = joy.rfind(append_anchor)
if last < 0:
    raise SystemExit("F27-M27 native builder closing anchor missing")
insert_at = last + len(append_anchor)
export_fn = r'''

bool f27JoyconBuildM27Session1Left(uint8_t slot, uint8_t features,
				   uint8_t *reportId, uint8_t out[63])
{
	(void)features;
	if (!f27JoyconEnabled() || !reportId || !out || slot >= NSLOT)
		return false;
#if OPK_F27_JOYCON_TARGET == F27_JOYCON_R
	*reportId = 0x08;
	m27BuildSession1Left(slot, out);
	return true;
#else
	return false;
#endif
}
'''
joy = joy[:insert_at] + export_fn + joy[insert_at:]

hdr = replace_once(
    hdr,
    "bool f27JoyconBuildNative(uint8_t slot, uint8_t features, uint8_t *reportId,\n"
    "\t\t\t  uint8_t out[63]);\n",
    "bool f27JoyconBuildNative(uint8_t slot, uint8_t features, uint8_t *reportId,\n"
    "\t\t\t  uint8_t out[63]);\n"
    "// M27 session1-only control: same Joy-Con-R/M3 report semantics, but mouse\n"
    "// motion/touch comes from the LEFT Steam trackpad with independent state.\n"
    "bool f27JoyconBuildM27Session1Left(uint8_t slot, uint8_t features,\n"
    "\t\t\t\t   uint8_t *reportId, uint8_t out[63]);\n",
    "header declaration",
)

# Replace only session1's periodic payload call. Session0's live branch remains
# byte-for-byte M25.
mode = replace_once(
    mode,
    "\t\tif (s == M15_SW2_JOYCON_R) {\n"
    "\t\t\t// Force the unseen companion to native report 0x08.\n"
    "\t\t\trid = 0x08;\n"
    "\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);\n"
    "\t\t} else if (rid == 0x05) {",
    "\t\tif (s == M15_SW2_JOYCON_R) {\n"
    "\t\t\t// M27: coherent proven Joy-Con-R/M3 payload, LEFT-pad signal.\n"
    "\t\t\tif (!f27JoyconBuildM27Session1Left((uint8_t)bond, g_sw2Features,\n"
    "\t\t\t\t\t\t     &rid, p)) {\n"
    "\t\t\t\trid = 0x08;\n"
    "\t\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);\n"
    "\t\t\t}\n"
    "\t\t} else if (rid == 0x05) {",
    "session1 periodic builder",
)

# Keep session1 GET_REPORT coherent with the same proven builder/source mapping.
mode = replace_once(
    mode,
    "\t} else if (itf == M15_SW2_JOYCON_R) {\n"
    "\t\tif (reportId == 0x08 || reportId == 0x09)\n"
    "\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);\n"
    "\t\telse if (reportId == 0x05)\n"
    "\t\t\tsw2Build05Neutral((uint8_t)bond, p);\n",
    "\t} else if (itf == M15_SW2_JOYCON_R) {\n"
    "\t\tif (reportId == 0x08 || reportId == 0x09) {\n"
    "\t\t\tuint8_t rid = reportId;\n"
    "\t\t\tif (!f27JoyconBuildM27Session1Left((uint8_t)bond, g_sw2Features,\n"
    "\t\t\t\t\t\t     &rid, p))\n"
    "\t\t\t\treturn 0;\n"
    "\t\t} else if (reportId == 0x05)\n"
    "\t\t\tsw2Build05Neutral((uint8_t)bond, p);\n",
    "session1 GET_REPORT builder",
)

mode = replace_once(
    mode,
    '\tasm volatile("" : : "r"(M25_BUILD_MARKER) : "memory");\n',
    '\tasm volatile("" : : "r"(M25_BUILD_MARKER) : "memory");\n'
    '\tasm volatile("" : : "r"(M27_BUILD_MARKER) : "memory");\n',
    "retain marker",
)

MODE.write_text(mode, encoding="utf-8")
JOY.write_text(joy, encoding="utf-8")
HDR.write_text(hdr, encoding="utf-8")
print("F27-M27 coherent proven-builder session1 LEFT-pad probe applied")
