#!/usr/bin/env python3
"""r395: trace-only observer over the hardware-tested M21 dual-JCR topology."""
from pathlib import Path
import re

MODE = Path("OpenPuck/mode_switch2_pro.cpp")
HDR = Path("OpenPuck/mode_switch2_pro.h")
SER = Path("OpenPuck/serial_console.cpp")


def repl(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"r395 {label}: anchor count {n}, expected 1")
    return s.replace(old, new, 1)


s = MODE.read_text(encoding="utf-8")
for required in (
    "F27-M15-DUAL-S2-TOPOLOGY",
    "F27-M21-DUAL-JCR-TOPOLOGY",
    "M15_SW2_SESSION_COUNT = 2",
    "static M15Sw2Session g_sw2Sessions[M15_SW2_SESSION_COUNT]",
    "g_sw2Sessions[s].activeReport = 0x08",
):
    if required not in s:
        raise SystemExit(f"r395 requires exact M21 reconstruction anchor: {required}")
if "M21T_TRACE_PAGE" in s:
    raise SystemExit("r395 already applied")

trace = r'''
// r395 trace-only observer over the hardware-tested M21 dual-JCR topology.
// One raw flash page outside the application + InternalFS. Magic is committed
// last so interrupted writes do not validate as a complete capture.
static constexpr uint32_t M21T_TRACE_PAGE = 0x000EB000UL;
static constexpr uint32_t M21T_TRACE_MAGIC = 0x5431324DUL; // "M21T"
static constexpr uint32_t M21T_TRACE_VERSION = 1;
struct __attribute__((packed)) M21TTraceRecord {
	uint32_t ms;
	uint8_t kind;
	uint8_t sess;
	uint8_t a;
	uint8_t b;
	uint8_t c;
	uint8_t d;
	uint8_t e;
	uint8_t f;
	uint16_t x;
	uint16_t y;
};
static_assert(sizeof(M21TTraceRecord) == 16, "r395 record size");
struct M21TTraceHeader {
	uint32_t magic, version, count, checksum;
};
static M21TTraceRecord g_m21tTrace[96];
static uint8_t g_m21tTraceCount;
static uint16_t g_m21tSeen;
static unsigned long g_m21tStartMs;
static bool g_m21tStored;

static void m21tAppend(uint8_t kind, uint8_t sess, uint8_t a = 0,
		       uint8_t b = 0, uint8_t c = 0, uint8_t d = 0,
		       uint8_t e = 0, uint8_t f = 0, uint16_t x = 0,
		       uint16_t y = 0)
{
	if (g_m21tTraceCount >= 96)
		return;
	M21TTraceRecord &r = g_m21tTrace[g_m21tTraceCount++];
	r.ms = millis();
	r.kind = kind;
	r.sess = sess;
	r.a = a;
	r.b = b;
	r.c = c;
	r.d = d;
	r.e = e;
	r.f = f;
	r.x = x;
	r.y = y;
}
static void m21tReady(uint8_t sess, bool ready, uint8_t rid)
{
	if (sess >= M15_SW2_SESSION_COUNT)
		return;
	uint8_t phase = ready ? 1 : 0;
	uint16_t bit = (uint16_t)(1u << (sess * 3u + phase));
	if (g_m21tSeen & bit)
		return;
	g_m21tSeen |= bit;
	m21tAppend('R', sess, ready ? 1 : 0,
		   g_sw2Sessions[sess].inputEnabled ? 1 : 0, rid,
		   g_sw2Sessions[sess].vendorEpOut,
		   g_sw2Sessions[sess].vendorEpIn);
}
static void m21tQueued(uint8_t sess, uint8_t rid)
{
	uint16_t bit = (uint16_t)(1u << (sess * 3u + 2u));
	if (g_m21tSeen & bit)
		return;
	g_m21tSeen |= bit;
	m21tAppend('Q', sess, rid,
		   g_sw2Sessions[sess].inputEnabled ? 1 : 0);
}
static void m21tOpened(uint8_t sess, uint8_t local, bool ok, uint8_t ifnum,
		       uint8_t epOut, uint8_t epIn)
{
	m21tAppend('O', sess, local, ok ? 1 : 0, ifnum, epOut, epIn);
}
static void m21tVendorRx(uint8_t sess, const uint8_t *cmd, uint8_t n)
{
	uint8_t id = n > 0 ? cmd[0] : 0;
	uint8_t marker = n > 1 ? cmd[1] : 0;
	uint8_t seq = n > 2 ? cmd[2] : 0;
	uint8_t sub = n > 3 ? cmd[3] : 0;
	m21tAppend('V', sess, id, marker, seq, sub, n,
		   g_sw2Sessions[sess].inputEnabled ? 1 : 0,
		   g_sw2Sessions[sess].vendorEpOut,
		   g_sw2Sessions[sess].vendorEpIn);
}
static uint32_t m21tChecksum(const M21TTraceRecord *r, uint32_t count)
{
	uint32_t h = 2166136261UL;
	const uint8_t *p = (const uint8_t *)r;
	uint32_t n = count * sizeof(M21TTraceRecord);
	while (n--) {
		h ^= *p++;
		h *= 16777619UL;
	}
	return h;
}
static void m21tErase()
{
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Een;
	while (!NRF_NVMC->READY) {}
	NRF_NVMC->ERASEPAGE = M21T_TRACE_PAGE;
	while (!NRF_NVMC->READY) {}
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Ren;
	while (!NRF_NVMC->READY) {}
}
static void m21tWrite(uint32_t addr, uint32_t value)
{
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Wen;
	while (!NRF_NVMC->READY) {}
	*(volatile uint32_t *)addr = value;
	while (!NRF_NVMC->READY) {}
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Ren;
	while (!NRF_NVMC->READY) {}
}
static bool m21tValid(uint32_t *count)
{
	const volatile M21TTraceHeader *h =
		(const volatile M21TTraceHeader *)M21T_TRACE_PAGE;
	if (h->magic != M21T_TRACE_MAGIC || h->version != M21T_TRACE_VERSION ||
	    h->count > 96)
		return false;
	const M21TTraceRecord *r = (const M21TTraceRecord *)(
		M21T_TRACE_PAGE + sizeof(M21TTraceHeader));
	if (m21tChecksum(r, h->count) != h->checksum)
		return false;
	if (count)
		*count = h->count;
	return true;
}
static void m21tStore()
{
	uint32_t count = g_m21tTraceCount;
	uint32_t sum = m21tChecksum(g_m21tTrace, count);
	m21tErase();
	const uint8_t *bytes = (const uint8_t *)g_m21tTrace;
	uint32_t nbytes = count * sizeof(M21TTraceRecord);
	for (uint32_t off = 0; off < nbytes; off += 4) {
		uint32_t word = 0xffffffffUL;
		uint32_t rem = nbytes - off;
		memcpy(&word, bytes + off, rem >= 4 ? 4 : rem);
		m21tWrite(M21T_TRACE_PAGE + sizeof(M21TTraceHeader) + off, word);
	}
	m21tWrite(M21T_TRACE_PAGE + 4, M21T_TRACE_VERSION);
	m21tWrite(M21T_TRACE_PAGE + 8, count);
	m21tWrite(M21T_TRACE_PAGE + 12, sum);
	m21tWrite(M21T_TRACE_PAGE, M21T_TRACE_MAGIC);
	g_m21tStored = true;
}
static void m21tService()
{
	if (!g_m21tStartMs)
		g_m21tStartMs = millis();
	if (!g_m21tStored && g_m21tTraceCount &&
	    (uint32_t)(millis() - g_m21tStartMs) >= 15000u)
		m21tStore();
}
void switch2ProM21TraceClear()
{
	m21tErase();
	g_m21tTraceCount = 0;
	g_m21tSeen = 0;
	g_m21tStartMs = millis();
	g_m21tStored = false;
}
void switch2ProM21TraceDump()
{
	uint32_t count = 0;
	if (!m21tValid(&count)) {
		Serial.println("# JT no valid M21 dual-JCR raw trace");
		return;
	}
	const M21TTraceRecord *r = (const M21TTraceRecord *)(
		M21T_TRACE_PAGE + sizeof(M21TTraceHeader));
	Serial.printf("# JT begin bytes=%lu records=%lu source=M21-DualJCR-r395-raw\n",
		      (unsigned long)(count * sizeof(M21TTraceRecord)),
		      (unsigned long)count);
	for (uint32_t i = 0; i < count; i++) {
		if (r[i].kind == 'O')
			Serial.printf("# JT %lu O t=%lu sess=%u local=%u ok=%u if=%u epout=%02X epin=%02X\n",
				      (unsigned long)i, (unsigned long)r[i].ms,
				      r[i].sess, r[i].a, r[i].b, r[i].c,
				      r[i].d, r[i].e);
		else if (r[i].kind == 'R')
			Serial.printf("# JT %lu R t=%lu sess=%u ready=%u input=%u rid=%02X epout=%02X epin=%02X\n",
				      (unsigned long)i, (unsigned long)r[i].ms,
				      r[i].sess, r[i].a, r[i].b, r[i].c,
				      r[i].d, r[i].e);
		else if (r[i].kind == 'Q')
			Serial.printf("# JT %lu Q t=%lu sess=%u rid=%02X input=%u\n",
				      (unsigned long)i, (unsigned long)r[i].ms,
				      r[i].sess, r[i].a, r[i].b);
		else if (r[i].kind == 'V')
			Serial.printf("# JT %lu V t=%lu sess=%u cmd=%02X mark=%02X seq=%02X sub=%02X n=%u input_before=%u epout=%02X epin=%02X\n",
				      (unsigned long)i, (unsigned long)r[i].ms,
				      r[i].sess, r[i].a, r[i].b, r[i].c,
				      r[i].d, r[i].e, r[i].f,
				      (unsigned)r[i].x, (unsigned)r[i].y);
	}
	Serial.println("# JT end");
}

'''
s = repl(s, "static void sw2Drain(void)\n{", trace + "static void sw2Drain(void)\n{", "trace implementation")

