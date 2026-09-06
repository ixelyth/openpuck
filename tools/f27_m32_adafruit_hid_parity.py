#!/usr/bin/env python3
"""F27-M32/r389: Four Joy-Con discriminator using Adafruit_USBD_HID sibling infrastructure.

Applied after the accepted r384 reconstruction. HID0 remains the exact M27/r384
Nintendo custom-class/bootstrap path. HID1..3 are real Adafruit_USBD_HID objects,
matching the infrastructure that is hardware-positive four-wide in HORIPAD r388:
  HID0 JCR A (existing M27 path)
  HID1 JCL A (Adafruit_USBD_HID)
  HID2 JCR B (Adafruit_USBD_HID)
  HID3 JCL B (Adafruit_USBD_HID)

Only session0 owns Nintendo vendor/audio transport. The sibling HIDs receive no
fabricated Nintendo vendor session. Per-HID JT events distinguish host readiness
and software enqueue. No experimental filesystem writes are introduced.
"""
from pathlib import Path
import re

MODE = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"M32 {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)


def regex_once(text, pattern, repl, label):
    out, n = re.subn(pattern, repl, text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"M32 {label}: regex count {n}, expected 1")
    return out


src = MODE.read_text(encoding="utf-8")
for required in (
    "F27-M27-PROVEN-SESSION1-LEFT-JCR",
    "F27-M28G-GRIP-CONTEXT",
    "F27-M29-JCR-JCL-PAIR",
    "M27_TRACE_RAW_PAGE",
    "m27TraceRawStore",
):
    if required not in src:
        raise SystemExit(f"M32 requires {required}")
if "F27-M32-ADA-HID-PARITY" in src:
    raise SystemExit("M32 already applied")

src = regex_once(
    src,
    r'(static\s+const\s+char\s+M29_BUILD_MARKER\[\]\s*__attribute__\(\(used\)\)\s*=\s*"F27-M29-JCR-JCL-PAIR";)',
    r'\1\nstatic const char M32_BUILD_MARKER[] __attribute__((used)) = "F27-M32-ADA-HID-PARITY";',
    "marker",
)
src = replace_once(
    src,
    'asm volatile("" : : "r"(M29_BUILD_MARKER) : "memory");',
    'asm volatile("" : : "r"(M29_BUILD_MARKER) : "memory");\n\tasm volatile("" : : "r"(M32_BUILD_MARKER) : "memory");',
    "marker retain",
)

