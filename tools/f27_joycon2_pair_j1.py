#!/usr/bin/env python3
"""J1: clean Joy-Con 2 L+R pair-registration probe over the M21 dual-session scaffold."""
from pathlib import Path

MODE = Path("OpenPuck/mode_switch2_pro.cpp")
JOY = Path("OpenPuck/f27_joycon2.cpp")
HDR = Path("OpenPuck/f27_joycon2.h")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"J1 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


mode = MODE.read_text(encoding="utf-8")
if "F27-M21-DUAL-JCR-TOPOLOGY" not in mode:
    raise SystemExit("J1 requires the composed M21 dual-session topology")
if "F27-J1-JCL-JCR-PAIR" in mode:
    raise SystemExit("J1 already applied")

mode = replace_once(
    mode,
    'static const char M21_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M21-DUAL-JCR-TOPOLOGY";\n',
    'static const char M21_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M21-DUAL-JCR-TOPOLOGY";\n'
    'static const char J1_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-J1-JCL-JCR-PAIR";\n',
    "build marker",
)

# Session 0 remains Joy-Con 2 R. Session 1 becomes Joy-Con 2 L. M21 already
# gives the second session a distinct controller address and factory serial.
mode = replace_once(
    mode,
    "\t\t\tblock[pid - address] = 0x66;\n",
    "\t\t\tblock[pid - address] = g_sw2SessionCtx ? 0x67 : 0x66;\n",
    "session factory PID",
)

# Keep the secondary interface string consistent with the factory-side identity.
mode = replace_once(
    mode,
    'vendorStr = TinyUSBDevice.addStringDescriptor("Joy-Con 2 (R)");',
    'vendorStr = TinyUSBDevice.addStringDescriptor("Joy-Con 2 (L)");',
    "secondary product string",
)

# Each session accepts its own native report family. The shared EP0 identity is
# intentionally left as the hardware-positive Joy-Con 2 R path because one
# physical USB device has only one control endpoint.
mode = replace_once(
    mode,
    '''\t\tif (sw2JoyconR()) {
\t\t\tif (cmd[8] == 0x05)
\t\t\t\tg_sw2ActiveReport = 0x05;
\t\t\telse if (cmd[8] == 0x08 || cmd[8] == 0x09)
\t\t\t\tg_sw2ActiveReport = 0x08;
\t\t} else if (cmd[8] == 0x05 || cmd[8] == 0x09) {
''',
    '''\t\tif (sw2JoyconR()) {
\t\t\tif (cmd[8] == 0x05)
\t\t\t\tg_sw2ActiveReport = 0x05;
\t\t\telse if (g_sw2SessionCtx == M15_SW2_JOYCON_R &&
\t\t\t\t (cmd[8] == 0x07 || cmd[8] == 0x09))
\t\t\t\tg_sw2ActiveReport = 0x07;
\t\t\telse if (g_sw2SessionCtx == M15_SW2_PRO &&
\t\t\t\t (cmd[8] == 0x08 || cmd[8] == 0x09))
\t\t\t\tg_sw2ActiveReport = 0x08;
\t\t} else if (cmd[8] == 0x05 || cmd[8] == 0x09) {
''',
    "session report selection",
)

mode = replace_once(
    mode,
    "\t\tg_sw2ActiveReport = sw2JoyconR() ? 0x08 : 0x09;\n",
    "\t\tg_sw2ActiveReport = g_sw2SessionCtx ? 0x07 : 0x08;\n",
    "reset report default",
)

mode = replace_once(
    mode,
    "\t\tg_sw2Sessions[s].activeReport = 0x08;\n",
    "\t\tg_sw2Sessions[s].activeReport = s ? 0x07 : 0x08;\n",
    "beginPool report defaults",
)

# The console previously never enabled the hidden second session. For this
# registration probe, keep the known-good R side console-gated, but allow the L
# side to emit its native neutral/live stream as soon as HID1 is ready so the
# console can discover the missing half.
mode = replace_once(
    mode,
    "\t\tif (!g_sw2InputEnabled || !tud_hid_n_ready(s))\n\t\t\tcontinue;",
    "\t\tif ((s != M15_SW2_JOYCON_R && !g_sw2InputEnabled) ||\n"
    "\t\t    !tud_hid_n_ready(s))\n"
    "\t\t\tcontinue;",
    "left-session discovery stream",
)

