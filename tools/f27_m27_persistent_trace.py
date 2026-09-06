#!/usr/bin/env python3
"""Add an observation-only persistent USB trace to the hardware-positive M27 runtime.

Apply after the exact M15+M21+M22+M25+M27 composition. The trace records the
same event classes as the native-JCR r375 diagnostic and batches LittleFS writes
only after >=1 s of USB-command silence. USB descriptors, replies and M27 report
builders are not changed.
"""
from pathlib import Path

MODE = Path("OpenPuck/mode_switch2_pro.cpp")
HDR = Path("OpenPuck/mode_switch2_pro.h")
SER = Path("OpenPuck/serial_console.cpp")
src = MODE.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"M27 trace {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)


src = replace_once(
    src,
    '#include "usb_tx.h"\n#include <Adafruit_TinyUSB.h>\n',
    '#include "usb_tx.h"\n#include "build_info.h"\n'
    '#include <Adafruit_LittleFS.h>\n#include <InternalFileSystem.h>\n'
    '#include <Adafruit_TinyUSB.h>\n',
    "trace includes",
)
src = replace_once(
    src,
    'extern "C" {\n',
    'using namespace Adafruit_LittleFS_Namespace;\n\nextern "C" {\n',
    "LittleFS namespace",
)

trace = r'''
// R376 control trace for the hardware-positive M27 transport. Records are
// captured in RAM during host traffic; LittleFS is touched only after >=1 s of
// silence so tracing does not add flash stalls to Nintendo initialization.
static const char M27_TRACE_FILE[] = "/jc2trace.bin";
static const char M27_TRACE_TAG[] = "/jc2trtag";
static constexpr uint8_t M27_TRACE_RAM_MAX = 128;
static constexpr uint8_t M27_TRACE_PENDING_MAX = 12;

struct M27TraceRecord {
	uint32_t ms;
	uint8_t kind;
	uint8_t a, b, c, d, e, f, g, h, i, j, k;
} __attribute__((packed));
static_assert(sizeof(M27TraceRecord) == 16, "M27 trace record must remain 16 bytes");

static M27TraceRecord g_m27TraceRam[M27_TRACE_RAM_MAX];
static uint8_t g_m27TraceCount = 0;
static uint8_t g_m27TracePersisted = 0;
static bool g_m27TraceDirty = false;
static unsigned long g_m27TraceLastActivityMs = 0;
static M27TraceRecord g_m27TracePending[M27_TRACE_PENDING_MAX];
static volatile uint8_t g_m27TracePendHead = 0;
static volatile uint8_t g_m27TracePendTail = 0;

static void m27TraceRamAppend(const M27TraceRecord &r)
{
	if (g_m27TraceCount >= M27_TRACE_RAM_MAX)
		return;
	g_m27TraceRam[g_m27TraceCount++] = r;
	g_m27TraceDirty = true;
	g_m27TraceLastActivityMs = millis();
}

static void m27TraceQueue(const M27TraceRecord &r)
{
	uint32_t pm = __get_PRIMASK();
	__disable_irq();
	uint8_t head = g_m27TracePendHead;
	uint8_t next = (uint8_t)((head + 1u) % M27_TRACE_PENDING_MAX);
	if (next != g_m27TracePendTail) {
		g_m27TracePending[head] = r;
		g_m27TracePendHead = next;
	}
	__set_PRIMASK(pm);
}

static bool m27TracePendingPop(M27TraceRecord *out)
{
	uint32_t pm = __get_PRIMASK();
	__disable_irq();
	uint8_t tail = g_m27TracePendTail;
	if (tail == g_m27TracePendHead) {
		__set_PRIMASK(pm);
		return false;
	}
	*out = g_m27TracePending[tail];
	g_m27TracePendTail = (uint8_t)((tail + 1u) % M27_TRACE_PENDING_MAX);
	__set_PRIMASK(pm);
	return true;
}

static void m27TraceQueueControl(uint8_t stage,
				 const tusb_control_request_t *request)
{
	if (!request || stage != CONTROL_STAGE_SETUP)
		return;
	M27TraceRecord r = {};
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
	m27TraceQueue(r);
}

static void m27TraceQueueHid(char kind, uint8_t reportId,
			     hid_report_type_t reportType, uint16_t size)
{
	M27TraceRecord r = {};
	r.ms = millis();
	r.kind = (uint8_t)kind;
	r.a = reportId;
	r.b = (uint8_t)reportType;
	r.c = (uint8_t)size;
	r.d = (uint8_t)(size >> 8);
	m27TraceQueue(r);
}

static void m27TraceQueueReset(uint8_t rhport)
{
	M27TraceRecord r = {};
	r.ms = millis();
	r.kind = 'R';
	r.a = rhport;
	m27TraceQueue(r);
}

static void m27TraceAppendBulk(const uint8_t *cmd, uint8_t n,
			       uint8_t replyLen)
{
	M27TraceRecord r = {};
	r.ms = millis();
	r.kind = 'B';
	r.a = n > 0 ? cmd[0] : 0xff;
	r.b = n > 3 ? cmd[3] : 0xff;
	r.c = n > 2 ? cmd[2] : 0xff;
	r.d = n;
	r.e = replyLen;
	r.f = g_sw2InputEnabled ? 1 : 0;
	r.g = g_sw2ActiveReport;
	r.h = n > 8 ? cmd[8] : 0;
	r.i = n > 9 ? cmd[9] : 0;
	r.j = n > 10 ? cmd[10] : 0;
	r.k = n > 11 ? cmd[11] : 0;
	m27TraceRamAppend(r);
}

static void m27TracePersistQuiet()
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

static void m27TracePrepare()
{
	char prior[48] = { 0 };
	char current[48] = { 0 };
	snprintf(current, sizeof current, "%s-M27-R376", OPK_GIT_HASH);
	bool fresh = true;
	File f(InternalFS);
	if (f.open(M27_TRACE_TAG, FILE_O_READ)) {
		int n = f.read((uint8_t *)prior, sizeof prior - 1);
		if (n > 0)
			prior[n] = 0;
		f.close();
		fresh = strncmp(prior, current, sizeof prior - 1) != 0;
	}
	if (fresh) {
		InternalFS.remove(M27_TRACE_FILE);
		InternalFS.remove(M27_TRACE_TAG);
		File tag(InternalFS);
		if (tag.open(M27_TRACE_TAG, FILE_O_WRITE)) {
			tag.write((const uint8_t *)current, strlen(current));
			tag.close();
		}
	}
	g_m27TraceCount = g_m27TracePersisted = 0;
	g_m27TraceDirty = false;
	g_m27TracePendHead = g_m27TracePendTail = 0;
	M27TraceRecord r = {};
	r.ms = millis();
	r.kind = 'S';
	r.a = 1;
	r.b = 27;
	m27TraceRamAppend(r);
}

void switch2ProTraceClear()
{
	InternalFS.remove(M27_TRACE_FILE);
	InternalFS.remove(M27_TRACE_TAG);
	g_m27TraceCount = g_m27TracePersisted = 0;
	g_m27TraceDirty = false;
	g_m27TracePendHead = g_m27TracePendTail = 0;
}

void switch2ProTraceDump()
{
	M27TraceRecord pending;
	while (m27TracePendingPop(&pending))
		m27TraceRamAppend(pending);
	g_m27TraceLastActivityMs = 0;
	m27TracePersistQuiet();
	File f(InternalFS);
	if (!f.open(M27_TRACE_FILE, FILE_O_READ)) {
		Serial.println("# JT no persisted M27 trace");
		return;
	}
	uint32_t bytes = f.size();
	Serial.printf("# JT begin bytes=%lu records=%lu source=M27-working\n",
		      (unsigned long)bytes,
		      (unsigned long)(bytes / sizeof(M27TraceRecord)));
	M27TraceRecord r;
	uint16_t index = 0;
	while (f.read((uint8_t *)&r, sizeof r) == sizeof r) {
		if (r.kind == 'B') {
			Serial.printf("# JT %u B t=%lu cmd=%02X sub=%02X tr=%02X n=%u reply=%u input=%u rid=%02X p=%02X%02X%02X%02X\n",
				      index, (unsigned long)r.ms, r.a, r.b, r.c,
				      r.d, r.e, r.f, r.g, r.h, r.i, r.j, r.k);
		} else if (r.kind == 'C') {
			Serial.printf("# JT %u C t=%lu bm=%02X req=%02X value=%02X%02X index=%02X%02X len=%u\n",
				      index, (unsigned long)r.ms, r.a, r.b, r.d, r.c,
				      r.f, r.e, (unsigned)(r.g | ((uint16_t)r.h << 8)));
		} else if (r.kind == 'G' || r.kind == 'O') {
			Serial.printf("# JT %u %c t=%lu rid=%02X type=%u len=%u\n",
				      index, (char)r.kind, (unsigned long)r.ms, r.a,
				      r.b, (unsigned)(r.c | ((uint16_t)r.d << 8)));
		} else if (r.kind == 'R') {
			Serial.printf("# JT %u R t=%lu rhport=%u\n", index,
				      (unsigned long)r.ms, r.a);
		} else if (r.kind == 'S') {
			Serial.printf("# JT %u S t=%lu fmt=%u source=M27-working\n", index,
				      (unsigned long)r.ms, r.a);
		} else {
			Serial.printf("# JT %u ? kind=%02X t=%lu\n", index, r.kind,
				      (unsigned long)r.ms);
		}
		index++;
	}
	f.close();
	Serial.println("# JT end");
}

'''

