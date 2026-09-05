#!/usr/bin/env python3
from pathlib import Path
import argparse
import re

ap = argparse.ArgumentParser()
ap.add_argument("--paths", type=int, choices=(4, 6), required=True)
args = ap.parse_args()
N = args.paths

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
    f"// mode_switch2_pro.cpp -- Nintendo Switch 2 Pro Controller (057E:2069).\n//\n// {N}-controller hardware discriminator derived from PR #269. Device identity,\n// HID report format, vendor protocol and pairing behavior remain the PR #269\n// implementation. Nintendo audio interfaces are intentionally omitted to free\n// endpoint budget; {N} Pro2 HID paths share one device-level vendor session.\n// Native 0x09 motion packing remains undocumented, so motion behavior is unchanged.\n",
    label="header",
)

# Configuration body: N independent Pro2 HID interfaces followed by one shared
# Nintendo vendor interface. Every HID keeps the exact PR #269 97-byte report
# descriptor and a full interrupt IN/OUT pair. Audio is intentionally absent.
body = []
for i in range(N):
    body += [0x08, 0x0B, i, 0x01, 0x03, 0x00, 0x00, 0x00]
    body += [0x09, 0x04, i, 0x00, 0x02, 0x03, 0x00, 0x00, 0x05]
    body += [0x09, 0x21, 0x11, 0x01, 0x00, 0x01, 0x22, 0x61, 0x00]
    body += [0x07, 0x05, 0x81 + i, 0x03, 0x40, 0x00, 0x04]
    body += [0x07, 0x05, 0x01 + i, 0x03, 0x40, 0x00, 0x04]
vendor_if = N
vendor_ep = N + 1
body += [0x08, 0x0B, vendor_if, 0x01, 0xFF, 0x00, 0x00, 0x00]
body += [0x09, 0x04, vendor_if, 0x00, 0x02, 0xFF, 0x00, 0x00, 0x06]
body += [0x07, 0x05, vendor_ep, 0x02, 0x40, 0x00, 0x00]
body += [0x07, 0x05, 0x80 | vendor_ep, 0x02, 0x40, 0x00, 0x00]
expected_cfg = N * 40 + 31
assert len(body) == expected_cfg
rows = []
for off in range(0, len(body), 12):
    rows.append("\t" + ", ".join(f"0x{x:02x}" for x in body[off:off+12]) + ",")
new_cfg = f"""// Diagnostic configuration body after the 9-byte configuration header.\n// IF0..IF{N-1} are independent Pro2 HID paths; IF{vendor_if} is one shared Nintendo vendor\n// session. The captured Nintendo audio interfaces are intentionally omitted.\nstatic const uint8_t SWITCH2_PRO_CFG_BODY[] = {{\n{"\n".join(rows)}\n}};\nstatic_assert(sizeof SWITCH2_PRO_CFG_BODY == {expected_cfg},\n\t      \"Switch 2 Pro multiselect configuration body must remain exact\");"""
sub(
    r"// Everything after the 9-byte configuration header\..*?static_assert\(sizeof SWITCH2_PRO_CFG_BODY == 259,\n\s*\"Switch 2 Pro configuration body must remain byte-exact\"\);",
    new_cfg,
    flags=re.S,
    label="configuration body",
)

replace(
    "static unsigned long g_sw2LastReportMs = 0;",
    f"static unsigned long g_sw2LastReportMs[{N}] = {{ 0 }};\n"
    f"static uint8_t g_sw2HidCounter8[{N}] = {{ 0 }};\n"
    f"static uint32_t g_sw2HidCounter32[{N}] = {{ 0 }};",
    label="per-HID state",
)

