#!/usr/bin/env python3
"""F27-M31/r387: four Joy-Con 2 HID discriminator over accepted r384.

The exact r384/M27 session-0 Nintendo bootstrap stays intact. The second full
Nintendo function is replaced by three HID-only siblings so one nRF52840 USB
address exposes four HID paths within endpoint budget:
  HID0 JCR A, HID1 JCL A, HID2 JCR B, HID3 JCL B.

Selectors mirror the hardware-positive HORIPAD FourSelect idea:
  L4->JCR A, R4->JCL A, L5->JCR B, R5->JCL B.
The two valid pair-selector combinations L4+R4 and L5+R5 activate both halves
of that pair simultaneously. Selector paddles are stripped from native reports
so they cannot accidentally request SL+SR solo-horizontal registration.

This transform is applied AFTER the accepted r384 raw JT observer, and extends
that observer with per-HID readiness/TX one-shot events.
"""
from pathlib import Path
import re

MODE = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"M31 {label}: anchor count {n}, expected 1")
    return text.replace(old, new, 1)


def regex_once(text, pattern, repl, label):
    out, n = re.subn(pattern, repl, text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"M31 {label}: regex count {n}, expected 1")
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
        raise SystemExit(f"M31 requires {required}")
if "F27-M31-FOURJOY-FOURSELECT" in src:
    raise SystemExit("M31 already applied")

src = regex_once(
    src,
    r'(static\s+const\s+char\s+M29_BUILD_MARKER\[\]\s*__attribute__\(\(used\)\)\s*=\s*"F27-M29-JCR-JCL-PAIR";)',
    r'\1\nstatic const char M31_BUILD_MARKER[] __attribute__((used)) = "F27-M31-FOURJOY-FOURSELECT";',
    "marker",
)
src = replace_once(
    src,
    'asm volatile("" : : "r"(M29_BUILD_MARKER) : "memory");',
    'asm volatile("" : : "r"(M29_BUILD_MARKER) : "memory");\n\tasm volatile("" : : "r"(M31_BUILD_MARKER) : "memory");',
    "marker retain",
)

# Genuine Switch-2 Joy-Con-2 HID descriptors. L/R differ only by native report
# ID 07/08. No original-Switch Joy-Con descriptor is used.
hid_desc = r'''
static constexpr uint8_t M31_HID_COUNT = 4;
static const uint8_t M31_JCL_HID_DESC[100] = {
	0x05,0x01,0x09,0x05,0xa1,0x01,0x85,0x05,0x05,0xff,0x09,0x01,0x15,0x00,0x26,0xff,
	0x00,0x95,0x3f,0x75,0x08,0x81,0x02,0x85,0x07,0x09,0x01,0x95,0x02,0x81,0x02,0x05,
	0x09,0x19,0x01,0x29,0x10,0x25,0x01,0x95,0x10,0x75,0x01,0x81,0x02,0x05,0xff,0x09,
	0x01,0x26,0xff,0x00,0x95,0x01,0x75,0x08,0x81,0x02,0x05,0x01,0x09,0x01,0xa1,0x00,
	0x09,0x30,0x09,0x31,0x26,0xff,0x0f,0x95,0x02,0x75,0x0c,0x81,0x02,0xc0,0x05,0xff,
	0x09,0x02,0x26,0xff,0x00,0x95,0x37,0x75,0x08,0x81,0x02,0x85,0x01,0x09,0x01,0x95,
	0x3f,0x91,0x02,0xc0,
};
static const uint8_t M31_JCR_HID_DESC[100] = {
	0x05,0x01,0x09,0x05,0xa1,0x01,0x85,0x05,0x05,0xff,0x09,0x01,0x15,0x00,0x26,0xff,
	0x00,0x95,0x3f,0x75,0x08,0x81,0x02,0x85,0x08,0x09,0x01,0x95,0x02,0x81,0x02,0x05,
	0x09,0x19,0x01,0x29,0x10,0x25,0x01,0x95,0x10,0x75,0x01,0x81,0x02,0x05,0xff,0x09,
	0x01,0x26,0xff,0x00,0x95,0x01,0x75,0x08,0x81,0x02,0x05,0x01,0x09,0x01,0xa1,0x00,
	0x09,0x30,0x09,0x31,0x26,0xff,0x0f,0x95,0x02,0x75,0x0c,0x81,0x02,0xc0,0x05,0xff,
	0x09,0x02,0x26,0xff,0x00,0x95,0x37,0x75,0x08,0x81,0x02,0x85,0x01,0x09,0x01,0x95,
	0x3f,0x91,0x02,0xc0,
};
static_assert(sizeof M31_JCL_HID_DESC == 100 && sizeof M31_JCR_HID_DESC == 100,
	      "M31 Joy-Con 2 HID descriptors must remain byte-exact");

'''
src = replace_once(src, "class Switch2ProUsbInterface : public Adafruit_USBD_Interface {",
                   hid_desc + "class Switch2ProUsbInterface : public Adafruit_USBD_Interface {",
                   "HID descriptors")

