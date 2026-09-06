#!/usr/bin/env python3
"""F27-M33/r390: one real Adafruit JCL sibling, deliberately silent.

Applied after the accepted r384 reconstruction. Session0/HID0 remains the
hardware-positive M27/M28G/M29 JCR path. The old full session1 Nintendo
function is not mounted. Instead exactly one genuine Joy-Con 2 L HID report
descriptor is mounted through a real Adafruit_USBD_HID object, using the same
HID infrastructure that was four-wide hardware-positive in HORIPAD r388.

The sibling never sends an IN report. Its readiness is observed only. This
isolates descriptor/interface presence from live JCL traffic after r389 showed
that the first Adafruit sibling could become host-ready while no Nintendo
controller surfaced.
"""
from pathlib import Path
import re

MODE = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"M33 {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)


def regex_once(text, pattern, repl, label):
    out, n = re.subn(pattern, repl, text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"M33 {label}: regex count {n}, expected 1")
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
        raise SystemExit(f"M33 requires {required}")
if "F27-M33-ONE-SILENT-JCL" in src:
    raise SystemExit("M33 already applied")

src = regex_once(
    src,
    r'(static\s+const\s+char\s+M29_BUILD_MARKER\[\]\s*__attribute__\(\(used\)\)\s*=\s*"F27-M29-JCR-JCL-PAIR";)',
    r'\1\nstatic const char M33_BUILD_MARKER[] __attribute__((used)) = "F27-M33-ONE-SILENT-JCL";',
    "marker",
)
src = replace_once(
    src,
    'asm volatile("" : : "r"(M29_BUILD_MARKER) : "memory");',
    'asm volatile("" : : "r"(M29_BUILD_MARKER) : "memory");\n\tasm volatile("" : : "r"(M33_BUILD_MARKER) : "memory");',
    "marker retain",
)

hid_object = r'''
static const uint8_t M33_JCL_HID_DESC[100] = {
	0x05,0x01,0x09,0x05,0xa1,0x01,0x85,0x05,0x05,0xff,0x09,0x01,0x15,0x00,0x26,0xff,
	0x00,0x95,0x3f,0x75,0x08,0x81,0x02,0x85,0x07,0x09,0x01,0x95,0x02,0x81,0x02,0x05,
	0x09,0x19,0x01,0x29,0x10,0x25,0x01,0x95,0x10,0x75,0x01,0x81,0x02,0x05,0xff,0x09,
	0x01,0x26,0xff,0x00,0x95,0x01,0x75,0x08,0x81,0x02,0x05,0x01,0x09,0x01,0xa1,0x00,
	0x09,0x30,0x09,0x31,0x26,0xff,0x0f,0x95,0x02,0x75,0x0c,0x81,0x02,0xc0,0x05,0xff,
	0x09,0x02,0x26,0xff,0x00,0x95,0x37,0x75,0x08,0x81,0x02,0x85,0x01,0x09,0x01,0x95,
	0x3f,0x91,0x02,0xc0,
};
static_assert(sizeof M33_JCL_HID_DESC == 100,
	      "M33 Joy-Con 2 L HID report descriptor must remain byte-exact");
static Adafruit_USBD_HID g_m33SilentJcl;
static bool g_m33SilentJclBegun = false;

'''
src = replace_once(
    src,
    "class Switch2ProUsbInterface : public Adafruit_USBD_Interface {",
    hid_object + "class Switch2ProUsbInterface : public Adafruit_USBD_Interface {",
    "silent JCL object",
)

