#!/usr/bin/env python3
"""Add a persistent, non-perturbing Joy-Con 2 USB handshake trace.

Apply last, after the r374 full JCR composition. USB-facing replies, descriptors,
and timing are unchanged. Events are captured to RAM during host traffic and
batched to LittleFS only after >=1 second of command silence, so flash stalls do
not sit inside the Nintendo initialization exchange.
"""
from pathlib import Path
import re

MODE = Path("OpenPuck/mode_joycon2.cpp")
HDR = Path("OpenPuck/mode_joycon2.h")
SER = Path("OpenPuck/serial_console.cpp")
src = MODE.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"R375 trace {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


# LittleFS + build hash are needed only for the trace; they do not alter USB.
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

trace_impl = r'''
// R375 persistent trace. Records are intentionally compact (16 bytes) and are
// accumulated in RAM during the Nintendo exchange. LittleFS is touched only
// after the bus has been quiet for >=1 s, avoiding flash stalls in the init path.
static const char JC2_TRACE_FILE[] = "/jc2trace.bin";
static const char JC2_TRACE_TAG[] = "/jc2trtag";
static constexpr uint8_t JC2_TRACE_RAM_MAX = 96;
static constexpr uint8_t JC2_TRACE_PENDING_MAX = 8;

struct Jc2TraceRecord {
	uint32_t ms;
	uint8_t kind;
	uint8_t a, b, c, d, e, f, g, h, i, j, k;
} __attribute__((packed));
static_assert(sizeof(Jc2TraceRecord) == 16, "JC2 trace record must remain 16 bytes");

static Jc2TraceRecord g_jc2TraceRam[JC2_TRACE_RAM_MAX];
static uint8_t g_jc2TraceCount = 0;
static uint8_t g_jc2TracePersisted = 0;
static bool g_jc2TraceDirty = false;
static unsigned long g_jc2TraceLastActivityMs = 0;

// USB callbacks can run off-loop. They enqueue only to this tiny RAM ring;
// joyCon2Drain() consumes it from the normal OpenPuck loop/usbTxPump context.
static Jc2TraceRecord g_jc2TracePending[JC2_TRACE_PENDING_MAX];
static volatile uint8_t g_jc2TracePendHead = 0;
static volatile uint8_t g_jc2TracePendTail = 0;

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

static void jc2TracePersistQuiet()
{
	Jc2TraceRecord r;
	while (jc2TracePendingPop(&r))
		jc2TraceRamAppend(r);
	if (!g_jc2TraceDirty || g_jc2TracePersisted >= g_jc2TraceCount)
		return;
	if ((uint32_t)(millis() - g_jc2TraceLastActivityMs) < 1000u)
		return;

	File f(InternalFS);
	if (!f.open(JC2_TRACE_FILE, FILE_O_WRITE))
		return;
	f.seek(f.size());
	while (g_jc2TracePersisted < g_jc2TraceCount) {
		const Jc2TraceRecord &q = g_jc2TraceRam[g_jc2TracePersisted];
		if (f.write((const uint8_t *)&q, sizeof q) != sizeof q)
			break;
		g_jc2TracePersisted++;
	}
	f.close();
	g_jc2TraceDirty = g_jc2TracePersisted < g_jc2TraceCount;
}

static void jc2TracePrepare()
{
#ifndef OPK_JC2_START_VARIANT
#define OPK_JC2_START_VARIANT 0
#endif
	char prior[40] = { 0 };
	char current[40] = { 0 };
	snprintf(current, sizeof current, "%s-T%u", OPK_GIT_HASH,
		 (unsigned)OPK_JC2_START_VARIANT);
	bool fresh = true;
	File f(InternalFS);
	if (f.open(JC2_TRACE_TAG, FILE_O_READ)) {
		int n = f.read((uint8_t *)prior, sizeof prior - 1);
		if (n > 0)
			prior[n] = 0;
		f.close();
		fresh = strncmp(prior, current, sizeof prior - 1) != 0;
	}
	if (fresh) {
		InternalFS.remove(JC2_TRACE_FILE);
		InternalFS.remove(JC2_TRACE_TAG);
		File tag(InternalFS);
		if (tag.open(JC2_TRACE_TAG, FILE_O_WRITE)) {
			tag.write((const uint8_t *)current, strlen(current));
			tag.close();
		}
	}
	g_jc2TraceCount = g_jc2TracePersisted = 0;
	g_jc2TraceDirty = false;
	g_jc2TracePendHead = g_jc2TracePendTail = 0;
	Jc2TraceRecord r = {};
	r.ms = millis();
	r.kind = 'S';
	r.a = 1; // trace format version
	r.b = (uint8_t)OPK_JC2_START_VARIANT;
	jc2TraceRamAppend(r);
}

void joyCon2TraceClear()
{
	InternalFS.remove(JC2_TRACE_FILE);
	InternalFS.remove(JC2_TRACE_TAG);
	g_jc2TraceCount = g_jc2TracePersisted = 0;
	g_jc2TraceDirty = false;
	g_jc2TracePendHead = g_jc2TracePendTail = 0;
}

void joyCon2TraceDump()
{
	Jc2TraceRecord pending;
	while (jc2TracePendingPop(&pending))
		jc2TraceRamAppend(pending);
	// A manual dump is outside the Switch handshake, so it is safe to force the
	// quiet batch to disk first.
	g_jc2TraceLastActivityMs = 0;
	jc2TracePersistQuiet();

	File f(InternalFS);
	if (!f.open(JC2_TRACE_FILE, FILE_O_READ)) {
		Serial.println("# JT no persisted JC2 trace");
		return;
	}
	uint32_t bytes = f.size();
	Serial.printf("# JT begin bytes=%lu records=%lu\n", (unsigned long)bytes,
		      (unsigned long)(bytes / sizeof(Jc2TraceRecord)));
	Jc2TraceRecord r;
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
			Serial.printf("# JT %u S t=%lu fmt=%u variant=%u\n", index,
				      (unsigned long)r.ms, r.a, r.b);
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
    "\nstatic void buildVendorReply()\n",
    "\n" + trace_impl + "static void buildVendorReply()\n",
    "trace implementation insertion",
)

# Capture malformed/unexpected bulk frames too; this does not change the reply.
src = replace_once(
    src,
    "\tif (n < 8 || cmd[1] != 0x91) {\n\t\tg_jc2VendorReplyLen = 0;\n\t\treturn;\n\t}\n",
    "\tif (n < 8 || cmd[1] != 0x91) {\n\t\tjc2TraceAppendBulk(cmd, n, 0);\n\t\tg_jc2VendorReplyLen = 0;\n\t\treturn;\n\t}\n",
    "invalid bulk trace",
)

src = replace_once(
    src,
    "\tuint8_t first = replyLen > sizeof g_jc2VendorReply ?\n",
    "\tjc2TraceAppendBulk(cmd, n, replyLen);\n\n"
    "\tuint8_t first = replyLen > sizeof g_jc2VendorReply ?\n",
    "bulk trace",
)

# Drain queued USB-callback records and persist only after quiet, before the
# normal mode guard. This work is loop-context and silent during active traffic.
src = replace_once(
    src,
    "static void joyCon2Drain()\n{\n\tif (g_usbMode != MODE_JOYCON2)\n",
    "static void joyCon2Drain()\n{\n\tjc2TracePersistQuiet();\n\tif (g_usbMode != MODE_JOYCON2)\n",
    "trace service",
)

# Observe device-level vendor-control SETUP requests but preserve r374's exact
# behavior: still decline them, so the real WebUSB callback gets the same chance.
control_re = re.compile(
    r"bool joyCon2VendorControlXfer\(uint8_t rhport, uint8_t stage,\n"
    r"\s*const tusb_control_request_t \*request\)\n"
    r"\{\n\s*\(void\)rhport;\n\s*\(void\)stage;\n\s*\(void\)request;\n\s*return false;\n\}",
    re.S,
)
control_new = '''bool joyCon2VendorControlXfer(uint8_t rhport, uint8_t stage,
                              const tusb_control_request_t *request)
{
\t(void)rhport;
\tif (g_usbMode == MODE_JOYCON2)
\t\tjc2TraceQueueControl(stage, request);
\treturn false;
}'''
src, n = control_re.subn(control_new, src, count=1)
if n != 1:
    raise SystemExit("R375 trace control-stub anchor mismatch")

# USB reset boundaries let a later PC reconnect be distinguished from the
# original Switch session in the persisted trace.
src = replace_once(
    src,
    "static void driverReset(uint8_t rhport)\n{\n\t(void)rhport;\n",
    "static void driverReset(uint8_t rhport)\n{\n\tjc2TraceQueueReset(rhport);\n",
    "reset trace",
)

# Control-path HID GET/SET events can reveal whether the host ever reaches HID
# negotiation even when no vendor bulk command is observed.
src = replace_once(
    src,
    "\t(void)reportType;\n\tif (!buffer || !reqLen)\n",
    "\tjc2TraceQueueHid('G', reportId, reportType, reqLen);\n"
    "\t(void)reportType;\n\tif (!buffer || !reqLen)\n",
    "HID GET trace",
)
src = replace_once(
    src,
    "\tif (g_usbMode == MODE_JOYCON2 && itf == 0) {\n\t\t// Joy-Con output report 0x01 is accepted but intentionally not translated\n",
    "\tif (g_usbMode == MODE_JOYCON2 && itf == 0) {\n"
    "\t\tjc2TraceQueueHid('O', reportId, reportType, size);\n"
    "\t\t// Joy-Con output report 0x01 is accepted but intentionally not translated\n",
    "HID SET trace",
)

src = replace_once(
    src,
    "\tUSBDevice.addInterface(g_jc2Usb);\n\tif (!g_jc2DrainRegistered) {\n",
    "\tUSBDevice.addInterface(g_jc2Usb);\n\tjc2TracePrepare();\n\tif (!g_jc2DrainRegistered) {\n",
    "trace prepare",
)

MODE.write_text(src, encoding="utf-8")

hdr = HDR.read_text(encoding="utf-8")
hdr = replace_once(
    hdr,
    "extern JoyCon2Controller g_joyCon2;\n",
    "extern JoyCon2Controller g_joyCon2;\n\n"
    "void joyCon2TraceDump();\n"
    "void joyCon2TraceClear();\n",
    "header declarations",
)
HDR.write_text(hdr, encoding="utf-8")

ser = SER.read_text(encoding="utf-8")
ser = replace_once(
    ser,
    '#include "usb_mount.h" // modeSwitchReboot()\n',
    '#include "usb_mount.h" // modeSwitchReboot()\n#include "mode_joycon2.h"\n',
    "serial include",
)
ser = replace_once(
    ser,
    '\t\t\t} else if (!strcmp(line, "FR")) {\n',
    '\t\t\t} else if (!strcmp(line, "JT")) {\n'
    '\t\t\t\tjoyCon2TraceDump();\n'
    '\t\t\t} else if (!strcmp(line, "JC")) {\n'
    '\t\t\t\tjoyCon2TraceClear();\n'
    '\t\t\t\tSerial.println("# JC2 trace cleared; next JC2 boot starts a fresh trace");\n'
    '\t\t\t} else if (!strcmp(line, "FR")) {\n',
    "serial trace commands",
)
SER.write_text(ser, encoding="utf-8")

print("F27 JC2 R375 persistent trace applied")
