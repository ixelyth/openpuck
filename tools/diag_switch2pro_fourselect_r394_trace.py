#!/usr/bin/env python3
"""r394: trace-only observer over the accepted Switch2Pro FourSelect/no-audio transform."""
from pathlib import Path

CPP = Path("OpenPuck/mode_switch2_pro.cpp")
HDR = Path("OpenPuck/mode_switch2_pro.h")
SER = Path("OpenPuck/serial_console.cpp")


def repl(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"r394 {label}: anchor count {n}, expected 1")
    return s.replace(old, new, 1)


s = CPP.read_text(encoding="utf-8")
for required in (
    "sizeof SWITCH2_PRO_CFG_BODY == 191",
    "vendorOut != 0x05 || vendorIn != 0x85",
    "itf->bInterfaceNumber < 4",
    "tud_hid_n_report(hid, rid",
    "TB_L4, TB_R4, TB_L5, TB_R5",
):
    if required not in s:
        raise SystemExit(f"r394 requires accepted FourSelect anchor: {required}")
if "SW2P4_TRACE_PAGE" in s:
    raise SystemExit("r394 already applied")

trace = r'''
// r394 trace-only observer over the accepted four-Pro2-HID/no-audio topology.
// Raw page is outside application + InternalFS. The magic is committed last so
// interrupted writes do not validate as complete snapshots.
static constexpr uint32_t SW2P4_TRACE_PAGE = 0x000EB000UL;
static constexpr uint32_t SW2P4_TRACE_MAGIC = 0x34505453UL;
static constexpr uint32_t SW2P4_TRACE_VERSION = 1;
struct __attribute__((packed)) Sw2P4TraceRecord {
	uint32_t ms;
	uint8_t hid;
	uint8_t phase; // 1=not-ready, 2=ready, 3=report queued
	uint8_t ready;
	int8_t selected;
	uint8_t rid;
	uint8_t inputEnabled;
	uint16_t reserved;
};
static_assert(sizeof(Sw2P4TraceRecord) == 12, "r394 record size");
struct Sw2P4TraceHeader {
	uint32_t magic, version, count, checksum;
};
static Sw2P4TraceRecord g_sw2p4Trace[32];
static uint8_t g_sw2p4TraceCount;
static uint16_t g_sw2p4Seen;
static unsigned long g_sw2p4StartMs;
static bool g_sw2p4Stored;

static void sw2p4TraceAppend(uint8_t hid, uint8_t phase, bool ready,
			    int selected, uint8_t rid)
{
	if (hid >= 4 || phase < 1 || phase > 3)
		return;
	uint16_t bit = (uint16_t)(1u << (hid * 3u + phase - 1u));
	if (g_sw2p4Seen & bit)
		return;
	g_sw2p4Seen |= bit;
	if (g_sw2p4TraceCount >= 32)
		return;
	Sw2P4TraceRecord &r = g_sw2p4Trace[g_sw2p4TraceCount++];
	r.ms = millis();
	r.hid = hid;
	r.phase = phase;
	r.ready = ready ? 1 : 0;
	r.selected = (int8_t)selected;
	r.rid = rid;
	r.inputEnabled = g_sw2InputEnabled ? 1 : 0;
	r.reserved = 0;
}
static void sw2p4TraceReady(uint8_t hid, bool ready, int selected, uint8_t rid)
{
	sw2p4TraceAppend(hid, ready ? 2 : 1, ready, selected, rid);
}
static void sw2p4TraceQueued(uint8_t hid, int selected, uint8_t rid)
{
	sw2p4TraceAppend(hid, 3, true, selected, rid);
}
static uint32_t sw2p4Checksum(const Sw2P4TraceRecord *r, uint32_t count)
{
	uint32_t h = 2166136261UL;
	const uint8_t *p = (const uint8_t *)r;
	uint32_t n = count * sizeof(Sw2P4TraceRecord);
	while (n--) {
		h ^= *p++;
		h *= 16777619UL;
	}
	return h;
}
static void sw2p4Erase()
{
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Een;
	while (!NRF_NVMC->READY) {}
	NRF_NVMC->ERASEPAGE = SW2P4_TRACE_PAGE;
	while (!NRF_NVMC->READY) {}
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Ren;
	while (!NRF_NVMC->READY) {}
}
static void sw2p4Write(uint32_t addr, uint32_t value)
{
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Wen;
	while (!NRF_NVMC->READY) {}
	*(volatile uint32_t *)addr = value;
	while (!NRF_NVMC->READY) {}
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Ren;
	while (!NRF_NVMC->READY) {}
}
static bool sw2p4Valid(uint32_t *count)
{
	const volatile Sw2P4TraceHeader *h =
		(const volatile Sw2P4TraceHeader *)SW2P4_TRACE_PAGE;
	if (h->magic != SW2P4_TRACE_MAGIC || h->version != SW2P4_TRACE_VERSION ||
	    h->count > 32)
		return false;
	const Sw2P4TraceRecord *r = (const Sw2P4TraceRecord *)(
		SW2P4_TRACE_PAGE + sizeof(Sw2P4TraceHeader));
	if (sw2p4Checksum(r, h->count) != h->checksum)
		return false;
	if (count)
		*count = h->count;
	return true;
}
static void sw2p4Store()
{
	uint32_t count = g_sw2p4TraceCount;
	uint32_t sum = sw2p4Checksum(g_sw2p4Trace, count);
	sw2p4Erase();
	const uint8_t *bytes = (const uint8_t *)g_sw2p4Trace;
	uint32_t nbytes = count * sizeof(Sw2P4TraceRecord);
	for (uint32_t off = 0; off < nbytes; off += 4) {
		uint32_t word = 0xffffffffUL;
		uint32_t rem = nbytes - off;
		memcpy(&word, bytes + off, rem >= 4 ? 4 : rem);
		sw2p4Write(SW2P4_TRACE_PAGE + sizeof(Sw2P4TraceHeader) + off, word);
	}
	sw2p4Write(SW2P4_TRACE_PAGE + 4, SW2P4_TRACE_VERSION);
	sw2p4Write(SW2P4_TRACE_PAGE + 8, count);
	sw2p4Write(SW2P4_TRACE_PAGE + 12, sum);
	sw2p4Write(SW2P4_TRACE_PAGE, SW2P4_TRACE_MAGIC);
	g_sw2p4Stored = true;
}
static void sw2p4TraceService()
{
	if (!g_sw2p4StartMs)
		g_sw2p4StartMs = millis();
	if (!g_sw2p4Stored && g_sw2p4TraceCount &&
	    (uint32_t)(millis() - g_sw2p4StartMs) >= 15000u)
		sw2p4Store();
}
void switch2ProFourSelectTraceClear()
{
	sw2p4Erase();
	g_sw2p4TraceCount = 0;
	g_sw2p4Seen = 0;
	g_sw2p4StartMs = millis();
	g_sw2p4Stored = false;
}
void switch2ProFourSelectTraceDump()
{
	uint32_t count = 0;
	if (!sw2p4Valid(&count)) {
		Serial.println("# JT no valid Switch2Pro FourSelect raw trace");
		return;
	}
	const Sw2P4TraceRecord *r = (const Sw2P4TraceRecord *)(
		SW2P4_TRACE_PAGE + sizeof(Sw2P4TraceHeader));
	Serial.printf("# JT begin bytes=%lu records=%lu source=Switch2Pro-FourSelect-r394-raw\n",
		      (unsigned long)(count * sizeof(Sw2P4TraceRecord)),
		      (unsigned long)count);
	for (uint32_t i = 0; i < count; i++)
		Serial.printf("# JT %lu I t=%lu hid=%u phase=%u ready=%u selected=%d rid=%02X input=%u\n",
			      (unsigned long)i, (unsigned long)r[i].ms, r[i].hid,
			      r[i].phase, r[i].ready, r[i].selected, r[i].rid,
			      r[i].inputEnabled);
	Serial.println("# JT end");
}

'''
s = repl(s, "static void sw2Drain(void)\n{", trace + "static void sw2Drain(void)\n{", "trace implementation")

