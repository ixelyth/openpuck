#!/usr/bin/env python3
"""Move the M27 control trace from LittleFS to a dedicated raw scratch page.

Apply after the exact r376 observer + dual-session fixup + r377 RF gate have
been composed over the frozen hardware-positive M27 runtime. r378 removes every
trace-side InternalFS operation. RAM capture remains unchanged; persistence is a
single power-cut-safe snapshot to raw flash page 0xEB000 only after the working
RF+Nintendo session has already been stable for 10 s and host command traffic
has been quiet for 5 s.

0xEB000 is inside the otherwise-unused upper app region, one page below the
firmware-update metadata page at 0xEC000 and two pages below InternalFS at
0xED000. CI must prove the linked application ends below 0xEB000.
"""
from pathlib import Path

P = Path("OpenPuck/mode_switch2_pro.cpp")
s = P.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"R378 {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)


# Remove the trace-only filesystem dependencies injected by r376. OpenPuck's
# normal boot still mounts InternalFS in OpenPuck.ino for its existing config and
# bond implementation; r378 itself never reads, writes, removes or formats it.
s = replace_once(
    s,
    '#include "build_info.h"\n#include <Adafruit_LittleFS.h>\n#include <InternalFileSystem.h>\n#include <Adafruit_TinyUSB.h>\n',
    '#include "build_info.h"\n#include <Adafruit_TinyUSB.h>\n',
    "filesystem includes",
)
s = replace_once(
    s,
    'using namespace Adafruit_LittleFS_Namespace;\n\nextern "C" {\n',
    'extern "C" {\n',
    "filesystem namespace",
)

s = s.replace(
    '// R377 control trace for the hardware-positive M27 transport. Acquisition and\n'
    '// Nintendo initialization are RAM-only. LittleFS is forbidden until a physical\n'
    '// controller is mounted, input is enabled, and the session has been stable.\n',
    '// R378 control trace for the hardware-positive M27 transport. Capture is RAM-only\n'
    '// through RF acquisition and Nintendo initialization. The eventual snapshot uses\n'
    '// raw scratch page 0xEB000; the InternalFS volume containing /bonds.bin is never\n'
    '// touched by this diagnostic.\n',
    1,
)

s = replace_once(
    s,
    'static const char M27_TRACE_FILE[] = "/jc2trace.bin";\n',
    'static constexpr uint32_t M27_TRACE_RAW_PAGE = 0x000EB000UL;\n'
    'static constexpr uint32_t M27_TRACE_RAW_MAGIC = 0x3837544DUL; // "MT78"\n'
    'static constexpr uint32_t M27_TRACE_RAW_VERSION = 1UL;\n',
    "trace storage constants",
)

service_start = s.find("static void m27TraceService()\n{")
prepare_start = s.find("static void m27TracePrepare()\n{", service_start)
if service_start < 0 or prepare_start < 0:
    raise SystemExit("R378 persistence service boundaries missing")

raw_service = r'''struct M27TraceRawHeader {
	uint32_t magic;
	uint32_t version;
	uint32_t count;
	uint32_t checksum;
};
static_assert(sizeof(M27TraceRawHeader) == 16,
	      "M27 raw trace header must remain 16 bytes");

static uint32_t m27TraceChecksum(const M27TraceRecord *records, uint8_t count)
{
	uint32_t h = 2166136261UL;
	const uint8_t *p = (const uint8_t *)records;
	uint32_t n = (uint32_t)count * sizeof(M27TraceRecord);
	while (n--) {
		h ^= *p++;
		h *= 16777619UL;
	}
	return h;
}

static void m27TraceRawErase()
{
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Een;
	while (!NRF_NVMC->READY) {
	}
	NRF_NVMC->ERASEPAGE = M27_TRACE_RAW_PAGE;
	while (!NRF_NVMC->READY) {
	}
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Ren;
	while (!NRF_NVMC->READY) {
	}
}

static void m27TraceRawWriteWord(uint32_t addr, uint32_t value)
{
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Wen;
	while (!NRF_NVMC->READY) {
	}
	*(volatile uint32_t *)addr = value;
	while (!NRF_NVMC->READY) {
	}
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Ren;
	while (!NRF_NVMC->READY) {
	}
}

static bool m27TraceRawValid(uint32_t *countOut)
{
	const volatile M27TraceRawHeader *h =
		(const volatile M27TraceRawHeader *)M27_TRACE_RAW_PAGE;
	if (h->magic != M27_TRACE_RAW_MAGIC ||
	    h->version != M27_TRACE_RAW_VERSION || h->count > M27_TRACE_RAM_MAX)
		return false;
	uint8_t count = (uint8_t)h->count;
	const M27TraceRecord *records =
		(const M27TraceRecord *)(M27_TRACE_RAW_PAGE + sizeof(M27TraceRawHeader));
	if (m27TraceChecksum(records, count) != h->checksum)
		return false;
	if (countOut)
		*countOut = count;
	return true;
}

static bool m27TraceRawStore()
{
	const uint32_t count = g_m27TraceCount;
	const uint32_t checksum =
		m27TraceChecksum(g_m27TraceRam, g_m27TraceCount);
	m27TraceRawErase();

	// Records first. The magic word is committed last so a power cut during the
	// erase/write sequence can never make a partial snapshot look valid.
	const uint32_t recordsAddr =
		M27_TRACE_RAW_PAGE + sizeof(M27TraceRawHeader);
	const uint32_t *words = (const uint32_t *)g_m27TraceRam;
	const uint32_t wordCount =
		(count * sizeof(M27TraceRecord) + sizeof(uint32_t) - 1u) /
		sizeof(uint32_t);
	for (uint32_t i = 0; i < wordCount; i++)
		m27TraceRawWriteWord(recordsAddr + 4u * i, words[i]);

	m27TraceRawWriteWord(M27_TRACE_RAW_PAGE + 4u,
			     M27_TRACE_RAW_VERSION);
	m27TraceRawWriteWord(M27_TRACE_RAW_PAGE + 8u, count);
	m27TraceRawWriteWord(M27_TRACE_RAW_PAGE + 12u, checksum);
	m27TraceRawWriteWord(M27_TRACE_RAW_PAGE, M27_TRACE_RAW_MAGIC);

	uint32_t stored = 0;
	return m27TraceRawValid(&stored) && stored == count;
}

static void m27TraceService()
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

	// The complete control trace is already in RAM before any flash operation.
	// This page is outside InternalFS, so even an interrupted write cannot damage
	// /bonds.bin or force LittleFS to reformat on the next boot.
	if (m27TraceRawStore()) {
		g_m27TracePersisted = g_m27TraceCount;
		g_m27TraceFlushed = true;
		g_m27TraceDirty = false;
	}
}

'''
s = s[:service_start] + raw_service + s[prepare_start:]

