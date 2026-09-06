#!/usr/bin/env python3
"""Extend the accepted M27 raw JT observer with four one-shot r386 session1 HID events."""
from pathlib import Path

MODE = Path("OpenPuck/mode_switch2_pro.cpp")
src = MODE.read_text(encoding="utf-8")


def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"M30 trace {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)


if "F27-M30-FORCE-SESSION1-JCL" not in src:
    raise SystemExit("M30 trace requires forced-session1 transform")
if "struct M27TraceRecord" not in src or "m27TraceRamAppend" not in src:
    raise SystemExit("M30 trace requires M27 observer before application")

impl = r'''
static uint8_t g_m30TraceSeen = 0;

static void m30TraceSession1Event(uint8_t phase, bool ready, uint8_t rid)
{
	if (phase < 1 || phase > 4)
		return;
	uint8_t bit = (uint8_t)(1u << (phase - 1u));
	if (g_m30TraceSeen & bit)
		return;
	g_m30TraceSeen |= bit;
	M27TraceRecord r = {};
	r.ms = millis();
	r.kind = 'I';
	r.a = phase; // 1=not-ready, 2=ready, 3=TX attempt, 4=TX queued
	r.b = ready ? 1 : 0;
	r.c = rid;
	r.d = g_sw2Sessions[M15_SW2_JOYCON_R].inputEnabled ? 1 : 0;
	r.e = g_sw2Sessions[M15_SW2_JOYCON_R].features;
	r.f = g_sw2Sessions[M15_SW2_JOYCON_R].featureMask;
	r.g = M15_SW2_JOYCON_R;
	m27TraceRamAppend(r);
}

'''
src = replace_once(
    src,
    "static void m27TracePersistQuiet()",
    impl + "static void m27TracePersistQuiet()",
    "event implementation",
)

old = """\t\t} else if (r.kind == 'G' || r.kind == 'O') {\n\t\t\tSerial.printf(\"# JT %u %c t=%lu rid=%02X type=%u len=%u\\n\",\n\t\t\t\t      index, (char)r.kind, (unsigned long)r.ms, r.a,\n\t\t\t\t      r.b, (unsigned)(r.c | ((uint16_t)r.d << 8)));\n"""
new = """\t\t} else if (r.kind == 'I') {\n\t\t\tSerial.printf(\"# JT %u I t=%lu phase=%u ready=%u rid=%02X input=%u feat=%02X mask=%02X sess=%u\\n\",\n\t\t\t\t      index, (unsigned long)r.ms, r.a, r.b, r.c, r.d,\n\t\t\t\t      r.e, r.f, r.g);\n\t\t} else if (r.kind == 'G' || r.kind == 'O') {\n\t\t\tSerial.printf(\"# JT %u %c t=%lu rid=%02X type=%u len=%u\\n\",\n\t\t\t\t      index, (char)r.kind, (unsigned long)r.ms, r.a,\n\t\t\t\t      r.b, (unsigned)(r.c | ((uint16_t)r.d << 8)));\n"""
src = replace_once(src, old, new, "dump formatter")

MODE.write_text(src, encoding="utf-8")
print("F27-M30 r386 session1 JT events applied")
