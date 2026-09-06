#!/usr/bin/env python3
"""F27-M30/r386: force session1 JCL live behind the hardware-positive r384 JCR/JCL baseline.

Session 0 remains the accepted JCR path. Whenever session0 Nintendo state changes,
mirror only input/report/feature state into session1 while retaining JCL report 0x07.
The accepted r384 drain control flow is preserved; only its TinyUSB readiness/report
calls are wrapped to persist first session1 endpoint/TX observations.
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

# Rewrite only the original r384 drain call sites BEFORE defining wrappers, so
# the transform cannot accidentally match the wrappers' own TinyUSB calls.
ready_calls = list(re.finditer(r'tud_hid_n_ready\(([^)]+)\)', src))
if len(ready_calls) != 1:
    raise SystemExit(f"M30 expected one baseline tud_hid_n_ready call, found {len(ready_calls)}")
m = ready_calls[0]
src = src[:m.start()] + f"m30HidReady(s, {m.group(1)})" + src[m.end():]

report_matches = list(re.finditer(
    r'tud_hid_n_report\(([^,]+),\s*rid,\s*p,\s*sizeof p\)', src))
if len(report_matches) != 1:
    raise SystemExit(f"M30 expected one baseline periodic tud_hid_n_report call, found {len(report_matches)}")
m = report_matches[0]
src = (src[:m.start()] +
       f"m30HidReport(s, {m.group(1).strip()}, rid, p, sizeof p)" +
       src[m.end():])

helper = r'''
// r386 discriminator: session1 is deliberately not given synthetic Nintendo
// vendor traffic. It only inherits state that gates native HID streaming.
static void m30MirrorSession0ToJcl(void)
{
	M15Sw2Session &src = g_sw2Sessions[M15_SW2_PRO];
	M15Sw2Session &dst = g_sw2Sessions[M15_SW2_JOYCON_R];
	dst.inputEnabled = src.inputEnabled;
	dst.featureMask = src.featureMask;
	dst.features = src.features;
	dst.activeReport = src.activeReport == 0x05 ? 0x05 : 0x07;
}

// Defined by the post-observer transform so these one-shot events persist in JT.
static void m30TraceSession1Event(uint8_t phase, bool ready, uint8_t rid);

static bool m30HidReady(uint8_t session, uint8_t instance)
{
	bool ready = tud_hid_n_ready(instance);
	if (session == M15_SW2_JOYCON_R)
		m30TraceSession1Event(ready ? 2 : 1, ready,
					g_sw2Sessions[session].activeReport);
	return ready;
}

static bool m30HidReport(uint8_t session, uint8_t instance, uint8_t rid,
			 uint8_t const *report, uint16_t len)
{
	if (session == M15_SW2_JOYCON_R)
		m30TraceSession1Event(3, true, rid);
	bool queued = tud_hid_n_report(instance, rid, report, len);
	if (session == M15_SW2_JOYCON_R && queued)
		m30TraceSession1Event(4, true, rid);
	return queued;
}

'''
src = replace_once(
    src,
    "static void sw2BuildVendorReply(void)",
    helper + "static void sw2BuildVendorReply(void)",
    "mirror/helper insertion",
)

# Mirror at the beginning of each valid drain cycle. This intentionally occurs
# outside sw2BuildVendorReply so the frozen r381/r384 bulk-observer anchor stays
# byte-exact. A command processed in one loop is reflected to session1 on the
# next loop, before any subsequent periodic stream opportunity.
src = replace_once(
    src,
    "\tif (g_usbMode != MODE_SW2_PRO || g_usbMountCount == 0)\n\t\treturn;\n\n\tint bond = g_usbToBond[0];",
    "\tif (g_usbMode != MODE_SW2_PRO || g_usbMountCount == 0)\n\t\treturn;\n\n"
    "\tm30MirrorSession0ToJcl();\n\n"
    "\tint bond = g_usbToBond[0];",
    "drain-cycle state mirror",
)

MODE.write_text(src, encoding="utf-8")
print("F27-M30 r386 forced session1 JCL discriminator applied")