# Replace M15's two complete 5-interface controller functions with one exact
# session0 five-interface Pro2 body plus three HID-only siblings. The physical
# device/EP0 identity and session0 vendor/audio topology remain M27/r384.
class_pattern = r'''class Switch2ProUsbInterface : public Adafruit_USBD_Interface \{.*?\n\};\nstatic Switch2ProUsbInterface g_sw2Usb\[M15_SW2_SESSION_COUNT\]\s*=\s*\{.*?\n\};'''
class_repl = r'''class Switch2ProUsbInterface : public Adafruit_USBD_Interface {
    public:
	uint16_t getInterfaceDescriptor(uint8_t, uint8_t *buf,
					uint16_t bufsize) override
	{
		static constexpr uint16_t EXTRA_HID_BYTES = 3u * 40u;
		static constexpr uint16_t TOTAL_BYTES =
			sizeof SWITCH2_PRO_CFG_BODY + EXTRA_HID_BYTES;
		if (!buf)
			return TOTAL_BYTES;
		if (bufsize < TOTAL_BYTES)
			return 0;

		uint8_t first = TinyUSBDevice.allocInterface(8);
		uint8_t hidIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		uint8_t hidOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
		uint8_t vendorOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
		uint8_t vendorIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		uint8_t audioOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
		uint8_t audioIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		uint8_t extraIn[3], extraOut[3];
		for (uint8_t i = 0; i < 3; i++) {
			extraIn[i] = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
			extraOut[i] = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
		}
		if (first != 0 || hidIn != 0x81 || hidOut != 0x01 ||
		    vendorOut != 0x02 || vendorIn != 0x82 || audioOut != 0x03 ||
		    audioIn != 0x83)
			return 0;
		for (uint8_t i = 0; i < 3; i++)
			if (extraIn[i] != (uint8_t)(0x84u + i) ||
			    extraOut[i] != (uint8_t)(0x04u + i))
				return 0;

		uint8_t configStr = TinyUSBDevice.addStringDescriptor("Config_0");
		uint8_t hidStr = TinyUSBDevice.addStringDescriptor("If_Hid");
		uint8_t vendorStr = TinyUSBDevice.addStringDescriptor("Switch 2 Pro Controller");
		uint8_t extraStr[3] = {
			TinyUSBDevice.addStringDescriptor("Joy-Con 2 (L) A"),
			TinyUSBDevice.addStringDescriptor("Joy-Con 2 (R) B"),
			TinyUSBDevice.addStringDescriptor("Joy-Con 2 (L) B"),
		};
		if (configStr != 4 || hidStr != 5 || vendorStr != 6)
			return 0;

		memcpy(buf, SWITCH2_PRO_CFG_BODY, sizeof SWITCH2_PRO_CFG_BODY);
		// The copied session0 HID descriptor now returns native JCR report 08,
		// whose descriptor is 100 bytes rather than Pro2's 97.
		for (uint16_t off = 0; off < sizeof SWITCH2_PRO_CFG_BODY;) {
			uint8_t len = buf[off];
			if (!len || off + len > sizeof SWITCH2_PRO_CFG_BODY)
				return 0;
			if (buf[off + 1u] == 0x21 && len == 9) {
				buf[off + 7u] = 100;
				buf[off + 8u] = 0;
				break;
			}
			off = (uint16_t)(off + len);
		}

		uint16_t off = sizeof SWITCH2_PRO_CFG_BODY;
		for (uint8_t i = 0; i < 3; i++) {
			uint8_t ifnum = (uint8_t)(5u + i);
			uint8_t ep = (uint8_t)(4u + i);
			const uint8_t block[40] = {
				0x08,0x0b,ifnum,0x01,0x03,0x00,0x00,0x00,
				0x09,0x04,ifnum,0x00,0x02,0x03,0x00,0x00,extraStr[i],
				0x09,0x21,0x11,0x01,0x00,0x01,0x22,0x64,0x00,
				0x07,0x05,(uint8_t)(0x80u | ep),0x03,0x40,0x00,0x04,
				0x07,0x05,ep,0x03,0x40,0x00,0x04,
			};
			memcpy(buf + off, block, sizeof block);
			off = (uint16_t)(off + sizeof block);
		}
		g_sw2Sessions[M15_SW2_PRO].baseInterface = 0;
		g_sw2Sessions[M15_SW2_PRO].hidInstance = 0;
		g_sw2Sessions[M15_SW2_JOYCON_R].baseInterface = 5;
		g_sw2Sessions[M15_SW2_JOYCON_R].hidInstance = 1;
		return TOTAL_BYTES;
	}
};
static Switch2ProUsbInterface g_sw2UsbM31;'''
src = regex_once(src, class_pattern, class_repl, "USB topology")

