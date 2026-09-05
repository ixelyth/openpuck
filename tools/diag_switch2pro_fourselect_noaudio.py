#!/usr/bin/env python3
from pathlib import Path
import re

P = Path("OpenPuck/mode_switch2_pro.cpp")
s = P.read_text()


def sub(pattern, repl, expected=1, flags=0, label="transform"):
    global s
    s, n = re.subn(pattern, repl, s, flags=flags)
    if n != expected:
        raise SystemExit(f"{label}: expected {expected} replacement(s), got {n}")


def replace(old, new, expected=1, label="replace"):
    global s
    n = s.count(old)
    if n != expected:
        raise SystemExit(f"{label}: expected {expected} occurrence(s), got {n}")
    s = s.replace(old, new)


replace(
    "// mode_switch2_pro.cpp -- Nintendo Switch 2 Pro Controller (057E:2069).\n//\n// The USB descriptors are byte-for-byte captures of a physical controller. The\n// native 0x09 motion packing is still undocumented, so this implementation\n// deliberately advertises zero 0x09 motion length and carries decoded Steam IMU\n// samples only in the documented common 0x05 report.\n",
    "// mode_switch2_pro.cpp -- Nintendo Switch 2 Pro Controller (057E:2069).\n//\n// Four-controller hardware discriminator derived from PR #269. Device identity,\n// HID report format, vendor protocol and pairing behavior remain the PR #269\n// implementation. Nintendo audio interfaces are intentionally omitted to free\n// endpoint budget; four Pro2 HID paths share one device-level vendor session.\n// Native 0x09 motion packing remains undocumented, so motion behavior is unchanged.\n",
    label="header",
)

# Build a 5-interface diagnostic configuration body: HID0..HID3 + one shared
# Nintendo vendor interface. Each HID keeps the exact 97-byte PR #269 report
# descriptor and its own interrupt IN/OUT pair. Audio is intentionally absent.
body = []
for i in range(4):
    body += [0x08, 0x0B, i, 0x01, 0x03, 0x00, 0x00, 0x00]
    body += [0x09, 0x04, i, 0x00, 0x02, 0x03, 0x00, 0x00, 0x05]
    body += [0x09, 0x21, 0x11, 0x01, 0x00, 0x01, 0x22, 0x61, 0x00]
    body += [0x07, 0x05, 0x81 + i, 0x03, 0x40, 0x00, 0x04]
    body += [0x07, 0x05, 0x01 + i, 0x03, 0x40, 0x00, 0x04]
body += [0x08, 0x0B, 0x04, 0x01, 0xFF, 0x00, 0x00, 0x00]
body += [0x09, 0x04, 0x04, 0x00, 0x02, 0xFF, 0x00, 0x00, 0x06]
body += [0x07, 0x05, 0x05, 0x02, 0x40, 0x00, 0x00]
body += [0x07, 0x05, 0x85, 0x02, 0x40, 0x00, 0x00]
assert len(body) == 191
rows = []
for off in range(0, len(body), 12):
    rows.append("\t" + ", ".join(f"0x{x:02x}" for x in body[off:off+12]) + ",")
new_cfg = """// Diagnostic configuration body after the 9-byte configuration header.\n// IF0..IF3 are independent Pro2 HID paths; IF4 is one shared Nintendo vendor\n// session. The captured Nintendo audio interfaces are intentionally omitted.\nstatic const uint8_t SWITCH2_PRO_CFG_BODY[] = {\n%s\n};\nstatic_assert(sizeof SWITCH2_PRO_CFG_BODY == 191,\n\t      \"Switch 2 Pro four-select configuration body must remain exact\");""" % "\n".join(rows)
sub(
    r"// Everything after the 9-byte configuration header\..*?static_assert\(sizeof SWITCH2_PRO_CFG_BODY == 259,\n\s*\"Switch 2 Pro configuration body must remain byte-exact\"\);",
    new_cfg,
    flags=re.S,
    label="configuration body",
)

replace(
    "static unsigned long g_sw2LastReportMs = 0;",
    "static unsigned long g_sw2LastReportMs[4] = { 0, 0, 0, 0 };",
    label="report timers",
)

old_alloc = """\t\tuint8_t first = TinyUSBDevice.allocInterface(5);\n\t\tuint8_t hidIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tuint8_t hidOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t vendorOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t vendorIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tuint8_t audioOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t audioIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tif (first != 0 || hidIn != 0x81 || hidOut != 0x01 ||\n\t\t    vendorOut != 0x02 || vendorIn != 0x82 || audioOut != 0x03 ||\n\t\t    audioIn != 0x83)\n\t\t\treturn 0;\n"""
new_alloc = """\t\tuint8_t first = TinyUSBDevice.allocInterface(5);\n\t\tuint8_t hidIn[4], hidOut[4];\n\t\tfor (uint8_t i = 0; i < 4; i++) {\n\t\t\thidIn[i] = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\t\thidOut[i] = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\t}\n\t\tuint8_t vendorOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t vendorIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tif (first != 0)\n\t\t\treturn 0;\n\t\tfor (uint8_t i = 0; i < 4; i++)\n\t\t\tif (hidIn[i] != (uint8_t)(0x81 + i) ||\n\t\t\t    hidOut[i] != (uint8_t)(0x01 + i))\n\t\t\t\treturn 0;\n\t\tif (vendorOut != 0x05 || vendorIn != 0x85)\n\t\t\treturn 0;\n"""
replace(old_alloc, new_alloc, label="endpoint allocation")

