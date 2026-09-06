#!/usr/bin/env python3
"""F27-M29 v3: coherent Joy-Con 2 L/R role assignment over hardware-positive M28G/M27.

The physical USB/bootstrap shell remains the proven Switch 2 Pro transport.
M27's post-copy C0/03 logical PID patch, per-session SPI identity, native report,
firmware side type, and native payload are assigned coherently as JCL/JCR.
Only Switch-2/Joy-Con-2-specific facts are used.
"""

from pathlib import Path
import argparse
import re

MODE = Path("OpenPuck/mode_switch2_pro.cpp")
JOY = Path("OpenPuck/f27_joycon2.cpp")
HDR = Path("OpenPuck/f27_joycon2.h")


def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"F27-M29v3 {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)


def regex_once(text, pattern, repl, label):
    out, n = re.subn(pattern, repl, text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"F27-M29v3 {label}: regex count {n}, expected 1")
    return out


def regex_exact(text, pattern, repl, expected, label):
    out, n = re.subn(pattern, repl, text, flags=re.S)
    if n != expected:
        raise SystemExit(f"F27-M29v3 {label}: regex count {n}, expected {expected}")
    return out


ap = argparse.ArgumentParser()
ap.add_argument("--session0", choices=("JCR", "JCL"), required=True)
a = ap.parse_args()
s0_right = a.session0 == "JCR"
order = "JCR-JCL" if s0_right else "JCL-JCR"
right_session = "M15_SW2_PRO" if s0_right else "M15_SW2_JOYCON_R"
marker = f"F27-M29-{order}-PAIR"

mode = MODE.read_text(encoding="utf-8")
joy = JOY.read_text(encoding="utf-8")
hdr = HDR.read_text(encoding="utf-8")
for required in ("F27-M27-PROVEN-SESSION1-LEFT-JCR", "F27-M28G-GRIP-CONTEXT"):
    if required not in mode:
        raise SystemExit(f"F27-M29v3 requires {required}")
if "F27-M29-" in mode:
    raise SystemExit("F27-M29v3 already applied")

mode = regex_once(
    mode,
    r'(static\s+const\s+char\s+M28G_BUILD_MARKER\[\]\s*__attribute__\(\(used\)\)\s*=\s*"F27-M28G-GRIP-CONTEXT";)',
    r'\1\nstatic const char M29_BUILD_MARKER[] __attribute__((used)) = "' + marker + r'";',
    "marker",
)
mode = replace_once(
    mode,
    'asm volatile("" : : "r"(M28G_BUILD_MARKER) : "memory");',
    'asm volatile("" : : "r"(M28G_BUILD_MARKER) : "memory");\n\tasm volatile("" : : "r"(M29_BUILD_MARKER) : "memory");',
    "marker retain",
)

helpers = f'''
static inline bool m29SessionRight(uint8_t session)
{{
\treturn session == {right_session};
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
\t// Switch 2 command 0x10/0x01: 00=Joy-Con 2 L, 01=Joy-Con 2 R.
\treturn m29SessionRight(session) ? 0x01 : 0x00;
}}
'''
mode = regex_once(
    mode,
    r'(static\s+inline\s+bool\s+sw2JoyconR\(\)\s*\{\s*return\s+true;\s*\})',
    r'\1\n' + helpers,
    "side helpers",
)

# M21/M27 already copy the proven Pro2 factory block and then patch its PID to
# JCR. Preserve that architecture; only make the post-copy logical PID match
# whichever Joy-Con 2 side occupies session 0.
mode = regex_once(
    mode,
    r'(f27JoyconPatchIdentity\(g_sw2ControlReply,\s*sizeof\s+g_sw2ControlReply\);)',
    r'\1\n\t\tg_sw2ControlReply[20] = m29SessionPidLow(M15_SW2_PRO);\n\t\tg_sw2ControlReply[21] = 0x20;',
    "C0/03 logical PID",
)

# Per-session factory/SPI PID: 2066=R, 2067=L.
mode = regex_once(
    mode,
    r'if\s*\(sw2JoyconR\(\)\)\s*\{\s*const\s+uint32_t\s+pid\s*=\s*0x00013014u;\s*if\s*\(address\s*<=\s*pid\s*&&\s*pid\s*<\s*address\s*\+\s*len\)\s*block\[pid\s*-\s*address\]\s*=\s*0x66;\s*if\s*\(address\s*<=\s*pid\s*\+\s*1u\s*&&\s*pid\s*\+\s*1u\s*<\s*address\s*\+\s*len\)\s*block\[pid\s*\+\s*1u\s*-\s*address\]\s*=\s*0x20;\s*\}',
    '''{\n\t\tconst uint32_t pid = 0x00013014u;\n\t\tif (address <= pid && pid < address + len)\n\t\t\tblock[pid - address] = m29SessionPidLow(g_sw2SessionCtx);\n\t\tif (address <= pid + 1u && pid + 1u < address + len)\n\t\t\tblock[pid + 1u - address] = 0x20;\n\t}''',
    "SPI PID",
)

