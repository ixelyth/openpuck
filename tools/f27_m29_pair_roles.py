#!/usr/bin/env python3
"""F27-M29: convert the hardware-positive M28G/M27 dual-JCR baseline into a coherent Joy-Con 2 R/L pair.

Only Switch-2/Joy-Con-2-specific side semantics are used. Original Switch/Joy-Con
protocol data is deliberately non-authoritative for this transform. The proven
M27 Pro2 EP0/bootstrap identity is deliberately preserved unchanged.
"""

from pathlib import Path
import argparse
import re

MODE = Path("OpenPuck/mode_switch2_pro.cpp")
JOY = Path("OpenPuck/f27_joycon2.cpp")
HDR = Path("OpenPuck/f27_joycon2.h")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M29 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, repl: str, label: str) -> str:
    out, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"F27-M29 {label}: regex count {count}, expected 1")
    return out


ap = argparse.ArgumentParser()
ap.add_argument("--session0", choices=("JCR", "JCL"), required=True)
args = ap.parse_args()
s0_right = args.session0 == "JCR"
order = "JCR-JCL" if s0_right else "JCL-JCR"
right_expr = "M15_SW2_PRO" if s0_right else "M15_SW2_JOYCON_R"
marker = f"F27-M29-{order}-PAIR"

mode = MODE.read_text(encoding="utf-8")
joy = JOY.read_text(encoding="utf-8")
hdr = HDR.read_text(encoding="utf-8")

for required in (
    "F27-M27-PROVEN-SESSION1-LEFT-JCR",
    "F27-M28G-GRIP-CONTEXT",
):
    if required not in mode:
        raise SystemExit(f"F27-M29 requires {required}")
if "F27-M29-" in mode:
    raise SystemExit("F27-M29 already applied")

mode = regex_once(
    mode,
    r'''(static\s+const\s+char\s+M28G_BUILD_MARKER\[\]\s*__attribute__\(\(used\)\)\s*=\s*"F27-M28G-GRIP-CONTEXT";)''',
    r'''\1\nstatic const char M29_BUILD_MARKER[] __attribute__((used)) = "''' + marker + r'''";''',
    "pair marker",
)
mode = replace_once(
    mode,
    'asm volatile("" : : "r"(M28G_BUILD_MARKER) : "memory");',
    'asm volatile("" : : "r"(M28G_BUILD_MARKER) : "memory");\n'
    '\tasm volatile("" : : "r"(M29_BUILD_MARKER) : "memory");',
    "retain pair marker",
)

# M21 made sw2JoyconR() true for both sessions so both retain Joy-Con-family
# feature/command semantics. Keep it untouched; side helpers cover only L/R facts.
side_helpers = f'''
static inline bool m29SessionRight(uint8_t session)
{{
\treturn session == {right_expr};
}}

static inline uint8_t m29SessionNativeReport(uint8_t session)
{{
\treturn m29SessionRight(session) ? 0x08 : 0x07;
}}

static inline uint8_t m29SessionPidLow(uint8_t session)
{{
\treturn m29SessionRight(session) ? 0x66 : 0x67;
}}

static inline uint8_t m29SessionFirmwareType(uint8_t session)
{{
\t// Switch 2 command 0x10/0x01: 0=Joy-Con 2 L, 1=Joy-Con 2 R.
\treturn m29SessionRight(session) ? 0x01 : 0x00;
}}
'''
mode = regex_once(
    mode,
    r'''(static\s+inline\s+bool\s+sw2JoyconR\(\)\s*\{\s*return\s+true;\s*\})''',
    r'''\1\n''' + side_helpers,
    "side helpers",
)

# Important: do NOT alter switch2ProVendorControlXfer/C0/03. r383 proves the
# Pro2 EP0 identity is a working admission shell. M29 changes only per-session
# logical identity after that shell has been accepted.

# Per-session factory reads expose 2066 for R and 2067 for L while preserving
# M25's distinct controller-address/serial role assignment.
mode = regex_once(
    mode,
    r'''if\s*\(sw2JoyconR\(\)\)\s*\{\s*const\s+uint32_t\s+pid\s*=\s*0x00013014u;\s*if\s*\(address\s*<=\s*pid\s*&&\s*pid\s*<\s*address\s*\+\s*len\)\s*block\[pid\s*-\s*address\]\s*=\s*0x66;\s*if\s*\(address\s*<=\s*pid\s*\+\s*1u\s*&&\s*pid\s*\+\s*1u\s*<\s*address\s*\+\s*len\)\s*block\[pid\s*\+\s*1u\s*-\s*address\]\s*=\s*0x20;\s*\}''',
    '''{\n\t\tconst uint32_t pid = 0x00013014u;\n\t\tif (address <= pid && pid < address + len)\n\t\t\tblock[pid - address] = m29SessionPidLow(g_sw2SessionCtx);\n\t\tif (address <= pid + 1u && pid + 1u < address + len)\n\t\t\tblock[pid + 1u - address] = 0x20;\n\t}''',
    "per-session factory PID",
)