# M28's session-safe driver is retained conceptually, but the three extra HID
# interfaces are not full Nintendo sessions. Only IF1 owns vendor bulk.
driver_pattern = r'''static uint16_t m28DriverOpenCurrent\(.*?\n\}\n\nstatic uint16_t sw2DriverOpen\(.*?\n\}\n\n(?=static bool sw2DriverControl)'''
driver_repl = r'''static uint16_t sw2DriverOpen(uint8_t rhport, tusb_desc_interface_t const *itf,
			      uint16_t maxLen)
{
	if (g_usbMode != MODE_SW2_PRO)
		return 0;
	g_sw2Rhport = rhport;
	uint8_t ifnum = itf->bInterfaceNumber;
	if ((ifnum == 0 || (ifnum >= 5 && ifnum <= 7)) &&
	    itf->bInterfaceClass == TUSB_CLASS_HID) {
		g_sw2SessionCtx = (ifnum == 5 || ifnum == 7) ?
					 M15_SW2_JOYCON_R : M15_SW2_PRO;
		uint16_t result = hidd_open(rhport, itf, maxLen);
		g_sw2SessionCtx = M15_SW2_PRO;
		return result;
	}
	if (ifnum == 1 && itf->bInterfaceClass == 0xff) {
		g_sw2SessionCtx = M15_SW2_PRO;
		uint8_t const *p = (uint8_t const *)itf;
		uint8_t const *end = p + maxLen;
		uint16_t used = 0;
		uint8_t opened = 0;
		while (p < end) {
			uint8_t len = p[0], type = p[1];
			if (!len)
				return 0;
			if (p != (uint8_t const *)itf &&
			    (type == TUSB_DESC_INTERFACE ||
			     type == TUSB_DESC_INTERFACE_ASSOCIATION))
				break;
			if (type == TUSB_DESC_ENDPOINT) {
				auto ep = (tusb_desc_endpoint_t const *)p;
				if (!usbd_edpt_open(rhport, ep))
					return 0;
				if (tu_edpt_dir(ep->bEndpointAddress) == TUSB_DIR_IN)
					g_sw2VendorEpIn = ep->bEndpointAddress;
				else
					g_sw2VendorEpOut = ep->bEndpointAddress;
				opened++;
			}
			used += len;
			p += len;
		}
		if (opened != 2 || !g_sw2VendorEpOut || !g_sw2VendorEpIn)
			return 0;
		if (!usbd_edpt_xfer(rhport, g_sw2VendorEpOut, g_sw2VendorOut,
				    sizeof g_sw2VendorOut))
			return 0;
		return used;
	}
	if (ifnum == 2 && itf->bInterfaceClass == TUSB_CLASS_AUDIO)
		return maxLen;
	return 0;
}

'''
src = regex_once(src, driver_pattern, driver_repl, "driver open")

src = regex_once(
    src,
    r'''if \(req->wIndex == g_sw2Sessions\[M15_SW2_PRO\]\.baseInterface \|\|\s*req->wIndex == g_sw2Sessions\[M15_SW2_JOYCON_R\]\.baseInterface\)\s*return hidd_control_xfer_cb\(rhport, stage, req\);''',
    '''if (req->wIndex == 0 || req->wIndex == 5 || req->wIndex == 6 ||
	    req->wIndex == 7)
		return hidd_control_xfer_cb(rhport, stage, req);''',
    "HID control routing",
)

