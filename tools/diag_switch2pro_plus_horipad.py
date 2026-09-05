#!/usr/bin/env python3
from pathlib import Path
import re

P = Path("OpenPuck/mode_switch2_pro.cpp")
s = P.read_text()


def replace(old, new, expected=1, label="replace"):
    global s
    n = s.count(old)
    if n != expected:
        raise SystemExit(f"{label}: expected {expected} occurrence(s), got {n}")
    s = s.replace(old, new)


def sub(pattern, repl, expected=1, flags=0, label="sub"):
    global s
    s, n = re.subn(pattern, repl, s, flags=flags)
    if n != expected:
        raise SystemExit(f"{label}: expected {expected} replacement(s), got {n}")


replace(
    "// mode_switch2_pro.cpp -- Nintendo Switch 2 Pro Controller (057E:2069).\n//\n// The USB descriptors are byte-for-byte captures of a physical controller. The\n// native 0x09 motion packing is still undocumented, so this implementation\n// deliberately advertises zero 0x09 motion length and carries decoded Steam IMU\n// samples only in the documented common 0x05 report.\n",
    "// mode_switch2_pro.cpp -- Nintendo Switch 2 Pro Controller (057E:2069).\n//\n// Mixed-protocol hardware discriminator derived from PR #269. It retains one\n// Nintendo Switch2Pro HID + vendor/pairing session, removes unused Nintendo audio,\n// and appends one ordinary HORIPAD HID on the same USB device/address. L4 selects\n// the Pro2 input path; R4 selects the HORIPAD input path; otherwise both stay neutral.\n// Native 0x09 motion packing remains undocumented, so motion behavior is unchanged.\n",
    label="header",
)

HORI_DESC = [
    0x05,0x01,0x09,0x05,0xA1,0x01,0x15,0x00,0x25,0x01,0x35,0x00,
    0x45,0x01,0x75,0x01,0x95,0x10,0x05,0x09,0x19,0x01,0x29,0x10,
    0x81,0x02,0x05,0x01,0x25,0x07,0x46,0x3B,0x01,0x75,0x04,0x95,
    0x01,0x65,0x14,0x09,0x39,0x81,0x42,0x65,0x00,0x95,0x01,0x81,
    0x01,0x26,0xFF,0x00,0x46,0xFF,0x00,0x09,0x30,0x09,0x31,0x09,
    0x32,0x09,0x35,0x75,0x08,0x95,0x04,0x81,0x02,0x06,0x00,0xFF,
    0x09,0x20,0x95,0x01,0x81,0x02,0x0A,0x21,0x26,0x95,0x08,0x91,
    0x02,0xC0,
]
assert len(HORI_DESC) == 86
hori_rows = []
for off in range(0, len(HORI_DESC), 12):
    hori_rows.append("\t" + ", ".join(f"0x{x:02x}" for x in HORI_DESC[off:off+12]) + ",")
hori_decl = """\n// Legacy HORIPAD report descriptor used only by this mixed-topology diagnostic.\nstatic const uint8_t SWITCH2_PRO_MIXED_HORI_DESC[] = {\n%s\n};\nstatic_assert(sizeof SWITCH2_PRO_MIXED_HORI_DESC == 86,\n\t      \"mixed HORIPAD report descriptor must remain exact\");\n""" % "\n".join(hori_rows)
replace(
    "static_assert(sizeof SWITCH2_PRO_HID_DESC == 97,\n\t      \"Switch 2 Pro HID descriptor must remain byte-exact\");\n",
    "static_assert(sizeof SWITCH2_PRO_HID_DESC == 97,\n\t      \"Switch 2 Pro HID descriptor must remain byte-exact\");\n" + hori_decl,
    label="HORIPAD descriptor insertion",
)