# Genuine Switch-2 Joy-Con-2 HID report descriptors. These are supplied to
# actual Adafruit_USBD_HID objects, not manually spliced configuration blocks.
hid_objects = r'''
static constexpr uint8_t M32_HID_COUNT = 4;
static const uint8_t M32_JCL_HID_DESC[100] = {
	0x05,0x01,0x09,0x05,0xa1,0x01,0x85,0x05,0x05,0xff,0x09,0x01,0x15,0x00,0x26,0xff,
	0x00,0x95,0x3f,0x75,0x08,0x81,0x02,0x85,0x07,0x09,0x01,0x95,0x02,0x81,0x02,0x05,
	0x09,0x19,0x01,0x29,0x10,0x25,0x01,0x95,0x10,0x75,0x01,0x81,0x02,0x05,0xff,0x09,
	0x01,0x26,0xff,0x00,0x95,0x01,0x75,0x08,0x81,0x02,0x05,0x01,0x09,0x01,0xa1,0x00,
	0x09,0x30,0x09,0x31,0x26,0xff,0x0f,0x95,0x02,0x75,0x0c,0x81,0x02,0xc0,0x05,0xff,
	0x09,0x02,0x26,0xff,0x00,0x95,0x37,0x75,0x08,0x81,0x02,0x85,0x01,0x09,0x01,0x95,
	0x3f,0x91,0x02,0xc0,
};
static const uint8_t M32_JCR_HID_DESC[100] = {
	0x05,0x01,0x09,0x05,0xa1,0x01,0x85,0x05,0x05,0xff,0x09,0x01,0x15,0x00,0x26,0xff,
	0x00,0x95,0x3f,0x75,0x08,0x81,0x02,0x85,0x08,0x09,0x01,0x95,0x02,0x81,0x02,0x05,
	0x09,0x19,0x01,0x29,0x10,0x25,0x01,0x95,0x10,0x75,0x01,0x81,0x02,0x05,0xff,0x09,
	0x01,0x26,0xff,0x00,0x95,0x01,0x75,0x08,0x81,0x02,0x05,0x01,0x09,0x01,0xa1,0x00,
	0x09,0x30,0x09,0x31,0x26,0xff,0x0f,0x95,0x02,0x75,0x0c,0x81,0x02,0xc0,0x05,0xff,
	0x09,0x02,0x26,0xff,0x00,0x95,0x37,0x75,0x08,0x81,0x02,0x85,0x01,0x09,0x01,0x95,
	0x3f,0x91,0x02,0xc0,
};
static_assert(sizeof M32_JCL_HID_DESC == 100 && sizeof M32_JCR_HID_DESC == 100,
	      "M32 Joy-Con 2 HID report descriptors must remain byte-exact");

// Exactly the same Adafruit HID object mechanism used by hardware-positive
// HORIPAD FourSelect. HID0 remains the custom M27 Nintendo function; these are
// HID instances 1..3 after dynamic mounting.
static Adafruit_USBD_HID g_m32SiblingHid[3];
static bool g_m32SiblingBegun = false;
static unsigned long g_m32LastReportMs[M32_HID_COUNT] = { 0, 0, 0, 0 };

'''
src = replace_once(
    src,
    "class Switch2ProUsbInterface : public Adafruit_USBD_Interface {",
    hid_objects + "class Switch2ProUsbInterface : public Adafruit_USBD_Interface {",
    "Adafruit HID objects",
)

# The custom Nintendo application driver must own only the original session0
# IF0..4. IF5+ must be left unclaimed so TinyUSB's normal HID driver can own the
# Adafruit_USBD_HID siblings, exactly as in HORIPAD mode.
src = regex_once(
    src,
    r'''static uint16_t sw2DriverOpen\(uint8_t rhport, tusb_desc_interface_t const \*itf,\n\s*uint16_t maxLen\)\n\{\n\s*if \(g_usbMode != MODE_SW2_PRO\)\n\s*return 0;\n\s*g_sw2Rhport = rhport;''',
    '''static uint16_t sw2DriverOpen(uint8_t rhport, tusb_desc_interface_t const *itf,\n\t\t\t      uint16_t maxLen)\n{\n\tif (g_usbMode != MODE_SW2_PRO)\n\t\treturn 0;\n\tif (itf->bInterfaceNumber >= 5)\n\t\treturn 0;\n\tg_sw2Rhport = rhport;''',
    "leave sibling HIDs to standard driver",
)

# Custom-class control ownership is likewise session0 only.
src = regex_once(
    src,
    r'''if \(req->wIndex == g_sw2Sessions\[M15_SW2_PRO\]\.baseInterface \|\|\s*req->wIndex == g_sw2Sessions\[M15_SW2_JOYCON_R\]\.baseInterface\)\s*return hidd_control_xfer_cb\(rhport, stage, req\);''',
    '''if (req->wIndex == g_sw2Sessions[M15_SW2_PRO].baseInterface)\n\t\treturn hidd_control_xfer_cb(rhport, stage, req);''',
    "session0 custom control ownership",
)