src = replace_once(
    src,
    "\nstatic void sw2BuildVendorReply()\n",
    "\n" + trace + "static void sw2BuildVendorReply()\n",
    "trace implementation",
)

src = replace_once(
    src,
    "\tif (n < 8 || cmd[1] != 0x91) {\n\t\tg_sw2VendorReplyLen = 0;\n\t\treturn;\n\t}\n",
    "\tif (n < 8 || cmd[1] != 0x91) {\n\t\tm27TraceAppendBulk(cmd, n, 0);\n\t\tg_sw2VendorReplyLen = 0;\n\t\treturn;\n\t}\n",
    "invalid bulk",
)
src = replace_once(
    src,
    "\tcase 0x06:\n\t\tif (sub == 0x02) {\n\t\t\tg_sw2VendorReplyLen = 0;\n\t\t\treturn;\n\t\t}\n",
    "\tcase 0x06:\n\t\tif (sub == 0x02) {\n\t\t\tm27TraceAppendBulk(cmd, n, 0);\n\t\t\tg_sw2VendorReplyLen = 0;\n\t\t\treturn;\n\t\t}\n",
    "early bulk",
)
src = replace_once(
    src,
    "\tuint8_t first = replyLen > sizeof g_sw2VendorReply ?\n",
    "\tm27TraceAppendBulk(cmd, n, replyLen);\n\n"
    "\tuint8_t first = replyLen > sizeof g_sw2VendorReply ?\n",
    "bulk trace",
)
src = replace_once(
    src,
    "static void sw2Drain()\n{\n\tif (g_usbMode != MODE_SW2_PRO || g_usbMountCount == 0)\n",
    "static void sw2Drain()\n{\n\tm27TracePersistQuiet();\n\tif (g_usbMode != MODE_SW2_PRO || g_usbMountCount == 0)\n",
    "trace service",
)
src = replace_once(
    src,
    "{\n\tif (g_usbMode != MODE_SW2_PRO || !request)\n\t\treturn false;\n\n\tbool identity = request->bmRequestType == 0xc0 &&\n",
    "{\n\tif (g_usbMode != MODE_SW2_PRO || !request)\n\t\treturn false;\n\tm27TraceQueueControl(stage, request);\n\n\tbool identity = request->bmRequestType == 0xc0 &&\n",
    "vendor control",
)
src = replace_once(
    src,
    "static void sw2DriverReset(uint8_t rhport)\n{\n\t(void)rhport;\n",
    "static void sw2DriverReset(uint8_t rhport)\n{\n\tm27TraceQueueReset(rhport);\n",
    "USB reset",
)
src = replace_once(
    src,
    "{\n\tif (g_usbMode != MODE_SW2_PRO || itf != 0)\n\t\treturn __real_tud_hid_get_report_cb(itf, reportId, reportType,\n",
    "{\n\tif (g_usbMode != MODE_SW2_PRO || itf != 0)\n\t\treturn __real_tud_hid_get_report_cb(itf, reportId, reportType,\n"
    "\t\t\t\t\t\t    buffer, reqLen);\n"
    "\tm27TraceQueueHid('G', reportId, reportType, reqLen);\n"
    "\tif (false)\n\t\treturn 0;\n",
    "HID GET trace",
)
# The replacement above consumes the original continuation line; remove the
# duplicated continuation emitted by the original source after the anchor.
src = src.replace("\t\t\t\t\t\t    buffer, reqLen);\n\t(void)reportType;\n",
                  "\t(void)reportType;\n", 1)

