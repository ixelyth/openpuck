#!/usr/bin/env python3
"""Instrument the exact r355 Switch 2 HORIPAD O FourSelect with raw JT tracing."""
from pathlib import Path

CPP = Path("OpenPuck/mode_switch_hori.cpp")
HDR = Path("OpenPuck/mode_switch_hori.h")
SER = Path("OpenPuck/serial_console.cpp")


def repl(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"r396 {label}: anchor count {n}, expected 1")
    return s.replace(old, new, 1)


s = CPP.read_text(encoding="utf-8")
for needle in (
    "USBDevice.setID(0x0F0D, 0x0202);",
    'USBDevice.setProductDescriptor("HORIPAD O");',
    "sizeof SWITCH_HID_DESC == 123",
    "TB_L4, TB_R4, TB_L5, TB_R5",
):
    if needle not in s:
        raise SystemExit(f"r396 missing exact r355 contract: {needle}")

old_task = r'''void SwitchHoriController::task()
{
	int bond = -1;
	for (uint8_t u = 0; u < g_usbMountCount; u++) {
		if (g_usbToBond[u] >= 0) {
			bond = g_usbToBond[u];
			break;
		}
	}
	static const uint32_t selector[NSLOT] = { TB_L4, TB_R4, TB_L5, TB_R5 };
	int selected = -1;
	uint32_t suppress = 0;
	if (bond >= 0) {
		uint32_t buttons = g_in[bond].buttons;
		for (uint8_t u = 0; u < NSLOT; u++) {
			if (!(buttons & selector[u])) continue;
			if (selected >= 0) {
				selected = -1;
				suppress = 0;
				break;
			}
			selected = (int)u;
			suppress = selector[u];
		}
	}
	const uint8_t neutral[8] = { 0x00, 0x00, 0x08, 0x80, 0x80, 0x80, 0x80, 0x00 };
	uint8_t active[8];
	if (selected >= 0)
		switchBuildHoripad((uint8_t)bond, suppress, active);
	for (uint8_t u = 0; u < maxSlots(); u++) {
		if (!g_switch[u].ready()) continue;
		if (millis() - g_swLastMs[u] < USB_STREAM_MS) continue;
		g_swLastMs[u] = millis();
		const uint8_t *p = selected == (int)u ? active : neutral;
		usbTxHid(&g_switch[u], 0, p, 8);
	}
}
'''

new_task = r'''void SwitchHoriController::task()
{
	int bond = -1;
	for (uint8_t u = 0; u < g_usbMountCount; u++) {
		if (g_usbToBond[u] >= 0) {
			bond = g_usbToBond[u];
			break;
		}
	}
	static const uint32_t selector[NSLOT] = { TB_L4, TB_R4, TB_L5, TB_R5 };
	int selected = -1;
	uint32_t suppress = 0;
	if (bond >= 0) {
		uint32_t buttons = g_in[bond].buttons;
		for (uint8_t u = 0; u < NSLOT; u++) {
			if (!(buttons & selector[u])) continue;
			if (selected >= 0) {
				selected = -1;
				suppress = 0;
				break;
			}
			selected = (int)u;
			suppress = selector[u];
		}
	}
	const uint8_t neutral[8] = { 0x00, 0x00, 0x08, 0x80, 0x80, 0x80, 0x80, 0x00 };
	uint8_t active[8];
	if (selected >= 0)
		switchBuildHoripad((uint8_t)bond, suppress, active);
	for (uint8_t u = 0; u < maxSlots(); u++) {
		bool ready = g_switch[u].ready();
		h4TraceReady(u, ready, selected);
		if (!ready) continue;
		if (millis() - g_swLastMs[u] < USB_STREAM_MS) continue;
		g_swLastMs[u] = millis();
		const uint8_t *p = selected == (int)u ? active : neutral;
		h4TraceEnqueue(u, selected);
		usbTxHid(&g_switch[u], 0, p, 8);
	}
	h4TraceService();
}
'''