# Observe both sessions without changing stream gating or report generation.
old_ready = '''\t\tif (!g_sw2InputEnabled || !tud_hid_n_ready(s))\n\t\t\tcontinue;\n'''
new_ready = '''\t\tbool m21tHidReady = tud_hid_n_ready(s);\n\t\tm21tReady(s, m21tHidReady, g_sw2ActiveReport);\n\t\tif (!g_sw2InputEnabled || !m21tHidReady)\n\t\t\tcontinue;\n'''
s = repl(s, old_ready, new_ready, "readiness observer")
old_queue = '''\t\tif (tud_hid_n_report(s, rid, p, sizeof p))\n\t\t\tg_sw2LastReportMs = millis();\n\t}\n\tg_sw2SessionCtx = M15_SW2_PRO;\n}\n'''
new_queue = '''\t\tif (tud_hid_n_report(s, rid, p, sizeof p)) {\n\t\t\tg_sw2LastReportMs = millis();\n\t\t\tm21tQueued(s, rid);\n\t\t}\n\t}\n\tg_sw2SessionCtx = M15_SW2_PRO;\n\tm21tService();\n}\n'''
s = repl(s, old_queue, new_queue, "queue observer")

# Record successful HID and vendor-function opens per session. Return values and
# endpoint arming are unchanged.
old_hid_open = '''\tif (local == 0 && itf->bInterfaceClass == TUSB_CLASS_HID)\n\t\treturn hidd_open(rhport, itf, maxLen);\n'''
new_hid_open = '''\tif (local == 0 && itf->bInterfaceClass == TUSB_CLASS_HID) {\n\t\tuint16_t openedHid = hidd_open(rhport, itf, maxLen);\n\t\tm21tOpened(s, 0, openedHid != 0, ifnum, 0, 0);\n\t\treturn openedHid;\n\t}\n'''
s = repl(s, old_hid_open, new_hid_open, "HID open observer")
old_vendor_return = '''\t\tif (!usbd_edpt_xfer(rhport, g_sw2VendorEpOut, g_sw2VendorOut,\n\t\t\t\t    sizeof g_sw2VendorOut))\n\t\t\treturn 0;\n\t\treturn used;\n\t}\n'''
new_vendor_return = '''\t\tif (!usbd_edpt_xfer(rhport, g_sw2VendorEpOut, g_sw2VendorOut,\n\t\t\t\t    sizeof g_sw2VendorOut))\n\t\t\treturn 0;\n\t\tm21tOpened(s, 1, true, ifnum, g_sw2VendorEpOut, g_sw2VendorEpIn);\n\t\treturn used;\n\t}\n'''
s = repl(s, old_vendor_return, new_vendor_return, "vendor open observer")