# Leave IF5+ to TinyUSB's normal HID driver.
src = regex_once(
    src,
    r'''static uint16_t sw2DriverOpen\(uint8_t rhport, tusb_desc_interface_t const \*itf,\n\s*uint16_t maxLen\)\n\{\n\s*if \(g_usbMode != MODE_SW2_PRO\)\n\s*return 0;\n\s*g_sw2Rhport = rhport;''',
    '''static uint16_t sw2DriverOpen(uint8_t rhport, tusb_desc_interface_t const *itf,\n\t\t\t      uint16_t maxLen)\n{\n\tif (g_usbMode != MODE_SW2_PRO)\n\t\treturn 0;\n\tif (itf->bInterfaceNumber >= 5)\n\t\treturn 0;\n\tg_sw2Rhport = rhport;''',
    "leave sibling to standard driver",
)

# Session0 alone remains owned by the custom Nintendo control wrapper.
src = regex_once(
    src,
    r'''if \(req->wIndex == g_sw2Sessions\[M15_SW2_PRO\]\.baseInterface \|\|\s*req->wIndex == g_sw2Sessions\[M15_SW2_JOYCON_R\]\.baseInterface\)\s*return hidd_control_xfer_cb\(rhport, stage, req\);''',
    '''if (req->wIndex == g_sw2Sessions[M15_SW2_PRO].baseInterface)\n\t\treturn hidd_control_xfer_cb(rhport, stage, req);''',
    "session0 custom control ownership",
)

# HID0 keeps the frozen captured descriptor callback; the Adafruit JCL uses its
# own normal TinyUSB callback.
src = regex_once(
    src,
    r'''if \(g_usbMode == MODE_SW2_PRO && itf < M15_SW2_SESSION_COUNT\)\s*return SWITCH2_PRO_HID_DESC;''',
    '''if (g_usbMode == MODE_SW2_PRO && itf == 0)\n\t\treturn SWITCH2_PRO_HID_DESC;\n\tif (g_usbMode == MODE_SW2_PRO && itf == 1)\n\t\treturn __real_tud_hid_descriptor_report_cb(itf);''',
    "report descriptor ownership",
)
src = regex_once(
    src,
    r'''if \(g_usbMode != MODE_SW2_PRO \|\| itf >= M15_SW2_SESSION_COUNT\)\s*return __real_tud_hid_get_report_cb\(itf, reportId, reportType,\s*buffer, reqLen\);''',
    '''if (g_usbMode != MODE_SW2_PRO || itf != 0)\n\t\treturn __real_tud_hid_get_report_cb(itf, reportId, reportType,\n\t\t\t\t\t\t    buffer, reqLen);''',
    "GET_REPORT ownership",
)
src = regex_once(
    src,
    r'''if \(g_usbMode == MODE_SW2_PRO && itf < M15_SW2_SESSION_COUNT\) \{''',
    '''if (g_usbMode == MODE_SW2_PRO && itf == 0) {''',
    "SET_REPORT ownership",
)

begin_anchor = '''void Switch2ProController::beginPool()\n{\n'''
begin_insert = '''void Switch2ProController::beginPool()\n{\n\tif (!g_m33SilentJclBegun) {\n\t\tg_m33SilentJcl.enableOutEndpoint(true);\n\t\tg_m33SilentJcl.setReportDescriptor(M33_JCL_HID_DESC, sizeof M33_JCL_HID_DESC);\n\t\tg_m33SilentJcl.setPollInterval(4);\n\t\tg_m33SilentJcl.begin();\n\t\tg_m33SilentJclBegun = true;\n\t}\n'''
src = replace_once(src, begin_anchor, begin_insert, "begin silent sibling")

# Replace the old full Nintendo session1 function with one standard HID only.
mount_pattern = r'''void Switch2ProController::mountSlots\(uint8_t k\)\n\{\s*if \(!k\)\s*return;\s*USBDevice\.addInterface\(g_sw2Usb\[M15_SW2_PRO\]\);\s*USBDevice\.addInterface\(g_sw2Usb\[M15_SW2_JOYCON_R\]\);\s*\}'''
mount_repl = r'''void Switch2ProController::mountSlots(uint8_t k)
{
	if (!k)
		return;
	USBDevice.addInterface(g_sw2Usb[M15_SW2_PRO]);
	USBDevice.addInterface(g_m33SilentJcl);
}'''
src = regex_once(src, mount_pattern, mount_repl, "mount one silent sibling")

