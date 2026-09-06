#!/usr/bin/env python3
"""Remove all startup flash I/O from the M27 control trace and gate persistence.

Apply after f27_m27_persistent_trace.py has injected the r376 observer into the
exact M27 composition. r377 keeps acquisition/initialization RAM-only. A single
trace snapshot may be written only after a physical controller is mounted,
Nintendo input is enabled, that state has stayed stable for 10 s, and traced
host commands have been quiet for 5 s.
"""
from pathlib import Path

P = Path("OpenPuck/mode_switch2_pro.cpp")
s = P.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"R377 {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)


s = replace_once(
    s,
    '// R376 control trace for the hardware-positive M27 transport. Records are\n'
    '// captured in RAM during host traffic; LittleFS is touched only after >=1 s of\n'
    '// silence so tracing does not add flash stalls to Nintendo initialization.\n',
    '// R377 control trace for the hardware-positive M27 transport. Acquisition and\n'
    '// Nintendo initialization are RAM-only. LittleFS is forbidden until a physical\n'
    '// controller is mounted, input is enabled, and the session has been stable.\n',
    "trace comment",
)

s = replace_once(
    s,
    'static const char M27_TRACE_FILE[] = "/jc2trace.bin";\n'
    'static const char M27_TRACE_TAG[] = "/jc2trtag";\n',
    'static const char M27_TRACE_FILE[] = "/jc2trace.bin";\n',
    "remove startup tag path",
)

s = replace_once(
    s,
    'static bool g_m27TraceDirty = false;\n'
    'static unsigned long g_m27TraceLastActivityMs = 0;\n',
    'static bool g_m27TraceDirty = false;\n'
    'static bool g_m27TraceFlushed = false;\n'
    'static unsigned long g_m27TraceLastActivityMs = 0;\n'
    'static unsigned long g_m27TraceReadySinceMs = 0;\n',
    "gate state",
)

old_persist = r'''static void m27TracePersistQuiet()
{
	M27TraceRecord r;
	while (m27TracePendingPop(&r))
		m27TraceRamAppend(r);
	if (!g_m27TraceDirty || g_m27TracePersisted >= g_m27TraceCount)
		return;
	if ((uint32_t)(millis() - g_m27TraceLastActivityMs) < 1000u)
		return;
	File f(InternalFS);
	if (!f.open(M27_TRACE_FILE, FILE_O_WRITE))
		return;
	f.seek(f.size());
	while (g_m27TracePersisted < g_m27TraceCount) {
		const M27TraceRecord &q = g_m27TraceRam[g_m27TracePersisted];
		if (f.write((const uint8_t *)&q, sizeof q) != sizeof q)
			break;
		g_m27TracePersisted++;
	}
	f.close();
	g_m27TraceDirty = g_m27TracePersisted < g_m27TraceCount;
}
'''
new_persist = r'''static void m27TraceService()
{
	M27TraceRecord r;
	while (m27TracePendingPop(&r))
		m27TraceRamAppend(r);
	if (g_m27TraceFlushed || !g_m27TraceDirty || !g_m27TraceCount)
		return;

	const bool controllerMounted = g_usbMountCount > 0;
	const bool inputEnabled =
		g_sw2Sessions[M15_SW2_PRO].inputEnabled ||
		g_sw2Sessions[M15_SW2_JOYCON_R].inputEnabled;
	if (!controllerMounted || !inputEnabled) {
		g_m27TraceReadySinceMs = 0;
		return;
	}

	const unsigned long now = millis();
	if (!g_m27TraceReadySinceMs) {
		g_m27TraceReadySinceMs = now;
		return;
	}
	if ((uint32_t)(now - g_m27TraceReadySinceMs) < 10000u)
		return;
	if ((uint32_t)(now - g_m27TraceLastActivityMs) < 5000u)
		return;

	// First and only flash mutation in a Switch session. It happens only after
	// the known-good RF+USB state above has already been continuously observed.
	InternalFS.remove(M27_TRACE_FILE);
	File f(InternalFS);
	if (!f.open(M27_TRACE_FILE, FILE_O_WRITE))
		return;
	g_m27TracePersisted = 0;
	while (g_m27TracePersisted < g_m27TraceCount) {
		const M27TraceRecord &q = g_m27TraceRam[g_m27TracePersisted];
		if (f.write((const uint8_t *)&q, sizeof q) != sizeof q)
			break;
		g_m27TracePersisted++;
	}
	f.close();
	if (g_m27TracePersisted == g_m27TraceCount) {
		g_m27TraceFlushed = true;
		g_m27TraceDirty = false;
	}
}
'''
s = replace_once(s, old_persist, new_persist, "persistence service")

start = s.find("static void m27TracePrepare()\n{")
end = s.find("\nvoid switch2ProTraceClear()", start)
if start < 0 or end < 0:
    raise SystemExit("R377 trace prepare block missing")
new_prepare = r'''static void m27TracePrepare()
{
	// Deliberately no LittleFS read/write/remove here. RF acquisition and all
	// early Nintendo initialization must observe the exact working M27 timing.
	g_m27TraceCount = g_m27TracePersisted = 0;
	g_m27TraceDirty = false;
	g_m27TraceFlushed = false;
	g_m27TraceLastActivityMs = 0;
	g_m27TraceReadySinceMs = 0;
	g_m27TracePendHead = g_m27TracePendTail = 0;
	M27TraceRecord r = {};
	r.ms = millis();
	r.kind = 'S';
	r.a = 1;
	r.b = 27;
	m27TraceRamAppend(r);
}
'''
s = s[:start] + new_prepare + s[end:]

s = replace_once(
    s,
    '\tInternalFS.remove(M27_TRACE_FILE);\n'
    '\tInternalFS.remove(M27_TRACE_TAG);\n'
    '\tg_m27TraceCount = g_m27TracePersisted = 0;\n'
    '\tg_m27TraceDirty = false;\n'
    '\tg_m27TracePendHead = g_m27TracePendTail = 0;\n',
    '\tInternalFS.remove(M27_TRACE_FILE);\n'
    '\tg_m27TraceCount = g_m27TracePersisted = 0;\n'
    '\tg_m27TraceDirty = false;\n'
    '\tg_m27TraceFlushed = false;\n'
    '\tg_m27TraceReadySinceMs = 0;\n'
    '\tg_m27TracePendHead = g_m27TracePendTail = 0;\n',
    "explicit clear",
)

old_dump_prefix = r'''void switch2ProTraceDump()
{
	M27TraceRecord pending;
	while (m27TracePendingPop(&pending))
		m27TraceRamAppend(pending);
	g_m27TraceLastActivityMs = 0;
	m27TracePersistQuiet();
	File f(InternalFS);
'''
new_dump_prefix = r'''void switch2ProTraceDump()
{
	// Read only. A PC/debug boot must never replace the snapshot captured during
	// the preceding Switch session with this boot's fresh RAM trace.
	File f(InternalFS);
'''
s = replace_once(s, old_dump_prefix, new_dump_prefix, "dump read-only")

s = replace_once(s, "m27TracePersistQuiet();", "m27TraceService();", "drain service")
s = s.replace("source=M27-working", "source=M27-working-r377", 2)

P.write_text(s, encoding="utf-8")
print("F27 M27 r377 RF-gated persistent trace applied")