# HID report descriptor is selected by TinyUSB HID instance, not USB IF number.
src = regex_once(
    src,
    r'''if \(g_usbMode == MODE_SW2_PRO && itf < M15_SW2_SESSION_COUNT\)\s*return SWITCH2_PRO_HID_DESC;''',
    '''if (g_usbMode == MODE_SW2_PRO && itf < M31_HID_COUNT)
		return (itf & 1u) ? M31_JCL_HID_DESC : M31_JCR_HID_DESC;''',
    "report descriptor routing",
)

# Add FourSelect activation, per-HID report construction and one-shot JT events.
helpers = r'''
static unsigned long g_m31LastReportMs[M31_HID_COUNT] = { 0, 0, 0, 0 };
static uint16_t g_m31TraceSeen = 0;

static uint8_t m31SelectedMask(uint8_t bond)
{
	if (bond >= NSLOT)
		return 0;
	uint32_t b = g_in[bond].buttons;
	uint8_t mask = 0;
	if (b & TB_L4) mask |= 0x01; // JCR A
	if (b & TB_R4) mask |= 0x02; // JCL A
	if (b & TB_L5) mask |= 0x04; // JCR B
	if (b & TB_R5) mask |= 0x08; // JCL B
	if (!mask || (mask & (uint8_t)(mask - 1u)) == 0)
		return mask;
	if (mask == 0x03 || mask == 0x0c)
		return mask; // explicit paired selector combinations only
	return 0;
}

static uint8_t m31NativeRid(uint8_t hid)
{
	return (hid & 1u) ? 0x07 : 0x08;
}

static bool m31BuildNative(uint8_t hid, uint8_t bond, bool active,
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
	// FourSelect paddles are selectors only; never leak them as SL/SR.
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

static void m31TraceHidEvent(uint8_t hid, uint8_t phase, bool ready,
			     uint8_t rid)
{
	if (hid >= M31_HID_COUNT || phase < 1 || phase > 4)
		return;
	uint16_t bit = (uint16_t)(1u << (hid * 4u + phase - 1u));
	if (g_m31TraceSeen & bit)
		return;
	g_m31TraceSeen |= bit;
	M27TraceRecord r = {};
	r.ms = millis();
	r.kind = 'I';
	r.a = hid;
	r.b = phase; // 1=not-ready, 2=ready, 3=TX attempt, 4=TX queued
	r.c = ready ? 1 : 0;
	r.d = rid;
	r.e = (hid & 1u) ? 1 : 0; // 0=JCR, 1=JCL
	r.f = m31SelectedMask(g_usbMountCount ? (uint8_t)g_usbToBond[0] : 0xff);
	m27TraceRamAppend(r);
}

'''
src = replace_once(src, "static void sw2BuildVendorReply(void)",
                   helpers + "static void sw2BuildVendorReply(void)",
                   "FourSelect helpers")

# Replace the periodic drain but retain the existing session0 vendor transaction
# machinery and raw trace service. Session1 state is mirrored only as a gating
# source for JCL reports; no fake second vendor session is created.
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

	// Mirror only stream-gating state. The Nintendo vendor/bootstrap owner stays
	// session0 exactly as in the accepted M27 line.
	g_sw2Sessions[M15_SW2_JOYCON_R].inputEnabled =
		g_sw2Sessions[M15_SW2_PRO].inputEnabled;
	g_sw2Sessions[M15_SW2_JOYCON_R].featureMask =
		g_sw2Sessions[M15_SW2_PRO].featureMask;
	g_sw2Sessions[M15_SW2_JOYCON_R].features =
		g_sw2Sessions[M15_SW2_PRO].features;
	g_sw2Sessions[M15_SW2_JOYCON_R].activeReport = 0x07;

	uint8_t selected = m31SelectedMask((uint8_t)bond);
	for (uint8_t hid = 0; hid < M31_HID_COUNT; hid++) {
		uint8_t rid = m31NativeRid(hid);
		bool ready = tud_hid_n_ready(hid);
		m31TraceHidEvent(hid, ready ? 2 : 1, ready, rid);
		if (!g_sw2Sessions[M15_SW2_PRO].inputEnabled || !ready)
			continue;
		if ((uint32_t)(millis() - g_m31LastReportMs[hid]) < USB_STREAM_MS)
			continue;
		uint8_t p[63];
		if (!m31BuildNative(hid, (uint8_t)bond,
				    (selected & (uint8_t)(1u << hid)) != 0, p))
			continue;
		m31TraceHidEvent(hid, 3, true, rid);
		if (tud_hid_n_report(hid, rid, p, sizeof p)) {
			g_m31LastReportMs[hid] = millis();
			m31TraceHidEvent(hid, 4, true, rid);
		}
	}
	g_sw2SessionCtx = M15_SW2_PRO;
	m27TraceService();
}