# Select native 07/08 per session. Common report 05 remains common.
mode = regex_once(
    mode,
    r'if\s*\(sub\s*==\s*0x0a\s*&&\s*n\s*>=\s*9\)\s*\{.*?\n\s*\}\s*\n\s*return\s+8;',
    '''if (sub == 0x0a && n >= 9) {\n\t\tif (cmd[8] == 0x05)\n\t\t\tg_sw2ActiveReport = 0x05;\n\t\telse if (cmd[8] == 0x07 || cmd[8] == 0x08 || cmd[8] == 0x09)\n\t\t\tg_sw2ActiveReport = m29SessionNativeReport(g_sw2SessionCtx);\n\t}\n\treturn 8;''',
    "native report select",
)

# Explicit Switch-2 source: Joy-Con 2 FW 1.0.14; type 00=L, 01=R.
mode = regex_once(
    mode,
    r'case\s+0x10:\s*if\s*\(sub\s*==\s*0x01\)\s*\{\s*static\s+const\s+uint8_t\s+info\[12\]\s*=\s*\{.*?\};\s*sw2DataHeader\(reply,\s*id,\s*seq,\s*sub\);\s*memcpy\(reply\s*\+\s*8,\s*info,\s*sizeof\s+info\);\s*replyLen\s*=\s*20;\s*\}\s*break;',
    '''case 0x10:\n\t\tif (sub == 0x01) {\n\t\t\tuint8_t info[12] = {\n\t\t\t\t0x01, 0x00, 0x0e, 0x00, 0x0c, 0x00,\n\t\t\t\t0x00, 0x00, 0xff, 0xff, 0xff, 0xff,\n\t\t\t};\n\t\t\tinfo[3] = m29SessionFirmwareType(g_sw2SessionCtx);\n\t\t\tsw2DataHeader(reply, id, seq, sub);\n\t\t\tmemcpy(reply + 8, info, sizeof info);\n\t\t\treplyLen = 20;\n\t\t}\n\t\tbreak;''',
    "firmware side type",
)

mode = replace_once(mode, "g_sw2ActiveReport = sw2JoyconR() ? 0x08 : 0x09;",
                    "g_sw2ActiveReport = m29SessionNativeReport(s);", "reset report")
mode = replace_once(mode, "g_sw2Sessions[s].activeReport = 0x08;",
                    "g_sw2Sessions[s].activeReport = m29SessionNativeReport(s);", "begin report")

# Add a coherent JCL payload builder without touching the frozen JCR builders.
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
m = re.search(r'bool\s+f27JoyconBuildM27Session1Left\(.*?\n\}\n', joy, re.S)
if not m:
    raise SystemExit("F27-M29v3 M27 helper anchor missing")
joy = joy[:m.end()] + left_export + joy[m.end():]
hdr = regex_once(
    hdr,
    r'(bool\s+f27JoyconBuildM27Session1Left\([^;]+;)',
    r'''\1\n// M29 coherent Joy-Con 2 L builder.\nbool f27JoyconBuildM29Left(uint8_t slot, uint8_t features,\n\t\t\t   uint8_t *reportId, uint8_t out[63]);''',
    "left declaration",
)

# One dispatcher makes r384 and r385 identical except m29SessionRight().
dispatcher = r'''
static bool m29BuildSessionNative(uint8_t session, uint8_t slot,
				  uint8_t features, uint8_t *reportId,
				  uint8_t out[63])
{
	if (m29SessionRight(session))
		return f27JoyconBuildNative(slot, features, reportId, out);
	return f27JoyconBuildM29Left(slot, features, reportId, out);
}
'''
mode = mode.replace(helpers, helpers + dispatcher, 1)

# Redirect exactly the two M27 session1 call sites (periodic + GET_REPORT).
mode = regex_exact(
    mode,
    r'f27JoyconBuildM27Session1Left\(\(uint8_t\)bond,\s*g_sw2Features,\s*&rid,\s*p\)',
    'm29BuildSessionNative(M15_SW2_JOYCON_R, (uint8_t)bond, g_sw2Features, &rid, p)',
    2,
    "session1 dispatcher calls",
)
# Redirect exactly the two live session0 native call sites. Dispatcher itself has
# generic variable names and therefore cannot match this bond-specific pattern.
mode = regex_exact(
    mode,
    r'f27JoyconBuildNative\(\(uint8_t\)bond,\s*g_sw2Features,\s*&rid,\s*p\)',
    'm29BuildSessionNative(M15_SW2_PRO, (uint8_t)bond, g_sw2Features, &rid, p)',
    2,
    "session0 dispatcher calls",
)

# Both GET_REPORT branches must accept either native Joy-Con report request and
# then return the side assigned to that session.
mode = regex_exact(
    mode,
    r'reportId\s*==\s*0x08\s*\|\|\s*reportId\s*==\s*0x09',
    'reportId == 0x07 || reportId == 0x08 || reportId == 0x09',
    2,
    "GET_REPORT native acceptance",
)

# The two drain fallbacks are only defensive, but keep their report IDs coherent.
mode, fallbacks = re.subn(
    r'rid\s*=\s*0x08;\s*\n(\s*)sw2BuildJoyconRNeutral',
    r'rid = m29SessionNativeReport(s);\n\1sw2BuildJoyconRNeutral',
    mode,
)
if fallbacks != 2:
    raise SystemExit(f"F27-M29v3 drain fallback count {fallbacks}, expected 2")

MODE.write_text(mode, encoding="utf-8")
JOY.write_text(joy, encoding="utf-8")
HDR.write_text(hdr, encoding="utf-8")
print(f"F27-M29v3 applied: session0={a.session0} session1={'JCL' if s0_right else 'JCR'}")
