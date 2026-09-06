#!/usr/bin/env python3
"""Adapt the generic M27 trace transform to the exact composed dual-session source."""
from pathlib import Path
import re

p = Path("tools/f27_m27_persistent_trace.py")
s = p.read_text(encoding="utf-8")

for old, new, label in [
    ('sw2BuildVendorReply()\\n', 'sw2BuildVendorReply(void)\\n', 'vendor function spelling'),
    ('static void sw2Drain()\\n', 'static void sw2Drain(void)\\n', 'drain function spelling'),
    ('itf != 0', 'itf >= M15_SW2_SESSION_COUNT', 'dual HID GET guard'),
]:
    n = s.count(old)
    if n == 0:
        raise SystemExit(f"trace-fixup missing {label}")
    s = s.replace(old, new)

# M27 has comments and a session-specific rumble guard immediately inside the
# SET_REPORT branch, so inject the observer at the branch opening only.
pat = re.compile(
    r'''src = replace_once\(\n    src,\n    "\{\\n\\tif \(g_usbMode == MODE_SW2_PRO && itf == 0\) \{\\n\\t\\tif \(reportType == HID_REPORT_TYPE_OUTPUT\) \{\\n",\n    "\{\\n\\tif \(g_usbMode == MODE_SW2_PRO && itf == 0\) \{\\n"\n    "\\t\\tm27TraceQueueHid\('O', reportId, reportType, size\);\\n"\n    "\\t\\tif \(reportType == HID_REPORT_TYPE_OUTPUT\) \{\\n",\n    "HID SET trace",\n\)''',
    re.S,
)
repl = '''src = replace_once(\n    src,\n    "{\\n\\tif (g_usbMode == MODE_SW2_PRO && itf < M15_SW2_SESSION_COUNT) {\\n",\n    "{\\n\\tif (g_usbMode == MODE_SW2_PRO && itf < M15_SW2_SESSION_COUNT) {\\n"\n    "\\t\\tm27TraceQueueHid('O', reportId, reportType, size);\\n",\n    "HID SET trace",\n)'''
s, n = pat.subn(repl, s, count=1)
if n != 1:
    raise SystemExit("trace-fixup HID SET block mismatch")

# beginPool in M15 initializes two session structs before registering the drain.
# Insert trace preparation at the function opening instead of matching its body.
pat = re.compile(
    r'''src = replace_once\(\n    src,\n    "void Switch2ProController::beginPool\(\)\\n\{\\n\\tif \(!g_sw2DrainRegistered\) \{\\n",\n    "void Switch2ProController::beginPool\(\)\\n\{\\n\\tm27TracePrepare\(\);\\n\\tif \(!g_sw2DrainRegistered\) \{\\n",\n    "trace prepare",\n\)''',
    re.S,
)
repl = '''src = replace_once(\n    src,\n    "void Switch2ProController::beginPool()\\n{\\n",\n    "void Switch2ProController::beginPool()\\n{\\n\\tm27TracePrepare();\\n",\n    "trace prepare",\n)'''
s, n = pat.subn(repl, s, count=1)
if n != 1:
    raise SystemExit("trace-fixup beginPool block mismatch")

# The M27 transport has two independent vendor endpoints. Preserve the r375
# record shape but use the final byte to identify which session received each
# bulk command; that is more valuable than command byte 11 for this control.
s = s.replace("r.k = n > 11 ? cmd[11] : 0;", "r.k = g_sw2SessionCtx;", 1)
s = s.replace("p=%02X%02X%02X%02X\\\\n", "p=%02X%02X%02X sess=%u\\\\n", 1)

p.write_text(s, encoding="utf-8")
print("F27 M27 trace transform adapted to dual-session runtime")