replace(
    "static void sw2Buttons(uint8_t slot, uint8_t b09[3], uint8_t b05[4])\n{\n\tmemset(b09, 0, 3);\n\tmemset(b05, 0, 4);\n\tuint32_t b = g_in[slot].buttons;",
    "static void sw2Buttons(uint8_t slot, uint32_t suppressButtons, uint8_t b09[3],\n\t\t       uint8_t b05[4])\n{\n\tmemset(b09, 0, 3);\n\tmemset(b05, 0, 4);\n\tuint32_t b = g_in[slot].buttons & ~suppressButtons;",
    label="button suppression",
)
replace(
    "static void sw2Build09(uint8_t slot, uint8_t out[63])",
    "static void sw2Build09(uint8_t slot, uint32_t suppressButtons, uint8_t out[63])",
    label="build09 signature",
)
replace(
    "static void sw2Build05(uint8_t slot, uint8_t out[63])",
    "static void sw2Build05(uint8_t slot, uint32_t suppressButtons, uint8_t out[63])",
    label="build05 signature",
)
replace(
    "\tsw2Buttons(slot, b09, b05);",
    "\tsw2Buttons(slot, suppressButtons, b09, b05);",
    expected=2,
    label="builder button calls",
)

helpers = r'''
static int sw2FourSelectHid(uint8_t bond, uint32_t *suppress)
{
	static const uint32_t selector[4] = { TB_L4, TB_R4, TB_L5, TB_R5 };
	if (suppress)
		*suppress = 0;
	if (bond >= NSLOT)
		return -1;
	uint32_t buttons = g_in[bond].buttons;
	int selected = -1;
	for (uint8_t i = 0; i < 4; i++) {
		if (!(buttons & selector[i]))
			continue;
		if (selected >= 0)
			return -1; // ambiguous: two selectors means every HID stays neutral
		selected = (int)i;
		if (suppress)
			*suppress = selector[i];
	}
	return selected;
}

static void sw2BuildNeutral09(uint8_t out[63])
{
	memset(out, 0, 63);
	out[0] = g_sw2Counter8++;
	sw2PackStick(out + 5, 0, 0);
	sw2PackStick(out + 8, 0, 0);
	out[0x0b] = (g_sw2Features & (1u << 5)) ? 0x38 : 0x30;
	out[0x0e] = 0;
}

static void sw2BuildNeutral05(uint8_t out[63])
{
	memset(out, 0, 63);
	uint32_t counter = g_sw2Counter32++;
	memcpy(out, &counter, sizeof counter);
	sw2PackStick(out + 0x0a, 0, 0);
	sw2PackStick(out + 0x0d, 0, 0);
	out[0x1f] = 0xd8;
	out[0x20] = 0x0e;
	out[0x21] = 0x34;
	out[0x29] = 0x01;
	uint32_t ts = micros();
	memcpy(out + 0x2a, &ts, sizeof ts);
}

static bool sw2BuildForHid(uint8_t hid, uint8_t bond, uint8_t reportId,
			   uint8_t out[63])
{
	uint32_t suppress = 0;
	int selected = sw2FourSelectHid(bond, &suppress);
	bool active = selected == (int)hid;
	if (reportId == 0x05) {
		if (active)
			sw2Build05(bond, suppress, out);
		else
			sw2BuildNeutral05(out);
		return true;
	}
	if (reportId == 0x09) {
		if (active)
			sw2Build09(bond, suppress, out);
		else
			sw2BuildNeutral09(out);
		return true;
	}
	return false;
}
'''
replace("\nstatic void sw2AckHeader", helpers + "\nstatic void sw2AckHeader", label="four-select helpers")

new_drain = r'''static void sw2Drain(void)
{
	if (g_usbMode != MODE_SW2_PRO || g_usbMountCount == 0)
		return;

	if (g_sw2VendorCommandPending && !g_sw2VendorInFlight) {
		sw2BuildVendorReply();
		uint8_t n = g_sw2VendorReplyLen;
		uint8_t first = n > sizeof g_sw2VendorReply ?
					sizeof g_sw2VendorReply :
					n;
		if (first && g_sw2VendorEpIn &&
		    usbd_edpt_xfer(g_sw2Rhport, g_sw2VendorEpIn,
				   g_sw2VendorReply, first))
			g_sw2VendorInFlight = true;
	}

	if (!g_sw2InputEnabled)
		return;
	int bond = g_usbToBond[0];
	if (bond < 0 || bond >= NSLOT)
		return;
	uint8_t rid = g_sw2ActiveReport == 0x05 ? 0x05 : 0x09;
	for (uint8_t hid = 0; hid < 4; hid++) {
		if (!tud_hid_n_ready(hid))
			continue;
		if ((uint32_t)(millis() - g_sw2LastReportMs[hid]) < USB_STREAM_MS)
			continue;
		uint8_t p[63];
		if (!sw2BuildForHid(hid, (uint8_t)bond, rid, p))
			continue;
		if (tud_hid_n_report(hid, rid, p, sizeof p))
			g_sw2LastReportMs[hid] = millis();
	}
}'''
sub(
    r"static void sw2Drain\(void\)\n\{.*?\n\}\n\nbool switch2ProVendorControlXfer",
    new_drain + "\n\nbool switch2ProVendorControlXfer",
    flags=re.S,
    label="drain",
)