# HID0 remains the exact captured M27/r384 report-descriptor path. The sibling
# objects use their own setReportDescriptor() data via the real TinyUSB callback.
src = regex_once(
    src,
    r'''if \(g_usbMode == MODE_SW2_PRO && itf < M15_SW2_SESSION_COUNT\)\s*return SWITCH2_PRO_HID_DESC;''',
    '''if (g_usbMode == MODE_SW2_PRO && itf == 0)\n\t\treturn SWITCH2_PRO_HID_DESC;\n\tif (g_usbMode == MODE_SW2_PRO && itf < M32_HID_COUNT)\n\t\treturn __real_tud_hid_descriptor_report_cb(itf);''',
    "report descriptor ownership",
)

# Keep HID0's proven custom GET_REPORT behavior. Sibling Adafruit HID instances
# use the real callback, matching HORIPAD infrastructure.
src = regex_once(
    src,
    r'''if \(g_usbMode != MODE_SW2_PRO \|\| itf >= M15_SW2_SESSION_COUNT\)\s*return __real_tud_hid_get_report_cb\(itf, reportId, reportType,\s*buffer, reqLen\);''',
    '''if (g_usbMode != MODE_SW2_PRO || itf != 0)\n\t\treturn __real_tud_hid_get_report_cb(itf, reportId, reportType,\n\t\t\t\t\t\t    buffer, reqLen);''',
    "GET_REPORT infrastructure parity",
)

# Likewise, only HID0 is swallowed/decoded by the Nintendo wrapper. Output
# reports for sibling objects go through the normal Adafruit/TinyUSB callback.
src = regex_once(
    src,
    r'''if \(g_usbMode == MODE_SW2_PRO && itf < M15_SW2_SESSION_COUNT\) \{''',
    '''if (g_usbMode == MODE_SW2_PRO && itf == 0) {''',
    "SET_REPORT infrastructure parity",
)

# Configure the three sibling HID objects exactly like the proven HORIPAD pool:
# OUT endpoint enabled, report descriptor assigned, interval assigned, begin().
begin_anchor = '''void Switch2ProController::beginPool()\n{\n'''
begin_insert = '''void Switch2ProController::beginPool()\n{\n\tif (!g_m32SiblingBegun) {\n\t\tfor (uint8_t i = 0; i < 3; i++) {\n\t\t\tg_m32SiblingHid[i].enableOutEndpoint(true);\n\t\t\tconst uint8_t *desc = (i == 1) ? M32_JCR_HID_DESC : M32_JCL_HID_DESC;\n\t\t\tg_m32SiblingHid[i].setReportDescriptor(desc, 100);\n\t\t\tg_m32SiblingHid[i].setPollInterval(4);\n\t\t\tg_m32SiblingHid[i].begin();\n\t\t}\n\t\tg_m32SiblingBegun = true;\n\t}\n'''
src = replace_once(src, begin_anchor, begin_insert, "begin sibling HID objects")

# Mount one unchanged M27 Nintendo custom function, followed by three real
# Adafruit HID interfaces. The old session1 full Nintendo function is not mounted.
mount_pattern = r'''void Switch2ProController::mountSlots\(uint8_t k\)\n\{\s*if \(!k\)\s*return;\s*USBDevice\.addInterface\(g_sw2Usb\[M15_SW2_PRO\]\);\s*USBDevice\.addInterface\(g_sw2Usb\[M15_SW2_JOYCON_R\]\);\s*\}'''
mount_repl = r'''void Switch2ProController::mountSlots(uint8_t k)
{
	if (!k)
		return;
	USBDevice.addInterface(g_sw2Usb[M15_SW2_PRO]);
	for (uint8_t i = 0; i < 3; i++)
		USBDevice.addInterface(g_m32SiblingHid[i]);
}'''
src = regex_once(src, mount_pattern, mount_repl, "mount Adafruit siblings")

# Declare M32 trace state before the inherited raw trace prepare/clear functions
# so both can reset it without declaration-order coupling.
src = replace_once(
    src,
    "static void m27TracePrepare()\n{",
    "static uint16_t g_m32TraceSeen = 0;\n\nstatic void m27TracePrepare()\n{\n\tg_m32TraceSeen = 0;",
    "trace state declaration",
)
src = replace_once(
    src,
    "void switch2ProTraceClear()\n{",
    "void switch2ProTraceClear()\n{\n\tg_m32TraceSeen = 0;",
    "trace clear reset",
)

