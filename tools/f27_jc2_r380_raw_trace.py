#!/usr/bin/env python3
"""Convert the r375 direct-JCR observer to bond-isolated raw-page persistence.

Apply after the exact r379/r374 volatile runtime and the r375 observation transform.
All r375 USB observation hooks remain; every trace-side filesystem dependency is
removed. The snapshot is committed to raw page 0xEB000 only after >=10 s since
capture start and >=5 s of trace silence. A valid snapshot suppresses the
RAM-only JCR startup override on the next software reboot so the saved mode can
be entered for CDC/JT retrieval without any trace-side persistent tag.
"""
from pathlib import Path
import re

MODE = Path("OpenPuck/mode_joycon2.cpp")
HDR = Path("OpenPuck/mode_joycon2.h")
INO = Path("OpenPuck/OpenPuck.ino")
s = MODE.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"R380 {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)


s = replace_once(
    s,
    '#include "usb_tx.h"\n#include "build_info.h"\n#include <Adafruit_LittleFS.h>\n#include <InternalFileSystem.h>\n#include <Adafruit_TinyUSB.h>\n',
    '#include "usb_tx.h"\n#include <Adafruit_TinyUSB.h>\n',
    "trace filesystem includes",
)
s = replace_once(
    s,
    'using namespace Adafruit_LittleFS_Namespace;\n\nextern "C" {\n',
    'extern "C" {\n',
    "trace filesystem namespace",
)

start = s.find("// R375 persistent trace.")
end = s.find("static void buildVendorReply()", start)
if start < 0 or end < 0:
    raise SystemExit("R380 r375 trace implementation boundaries missing")