old_drain = '''\t\tif (s == M15_SW2_JOYCON_R) {
\t\t\tif (rid == 0x05)
\t\t\t\tsw2Build05Neutral((uint8_t)bond, p);
\t\t\telse {
\t\t\t\trid = 0x08;
\t\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);
\t\t\t}
\t\t} else if (rid == 0x05) {
\t\t\tsw2Build05((uint8_t)bond, p);
\t\t} else if (!f27JoyconBuildNative((uint8_t)bond, g_sw2Features, &rid, p)) {
\t\t\trid = 0x08;
\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);
\t\t}
'''
new_drain = '''\t\t// J1 deliberately streams only the native side-specific reports. A
\t\t// physical Steam LB+RB chord therefore becomes L on JCL plus R on JCR
\t\t// in the same report window, matching Change Grip/Order pairing.
\t\tif (s == M15_SW2_JOYCON_R) {
\t\t\trid = 0x07;
\t\t\tif (!f27JoyconBuildSideNative((uint8_t)bond, false, &rid, p))
\t\t\t\tcontinue;
\t\t} else {
\t\t\trid = 0x08;
\t\t\tif (!f27JoyconBuildSideNative((uint8_t)bond, true, &rid, p))
\t\t\t\tcontinue;
\t\t}
'''
mode = replace_once(mode, old_drain, new_drain, "live L/R native streams")

old_get = '''\t} else if (itf == M15_SW2_JOYCON_R) {
\t\tif (reportId == 0x05)
\t\t\tsw2Build05Neutral((uint8_t)bond, p);
\t\telse if (reportId == 0x08 || reportId == 0x09)
\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);
\t\telse
\t\t\treturn 0;
\t} else if (reportId == 0x05) {
\t\tsw2Build05((uint8_t)bond, p);
\t} else if (reportId == 0x08 || reportId == 0x09) {
\t\tuint8_t rid = reportId;
\t\tif (!f27JoyconBuildNative((uint8_t)bond, g_sw2Features, &rid, p))
\t\t\treturn 0;
\t} else {
\t\treturn 0;
\t}
'''
new_get = '''\t} else if (itf == M15_SW2_JOYCON_R) {
\t\tif (reportId == 0x05)
\t\t\tsw2Build05Neutral((uint8_t)bond, p);
\t\telse if (reportId == 0x07 || reportId == 0x09) {
\t\t\tuint8_t rid = 0x07;
\t\t\tif (!f27JoyconBuildSideNative((uint8_t)bond, false, &rid, p))
\t\t\t\treturn 0;
\t\t} else
\t\t\treturn 0;
\t} else if (reportId == 0x05) {
\t\tsw2Build05((uint8_t)bond, p);
\t} else if (reportId == 0x08 || reportId == 0x09) {
\t\tuint8_t rid = 0x08;
\t\tif (!f27JoyconBuildSideNative((uint8_t)bond, true, &rid, p))
\t\t\treturn 0;
\t} else {
\t\treturn 0;
\t}
'''
mode = replace_once(mode, old_get, new_get, "GET_REPORT side routing")

mode = replace_once(
    mode,
    '\tasm volatile("" : : "r"(M21_BUILD_MARKER) : "memory");\n',
    '\tasm volatile("" : : "r"(M21_BUILD_MARKER) : "memory");\n'
    '\tasm volatile("" : : "r"(J1_BUILD_MARKER) : "memory");\n',
    "retain J1 marker",
)

MODE.write_text(mode, encoding="utf-8")

joy = JOY.read_text(encoding="utf-8")
if "f27JoyconBuildSideNative" in joy:
    raise SystemExit("J1 side builder already present")

# M21 forced mouse on for the old mouse experiments. J1 explicitly removes
# mouse from the payload layer; later milestones will re-add it after pairing.
joy = replace_once(
    joy,
    "\tbool requestedMouse = true;\n",
    "\tbool requestedMouse = false;\n",
    "disable mouse",
)

joy += '''\n// J1 pair-registration helper: emit one ordinary native Joy-Con side with\n// mouse/motion features disabled. The existing side mappings provide L from\n// TB_LB and R from TB_RB, so LB+RB naturally supplies the cross-side pair chord.\nbool f27JoyconBuildSideNative(uint8_t slot, bool right, uint8_t *reportId,\n\t\t\t      uint8_t out[63])\n{\n\tif (!reportId || !out || slot >= NSLOT)\n\t\treturn false;\n\t*reportId = right ? 0x08 : 0x07;\n\tbuildSide(slot, right, 0, out);\n\treturn true;\n}\n'''
JOY.write_text(joy, encoding="utf-8")

hdr = HDR.read_text(encoding="utf-8")
hdr = replace_once(
    hdr,
    "bool f27JoyconBuildNative(uint8_t slot, uint8_t features, uint8_t *reportId,\n\t\t\t  uint8_t out[63]);\n",
    "bool f27JoyconBuildNative(uint8_t slot, uint8_t features, uint8_t *reportId,\n\t\t\t  uint8_t out[63]);\n"
    "bool f27JoyconBuildSideNative(uint8_t slot, bool right, uint8_t *reportId,\n"
    "\t\t\t      uint8_t out[63]);\n",
    "side builder declaration",
)
HDR.write_text(hdr, encoding="utf-8")

print("J1 clean Joy-Con 2 L+R pair-registration probe applied")