helpers = r'''
static uint8_t m32SelectedMask(uint8_t bond)
{
	if (bond >= NSLOT)
		return 0;
	uint32_t b = g_in[bond].buttons;
	uint8_t mask = 0;
	if (b & TB_L4) mask |= 0x01; // JCR A / HID0
	if (b & TB_R4) mask |= 0x02; // JCL A / HID1
	if (b & TB_L5) mask |= 0x04; // JCR B / HID2
	if (b & TB_R5) mask |= 0x08; // JCL B / HID3
	if (!mask || (mask & (uint8_t)(mask - 1u)) == 0)
		return mask;
	if (mask == 0x03 || mask == 0x0c)
		return mask;
	return 0;
}

static uint8_t m32NativeRid(uint8_t hid)
{
	return (hid & 1u) ? 0x07 : 0x08;
}

static bool m32BuildNative(uint8_t hid, uint8_t bond, bool active,
			   uint8_t out[63])
{
	uint8_t rid = 0;
	bool ok;
	if (hid & 1u) {
		g_sw2SessionCtx = M15_SW2_JOYCON_R;
		ok = m29BuildSession1Native(bond,
				g_sw2Sessions[M15_SW2_JOYCON_R].features, &rid, out);
	} else {
		g_sw2SessionCtx = M15_SW2_PRO;
		ok = m29BuildSession0Native(bond,
				g_sw2Sessions[M15_SW2_PRO].features, &rid, out);
	}
	g_sw2SessionCtx = M15_SW2_PRO;
	if (!ok)
		return false;

	// FourSelect paddles select USB controller paths only. Never leak them into
	// Joy-Con native SL/SR bits, which would request solo-horizontal mode.
	out[3] &= 0x3f;
	if (!active) {
		uint8_t counter = out[0], power = out[1];
		memset(out + 2, 0, 61);
		out[0] = counter;
		out[1] = power;
		out[4] = 0x07;
		sw2PackStick(out + 5, 0, 0);
		out[0x0d] = 0xff;
		out[0x0e] = 0;
		out[0x0f] = 0;
	}
	return true;
}

static void m32TraceHidEvent(uint8_t hid, uint8_t phase, bool ready,
			     uint8_t rid, uint8_t selected)
{
	if (hid >= M32_HID_COUNT || phase < 1 || phase > 3)
		return;
	uint16_t bit = (uint16_t)(1u << (hid * 3u + phase - 1u));
	if (g_m32TraceSeen & bit)
		return;
	g_m32TraceSeen |= bit;
	M27TraceRecord r = {};
	r.ms = millis();
	r.kind = 'I';
	r.a = hid;
	r.b = phase; // 1=not-ready, 2=ready, 3=report submitted/enqueued
	r.c = ready ? 1 : 0;
	r.d = rid;
	r.e = (hid & 1u) ? 1 : 0; // 0=JCR, 1=JCL
	r.f = selected;
	m27TraceRamAppend(r);
}

'''
src = replace_once(
    src,
    "static void sw2BuildVendorReply(void)",
    helpers + "static void sw2BuildVendorReply(void)",
    "FourSelect helpers",
)