# Record every completed Nintendo vendor OUT packet before the existing pending
# flag is set. The command buffer and state machine are otherwise untouched.
old_rx = '''\t\tif (ep == g_sw2VendorEpOut) {\n\t\t\tif (result == XFER_RESULT_SUCCESS) {\n\t\t\t\tg_sw2VendorCommandLen =\n\t\t\t\t\t(uint8_t)(transferred > 64 ? 64 : transferred);\n\t\t\t\tg_sw2VendorCommandPending = true;\n\t\t\t}\n'''
new_rx = '''\t\tif (ep == g_sw2VendorEpOut) {\n\t\t\tif (result == XFER_RESULT_SUCCESS) {\n\t\t\t\tg_sw2VendorCommandLen =\n\t\t\t\t\t(uint8_t)(transferred > 64 ? 64 : transferred);\n\t\t\t\tm21tVendorRx(s, g_sw2VendorOut, g_sw2VendorCommandLen);\n\t\t\t\tg_sw2VendorCommandPending = true;\n\t\t\t}\n'''
s = repl(s, old_rx, new_rx, "vendor RX observer")
MODE.write_text(s, encoding="utf-8")

h = HDR.read_text(encoding="utf-8")
h += "\n// r395 trace-only diagnostic accessors.\nvoid switch2ProM21TraceDump();\nvoid switch2ProM21TraceClear();\n"
HDR.write_text(h, encoding="utf-8")

ser = SER.read_text(encoding="utf-8")
if '#include "mode_switch2_pro.h"' not in ser:
    ser = repl(ser, '#include "usb_mount.h" // modeSwitchReboot()\n',
               '#include "usb_mount.h" // modeSwitchReboot()\n#include "mode_switch2_pro.h"\n', "serial include")
cmd_anchor = '''\t\t\t} else if (!strcmp(line, "CD")) {\n'''
cmd_repl = '''\t\t\t} else if (!strcmp(line, "JT")) {\n\t\t\t\tswitch2ProM21TraceDump();\n\t\t\t} else if (!strcmp(line, "JC")) {\n\t\t\t\tswitch2ProM21TraceClear();\n\t\t\t\tSerial.println("# JT M21 dual-JCR raw trace cleared");\n\t\t\t} else if (!strcmp(line, "CD")) {\n'''
ser = repl(ser, cmd_anchor, cmd_repl, "serial commands")
SER.write_text(ser, encoding="utf-8")
print("r395 trace-only observer applied over M21 dual-JCR topology")