# Observe readiness before Nintendo input-enable so this is directly comparable
# with the HORIPAD FourSelect trace. No report, selector, or vendor behavior changes.
anchor = '''\tif (!g_sw2InputEnabled)\n\t\treturn;\n\tint bond = g_usbToBond[0];\n'''
replacement = '''\tint traceBond = g_usbToBond[0];\n\tuint32_t traceSuppress = 0;\n\tint traceSelected = (traceBond >= 0 && traceBond < NSLOT) ?\n\t\tsw2FourSelectHid((uint8_t)traceBond, &traceSuppress) : -1;\n\tuint8_t traceRid = g_sw2ActiveReport == 0x05 ? 0x05 : 0x09;\n\tfor (uint8_t hid = 0; hid < 4; hid++)\n\t\tsw2p4TraceReady(hid, tud_hid_n_ready(hid), traceSelected, traceRid);\n\tif (!g_sw2InputEnabled) {\n\t\tsw2p4TraceService();\n\t\treturn;\n\t}\n\tint bond = g_usbToBond[0];\n'''
s = repl(s, anchor, replacement, "pre-enable readiness observer")

old = '''\t\tif (tud_hid_n_report(hid, rid, p, sizeof p))\n\t\t\tg_sw2LastReportMs[hid] = millis();\n\t}\n}\n'''
new = '''\t\tif (tud_hid_n_report(hid, rid, p, sizeof p)) {\n\t\t\tg_sw2LastReportMs[hid] = millis();\n\t\t\tsw2p4TraceQueued(hid, selected, rid);\n\t\t}\n\t}\n\tsw2p4TraceService();\n}\n'''
# The accepted FourSelect transform has exactly one sw2Drain() occurrence with
# this tail. `selected` is recomputed here only for trace metadata and cannot
# influence the already-built report.
if old not in s:
    raise SystemExit("r394 drain tail anchor missing")