old_alloc = """\t\tuint8_t first = TinyUSBDevice.allocInterface(5);\n\t\tuint8_t hidIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tuint8_t hidOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t vendorOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t vendorIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tuint8_t audioOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t audioIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tif (first != 0 || hidIn != 0x81 || hidOut != 0x01 ||\n\t\t    vendorOut != 0x02 || vendorIn != 0x82 || audioOut != 0x03 ||\n\t\t    audioIn != 0x83)\n\t\t\treturn 0;\n"""
new_alloc = f"""\t\tuint8_t first = TinyUSBDevice.allocInterface({N + 1});\n\t\tuint8_t hidIn[{N}], hidOut[{N}];\n\t\tfor (uint8_t i = 0; i < {N}; i++) {{\n\t\t\thidIn[i] = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\t\thidOut[i] = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\t}}\n\t\tuint8_t vendorOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);\n\t\tuint8_t vendorIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);\n\t\tif (first != 0)\n\t\t\treturn 0;\n\t\tfor (uint8_t i = 0; i < {N}; i++)\n\t\t\tif (hidIn[i] != (uint8_t)(0x81 + i) ||\n\t\t\t    hidOut[i] != (uint8_t)(0x01 + i))\n\t\t\t\treturn 0;\n\t\tif (vendorOut != 0x{vendor_ep:02x} || vendorIn != 0x{0x80 | vendor_ep:02x})\n\t\t\treturn 0;\n"""
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

if N == 4:
    select_logic = """\tstatic const uint32_t selector[4] = { TB_L4, TB_R4, TB_L5, TB_R5 };\n\tuint32_t held = g_in[bond].buttons & CHORD_BACK4;\n\tfor (uint8_t i = 0; i < 4; i++) {\n\t\tif (held == selector[i]) {\n\t\t\tif (suppress)\n\t\t\t\t*suppress = selector[i];\n\t\t\treturn (int)i;\n\t\t}\n\t}\n"""
else:
    select_logic = """\tstatic const uint32_t selector[6] = {\n\t\tTB_L4, TB_R4, TB_L5, TB_R5,\n\t\t(uint32_t)(TB_L4 | TB_L5), (uint32_t)(TB_R4 | TB_R5)\n\t};\n\tuint32_t held = g_in[bond].buttons & CHORD_BACK4;\n\tfor (uint8_t i = 0; i < 6; i++) {\n\t\tif (held == selector[i]) {\n\t\t\tif (suppress)\n\t\t\t\t*suppress = selector[i];\n\t\t\treturn (int)i;\n\t\t}\n\t}\n"""

helpers = f'''
static int sw2MultiSelectHid(uint8_t bond, uint32_t *suppress)
{{
\tif (suppress)
\t\t*suppress = 0;
\tif (bond >= NSLOT)
\t\treturn -1;
{select_logic}\treturn -1;
}}

static void sw2StampHidCounter(uint8_t hid, uint8_t reportId, uint8_t out[63])
{{
\tif (reportId == 0x05) {{
\t\tuint32_t counter = g_sw2HidCounter32[hid]++;
\t\tmemcpy(out, &counter, sizeof counter);
\t}} else {{
\t\tout[0] = g_sw2HidCounter8[hid]++;
\t}}
}}

static void sw2BuildNeutral09(uint8_t hid, uint8_t bond, uint8_t out[63])
{{
\tmemset(out, 0, 63);
\tout[1] = sw2PowerInfo(bond);
\tsw2PackStick(out + 5, 0, 0);
\tsw2PackStick(out + 8, 0, 0);
\tout[0x0b] = (g_sw2Features & (1u << 5)) ? 0x38 : 0x30;
\tout[0x0e] = 0;
\tsw2StampHidCounter(hid, 0x09, out);
}}

static void sw2BuildNeutral05(uint8_t hid, uint8_t out[63])
{{
\tmemset(out, 0, 63);
\tsw2PackStick(out + 0x0a, 0, 0);
\tsw2PackStick(out + 0x0d, 0, 0);
\tout[0x1f] = 0xd8;
\tout[0x20] = 0x0e;
\tout[0x21] = 0x34;
\tout[0x29] = 0x01;
\tuint32_t ts = micros();
\tmemcpy(out + 0x2a, &ts, sizeof ts);
\tsw2StampHidCounter(hid, 0x05, out);
}}

static bool sw2BuildForHid(uint8_t hid, uint8_t bond, uint8_t reportId,
\t\t\t   uint8_t out[63])
{{
\tuint32_t suppress = 0;
\tint selected = sw2MultiSelectHid(bond, &suppress);
\tbool active = selected == (int)hid;
\tif (reportId == 0x05) {{
\t\tif (active) {{
\t\t\tsw2Build05(bond, suppress, out);
\t\t\tsw2StampHidCounter(hid, 0x05, out);
\t\t}} else {{
\t\t\tsw2BuildNeutral05(hid, out);
\t\t}}
\t\treturn true;
\t}}
\tif (reportId == 0x09) {{
\t\tif (active) {{
\t\t\tsw2Build09(bond, suppress, out);
\t\t\tsw2StampHidCounter(hid, 0x09, out);
\t\t}} else {{
\t\t\tsw2BuildNeutral09(hid, bond, out);
\t\t}}
\t\treturn true;
\t}}
\treturn false;
}}
'''
replace("\nstatic void sw2AckHeader", helpers + "\nstatic void sw2AckHeader", label="multiselect helpers")