# 07=L, 08=R. Generic 09 requests are treated as "native" through the Pro2 shell.
mode = regex_once(
    mode,
    r'''if\s*\(sub\s*==\s*0x0a\s*&&\s*n\s*>=\s*9\)\s*\{.*?\n\s*\}\s*\n\s*return\s+8;''',
    '''if (sub == 0x0a && n >= 9) {\n\t\tif (cmd[8] == 0x05)\n\t\t\tg_sw2ActiveReport = 0x05;\n\t\telse if (cmd[8] == 0x07 || cmd[8] == 0x08 || cmd[8] == 0x09)\n\t\t\tg_sw2ActiveReport = m29SessionNativeReport(g_sw2SessionCtx);\n\t}\n\treturn 8;''',
    "side-native report selection",
)

# Switch-2-specific Joy-Con 2 firmware response: 1.0.14, type 0=L / 1=R.
mode = regex_once(
    mode,
    r'''case\s+0x10:\s*if\s*\(sub\s*==\s*0x01\)\s*\{\s*static\s+const\s+uint8_t\s+info\[12\]\s*=\s*\{.*?\};\s*sw2DataHeader\(reply,\s*id,\s*seq,\s*sub\);\s*memcpy\(reply\s*\+\s*8,\s*info,\s*sizeof\s+info\);\s*replyLen\s*=\s*20;\s*\}\s*break;''',
    '''case 0x10:\n\t\tif (sub == 0x01) {\n\t\t\tuint8_t info[12] = {\n\t\t\t\t0x01, 0x00, 0x0e, 0x00, 0x0c, 0x00,\n\t\t\t\t0x00, 0x00, 0xff, 0xff, 0xff, 0xff,\n\t\t\t};\n\t\t\tinfo[3] = m29SessionFirmwareType(g_sw2SessionCtx);\n\t\t\tsw2DataHeader(reply, id, seq, sub);\n\t\t\tmemcpy(reply + 8, info, sizeof info);\n\t\t\treplyLen = 20;\n\t\t}\n\t\tbreak;''',
    "Joy-Con 2 firmware type",
)

mode = replace_once(
    mode,
    "g_sw2ActiveReport = sw2JoyconR() ? 0x08 : 0x09;",
    "g_sw2ActiveReport = m29SessionNativeReport(s);",
    "reset native report",
)
mode = replace_once(
    mode,
    "g_sw2Sessions[s].activeReport = 0x08;",
    "g_sw2Sessions[s].activeReport = m29SessionNativeReport(s);",
    "beginPool native reports",
)

# Coherent JCL builder: same Switch-2 Joy-Con-2 report-0x07 implementation,
# left buttons/stick/mouse, with the M21/M3-proven motion carrier behavior.
left_export = r'''

bool f27JoyconBuildM29Left(uint8_t slot, uint8_t features,
			   uint8_t *reportId, uint8_t out[63])
{
	if (!f27JoyconEnabled() || !reportId || !out || slot >= NSLOT)
		return false;
	*reportId = 0x07;
	buildSide(slot, false, features, out);
	return true;
}
'''
match = re.search(r'''bool\s+f27JoyconBuildM27Session1Left\(.*?\n\}\n''', joy, re.S)
if not match:
    raise SystemExit("F27-M29 M27 exported helper anchor missing")
joy = joy[:match.end()] + left_export + joy[match.end():]

hdr = regex_once(
    hdr,
    r'''(bool\s+f27JoyconBuildM27Session1Left\([^;]+;)''',
    r'''\1\n// M29 coherent Joy-Con 2 L builder for whichever logical session is left.\nbool f27JoyconBuildM29Left(uint8_t slot, uint8_t features,\n\t\t\t   uint8_t *reportId, uint8_t out[63]);''',
    "M29 left builder declaration",
)

right_call = "f27JoyconBuildNative"
left_call = "f27JoyconBuildM29Left"
s0_call = right_call if s0_right else left_call
s1_call = left_call if s0_right else right_call