raw_impl = r'''// R380 direct-JCR trace. USB events remain RAM-only during enumeration and
// Nintendo negotiation. A complete snapshot is later committed to one isolated
// raw flash page; the filesystem containing controller bonds is never touched.
static constexpr uint32_t JC2_TRACE_RAW_PAGE = 0x000EB000UL;
static constexpr uint32_t JC2_TRACE_RAW_MAGIC = 0x3038544AUL; // "JT80"
static constexpr uint32_t JC2_TRACE_RAW_VERSION = 1UL;
static constexpr uint8_t JC2_TRACE_RAM_MAX = 96;
static constexpr uint8_t JC2_TRACE_PENDING_MAX = 8;

struct Jc2TraceRecord {
	uint32_t ms;
	uint8_t kind;
	uint8_t a, b, c, d, e, f, g, h, i, j, k;
} __attribute__((packed));
static_assert(sizeof(Jc2TraceRecord) == 16,
	      "JC2 trace record must remain 16 bytes");

struct Jc2TraceRawHeader {
	uint32_t magic;
	uint32_t version;
	uint32_t count;
	uint32_t checksum;
};
static_assert(sizeof(Jc2TraceRawHeader) == 16,
	      "JC2 raw trace header must remain 16 bytes");

static Jc2TraceRecord g_jc2TraceRam[JC2_TRACE_RAM_MAX];
static uint8_t g_jc2TraceCount = 0;
static bool g_jc2TraceDirty = false;
static bool g_jc2TraceFlushed = false;
static unsigned long g_jc2TraceStartMs = 0;
static unsigned long g_jc2TraceLastActivityMs = 0;

static Jc2TraceRecord g_jc2TracePending[JC2_TRACE_PENDING_MAX];
static volatile uint8_t g_jc2TracePendHead = 0;
static volatile uint8_t g_jc2TracePendTail = 0;

static uint32_t jc2TraceChecksum(const Jc2TraceRecord *records, uint8_t count)
{
	uint32_t h = 2166136261UL;
	const uint8_t *p = (const uint8_t *)records;
	uint32_t n = (uint32_t)count * sizeof(Jc2TraceRecord);
	while (n--) {
		h ^= *p++;
		h *= 16777619UL;
	}
	return h;
}

static void jc2TraceRawErase()
{
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Een;
	while (!NRF_NVMC->READY) {
	}
	NRF_NVMC->ERASEPAGE = JC2_TRACE_RAW_PAGE;
	while (!NRF_NVMC->READY) {
	}
	NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Ren;
	while (!NRF_NVMC->READY) {
	}
}

static void jc2TraceRawWriteWord(uint32_t addr, uint32_t value)
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

static bool jc2TraceRawValid(uint32_t *countOut)
{
	const volatile Jc2TraceRawHeader *h =
		(const volatile Jc2TraceRawHeader *)JC2_TRACE_RAW_PAGE;
	if (h->magic != JC2_TRACE_RAW_MAGIC ||
	    h->version != JC2_TRACE_RAW_VERSION || h->count > JC2_TRACE_RAM_MAX)
		return false;
	uint8_t count = (uint8_t)h->count;
	const Jc2TraceRecord *records =
		(const Jc2TraceRecord *)(JC2_TRACE_RAW_PAGE +
					 sizeof(Jc2TraceRawHeader));
	if (jc2TraceChecksum(records, count) != h->checksum)
		return false;
	if (countOut)
		*countOut = count;
	return true;
}

bool joyCon2TraceHasSnapshot()
{
	return jc2TraceRawValid(nullptr);
}

static bool jc2TraceRawStore()
{
	const uint32_t count = g_jc2TraceCount;
	const uint32_t checksum =
		jc2TraceChecksum(g_jc2TraceRam, g_jc2TraceCount);
	jc2TraceRawErase();

	const uint32_t recordsAddr =
		JC2_TRACE_RAW_PAGE + sizeof(Jc2TraceRawHeader);
	const uint32_t *words = (const uint32_t *)g_jc2TraceRam;
	const uint32_t wordCount =
		(count * sizeof(Jc2TraceRecord) + sizeof(uint32_t) - 1u) /
		sizeof(uint32_t);
	for (uint32_t i = 0; i < wordCount; i++)
		jc2TraceRawWriteWord(recordsAddr + 4u * i, words[i]);

	// Header payload first; magic is the final commit word. A power cut cannot
	// make a partial snapshot validate on the next boot.
	jc2TraceRawWriteWord(JC2_TRACE_RAW_PAGE + 4u,
			     JC2_TRACE_RAW_VERSION);
	jc2TraceRawWriteWord(JC2_TRACE_RAW_PAGE + 8u, count);
	jc2TraceRawWriteWord(JC2_TRACE_RAW_PAGE + 12u, checksum);
	jc2TraceRawWriteWord(JC2_TRACE_RAW_PAGE, JC2_TRACE_RAW_MAGIC);

	uint32_t stored = 0;
	return jc2TraceRawValid(&stored) && stored == count;
}

static void jc2TraceRamAppend(const Jc2TraceRecord &r)
{
	if (g_jc2TraceCount >= JC2_TRACE_RAM_MAX)
		return;
	g_jc2TraceRam[g_jc2TraceCount++] = r;
	g_jc2TraceDirty = true;
	g_jc2TraceLastActivityMs = millis();
}

static void jc2TraceQueue(const Jc2TraceRecord &r)
{
	uint32_t pm = __get_PRIMASK();
	__disable_irq();
	uint8_t head = g_jc2TracePendHead;
	uint8_t next = (uint8_t)((head + 1u) % JC2_TRACE_PENDING_MAX);
	if (next != g_jc2TracePendTail) {
		g_jc2TracePending[head] = r;
		g_jc2TracePendHead = next;
	}
	__set_PRIMASK(pm);
}

static bool jc2TracePendingPop(Jc2TraceRecord *out)
{
	uint32_t pm = __get_PRIMASK();
	__disable_irq();
	uint8_t tail = g_jc2TracePendTail;
	if (tail == g_jc2TracePendHead) {
		__set_PRIMASK(pm);
		return false;
	}
	*out = g_jc2TracePending[tail];
	g_jc2TracePendTail =
		(uint8_t)((tail + 1u) % JC2_TRACE_PENDING_MAX);
	__set_PRIMASK(pm);
	return true;
}

static void jc2TraceQueueControl(uint8_t stage,
				 const tusb_control_request_t *request)
{
	if (!request || stage != CONTROL_STAGE_SETUP)
		return;
	Jc2TraceRecord r = {};
	r.ms = millis();
	r.kind = 'C';
	r.a = request->bmRequestType;
	r.b = request->bRequest;
	r.c = (uint8_t)request->wValue;
	r.d = (uint8_t)(request->wValue >> 8);
	r.e = (uint8_t)request->wIndex;
	r.f = (uint8_t)(request->wIndex >> 8);
	r.g = (uint8_t)request->wLength;
	r.h = (uint8_t)(request->wLength >> 8);
	jc2TraceQueue(r);
}

static void jc2TraceQueueHid(char kind, uint8_t reportId,
			     hid_report_type_t reportType, uint16_t size)
{
	Jc2TraceRecord r = {};
	r.ms = millis();
	r.kind = (uint8_t)kind;
	r.a = reportId;
	r.b = (uint8_t)reportType;
	r.c = (uint8_t)size;
	r.d = (uint8_t)(size >> 8);
	jc2TraceQueue(r);
}

static void jc2TraceQueueReset(uint8_t rhport)
{
	Jc2TraceRecord r = {};
	r.ms = millis();
	r.kind = 'R';
	r.a = rhport;
	jc2TraceQueue(r);
}

static void jc2TraceAppendBulk(const uint8_t *cmd, uint8_t n,
			       uint8_t replyLen)
{
	Jc2TraceRecord r = {};
	r.ms = millis();
	r.kind = 'B';
	r.a = n > 0 ? cmd[0] : 0xff;
	r.b = n > 3 ? cmd[3] : 0xff;
	r.c = n > 2 ? cmd[2] : 0xff;
	r.d = n;
	r.e = replyLen;
	r.f = g_jc2InputEnabled ? 1 : 0;
	r.g = g_jc2ActiveReport;
	r.h = n > 8 ? cmd[8] : 0;
	r.i = n > 9 ? cmd[9] : 0;
	r.j = n > 10 ? cmd[10] : 0;
	r.k = n > 11 ? cmd[11] : 0;
	jc2TraceRamAppend(r);
}

static void jc2TraceService()
{
	Jc2TraceRecord r;
	while (jc2TracePendingPop(&r))
		jc2TraceRamAppend(r);
	if (g_jc2TraceFlushed || !g_jc2TraceDirty || !g_jc2TraceCount)
		return;
	const unsigned long now = millis();
	if ((uint32_t)(now - g_jc2TraceStartMs) < 10000u)
		return;
	if ((uint32_t)(now - g_jc2TraceLastActivityMs) < 5000u)
		return;
	if (jc2TraceRawStore()) {
		g_jc2TraceFlushed = true;
		g_jc2TraceDirty = false;
	}
}

static void jc2TracePrepare()
{
	g_jc2TraceCount = 0;
	g_jc2TraceDirty = false;
	g_jc2TraceFlushed = false;
	g_jc2TracePendHead = g_jc2TracePendTail = 0;
	g_jc2TraceStartMs = millis();
	g_jc2TraceLastActivityMs = g_jc2TraceStartMs;
	Jc2TraceRecord r = {};
	r.ms = g_jc2TraceStartMs;
	r.kind = 'S';
	r.a = 1;
	jc2TraceRamAppend(r);
}

void joyCon2TraceClear()
{
	jc2TraceRawErase();
	g_jc2TraceCount = 0;
	g_jc2TraceDirty = false;
	g_jc2TraceFlushed = false;
	g_jc2TracePendHead = g_jc2TracePendTail = 0;
	g_jc2TraceStartMs = millis();
	g_jc2TraceLastActivityMs = g_jc2TraceStartMs;
}

void joyCon2TraceDump()
{
	uint32_t count = 0;
	if (!jc2TraceRawValid(&count)) {
		Serial.println("# JT no valid raw direct-JCR trace");
		return;
	}
	const Jc2TraceRecord *records =
		(const Jc2TraceRecord *)(JC2_TRACE_RAW_PAGE +
					 sizeof(Jc2TraceRawHeader));
	Serial.printf("# JT begin bytes=%lu records=%lu source=JCR-direct-r380-raw\n",
		      (unsigned long)(count * sizeof(Jc2TraceRecord)),
		      (unsigned long)count);
	for (uint16_t index = 0; index < count; index++) {
		const Jc2TraceRecord &r = records[index];
		if (r.kind == 'B') {
			Serial.printf("# JT %u B t=%lu cmd=%02X sub=%02X tr=%02X n=%u reply=%u input=%u rid=%02X p=%02X%02X%02X%02X\n",
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
			Serial.printf("# JT %u S t=%lu fmt=%u source=JCR-direct-r380-raw\n",
				      index, (unsigned long)r.ms, r.a);
		} else {
			Serial.printf("# JT %u ? kind=%02X t=%lu\n", index,
				      r.kind, (unsigned long)r.ms);
		}
	}
	Serial.println("# JT end");
}

'''
s = s[:start] + raw_impl + s[end:]
s = replace_once(s, "\tjc2TracePersistQuiet();\n", "\tjc2TraceService();\n", "trace service call")