replace(
    "if (g_usbMode == MODE_SW2_PRO && itf == 0)\n\t\treturn SWITCH2_PRO_HID_DESC;",
    "if (g_usbMode == MODE_SW2_PRO && itf < 4)\n\t\treturn SWITCH2_PRO_HID_DESC;",
    label="report descriptor callback",
)

new_get = r'''extern "C" uint16_t __wrap_tud_hid_get_report_cb(uint8_t itf, uint8_t reportId,
						 hid_report_type_t reportType,
						 uint8_t *buffer,
						 uint16_t reqLen)
{
	if (g_usbMode != MODE_SW2_PRO || itf >= 4)
		return __real_tud_hid_get_report_cb(itf, reportId, reportType,
						    buffer, reqLen);
	(void)reportType;
	if (!buffer || !reqLen || (reportId != 0x05 && reportId != 0x09))
		return 0;
	uint8_t p[63];
	int bond = g_usbMountCount ? g_usbToBond[0] : -1;
	if (bond >= 0 && bond < NSLOT) {
		if (!sw2BuildForHid(itf, (uint8_t)bond, reportId, p))
			return 0;
	} else if (reportId == 0x05) {
		sw2BuildNeutral05(p);
	} else {
		sw2BuildNeutral09(p);
	}
	uint16_t n = reqLen < sizeof p ? reqLen : sizeof p;
	memcpy(buffer, p, n);
	return n;
}'''
sub(
    r'extern "C" uint16_t __wrap_tud_hid_get_report_cb\(uint8_t itf, uint8_t reportId,.*?\n\}\n\n// Switch 2 Pro output report',
    new_get + "\n\n// Switch 2 Pro output report",
    flags=re.S,
    label="get report wrapper",
)

# Accept output reports on all four Pro2 HID instances. Rumble remains routed to
# the one physical Steam Controller; this diagnostic adjudicates input topology.
replace(
    "if (g_usbMode == MODE_SW2_PRO && itf == 0) {",
    "if (g_usbMode == MODE_SW2_PRO && itf < 4) {",
    label="set report wrapper",
)

replace(
    "if (itf->bInterfaceNumber == 0 &&\n\t    itf->bInterfaceClass == TUSB_CLASS_HID)",
    "if (itf->bInterfaceNumber < 4 &&\n\t    itf->bInterfaceClass == TUSB_CLASS_HID)",
    label="driver HID open",
)
replace(
    "if (itf->bInterfaceNumber == 1 && itf->bInterfaceClass == 0xff) {",
    "if (itf->bInterfaceNumber == 4 && itf->bInterfaceClass == 0xff) {",
    label="driver vendor open",
)
sub(
    r"\n\t// Preserve the captured audio-control/streaming descriptor block as one\n\t// associated three-interface Nintendo function\. Audio data itself is not\n\t// synthesized by OpenPuck\.\n\tif \(itf->bInterfaceNumber == 2 &&\n\t    itf->bInterfaceClass == TUSB_CLASS_AUDIO\)\n\t\treturn maxLen;",
    "",
    label="remove audio driver path",
)
replace(
    "if (req->wIndex == 0)\n\t\treturn hidd_control_xfer_cb(rhport, stage, req);",
    "if (req->wIndex < 4)\n\t\treturn hidd_control_xfer_cb(rhport, stage, req);",
    label="driver HID control",
)

# Deliberately keep maxSlots() == 1: there is one real RF bond. The four host
# controller paths are four HID instances inside the single Pro2 USB personality.

# Fail closed on stale single-HID assumptions that would invalidate the test.
for forbidden in [
    "tud_hid_n_ready(0)",
    "tud_hid_n_report(0, rid",
    "g_sw2LastReportMs =",
    "itf->bInterfaceNumber == 1 && itf->bInterfaceClass == 0xff",
    "TUSB_CLASS_AUDIO",
]:
    if forbidden in s:
        raise SystemExit(f"stale single-controller/audio anchor remains: {forbidden}")

for required in [
    "sizeof SWITCH2_PRO_CFG_BODY == 191",
    "vendorOut != 0x05 || vendorIn != 0x85",
    "itf->bInterfaceNumber < 4",
    "itf->bInterfaceNumber == 4",
    "L4, TB_R4, TB_L5, TB_R5",
    "tud_hid_n_report(hid, rid",
]:
    if required not in s:
        raise SystemExit(f"required diagnostic anchor missing: {required}")

P.write_text(s)
