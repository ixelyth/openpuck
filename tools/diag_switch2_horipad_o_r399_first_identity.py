#!/usr/bin/env python3
"""Answer only the first Nintendo C0/03 identity probe over hardware-positive r398."""
from pathlib import Path

CPP = Path("OpenPuck/mode_switch_hori.cpp")
WEB = Path("OpenPuck/webusb_config.cpp")


def repl(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"r399 {label}: anchor count {n}, expected 1")
    return s.replace(old, new, 1)


s = CPP.read_text(encoding="utf-8")
for needle in (
    "USBDevice.setID(0x0F0D, 0x0202);",
    'USBDevice.setProductDescriptor("HORIPAD O");',
    "sizeof SWITCH_HID_DESC == 123",
    "usbTxHid(&g_switch[u], 0, p, 8)",
    "Switch 2 Pro Controller",
    "H4_TRACE_MAGIC = 0x38393448UL",
    "source=Switch2-HORIPAD-O-FourSelect-r398-inertvendor",
    "return false; // intentionally no Nintendo control-handshake implementation",
):
    if needle not in s:
        raise SystemExit(f"r399 missing exact r398 contract: {needle}")

meta_block = r'''
static void h4TraceMeta(uint8_t phase, uint8_t a, uint8_t b, int c)
{
	if (phase < 5 || phase > 7 || g_h4TraceCount >= 32)
		return;
	H4TraceRecord &r = g_h4Trace[g_h4TraceCount++];
	r.ms = millis();
	r.hid = a;
	r.phase = phase; // 5=vendor control SETUP, 6=bulk RX, 7=C0/03 reply
	r.ready = b;
	r.selected = (int8_t)c;
}

// Exact 64-byte C0/03 identity payload from the accepted Switch 2 Pro
// implementation. r399 exposes ONLY this first device-level identity reply;
// C0/02 protocol, 40/04 commit, bulk 03/0D, pairing, features, native HID,
// rumble and motion remain deliberately absent.
static const uint8_t H4_R399_PRO2_IDENTITY[64] = {
	0x01, 0x00, 'H',  'E',  'W',  '7',  '0',  '0',  '0',  '6',  '1',
	'6',  '9',  '7',  '8',  '0',  0x00, 0x00, 0x7e, 0x05, 0x69, 0x20,
	0x01, 0x06, 0x01, 0x23, 0x23, 0x23, 0xa0, 0xa0, 0xa0, 0xe6, 0xe6,
	0xe6, 0x32, 0x32, 0x32, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
};
static_assert(sizeof H4_R399_PRO2_IDENTITY == 64,
	      "r399 first Nintendo identity must remain 64 bytes");
static uint8_t g_h4R399ControlReply[64];

bool switchHoriFirstIdentityControlXfer(
	uint8_t rhport, uint8_t stage, const tusb_control_request_t *request)
{
	if (g_usbMode != MODE_SW_HORI || !request)
		return false;

	if (stage == CONTROL_STAGE_SETUP) {
		int len = request->wLength > 127u ? 127 : (int)request->wLength;
		h4TraceMeta(5, request->bRequest, request->bmRequestType, len);
	}

	bool identity = request->bmRequestType == 0xc0 &&
			request->bRequest == 0x03 && request->wLength >= 64;
	if (!identity)
		return false;
	if (stage != CONTROL_STAGE_SETUP)
		return true;

	memcpy(g_h4R399ControlReply, H4_R399_PRO2_IDENTITY,
	       sizeof H4_R399_PRO2_IDENTITY);
	h4TraceMeta(7, request->bRequest, 64, 0);
	return tud_control_xfer(rhport, request, g_h4R399ControlReply,
				sizeof H4_R399_PRO2_IDENTITY);
}

'''

s = repl(
    s,
    "static uint8_t g_h4VendorSink[64];\n",
    "static uint8_t g_h4VendorSink[64];\n\n" + meta_block,
    "first-identity implementation",
)

old_control = r'''static bool h4VendorDriverControl(uint8_t rhport, uint8_t stage,
				  tusb_control_request_t const *request)
{
	(void)rhport;
	(void)stage;
	(void)request;
	return false; // intentionally no Nintendo control-handshake implementation
}
'''
new_control = r'''static bool h4VendorDriverControl(uint8_t rhport, uint8_t stage,
				  tusb_control_request_t const *request)
{
	(void)rhport;
	(void)stage;
	(void)request;
	// Device-level Nintendo vendor controls are routed by the existing global
	// TinyUSB vendor callback wrapper. Keep this class callback inert so r399
	// changes only the explicitly routed C0/03 transaction.
	return false;
}
'''
s = repl(s, old_control, new_control, "class control comment")

old_xfer = r'''static bool h4VendorDriverXfer(uint8_t rhport, uint8_t ep,
			       xfer_result_t result, uint32_t transferred)
{
	(void)transferred;
	if (g_usbMode != MODE_SW_HORI)
		return false;
	if (ep == g_h4VendorEpOut) {
		if (result != XFER_RESULT_SUCCESS)
			return true;
		// Sink host traffic without interpreting or replying to it, then re-arm.
		return usbd_edpt_xfer(rhport, g_h4VendorEpOut, g_h4VendorSink,
				      sizeof g_h4VendorSink);
	}
	if (ep == g_h4VendorEpIn)
		return true;
	return false;
}
'''
new_xfer = r'''static bool h4VendorDriverXfer(uint8_t rhport, uint8_t ep,
			       xfer_result_t result, uint32_t transferred)
{
	if (g_usbMode != MODE_SW_HORI)
		return false;
	if (ep == g_h4VendorEpOut) {
		if (result != XFER_RESULT_SUCCESS)
			return true;
		uint32_t n = transferred > sizeof g_h4VendorSink ?
				     sizeof g_h4VendorSink : transferred;
		if (n >= 4)
			h4TraceMeta(6, g_h4VendorSink[0], g_h4VendorSink[3],
				    g_h4VendorSink[2]);
		// r399 remains bulk-IN silent: observe and sink every command, then re-arm.
		return usbd_edpt_xfer(rhport, g_h4VendorEpOut, g_h4VendorSink,
				      sizeof g_h4VendorSink);
	}
	if (ep == g_h4VendorEpIn)
		return true;
	return false;
}
'''
s = repl(s, old_xfer, new_xfer, "bulk observer")

