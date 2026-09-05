#!/usr/bin/env python3
"""Apply F27-M21 dual Joy-Con 2 R topology over the validated M15 scaffold."""
from pathlib import Path

MODE = Path("OpenPuck/mode_switch2_pro.cpp")
JOY = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M21 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)

mode = MODE.read_text(encoding="utf-8")
if "F27-M15-DUAL-S2-TOPOLOGY" not in mode:
    raise SystemExit("F27-M21 requires the accepted M15 topology scaffold")
if "F27-M21-DUAL-JCR-TOPOLOGY" in mode:
    raise SystemExit("F27-M21 already applied")

mode = replace_once(mode, '#include "mode_switch2_pro.h"\n', '#include "mode_switch2_pro.h"\n#include "f27_joycon2.h"\n', "Joy-Con helper include")
mode = replace_once(mode,
    'static const char M15_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M15-DUAL-S2-TOPOLOGY";\n',
    'static const char M15_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M15-DUAL-S2-TOPOLOGY";\nstatic const char M21_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M21-DUAL-JCR-TOPOLOGY";\n',
    "M21 build marker")
mode = replace_once(mode,
    'static inline bool sw2JoyconR()\n{\n\treturn g_sw2SessionCtx == M15_SW2_JOYCON_R;\n}',
    'static inline bool sw2JoyconR()\n{\n\treturn true;\n}',
    "both sessions Joy-Con-R")

mode = replace_once(mode,
    '\t\tmemcpy(g_sw2ControlReply, SW2_VENDOR_IDENTITY,\n\t\t       sizeof SW2_VENDOR_IDENTITY);\n\t\treturn tud_control_xfer(rhport, request, g_sw2ControlReply,\n',
    '\t\tmemcpy(g_sw2ControlReply, SW2_VENDOR_IDENTITY,\n\t\t       sizeof SW2_VENDOR_IDENTITY);\n\t\tf27JoyconPatchIdentity(g_sw2ControlReply, sizeof g_sw2ControlReply);\n\t\treturn tud_control_xfer(rhport, request, g_sw2ControlReply,\n',
    "shared EP0 Joy-Con identity")

mode = replace_once(mode,
    '\tout[5] = (uint8_t)(b >> 8);\n}',
    '\tout[5] = (uint8_t)(b >> 8);\n\tif (g_sw2SessionCtx == M15_SW2_JOYCON_R)\n\t\tout[5] ^= 0x01u;\n}',
    "distinct companion controller address")

needle = ('\tif (sw2JoyconR()) {\n\t\tconst uint32_t pid = 0x00013014u;\n\t\tif (address <= pid && pid < address + len)\n\t\t\tblock[pid - address] = 0x66;\n\t\tif (address <= pid + 1u && pid + 1u < address + len)\n\t\t\tblock[pid + 1u - address] = 0x20;\n\t}\n')
mode = replace_once(mode, needle,
    needle + '\tif (g_sw2SessionCtx == M15_SW2_JOYCON_R) {\n\t\tconst uint32_t serialTail = 0x0001300fu;\n\t\tif (address <= serialTail && serialTail < address + len)\n\t\t\tblock[serialTail - address] = \'1\';\n\t}\n',
    "distinct companion factory serial")

old_drain = '''\t\tif (s == M15_SW2_JOYCON_R) {
\t\t\tif (rid == 0x05)
\t\t\t\tsw2Build05Neutral((uint8_t)bond, p);
\t\t\telse {
\t\t\t\trid = 0x08;
\t\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);
\t\t\t}
\t\t} else if (rid == 0x05) {
\t\t\tsw2Build05((uint8_t)bond, p);
\t\t} else {
\t\t\trid = 0x09;
\t\t\tsw2Build09((uint8_t)bond, p);
\t\t}
'''
new_drain = '''\t\tif (s == M15_SW2_JOYCON_R) {
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
mode = replace_once(mode, old_drain, new_drain, "live session native stream")

old_get = '''\t} else if (itf == M15_SW2_JOYCON_R) {
\t\tif (reportId == 0x05)
\t\t\tsw2Build05Neutral((uint8_t)bond, p);
\t\telse if (reportId == 0x08 || reportId == 0x09)
\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);
\t\telse
\t\t\treturn 0;
\t} else if (reportId == 0x05) {
\t\tsw2Build05((uint8_t)bond, p);
\t} else if (reportId == 0x09) {
\t\tsw2Build09((uint8_t)bond, p);
\t} else {
\t\treturn 0;
\t}
'''
new_get = '''\t} else if (itf == M15_SW2_JOYCON_R) {
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
mode = replace_once(mode, old_get, new_get, "live session GET_REPORT")

mode = replace_once(mode,
    '\t\tg_sw2Sessions[s].activeReport =\n\t\t\ts == M15_SW2_JOYCON_R ? 0x08 : 0x09;\n\t\tg_sw2Sessions[s].featureMask =\n\t\t\ts == M15_SW2_JOYCON_R ? 0x37 : 0;\n',
    '\t\tg_sw2Sessions[s].activeReport = 0x08;\n\t\tg_sw2Sessions[s].featureMask = 0x37;\n',
    "both session defaults")
mode = replace_once(mode,
    '\tasm volatile("" : : "r"(M15_BUILD_MARKER) : "memory");\n',
    '\tasm volatile("" : : "r"(M15_BUILD_MARKER) : "memory");\n\tasm volatile("" : : "r"(M21_BUILD_MARKER) : "memory");\n',
    "retain M21 marker")
MODE.write_text(mode, encoding="utf-8")

joy = JOY.read_text(encoding="utf-8")
joy = replace_once(joy, '\tout[4] = 0x07;\n', '\tout[4] = 0x07;\n\tout[8] = 0x38;\n', "M3 steady-state byte")
joy = replace_once(joy, '\tbool requestedMouse = (features & 0x10u) != 0;\n', '\tbool requestedMouse = true;\n', "M3 forced mouse gate")
joy = replace_once(joy, '\tif (surface && (features & 0x04u)) {\n', '\tif (surface) {\n', "M3 stationary carrier gate")
JOY.write_text(joy, encoding="utf-8")
print("F27-M21 dual Joy-Con 2 R topology probe applied")
