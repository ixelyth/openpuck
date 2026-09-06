#!/usr/bin/env python3
"""Move the M31 one-shot trace state before r384 raw-trace prepare/clear users."""
from pathlib import Path

P = Path("OpenPuck/mode_switch2_pro.cpp")
s = P.read_text(encoding="utf-8")
needle = "static uint16_t g_m31TraceSeen = 0;\n"
if s.count(needle) != 1:
    raise SystemExit(f"M31 trace-state declaration count {s.count(needle)}, expected 1")
s = s.replace(needle, "", 1)
anchor = "static void m27TracePrepare()\n{"
if s.count(anchor) != 1:
    raise SystemExit(f"M31 trace prepare anchor count {s.count(anchor)}, expected 1")
s = s.replace(anchor, needle + "\n" + anchor, 1)
P.write_text(s, encoding="utf-8")
print("F27-M31 trace-state declaration ordered before raw-trace users")