clear_start = s.find("void switch2ProTraceClear()\n{")
dump_start = s.find("void switch2ProTraceDump()\n{", clear_start)
if clear_start < 0 or dump_start < 0:
    raise SystemExit("R378 clear/dump boundaries missing")
raw_clear = r'''void switch2ProTraceClear()
{
	// Explicit CDC command only. This erases the isolated raw trace page, never
	// the LittleFS filesystem where controller bonds are stored.
	m27TraceRawErase();
	g_m27TraceCount = g_m27TracePersisted = 0;
	g_m27TraceDirty = false;
	g_m27TraceFlushed = false;
	g_m27TraceReadySinceMs = 0;
	g_m27TracePendHead = g_m27TracePendTail = 0;
}

'''
s = s[:clear_start] + raw_clear + s[dump_start:]

dump_start = s.find("void switch2ProTraceDump()\n{")
dump_end = s.find("\nstatic void sw2BuildVendorReply", dump_start)
if dump_start < 0 or dump_end < 0:
    raise SystemExit("R378 dump boundaries missing")
raw_dump = r'''void switch2ProTraceDump()
{
	uint32_t count = 0;
	if (!m27TraceRawValid(&count)) {
		Serial.println("# JT no valid raw M27 trace");
		return;
	}
	const M27TraceRecord *records =
		(const M27TraceRecord *)(M27_TRACE_RAW_PAGE + sizeof(M27TraceRawHeader));
	Serial.printf("# JT begin bytes=%lu records=%lu source=M27-working-r378-raw\n",
		      (unsigned long)(count * sizeof(M27TraceRecord)),
		      (unsigned long)count);
	for (uint16_t index = 0; index < count; index++) {
		const M27TraceRecord &r = records[index];
		if (r.kind == 'B') {
			Serial.printf("# JT %u B t=%lu cmd=%02X sub=%02X tr=%02X n=%u reply=%u input=%u rid=%02X p=%02X%02X%02X sess=%u\n",
				      index, (unsigned long)r.ms, r.a, r.b, r.c,
				      r.d, r.e, r.f, r.g, r.h, r.i, r.j, r.k);
		} else if (r.kind == 'C') {
			Serial.printf("# JT %u C t=%lu bm=%02X req=%02X value=%02X%02X index=%02X%02X len=%u\n",
				      index, (unsigned long)r.ms, r.a, r.b, r.d, r.c,
				      r.f, r.e,
				      (unsigned)(r.g | ((uint16_t)r.h << 8)));
		} else if (r.kind == 'G' || r.kind == 'O') {
			Serial.printf("# JT %u %c t=%lu rid=%02X type=%u len=%u\n",
				      index, (char)r.kind, (unsigned long)r.ms, r.a,
				      r.b,
				      (unsigned)(r.c | ((uint16_t)r.d << 8)));
		} else if (r.kind == 'R') {
			Serial.printf("# JT %u R t=%lu rhport=%u\n", index,
				      (unsigned long)r.ms, r.a);
		} else if (r.kind == 'S') {
			Serial.printf("# JT %u S t=%lu fmt=%u source=M27-working-r378-raw\n",
				      index, (unsigned long)r.ms, r.a);
		} else {
			Serial.printf("# JT %u ? kind=%02X t=%lu\n", index,
				      r.kind, (unsigned long)r.ms);
		}
	}
	Serial.println("# JT end");
}
'''
s = s[:dump_start] + raw_dump + s[dump_end:]

# No trace-side filesystem symbol may survive this transform.
for forbidden in (
    "M27_TRACE_FILE",
    "M27_TRACE_TAG",
    "File f(InternalFS)",
    "InternalFS.remove",
    "Adafruit_LittleFS",
    "InternalFileSystem",
):
    if forbidden in s:
        raise SystemExit(f"R378 forbidden trace filesystem symbol remains: {forbidden}")

P.write_text(s, encoding="utf-8")
print("F27 M27 r378 raw-flash trace isolation applied")