# IF0 = Pro2 HID (81/01), IF1 = Nintendo vendor (02/82), IF2 = HORIPAD HID (83/03).
body = []
body += [0x08,0x0B,0x00,0x01,0x03,0x00,0x00,0x00]
body += [0x09,0x04,0x00,0x00,0x02,0x03,0x00,0x00,0x05]
body += [0x09,0x21,0x11,0x01,0x00,0x01,0x22,0x61,0x00]
body += [0x07,0x05,0x81,0x03,0x40,0x00,0x04]
body += [0x07,0x05,0x01,0x03,0x40,0x00,0x04]
body += [0x08,0x0B,0x01,0x01,0xFF,0x00,0x00,0x00]
body += [0x09,0x04,0x01,0x00,0x02,0xFF,0x00,0x00,0x06]
body += [0x07,0x05,0x02,0x02,0x40,0x00,0x00]
body += [0x07,0x05,0x82,0x02,0x40,0x00,0x00]
body += [0x08,0x0B,0x02,0x01,0x03,0x00,0x00,0x00]
body += [0x09,0x04,0x02,0x00,0x02,0x03,0x00,0x00,0x00]
body += [0x09,0x21,0x11,0x01,0x00,0x01,0x22,len(HORI_DESC)&0xff,(len(HORI_DESC)>>8)&0xff]
body += [0x07,0x05,0x83,0x03,0x40,0x00,0x04]
body += [0x07,0x05,0x03,0x03,0x40,0x00,0x04]
assert len(body) == 111
rows = []
for off in range(0, len(body), 12):
    rows.append("\t" + ", ".join(f"0x{x:02x}" for x in body[off:off+12]) + ",")
new_cfg = """// Mixed diagnostic configuration after the 9-byte configuration header.\n// IF0 is the captured Pro2 HID, IF1 is the captured Nintendo vendor session,\n// and IF2 is one ordinary HORIPAD HID. Nintendo audio is intentionally omitted.\nstatic const uint8_t SWITCH2_PRO_CFG_BODY[] = {\n%s\n};\nstatic_assert(sizeof SWITCH2_PRO_CFG_BODY == 111,\n\t      \"Switch2Pro + HORIPAD configuration body must remain exact\");""" % "\n".join(rows)
sub(
    r"// Everything after the 9-byte configuration header\..*?static_assert\(sizeof SWITCH2_PRO_CFG_BODY == 259,\n\s*\"Switch 2 Pro configuration body must remain byte-exact\"\);",
    new_cfg,
    flags=re.S,
    label="configuration body",
)

replace(
    "static unsigned long g_sw2LastReportMs = 0;",
    "static unsigned long g_sw2LastReportMs = 0;\nstatic unsigned long g_sw2HoriLastReportMs = 0;",
    label="HORIPAD timer",
)

old_alloc = """\t\tuint8_t first = TinyUSBDevice.allocInterface(5);\n\t\tuint8_t hidIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tuint8_t hidOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t vendorOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t vendorIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tuint8_t audioOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t audioIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tif (first != 0 || hidIn != 0x81 || hidOut != 0x01 ||\n\t\t    vendorOut != 0x02 || vendorIn != 0x82 || audioOut != 0x03 ||\n\t\t    audioIn != 0x83)\n\t\t\treturn 0;\n"""
new_alloc = """\t\tuint8_t first = TinyUSBDevice.allocInterface(3);\n\t\tuint8_t hidIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tuint8_t hidOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t vendorOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t vendorIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tuint8_t horiIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tuint8_t horiOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tif (first != 0 || hidIn != 0x81 || hidOut != 0x01 ||\n\t\t    vendorOut != 0x02 || vendorIn != 0x82 || horiIn != 0x83 ||\n\t\t    horiOut != 0x03)\n\t\t\treturn 0;\n"""
replace(old_alloc, new_alloc, label="endpoint allocation")

# Allow selector suppression in the Pro2 builders.
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
static bool sw2MixedSelectPro(uint8_t bond)
{
	if (bond >= NSLOT)
		return false;
	uint32_t selectors = g_in[bond].buttons & (TB_L4 | TB_R4);
	return selectors == TB_L4;
}