for forbidden in (
    "JC2_TRACE_FILE",
    "JC2_TRACE_TAG",
    "Adafruit_LittleFS",
    "InternalFileSystem",
    "InternalFS",
    '"/jc2trace.bin"',
    '"/jc2trtag"',
):
    if forbidden in s:
        raise SystemExit(f"R380 forbidden trace filesystem symbol remains: {forbidden}")
MODE.write_text(s, encoding="utf-8")

h = HDR.read_text(encoding="utf-8")
h = replace_once(
    h,
    "void joyCon2TraceDump();\nvoid joyCon2TraceClear();\n",
    "void joyCon2TraceDump();\nvoid joyCon2TraceClear();\nbool joyCon2TraceHasSnapshot();\n",
    "snapshot declaration",
)
HDR.write_text(h, encoding="utf-8")

ino = INO.read_text(encoding="utf-8")
pat = re.compile(
    r"#if defined\(OPK_JC2_VOLATILE_START\) && OPK_JC2_VOLATILE_START\n"
    r"\s*// R379 adjudication: enter JCR mode for this boot in RAM only\.\n"
    r"\s*// Do not create/remove/write any persistent tag or save this override\.\n"
    r"\s*g_usbMode = MODE_JOYCON2;\n"
    r"\s*applyActiveType\(\);\n"
    r"#endif",
    re.S,
)
new = '''#if defined(OPK_JC2_VOLATILE_START) && OPK_JC2_VOLATILE_START
	// Force direct JCR only until a valid raw trace exists. After capture, a
	// normal mode-switch reboot can honor the saved mode for CDC/JT retrieval.
	if (!joyCon2TraceHasSnapshot()) {
		g_usbMode = MODE_JOYCON2;
		applyActiveType();
	}
#endif'''
ino, n = pat.subn(new, ino, count=1)
if n != 1:
    raise SystemExit("R380 volatile-start block anchor mismatch")
INO.write_text(ino, encoding="utf-8")

print("F27 JC2 r380 raw-page direct-JCR trace applied")