old_dump = r'''	for (uint32_t i = 0; i < count; i++) {
		if (r[i].phase == 4 && r[i].hid == 0xff)
			Serial.printf("# JT %lu V t=%lu opened=1 itf=%d\n",
				      (unsigned long)i, (unsigned long)r[i].ms,
				      r[i].selected);
		else
			Serial.printf("# JT %lu I t=%lu hid=%u phase=%u ready=%u selected=%d\n",
				      (unsigned long)i, (unsigned long)r[i].ms, r[i].hid,
				      r[i].phase, r[i].ready, r[i].selected);
	}
'''
new_dump = r'''	for (uint32_t i = 0; i < count; i++) {
		if (r[i].phase == 4 && r[i].hid == 0xff)
			Serial.printf("# JT %lu V t=%lu opened=1 itf=%d\n",
				      (unsigned long)i, (unsigned long)r[i].ms,
				      r[i].selected);
		else if (r[i].phase == 5)
			Serial.printf("# JT %lu C t=%lu bm=%02X req=%02X len=%d\n",
				      (unsigned long)i, (unsigned long)r[i].ms,
				      r[i].ready, r[i].hid, r[i].selected);
		else if (r[i].phase == 6)
			Serial.printf("# JT %lu B t=%lu cmd=%02X sub=%02X seq=%02X\n",
				      (unsigned long)i, (unsigned long)r[i].ms,
				      r[i].hid, r[i].ready,
				      (uint8_t)r[i].selected);
		else if (r[i].phase == 7)
			Serial.printf("# JT %lu A t=%lu req=%02X reply_bytes=%u\n",
				      (unsigned long)i, (unsigned long)r[i].ms,
				      r[i].hid, r[i].ready);
		else
			Serial.printf("# JT %lu I t=%lu hid=%u phase=%u ready=%u selected=%d\n",
				      (unsigned long)i, (unsigned long)r[i].ms, r[i].hid,
				      r[i].phase, r[i].ready, r[i].selected);
	}
'''
s = repl(s, old_dump, new_dump, "trace dump")
s = repl(s, "H4_TRACE_MAGIC = 0x38393448UL", "H4_TRACE_MAGIC = 0x39393448UL",
         "trace magic")
s = repl(
    s,
    "source=Switch2-HORIPAD-O-FourSelect-r398-inertvendor",
    "source=Switch2-HORIPAD-O-FourSelect-r399-firstidentity",
    "trace source",
)
CPP.write_text(s, encoding="utf-8")

web = WEB.read_text(encoding="utf-8")
prototype = '''bool switch2ProVendorControlXfer(uint8_t rhport, uint8_t stage,\n\t\t\t\t const tusb_control_request_t *request);\n'''
web = repl(
    web,
    prototype,
    '''bool switchHoriFirstIdentityControlXfer(\n\tuint8_t rhport, uint8_t stage, const tusb_control_request_t *request);\n''' + prototype,
    "vendor-control prototype",
)
route = '''{\n\tif (g_usbMode == MODE_SW2_PRO &&\n\t    switch2ProVendorControlXfer(rhport, stage, request))\n\t\treturn true;\n'''
web = repl(
    web,
    route,
    '''{\n\tif (g_usbMode == MODE_SW_HORI &&\n\t    switchHoriFirstIdentityControlXfer(rhport, stage, request))\n\t\treturn true;\n\tif (g_usbMode == MODE_SW2_PRO &&\n\t    switch2ProVendorControlXfer(rhport, stage, request))\n\t\treturn true;\n''',
    "vendor-control route",
)
WEB.write_text(web, encoding="utf-8")

out = CPP.read_text(encoding="utf-8")
for needle in (
    "USBDevice.setID(0x0F0D, 0x0202);",
    'USBDevice.setProductDescriptor("HORIPAD O");',
    "sizeof SWITCH_HID_DESC == 123",
    "usbTxHid(&g_switch[u], 0, p, 8)",
    "H4_R399_PRO2_IDENTITY[64]",
    "request->bmRequestType == 0xc0",
    "request->bRequest == 0x03",
    "source=Switch2-HORIPAD-O-FourSelect-r399-firstidentity",
    "H4_TRACE_MAGIC = 0x39393448UL",
):
    if needle not in out:
        raise SystemExit(f"r399 missing output contract: {needle}")
for forbidden in (
    "SW2_VENDOR_PROTOCOL",
    "g_sw2Features",
    "g_sw2ActiveReport",
    "sw2HandlePairing",
):
    if forbidden in out:
        raise SystemExit(f"r399 accidentally imported later Nintendo layer: {forbidden}")
if "switchHoriFirstIdentityControlXfer" not in WEB.read_text(encoding="utf-8"):
    raise SystemExit("r399 global vendor-control route missing")
print("r399 exact r398 + first Nintendo C0/03 identity reply and trace observer applied")