new_drain = f'''static void sw2Drain(void)
{{
\tif (g_usbMode != MODE_SW2_PRO || g_usbMountCount == 0)
\t\treturn;

\tif (g_sw2VendorCommandPending && !g_sw2VendorInFlight) {{
\t\tsw2BuildVendorReply();
\t\tuint8_t n = g_sw2VendorReplyLen;
\t\tuint8_t first = n > sizeof g_sw2VendorReply ?
\t\t\t\tsizeof g_sw2VendorReply :
\t\t\t\tn;
\t\tif (first && g_sw2VendorEpIn &&
\t\t    usbd_edpt_xfer(g_sw2Rhport, g_sw2VendorEpIn,
\t\t\t\t   g_sw2VendorReply, first))
\t\t\tg_sw2VendorInFlight = true;
\t}}

\tif (!g_sw2InputEnabled)
\t\treturn;
\tint bond = g_usbToBond[0];
\tif (bond < 0 || bond >= NSLOT)
\t\treturn;
\tuint8_t rid = g_sw2ActiveReport == 0x05 ? 0x05 : 0x09;
\tfor (uint8_t hid = 0; hid < {N}; hid++) {{
\t\tif (!tud_hid_n_ready(hid))
\t\t\tcontinue;
\t\tif ((uint32_t)(millis() - g_sw2LastReportMs[hid]) < USB_STREAM_MS)
\t\t\tcontinue;
\t\tuint8_t p[63];
\t\tif (!sw2BuildForHid(hid, (uint8_t)bond, rid, p))
\t\t\tcontinue;
\t\tif (tud_hid_n_report(hid, rid, p, sizeof p))
\t\t\tg_sw2LastReportMs[hid] = millis();
\t}}
}}'''
sub(
    r"static void sw2Drain\(void\)\n\{.*?\n\}\n\nbool switch2ProVendorControlXfer",
    new_drain + "\n\nbool switch2ProVendorControlXfer",
    flags=re.S,
    label="drain",
)

replace(
    "if (g_usbMode == MODE_SW2_PRO && itf == 0)\n\t\treturn SWITCH2_PRO_HID_DESC;",
    f"if (g_usbMode == MODE_SW2_PRO && itf < {N})\n\t\treturn SWITCH2_PRO_HID_DESC;",
    label="report descriptor callback",
)

