#!/usr/bin/env python3
"""F27-M30/r386: force session1 JCL live behind the hardware-positive r384 JCR/JCL baseline.

Session 0 remains the accepted JCR path. Whenever session0 Nintendo state changes,
mirror only input/report/feature state into session1 while retaining JCL report 0x07.
The existing dual-session drain then attempts the second HID stream without requiring
Nintendo vendor initialization on session1.
"""
from pathlib import Path
import re

MODE = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"M30 {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)


def regex_once(text, pattern, repl, label):
    out, n = re.subn(pattern, repl, text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"M30 {label}: regex count {n}, expected 1")
    return out


src = MODE.read_text(encoding="utf-8")
for required in (
    "F27-M27-PROVEN-SESSION1-LEFT-JCR",
    "F27-M28G-GRIP-CONTEXT",
    "F27-M29-JCR-JCL-PAIR",
):
    if required not in src:
        raise SystemExit(f"M30 requires {required}")
if "F27-M30-FORCE-SESSION1-JCL" in src:
    raise SystemExit("M30 already applied")

src = regex_once(
    src,
    r'(static\s+const\s+char\s+M29_BUILD_MARKER\[\]\s*__attribute__\(\(used\)\)\s*=\s*"F27-M29-JCR-JCL-PAIR";)',
    r'\1\nstatic const char M30_BUILD_MARKER[] __attribute__((used)) = "F27-M30-FORCE-SESSION1-JCL";',
    "marker",
)
src = replace_once(
    src,
    'asm volatile("" : : "r"(M29_BUILD_MARKER) : "memory");',
    'asm volatile("" : : "r"(M29_BUILD_MARKER) : "memory");\n\tasm volatile("" : : "r"(M30_BUILD_MARKER) : "memory");',
    "marker retain",
)

helper = r'''
// r386 discriminator: session1 is deliberately not given synthetic Nintendo
// vendor traffic. It only inherits the state that gates native HID streaming.
static void m30MirrorSession0ToJcl(void)
{
	M15Sw2Session &src = g_sw2Sessions[M15_SW2_PRO];
	M15Sw2Session &dst = g_sw2Sessions[M15_SW2_JOYCON_R];
	dst.inputEnabled = src.inputEnabled;
	dst.featureMask = src.featureMask;
	dst.features = src.features;
	dst.activeReport = src.activeReport == 0x05 ? 0x05 : 0x07;
}

// Defined by the post-observer transform so first session1 readiness/TX events
// are persisted in the isolated JT raw snapshot rather than only kept in RAM.
static void m30TraceSession1Event(uint8_t phase, bool ready, uint8_t rid);

'''
src = replace_once(
    src,
    "static void sw2BuildVendorReply(void)",
    helper + "static void sw2BuildVendorReply(void)",
    "mirror helper",
)

# Mirror state after the command handler has applied session0 input/report/features.
src = regex_once(
    src,
    r'(\n\s*uint8_t first = replyLen > sizeof g_sw2VendorReply \?)',
    '\n\tif (g_sw2SessionCtx == M15_SW2_PRO)\n\t\tm30MirrorSession0ToJcl();\n\1',
    "post-command mirror",
)

# Split the readiness gate so JT can prove whether HID instance 1 ever became ready.
# M15-derived revisions may spell the TinyUSB instance as `s` or as the stored
# per-session hidInstance; preserve whichever expression the accepted baseline uses.
src = regex_once(
    src,
    r'if\s*\(\s*!g_sw2InputEnabled\s*\|\|\s*!tud_hid_n_ready\(([^)]]+)\)\s*\)\s*\n\s*continue;',
    '''if (!g_sw2InputEnabled)\n\t\t\tcontinue;\n\t\tbool hidReady = tud_hid_n_ready(\1);\n\t\tif (s == M15_SW2_JOYCON_R)\n\t\t\tm30TraceSession1Event(hidReady ? 2 : 1, hidReady, g_sw2ActiveReport);\n\t\tif (!hidReady)\n\t\t\tcontinue;''',
    "session1 readiness observation",
)

# Record first actual attempt and first successful queue without altering payload.
src = regex_once(
    src,
    r'if\s*\(tud_hid_n_report\(([^,]+),\s*rid,\s*p,\s*sizeof p\)\)\s*\n\s*g_sw2LastReportMs\s*=\s*millis\(\);',
    '''bool queued = tud_hid_n_report(\1, rid, p, sizeof p);\n\t\tif (s == M15_SW2_JOYCON_R) {\n\t\t\tm30TraceSession1Event(3, true, rid);\n\t\t\tif (queued)\n\t\t\t\tm30TraceSession1Event(4, true, rid);\n\t\t}\n\t\tif (queued)\n\t\t\tg_sw2LastReportMs = millis();''',
    "session1 transmit observation",
)

MODE.write_text(src, encoding="utf-8")
print("F27-M30 r386 forced session1 JCL discriminator applied")