trace = r'''
// r396 trace-only observer over the exact r355 Switch 2 HORIPAD O FourSelect.
// Raw page is outside app + InternalFS; magic is committed last so interrupted
// writes never validate as a snapshot.
static constexpr uint32_t H4_TRACE_PAGE = 0x000EB000UL;
static constexpr uint32_t H4_TRACE_MAGIC = 0x36393448UL; // "H496"
static constexpr uint32_t H4_TRACE_VERSION = 1;
struct __attribute__((packed)) H4TraceRecord {
	uint32_t ms;
	uint8_t hid;
	uint8_t phase; // 1=not-ready, 2=ready, 3=report enqueued
	uint8_t ready;
	int8_t selected;
};
static_assert(sizeof(H4TraceRecord) == 8, "r396 record size");
struct H4TraceHeader {
	uint32_t magic, version, count, checksum;
};
static H4TraceRecord g_h4Trace[32];
static uint8_t g_h4TraceCount;
static uint16_t g_h4Seen;
static unsigned long g_h4StartMs;
static bool g_h4Stored;

static void h4TraceAppend(uint8_t hid, uint8_t phase, bool ready, int selected)
{
	if (hid >= 4 || phase < 1 || phase > 3)
		return;
	uint16_t bit = (uint16_t)(1u << (hid * 3u + phase - 1u));
	if (g_h4Seen & bit)
		return;
	g_h4Seen |= bit;
	if (g_h4TraceCount >= 32)
		return;
	H4TraceRecord &r = g_h4Trace[g_h4TraceCount++];
	r.ms = millis();
	r.hid = hid;
	r.phase = phase;
	r.ready = ready ? 1 : 0;
	r.selected = (int8_t)selected;
}
static void h4TraceReady(uint8_t hid, bool ready, int selected)
{
	h4TraceAppend(hid, ready ? 2 : 1, ready, selected);
}
static void h4TraceEnqueue(uint8_t hid, int selected)
{
	h4TraceAppend(hid, 3, true, selected);
}
static uint32_t h4Checksum(const H4TraceRecord *r, uint32_t count)
{
	uint32_t h = 2166136261UL;
	const uint8_t *p = (const uint8_t *)r;
	uint32_t n = count * sizeof(H4TraceRecord);
	while (n--) {
		h ^= *p++;
		h *= 16777619UL;
	}
	return h;
}
static void h4Erase()
{
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Een;
	while (!NRF_NVMC->READY) {}
	NRF_NVMC->ERASEPAGE = H4_TRACE_PAGE;
	while (!NRF_NVMC->READY) {}
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Ren;
	while (!NRF_NVMC->READY) {}
}
static void h4Write(uint32_t addr, uint32_t value)
{
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Wen;
	while (!NRF_NVMC->READY) {}
	*(volatile uint32_t *)addr = value;
	while (!NRF_NVMC->READY) {}
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Ren;
	while (!NRF_NVMC->READY) {}
}
static bool h4Valid(uint32_t *count)
{
	const volatile H4TraceHeader *h = (const volatile H4TraceHeader *)H4_TRACE_PAGE;
	if (h->magic != H4_TRACE_MAGIC || h->version != H4_TRACE_VERSION || h->count > 32)
		return false;
	const H4TraceRecord *r =
		(const H4TraceRecord *)(H4_TRACE_PAGE + sizeof(H4TraceHeader));
	if (h4Checksum(r, h->count) != h->checksum)
		return false;
	if (count)
		*count = h->count;
	return true;
}
static void h4Store()
{
	uint32_t count = g_h4TraceCount;
	uint32_t sum = h4Checksum(g_h4Trace, count);
	h4Erase();
	const uint8_t *bytes = (const uint8_t *)g_h4Trace;
	uint32_t nbytes = count * sizeof(H4TraceRecord);
	for (uint32_t off = 0; off < nbytes; off += 4) {
		uint32_t word = 0xffffffffUL;
		memcpy(&word, bytes + off, (nbytes - off) >= 4 ? 4 : nbytes - off);
		h4Write(H4_TRACE_PAGE + sizeof(H4TraceHeader) + off, word);
	}
	h4Write(H4_TRACE_PAGE + 4, H4_TRACE_VERSION);
	h4Write(H4_TRACE_PAGE + 8, count);
	h4Write(H4_TRACE_PAGE + 12, sum);
	h4Write(H4_TRACE_PAGE, H4_TRACE_MAGIC);
	g_h4Stored = true;
}
static void h4TraceService()
{
	if (!g_h4StartMs)
		g_h4StartMs = millis();
	if (!g_h4Stored && g_h4TraceCount &&
	    (uint32_t)(millis() - g_h4StartMs) >= 15000u)
		h4Store();
}
void switchHoriTraceClear()
{
	h4Erase();
	g_h4TraceCount = 0;
	g_h4Seen = 0;
	g_h4StartMs = millis();
	g_h4Stored = false;
}
void switchHoriTraceDump()
{
	uint32_t count = 0;
	if (!h4Valid(&count)) {
		Serial.println("# JT no valid Switch2 HORIPAD O raw trace");
		return;
	}
	const H4TraceRecord *r =
		(const H4TraceRecord *)(H4_TRACE_PAGE + sizeof(H4TraceHeader));
	Serial.printf("# JT begin bytes=%lu records=%lu source=Switch2-HORIPAD-O-FourSelect-r396-raw\n",
		      (unsigned long)(count * sizeof(H4TraceRecord)),
		      (unsigned long)count);
	for (uint32_t i = 0; i < count; i++)
		Serial.printf("# JT %lu I t=%lu hid=%u phase=%u ready=%u selected=%d\n",
			      (unsigned long)i, (unsigned long)r[i].ms, r[i].hid,
			      r[i].phase, r[i].ready, r[i].selected);
	Serial.println("# JT end");
}

'''

s = repl(s, old_task, new_task, "exact r355 task")
s = repl(s, "void SwitchHoriController::task()\n{", trace + "void SwitchHoriController::task()\n{",
         "trace implementation")
CPP.write_text(s, encoding="utf-8")

h = HDR.read_text(encoding="utf-8")
if "switchHoriTraceDump" in h or "switchHoriTraceClear" in h:
    raise SystemExit("r396 trace declarations already present")
h += "\n// r396 diagnostic raw-trace accessors.\nvoid switchHoriTraceDump();\nvoid switchHoriTraceClear();\n"
HDR.write_text(h, encoding="utf-8")

ser = SER.read_text(encoding="utf-8")
ser = repl(ser, '#include "usb_mount.h" // modeSwitchReboot()\n',
           '#include "usb_mount.h" // modeSwitchReboot()\n#include "mode_switch_hori.h"\n',
           "serial include")
anchor = '''\t\t\t} else if (!strcmp(line, "CD")) {\n'''
ser = repl(ser, anchor,
'''\t\t\t} else if (!strcmp(line, "JT")) {\n\t\t\t\tswitchHoriTraceDump();\n\t\t\t} else if (!strcmp(line, "JC")) {\n\t\t\t\tswitchHoriTraceClear();\n\t\t\t\tSerial.println("# JT Switch2 HORIPAD O raw trace cleared");\n\t\t\t} else if (!strcmp(line, "CD")) {\n''',
           "serial commands")
SER.write_text(ser, encoding="utf-8")

print("r396 exact r355 Switch 2 HORIPAD O FourSelect + trace-only observer applied")
