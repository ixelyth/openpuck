#!/usr/bin/env python3
"""F27-M24: swap live/companion roles across the M22 dual Joy-Con-R topology.

Session 0 (first USB function) becomes the independently-addressed left-pad mouse
companion. Session 1 (second USB function) receives the original/live Joy-Con-R
identity semantics, normal controller inputs, and the proven right-pad mouse path.
The descriptor topology itself is unchanged from M22.
"""
from pathlib import Path

MODE = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M24 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = MODE.read_text(encoding="utf-8")
if "F27-M22-HIDDEN-JCR-LEFT-MOUSE" not in src:
    raise SystemExit("F27-M24 requires the composed M22 R+R left-pad probe")
if "F27-M23-JCR-JCL-LEFT-MOUSE" in src:
    raise SystemExit("F27-M24 must not compose the heterogeneous M23 experiment")
if "F27-M24-ROLE-SWAP-JCR" in src:
    raise SystemExit("F27-M24 already applied")

src = replace_once(
    src,
    'static const char M22_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M22-HIDDEN-JCR-LEFT-MOUSE";\n',
    'static const char M22_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M22-HIDDEN-JCR-LEFT-MOUSE";\n'
    'static const char M24_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M24-ROLE-SWAP-JCR";\n',
    "build marker",
)

# M21 gives session 1 the companion address/serial. M24 swaps those identity
# roles: first USB function/session 0 gets the companion identity, while the
# original/live identity moves to USB function/session 1.
src = replace_once(
    src,
    "\tif (g_sw2SessionCtx == M15_SW2_JOYCON_R)\n\t\tout[5] ^= 0x01u;",
    "\tif (g_sw2SessionCtx == M15_SW2_PRO)\n\t\tout[5] ^= 0x01u;",
    "companion controller address role",
)
src = replace_once(
    src,
    "\tif (g_sw2SessionCtx == M15_SW2_JOYCON_R) {\n"
    "\t\tconst uint32_t serialTail = 0x0001300fu;\n"
    "\t\tif (address <= serialTail && serialTail < address + len)\n"
    "\t\t\tblock[serialTail - address] = '1';\n"
    "\t}",
    "\tif (g_sw2SessionCtx == M15_SW2_PRO) {\n"
    "\t\tconst uint32_t serialTail = 0x0001300fu;\n"
    "\t\tif (address <= serialTail && serialTail < address + len)\n"
    "\t\t\tblock[serialTail - address] = '1';\n"
    "\t}",
    "companion factory serial role",
)

# Keep M22's input-enable bypass on session 1. It is now the second/live
# controller, so this forces its stream even if the console never enables HID1.
# Session 0 remains host-enabled exactly as the first/visible M20/M21 function.

old_drain = '''\t\tif (s == M15_SW2_JOYCON_R) {
\t\t\t// Force the unseen companion to native report 0x08.
\t\t\trid = 0x08;
\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);
\t\t} else if (rid == 0x05) {
\t\t\tsw2Build05((uint8_t)bond, p);
\t\t} else if (!f27JoyconBuildNative((uint8_t)bond, g_sw2Features, &rid, p)) {
\t\t\trid = 0x08;
\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);
\t\t}
'''
new_drain = '''\t\tif (s == M15_SW2_PRO) {
\t\t\t// M24 first function is the companion: LEFT-pad mouse only.
\t\t\trid = 0x08;
\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);
\t\t} else if (rid == 0x05) {
\t\t\t// M24 second function carries the original/live common report.
\t\t\tsw2Build05((uint8_t)bond, p);
\t\t} else if (!f27JoyconBuildNative((uint8_t)bond, g_sw2Features, &rid, p)) {
\t\t\trid = 0x08;
\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);
\t\t}
'''
src = replace_once(src, old_drain, new_drain, "interrupt payload role swap")

old_get = '''\t} else if (itf == M15_SW2_JOYCON_R) {
\t\tif (reportId == 0x08 || reportId == 0x09)
\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);
\t\telse if (reportId == 0x05)
\t\t\tsw2Build05Neutral((uint8_t)bond, p);
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
new_get = '''\t} else if (itf == M15_SW2_PRO) {
\t\tif (reportId == 0x08 || reportId == 0x09)
\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);
\t\telse if (reportId == 0x05)
\t\t\tsw2Build05Neutral((uint8_t)bond, p);
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
src = replace_once(src, old_get, new_get, "GET_REPORT payload role swap")

# Route output/rumble ownership with the live controller role as well. This does
# not affect topology registration, but keeps M24's role swap internally exact.
src = replace_once(
    src,
    "\t\tif (itf == M15_SW2_PRO && reportType == HID_REPORT_TYPE_OUTPUT) {\n"
    "\t\t\tg_sw2SessionCtx = M15_SW2_PRO;",
    "\t\tif (itf == M15_SW2_JOYCON_R &&\n"
    "\t\t    reportType == HID_REPORT_TYPE_OUTPUT) {\n"
    "\t\t\tg_sw2SessionCtx = M15_SW2_JOYCON_R;",
    "rumble/live output role",
)

src = replace_once(
    src,
    '\tasm volatile("" : : "r"(M22_BUILD_MARKER) : "memory");\n',
    '\tasm volatile("" : : "r"(M22_BUILD_MARKER) : "memory");\n'
    '\tasm volatile("" : : "r"(M24_BUILD_MARKER) : "memory");\n',
    "retain marker",
)

MODE.write_text(src, encoding="utf-8")
print("F27-M24 dual Joy-Con-R role swap applied")