mode = regex_once(
    mode,
    r'''if\s*\(s\s*==\s*M15_SW2_JOYCON_R\)\s*\{\s*// M27: coherent proven Joy-Con-R/M3 payload, LEFT-pad signal\.\s*if\s*\(!f27JoyconBuildM27Session1Left\(\(uint8_t\)bond,\s*g_sw2Features,\s*&rid,\s*p\)\)\s*\{\s*rid\s*=\s*0x08;\s*sw2BuildJoyconRNeutral\(\(uint8_t\)bond,\s*p\);\s*\}\s*\}\s*else\s+if\s*\(rid\s*==\s*0x05\)\s*\{\s*sw2Build05\(\(uint8_t\)bond,\s*p\);\s*\}\s*else\s+if\s*\(!f27JoyconBuildNative\(\(uint8_t\)bond,\s*g_sw2Features,\s*&rid,\s*p\)\)\s*\{\s*rid\s*=\s*0x08;\s*sw2BuildJoyconRNeutral\(\(uint8_t\)bond,\s*p\);\s*\}''',
    f'''if (s == M15_SW2_JOYCON_R) {{\n\t\t\tif (rid == 0x05) {{\n\t\t\t\tsw2Build05Neutral((uint8_t)bond, p);\n\t\t\t}} else if (!{s1_call}((uint8_t)bond, g_sw2Features, &rid, p)) {{\n\t\t\t\trid = m29SessionNativeReport(s);\n\t\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);\n\t\t\t}}\n\t\t}} else if (rid == 0x05) {{\n\t\t\tsw2Build05((uint8_t)bond, p);\n\t\t}} else if (!{s0_call}((uint8_t)bond, g_sw2Features, &rid, p)) {{\n\t\t\trid = m29SessionNativeReport(s);\n\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);\n\t\t}}''',
    "pair periodic builders",
)

mode = regex_once(
    mode,
    r'''\}\s*else\s+if\s*\(itf\s*==\s*M15_SW2_JOYCON_R\)\s*\{\s*if\s*\(reportId\s*==\s*0x08\s*\|\|\s*reportId\s*==\s*0x09\)\s*\{\s*uint8_t\s+rid\s*=\s*reportId;\s*if\s*\(!f27JoyconBuildM27Session1Left\(\(uint8_t\)bond,\s*g_sw2Features,\s*&rid,\s*p\)\)\s*return\s+0;\s*\}\s*else\s+if\s*\(reportId\s*==\s*0x05\)\s*sw2Build05Neutral\(\(uint8_t\)bond,\s*p\);''',
    f'''}} else if (itf == M15_SW2_JOYCON_R) {{\n\t\tif (reportId == 0x05) {{\n\t\t\tsw2Build05Neutral((uint8_t)bond, p);\n\t\t}} else if (reportId == 0x07 || reportId == 0x08 || reportId == 0x09) {{\n\t\t\tuint8_t rid = reportId;\n\t\t\tif (!{s1_call}((uint8_t)bond, g_sw2Features, &rid, p))\n\t\t\t\treturn 0;\n\t\t}} else {{\n\t\t\treturn 0;\n\t\t}}''',
    "session1 GET_REPORT",
)
mode = regex_once(
    mode,
    r'''\}\s*else\s+if\s*\(reportId\s*==\s*0x05\)\s*\{\s*sw2Build05\(\(uint8_t\)bond,\s*p\);\s*\}\s*else\s+if\s*\(reportId\s*==\s*0x08\s*\|\|\s*reportId\s*==\s*0x09\)\s*\{\s*uint8_t\s+rid\s*=\s*reportId;\s*if\s*\(!f27JoyconBuildNative\(\(uint8_t\)bond,\s*g_sw2Features,\s*&rid,\s*p\)\)\s*return\s+0;\s*\}\s*else\s*\{\s*return\s+0;\s*\}''',
    f'''}} else if (reportId == 0x05) {{\n\t\tsw2Build05((uint8_t)bond, p);\n\t}} else if (reportId == 0x07 || reportId == 0x08 || reportId == 0x09) {{\n\t\tuint8_t rid = reportId;\n\t\tif (!{s0_call}((uint8_t)bond, g_sw2Features, &rid, p))\n\t\t\treturn 0;\n\t}} else {{\n\t\treturn 0;\n\t}}''',
    "session0 GET_REPORT",
)

MODE.write_text(mode, encoding="utf-8")
JOY.write_text(joy, encoding="utf-8")
HDR.write_text(hdr, encoding="utf-8")
print(f"F27-M29 coherent Switch 2 pair applied: session0={args.session0}, session1={'JCL' if s0_right else 'JCR'}")