# Trace only the sibling's readiness. Never call sendReport/usbTxHid/tud_hid_n_report
# for HID1. Limit the inherited M29 drain loop to session0 so the old session1
# sender cannot accidentally target the new Adafruit HID instance.
src = replace_once(
    src,
    "static void m27TracePrepare()\n{",
    "static uint8_t g_m33TraceSeen = 0;\n\nstatic void m27TracePrepare()\n{\n\tg_m33TraceSeen = 0;",
    "trace state",
)
src = replace_once(
    src,
    "void switch2ProTraceClear()\n{",
    "void switch2ProTraceClear()\n{\n\tg_m33TraceSeen = 0;",
    "trace clear",
)

observer = r'''
static void m33TraceSilentJclReady()
{
	bool ready = g_m33SilentJcl.ready();
	uint8_t bit = ready ? 0x02 : 0x01;
	if (g_m33TraceSeen & bit)
		return;
	g_m33TraceSeen |= bit;
	M27TraceRecord r{};
	r.ms = millis();
	r.kind = 'I';
	r.a = 1;
	r.b = ready ? 2 : 1;
	r.c = ready ? 1 : 0;
	r.d = 0x07;
	r.e = 1;
	r.f = 0;
	m27TraceQueue(r);
}

'''
src = replace_once(
    src,
    "static void sw2Drain(void)\n{",
    observer + "static void sw2Drain(void)\n{",
    "silent readiness observer",
)

# Change only the session-loop bound inside the periodic drain, then observe the
# sibling after the proven session0 path has run. This prevents any HID1 IN TX.
drain_start = src.find("static void sw2Drain(void)\n{")
drain_end = src.find("\nbool switch2ProVendorControlXfer", drain_start)
if drain_start < 0 or drain_end < 0:
    raise SystemExit("M33 drain boundaries missing")
drain = src[drain_start:drain_end]
old_loop = "for (uint8_t s = 0; s < M15_SW2_SESSION_COUNT; s++) {"
if drain.count(old_loop) != 1:
    raise SystemExit(f"M33 drain session loop count {drain.count(old_loop)}, expected 1")
drain = drain.replace(old_loop, "for (uint8_t s = 0; s < 1; s++) {", 1)
# Append observer before final session-context restoration if possible.
anchor = "\tg_sw2SessionCtx = M15_SW2_PRO;\n}"
if drain.count(anchor) != 1:
    raise SystemExit(f"M33 drain tail anchor count {drain.count(anchor)}, expected 1")
drain = drain.replace(anchor, "\tm33TraceSilentJclReady();\n\tg_sw2SessionCtx = M15_SW2_PRO;\n}", 1)
src = src[:drain_start] + drain + src[drain_end:]

formatter_anchor = "\t\t} else if (r.kind == 'G' || r.kind == 'O') {\n"
formatter = """\t\t} else if (r.kind == 'I') {\n\t\t\tSerial.printf(\"# JT %u I t=%lu hid=%u phase=%u ready=%u rid=%02X side=%c\\n\",\n\t\t\t\t      index, (unsigned long)r.ms, r.a, r.b, r.c, r.d,\n\t\t\t\t      r.e ? 'L' : 'R');\n\t\t} else if (r.kind == 'G' || r.kind == 'O') {\n"""
src = replace_once(src, formatter_anchor, formatter, "trace formatter")

src = src.replace("M27-M29-JCR-JCL-r384-raw", "M27-M33-ONE-SILENT-JCL-r390-raw")
src = src.replace("0x4c52344dUL", "0x30334D53UL")

MODE.write_text(src, encoding="utf-8")
print("F27-M33 r390 one silent Adafruit JCL discriminator applied")