'''
src = regex_once(src, drain_pattern, drain_repl, "four-HID drain")

# GET_REPORT follows the same side/selector policy as periodic streaming.
get_pattern = r'''extern "C" uint16_t __wrap_tud_hid_get_report_cb\(uint8_t itf, uint8_t reportId,.*?\n\}\n\n(?=// Switch 2 Pro output report)'''
get_repl = r'''extern "C" uint16_t __wrap_tud_hid_get_report_cb(uint8_t itf, uint8_t reportId,
						 hid_report_type_t reportType,
						 uint8_t *buffer,
						 uint16_t reqLen)
{
	if (g_usbMode != MODE_SW2_PRO || itf >= M31_HID_COUNT)
		return __real_tud_hid_get_report_cb(itf, reportId, reportType,
						    buffer, reqLen);
	(void)reportType;
	if (!buffer || !reqLen)
		return 0;
	uint8_t expected = m31NativeRid(itf);
	if (reportId != expected && reportId != 0x05 && reportId != 0x09)
		return 0;
	int bond = g_usbMountCount ? g_usbToBond[0] : -1;
	uint8_t p[63] = {};
	if (bond >= 0 && bond < NSLOT) {
		uint8_t selected = m31SelectedMask((uint8_t)bond);
		if (!m31BuildNative(itf, (uint8_t)bond,
				    (selected & (uint8_t)(1u << itf)) != 0, p))
			return 0;
	}
	uint16_t n = reqLen < sizeof p ? reqLen : sizeof p;
	memcpy(buffer, p, n);
	return n;
}

'''
src = regex_once(src, get_pattern, get_repl, "GET_REPORT")

# Consume output reports on all four Joy-Con HID instances. Only HID0 is allowed
# to drive physical Steam rumble through the inherited M27 path.
src = src.replace(
    "if (g_usbMode == MODE_SW2_PRO && itf < M15_SW2_SESSION_COUNT) {",
    "if (g_usbMode == MODE_SW2_PRO && itf < M31_HID_COUNT) {",
    1,
)

# One compound interface object now owns the full session0 body + three HIDs.
mount_pattern = r'''void Switch2ProController::mountSlots\(uint8_t k\)\n\{\s*if \(!k\)\s*return;\s*USBDevice\.addInterface\(g_sw2Usb\[M15_SW2_PRO\]\);\s*USBDevice\.addInterface\(g_sw2Usb\[M15_SW2_JOYCON_R\]\);\s*\}'''
src = regex_once(
    src, mount_pattern,
    '''void Switch2ProController::mountSlots(uint8_t k)\n{\n\tif (k)\n\t\tUSBDevice.addInterface(g_sw2UsbM31);\n}''',
    "mount topology",
)

# Extend raw JT with per-HID readiness/TX event formatter and reset state.
src = replace_once(src, "static void m27TracePrepare()\n{",
                   "static void m27TracePrepare()\n{\n\tg_m31TraceSeen = 0;",
                   "trace prepare reset")
src = replace_once(src, "void switch2ProTraceClear()\n{",
                   "void switch2ProTraceClear()\n{\n\tg_m31TraceSeen = 0;",
                   "trace clear reset")
marker = "\t\t} else if (r.kind == 'G' || r.kind == 'O') {\n"
formatter = """\t\t} else if (r.kind == 'I') {\n\t\t\tSerial.printf(\"# JT %u I t=%lu hid=%u phase=%u ready=%u rid=%02X side=%c sel=%02X\\n\",\n\t\t\t\t      index, (unsigned long)r.ms, r.a, r.b, r.c, r.d,\n\t\t\t\t      r.e ? 'L' : 'R', r.f);\n\t\t} else if (r.kind == 'G' || r.kind == 'O') {\n"""
src = replace_once(src, marker, formatter, "trace formatter")

# Distinct raw snapshot authority; allows direct r384->r387 flashing without JC.
src = src.replace("M27-M29-JCR-JCL-r384-raw", "M27-M31-FOURJOY-r387-raw")
src = src.replace("0x4c52344dUL", "0x31334A46UL")

MODE.write_text(src, encoding="utf-8")
print("F27-M31 r387 four Joy-Con FourSelect discriminator applied")