src = replace_once(
    src,
    "{\n\tif (g_usbMode == MODE_SW2_PRO && itf == 0) {\n\t\tif (reportType == HID_REPORT_TYPE_OUTPUT) {\n",
    "{\n\tif (g_usbMode == MODE_SW2_PRO && itf == 0) {\n"
    "\t\tm27TraceQueueHid('O', reportId, reportType, size);\n"
    "\t\tif (reportType == HID_REPORT_TYPE_OUTPUT) {\n",
    "HID SET trace",
)
src = replace_once(
    src,
    "void Switch2ProController::beginPool()\n{\n\tif (!g_sw2DrainRegistered) {\n",
    "void Switch2ProController::beginPool()\n{\n\tm27TracePrepare();\n\tif (!g_sw2DrainRegistered) {\n",
    "trace prepare",
)
MODE.write_text(src, encoding="utf-8")

hdr = HDR.read_text(encoding="utf-8")
hdr = replace_once(
    hdr,
    "void switch2ProMapSet(uint8_t index, uint8_t value);\n",
    "void switch2ProMapSet(uint8_t index, uint8_t value);\n"
    "void switch2ProTraceDump();\nvoid switch2ProTraceClear();\n",
    "header declarations",
)
HDR.write_text(hdr, encoding="utf-8")

ser = SER.read_text(encoding="utf-8")
ser = replace_once(
    ser,
    '#include "usb_mount.h" // modeSwitchReboot()\n',
    '#include "usb_mount.h" // modeSwitchReboot()\n#include "mode_switch2_pro.h"\n',
    "serial include",
)
ser = replace_once(
    ser,
    '} else if (!strcmp(line, "CD")) {\n',
    '} else if (!strcmp(line, "JT")) {\n'
    '\t\t\t\tswitch2ProTraceDump();\n'
    '\t\t\t} else if (!strcmp(line, "JC")) {\n'
    '\t\t\t\tswitch2ProTraceClear();\n'
    '\t\t\t\tSerial.println("# JT trace cleared");\n'
    '\t\t\t} else if (!strcmp(line, "CD")) {\n',
    "serial commands",
)
SER.write_text(ser, encoding="utf-8")
print("F27 M27 R376 persistent trace applied")