static bool sw2MixedSelectHori(uint8_t bond)
{
	if (bond >= NSLOT)
		return false;
	uint32_t selectors = g_in[bond].buttons & (TB_L4 | TB_R4);
	return selectors == TB_R4;
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

static uint16_t sw2HoriCodeToSwitch(uint8_t c, uint16_t fA, uint16_t fB,
				     uint16_t fX, uint16_t fY)
{
	switch (c) {
	case 1: return fA;
	case 2: return fB;
	case 3: return fX;
	case 4: return fY;
	case 5: return 0x10;
	case 6: return 0x20;
	case 7: return 0x400;
	case 8: return 0x800;
	case 9: return 0x100;
	case 10: return 0x200;
	case 11: return 0x1000;
	case 18: return 0x2000;
	case 19: return 0x40;
	case 20: return 0x80;
	default: return 0;
	}
}

static void sw2HoriBackCodeToHat(uint8_t c, bool &u, bool &d, bool &l,
				 bool &r)
{
	if (c == 12) u = true;
	else if (c == 13) d = true;
	else if (c == 14) l = true;
	else if (c == 15) r = true;
}

static void sw2BuildMixedHori(uint8_t slot, uint8_t out[8])
{
	uint32_t b = g_in[slot].buttons & ~(uint32_t)TB_R4;
	uint16_t fY = g_abSwap ? 0x08 : 0x01;
	uint16_t fB = g_abSwap ? 0x04 : 0x02;
	uint16_t fA = g_abSwap ? 0x02 : 0x04;
	uint16_t fX = g_abSwap ? 0x01 : 0x08;
	uint16_t btn = 0;
	if (b & TB_Y) btn |= fY;
	if (b & TB_B) btn |= fB;
	if (b & TB_A) btn |= fA;
	if (b & TB_X) btn |= fX;
	if (b & TB_LB) btn |= 0x10;
	if (b & TB_RB) btn |= 0x20;
	if (g_in[slot].lt >= SW_TRIG_ON || (b & 0x8000000u)) btn |= 0x40;
	if (g_in[slot].rt >= SW_TRIG_ON || (b & 0x800000u)) btn |= 0x80;
	if (b & TB_MENU) btn |= 0x100;
	if (b & TB_VIEW) btn |= 0x200;
	if (b & TB_L3) btn |= 0x400;
	if (b & TB_R3) btn |= 0x800;
	if (b & TB_STEAM) btn |= 0x1000;
	if (b & TB_L4) btn |= sw2HoriCodeToSwitch(g_back[0], fA, fB, fX, fY);
	if (b & TB_L5) btn |= sw2HoriCodeToSwitch(g_back[2], fA, fB, fX, fY);
	if (b & TB_R5) btn |= sw2HoriCodeToSwitch(g_back[3], fA, fB, fX, fY);
	bool u = b & TB_DUP, d = b & TB_DDN, l = b & TB_DLF, r = b & TB_DRT;
	if (b & TB_L4) sw2HoriBackCodeToHat(g_back[0], u, d, l, r);
	if (b & TB_L5) sw2HoriBackCodeToHat(g_back[2], u, d, l, r);
	if (b & TB_R5) sw2HoriBackCodeToHat(g_back[3], u, d, l, r);
	uint8_t hat = 8;
	if (u && r) hat = 1;
	else if (r && d) hat = 3;
	else if (d && l) hat = 5;
	else if (l && u) hat = 7;
	else if (u) hat = 0;
	else if (r) hat = 2;
	else if (d) hat = 4;
	else if (l) hat = 6;
	out[0] = (uint8_t)btn;
	out[1] = (uint8_t)(btn >> 8);
	out[2] = hat;
	int16_t lx, ly, rx, ry;
	slotSticks(slot, &lx, &ly, &rx, &ry);
	out[3] = swStick(lx, false);
	out[4] = swStick(ly, true);
	out[5] = swStick(rx, false);
	out[6] = swStick(ry, true);
	out[7] = 0;
}

static void sw2BuildNeutralHori(uint8_t out[8])
{
	static const uint8_t neutral[8] = { 0, 0, 8, 0x80, 0x80, 0x80, 0x80, 0 };
	memcpy(out, neutral, sizeof neutral);
}
'''
replace("\nstatic void sw2AckHeader", helpers + "\nstatic void sw2AckHeader", label="mixed helpers")

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

	int bond = g_usbToBond[0];
	if (bond < 0 || bond >= NSLOT)
		return;

	if (g_sw2InputEnabled && tud_hid_n_ready(0) &&
	    (uint32_t)(millis() - g_sw2LastReportMs) >= USB_STREAM_MS) {
		uint8_t p[63];
		uint8_t rid = g_sw2ActiveReport == 0x05 ? 0x05 : 0x09;
		if (sw2MixedSelectPro((uint8_t)bond)) {
			if (rid == 0x05)
				sw2Build05((uint8_t)bond, TB_L4, p);
			else
				sw2Build09((uint8_t)bond, TB_L4, p);
		} else if (rid == 0x05) {
			sw2BuildNeutral05(p);
		} else {
			sw2BuildNeutral09(p);
		}
		if (tud_hid_n_report(0, rid, p, sizeof p))
			g_sw2LastReportMs = millis();
	}

	if (tud_hid_n_ready(1) &&
	    (uint32_t)(millis() - g_sw2HoriLastReportMs) >= USB_STREAM_MS) {
		uint8_t p[8];
		if (sw2MixedSelectHori((uint8_t)bond))
			sw2BuildMixedHori((uint8_t)bond, p);
		else
			sw2BuildNeutralHori(p);
		if (tud_hid_n_report(1, 0, p, sizeof p))
			g_sw2HoriLastReportMs = millis();
	}
}'''
sub(
    r"static void sw2Drain\(void\)\n\{.*?\n\}\n\nbool switch2ProVendorControlXfer",
    new_drain + "\n\nbool switch2ProVendorControlXfer",
    flags=re.S,
    label="drain",
)

# Two HID instances: TinyUSB HID instance 0 = Pro2, instance 1 = HORIPAD.
replace(
    "if (g_usbMode == MODE_SW2_PRO && itf == 0)\n\t\treturn SWITCH2_PRO_HID_DESC;",
    "if (g_usbMode == MODE_SW2_PRO && itf == 0)\n\t\treturn SWITCH2_PRO_HID_DESC;\n\tif (g_usbMode == MODE_SW2_PRO && itf == 1)\n\t\treturn SWITCH2_PRO_MIXED_HORI_DESC;",
    label="report descriptor callback",
)

new_get = r'''extern "C" uint16_t __wrap_tud_hid_get_report_cb(uint8_t itf, uint8_t reportId,
						 hid_report_type_t reportType,
						 uint8_t *buffer,
						 uint16_t reqLen)
{
	if (g_usbMode != MODE_SW2_PRO || itf > 1)
		return __real_tud_hid_get_report_cb(itf, reportId, reportType,
						    buffer, reqLen);
	(void)reportType;
	if (!buffer || !reqLen)
		return 0;
	int bond = g_usbMountCount ? g_usbToBond[0] : -1;
	if (itf == 1) {
		uint8_t p[8];
		if (bond >= 0 && bond < NSLOT && sw2MixedSelectHori((uint8_t)bond))
			sw2BuildMixedHori((uint8_t)bond, p);
		else
			sw2BuildNeutralHori(p);
		uint16_t n = reqLen < sizeof p ? reqLen : sizeof p;
		memcpy(buffer, p, n);
		return n;
	}
	if (reportId != 0x05 && reportId != 0x09)
		return 0;
	uint8_t p[63];
	if (bond >= 0 && bond < NSLOT && sw2MixedSelectPro((uint8_t)bond)) {
		if (reportId == 0x05)
			sw2Build05((uint8_t)bond, TB_L4, p);
		else
			sw2Build09((uint8_t)bond, TB_L4, p);
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

# Pro2 output remains on HID0; HORIPAD output reports are accepted/ignored on HID1.
old_set_head = """\tif (g_usbMode == MODE_SW2_PRO && itf == 0) {\n\t\tif (reportType == HID_REPORT_TYPE_OUTPUT) {"""
new_set_head = """\tif (g_usbMode == MODE_SW2_PRO && itf == 1)\n\t\treturn;\n\tif (g_usbMode == MODE_SW2_PRO && itf == 0) {\n\t\tif (reportType == HID_REPORT_TYPE_OUTPUT) {"""
replace(old_set_head, new_set_head, label="set report wrapper")

# Open IF0 and IF2 as HID instances; IF1 remains the shared Nintendo vendor session.
replace(
    "\tif (itf->bInterfaceNumber == 0 &&\n\t    itf->bInterfaceClass == TUSB_CLASS_HID)\n\t\treturn hidd_open(rhport, itf, maxLen);",
    "\tif ((itf->bInterfaceNumber == 0 || itf->bInterfaceNumber == 2) &&\n\t    itf->bInterfaceClass == TUSB_CLASS_HID)\n\t\treturn hidd_open(rhport, itf, maxLen);",
    label="driver HID open",
)
sub(
    r"\n\t// Preserve the captured audio-control/streaming descriptor block as one\n\t// associated three-interface Nintendo function\. Audio data itself is not\n\t// synthesized by OpenPuck\.\n\tif \(itf->bInterfaceNumber == 2 &&\n\t    itf->bInterfaceClass == TUSB_CLASS_AUDIO\)\n\t\treturn maxLen;",
    "",
    label="remove audio open",
)
replace(
    "\tif (req->wIndex == 0)\n\t\treturn hidd_control_xfer_cb(rhport, stage, req);",
    "\tif (req->wIndex == 0 || req->wIndex == 2)\n\t\treturn hidd_control_xfer_cb(rhport, stage, req);",
    label="driver HID control",
)

P.write_text(s)