# Replace only the periodic sender. Session0 vendor bootstrap remains exact.
# HID0 still transmits through the proven tud_hid_n_report path. HID1..3 use
# Adafruit_USBD_HID::ready() + usbTxHid(), exactly like HORIPAD r388.
drain_pattern = r'''static void sw2Drain\(void\)\n\{.*?\n\}\n\n(?=bool switch2ProVendorControlXfer)'''
drain_repl = r'''static void sw2Drain(void)
{
	if (g_usbMode != MODE_SW2_PRO || g_usbMountCount == 0)
		return;

	int bond = g_usbToBond[0];
	if (bond < 0 || bond >= NSLOT)
		return;

	g_sw2SessionCtx = M15_SW2_PRO;
	if (g_sw2VendorCommandPending && !g_sw2VendorInFlight) {
		sw2BuildVendorReply();
		uint8_t n = g_sw2VendorReplyLen;
		uint8_t first = n > sizeof g_sw2VendorReply ?
					sizeof g_sw2VendorReply : n;
		if (first && g_sw2VendorEpIn &&
		    usbd_edpt_xfer(g_sw2Rhport, g_sw2VendorEpIn,
				   g_sw2VendorReply, first))
			g_sw2VendorInFlight = true;
	}

	// Sibling Joy-Con builders borrow only the already-proven session0 stream
	// gating/features. They do not receive or synthesize a second vendor session.
	g_sw2Sessions[M15_SW2_JOYCON_R].inputEnabled =
		g_sw2Sessions[M15_SW2_PRO].inputEnabled;
	g_sw2Sessions[M15_SW2_JOYCON_R].featureMask =
		g_sw2Sessions[M15_SW2_PRO].featureMask;
	g_sw2Sessions[M15_SW2_JOYCON_R].features =
		g_sw2Sessions[M15_SW2_PRO].features;
	g_sw2Sessions[M15_SW2_JOYCON_R].activeReport = 0x07;

	uint8_t selected = m32SelectedMask((uint8_t)bond);
	for (uint8_t hid = 0; hid < M32_HID_COUNT; hid++) {
		uint8_t rid = m32NativeRid(hid);
		bool ready = hid == 0 ? tud_hid_n_ready(0) :
					 g_m32SiblingHid[hid - 1u].ready();
		m32TraceHidEvent(hid, ready ? 2 : 1, ready, rid, selected);
		if (!g_sw2Sessions[M15_SW2_PRO].inputEnabled || !ready)
			continue;
		if ((uint32_t)(millis() - g_m32LastReportMs[hid]) < USB_STREAM_MS)
			continue;
		uint8_t p[63];
		if (!m32BuildNative(hid, (uint8_t)bond,
				    (selected & (uint8_t)(1u << hid)) != 0, p))
			continue;
		if (hid == 0) {
			if (!tud_hid_n_report(0, rid, p, sizeof p))
				continue;
		} else {
			usbTxHid(&g_m32SiblingHid[hid - 1u], rid, p, sizeof p);
		}
		g_m32LastReportMs[hid] = millis();
		m32TraceHidEvent(hid, 3, true, rid, selected);
	}
	g_sw2SessionCtx = M15_SW2_PRO;
	m27TraceService();
}

'''
src = regex_once(src, drain_pattern, drain_repl, "Adafruit-HID drain")

# Add per-HID event output immediately before the inherited G/O formatter.
formatter_anchor = "\t\t} else if (r.kind == 'G' || r.kind == 'O') {\n"
formatter = """\t\t} else if (r.kind == 'I') {\n\t\t\tSerial.printf(\"# JT %u I t=%lu hid=%u phase=%u ready=%u rid=%02X side=%c sel=%02X\\n\",\n\t\t\t\t      index, (unsigned long)r.ms, r.a, r.b, r.c, r.d,\n\t\t\t\t      r.e ? 'L' : 'R', r.f);\n\t\t} else if (r.kind == 'G' || r.kind == 'O') {\n"""
src = replace_once(src, formatter_anchor, formatter, "trace formatter")

# Distinct raw snapshot authority permits direct r387/r388 -> r389 flashing
# without clearing the prior trace page.
src = src.replace("M27-M29-JCR-JCL-r384-raw", "M27-M32-ADA-HID-r389-raw")
src = src.replace("0x4c52344dUL", "0x39334D52UL")

MODE.write_text(src, encoding="utf-8")
print("F27-M32 r389 Adafruit HID infrastructure-parity discriminator applied")