new_get = f'''extern "C" uint16_t __wrap_tud_hid_get_report_cb(uint8_t itf, uint8_t reportId,
\t\t\t\t\t\t hid_report_type_t reportType,
\t\t\t\t\t\t uint8_t *buffer,
\t\t\t\t\t\t uint16_t reqLen)
{{
\tif (g_usbMode != MODE_SW2_PRO || itf >= {N})
\t\treturn __real_tud_hid_get_report_cb(itf, reportId, reportType,
\t\t\t\t\t\t    buffer, reqLen);
\t(void)reportType;
\tif (!buffer || !reqLen || (reportId != 0x05 && reportId != 0x09))
\t\treturn 0;
\tuint8_t p[63];
\tint bond = g_usbMountCount ? g_usbToBond[0] : -1;
\tif (bond >= 0 && bond < NSLOT) {{
\t\tif (!sw2BuildForHid(itf, (uint8_t)bond, reportId, p))
\t\t\treturn 0;
\t}} else if (reportId == 0x05) {{
\t\tsw2BuildNeutral05(itf, p);
\t}} else {{
\t\tsw2BuildNeutral09(itf, 0, p);
\t}}
\tuint16_t n = reqLen < sizeof p ? reqLen : sizeof p;
\tmemcpy(buffer, p, n);
\treturn n;
}}'''
sub(
    r'extern "C" uint16_t __wrap_tud_hid_get_report_cb\(uint8_t itf, uint8_t reportId,.*?\n\}\n\n// Switch 2 Pro output report',
    new_get + "\n\n// Switch 2 Pro output report",
    flags=re.S,
    label="get report wrapper",
)

replace(
    "if (g_usbMode == MODE_SW2_PRO && itf == 0) {",
    f"if (g_usbMode == MODE_SW2_PRO && itf < {N}) {{",
    label="set report wrapper",
)
replace(
    "if (itf->bInterfaceNumber == 0 &&\n\t    itf->bInterfaceClass == TUSB_CLASS_HID)",
    f"if (itf->bInterfaceNumber < {N} &&\n\t    itf->bInterfaceClass == TUSB_CLASS_HID)",
    label="driver HID open",
)
replace(
    "if (itf->bInterfaceNumber == 1 && itf->bInterfaceClass == 0xff) {",
    f"if (itf->bInterfaceNumber == {vendor_if} && itf->bInterfaceClass == 0xff) {{",
    label="driver vendor open",
)
sub(
    r"\n\t// Preserve the captured audio-control/streaming descriptor block as one\n\t// associated three-interface Nintendo function\. Audio data itself is not\n\t// synthesized by OpenPuck\.\n\tif \(itf->bInterfaceNumber == 2 &&\n\t    itf->bInterfaceClass == TUSB_CLASS_AUDIO\)\n\t\treturn maxLen;",
    "",
    label="remove audio driver path",
)
replace(
    "if (req->wIndex == 0)\n\t\treturn hidd_control_xfer_cb(rhport, stage, req);",
    f"if (req->wIndex < {N})\n\t\treturn hidd_control_xfer_cb(rhport, stage, req);",
    label="driver HID control",
)

# Keep maxSlots() == 1: one real RF bond feeds N host-side HID paths. This is a
# host-topology discriminator, not a production multi-RF implementation.

for forbidden in [
    "tud_hid_n_ready(0)",
    "tud_hid_n_report(0, rid",
    "g_sw2LastReportMs =",
    "TUSB_CLASS_AUDIO",
]:
    if forbidden in s:
        raise SystemExit(f"stale single-controller/audio anchor remains: {forbidden}")

for required in [
    f"sizeof SWITCH2_PRO_CFG_BODY == {expected_cfg}",
    f"vendorOut != 0x{vendor_ep:02x} || vendorIn != 0x{0x80 | vendor_ep:02x}",
    f"itf->bInterfaceNumber < {N}",
    f"itf->bInterfaceNumber == {vendor_if}",
    "sw2MultiSelectHid",
    "sw2StampHidCounter",
    "tud_hid_n_report(hid, rid",
]:
    if required not in s:
        raise SystemExit(f"required diagnostic anchor missing: {required}")

P.write_text(s)