# Insert a trace-only selected value immediately before the sender loop.
loop_anchor = '''\tuint8_t rid = g_sw2ActiveReport == 0x05 ? 0x05 : 0x09;\n\tfor (uint8_t hid = 0; hid < 4; hid++) {\n'''
loop_repl = '''\tuint8_t rid = g_sw2ActiveReport == 0x05 ? 0x05 : 0x09;\n\tuint32_t traceSendSuppress = 0;\n\tint selected = sw2FourSelectHid((uint8_t)bond, &traceSendSuppress);\n\tfor (uint8_t hid = 0; hid < 4; hid++) {\n'''
s = repl(s, loop_anchor, loop_repl, "send-loop trace metadata")
s = repl(s, old, new, "queue observer")
CPP.write_text(s, encoding="utf-8")

h = HDR.read_text(encoding="utf-8")
h += "\n// r394 trace-only diagnostic accessors.\nvoid switch2ProFourSelectTraceDump();\nvoid switch2ProFourSelectTraceClear();\n"
HDR.write_text(h, encoding="utf-8")

ser = SER.read_text(encoding="utf-8")
ser = repl(ser, '#include "usb_mount.h" // modeSwitchReboot()\n',
           '#include "usb_mount.h" // modeSwitchReboot()\n#include "mode_switch2_pro.h"\n', "serial include")
cmd_anchor = '''\t\t\t} else if (!strcmp(line, "CD")) {\n'''
cmd_repl = '''\t\t\t} else if (!strcmp(line, "JT")) {\n\t\t\t\tswitch2ProFourSelectTraceDump();\n\t\t\t} else if (!strcmp(line, "JC")) {\n\t\t\t\tswitch2ProFourSelectTraceClear();\n\t\t\t\tSerial.println("# JT Switch2Pro FourSelect raw trace cleared");\n\t\t\t} else if (!strcmp(line, "CD")) {\n'''
ser = repl(ser, cmd_anchor, cmd_repl, "serial commands")
SER.write_text(ser, encoding="utf-8")
print("r394 Switch2Pro FourSelect trace-only observer applied")
