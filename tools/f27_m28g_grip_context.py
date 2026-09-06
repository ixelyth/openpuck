#!/usr/bin/env python3
"""F27-M28G: preserve M27 JCR behavior while hardening session context and adding Switch 2 Charging Grip command 0x08."""

from pathlib import Path
import re

MODE = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M28G {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, repl: str, label: str) -> str:
    out, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"F27-M28G {label}: regex count {count}, expected 1")
    return out


src = MODE.read_text(encoding="utf-8")
for required in (
    "F27-M22-HIDDEN-JCR-LEFT-MOUSE",
    "F27-M25-IDENTITY-SWAP-JCR",
    "F27-M27-PROVEN-SESSION1-LEFT-JCR",
):
    if required not in src:
        raise SystemExit(f"F27-M28G requires M27 authority marker {required}")
for forbidden in (
    "F27-M23-JCR-JCL-LEFT-MOUSE",
    "F27-M24-ROLE-SWAP-JCR",
    "F27-M26-INPUT-PAYLOAD-SWAP-JCR",
    "F27-M28G-GRIP-CONTEXT",
):
    if forbidden in src:
        raise SystemExit(f"F27-M28G forbidden/already-applied marker present: {forbidden}")

src = replace_once(
    src,
    'static const char M27_BUILD_MARKER[] __attribute__((used)) =\n'
    '\t"F27-M27-PROVEN-SESSION1-LEFT-JCR";\n',
    'static const char M27_BUILD_MARKER[] __attribute__((used)) =\n'
    '\t"F27-M27-PROVEN-SESSION1-LEFT-JCR";\n'
    'static const char M28G_BUILD_MARKER[] __attribute__((used)) =\n'
    '\t"F27-M28G-GRIP-CONTEXT";\n',
    "build marker",
)

# Switch-2-specific Charging Grip information captured from real hardware in
# ndeadly/switch2_controller_research command 0x08. This is NOT Switch 1 data.
# The 64-byte grip factory block contains serial HDL50003485519 and PID 0x2068.
grip_impl = r'''
static bool g_m28GripButtonsEnabled[M15_SW2_SESSION_COUNT];
static const uint8_t M28G_CHARGING_GRIP_FACTORY[64] = {
	0x01, 0x00, 'H',  'D',  'L',  '5',  '0',  '0',  '0',  '3',  '4',
	'8',  '5',  '5',  '1',  '9',  0x00, 0x00, 0x7e, 0x05, 0x68, 0x20,
	0x01, 0x03, 0x01, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
};
static_assert(sizeof M28G_CHARGING_GRIP_FACTORY == 64,
	      "M28G Charging Grip factory block must remain 64 bytes");

static uint8_t m28HandleChargingGrip(const uint8_t *cmd, uint8_t n,
				     uint8_t *reply)
{
	uint8_t sub = cmd[3];
	// Observed Switch 2 USB replies use the 00/F8 ACK header for grip command 08.
	sw2AckHeader(reply, 0x08, cmd[2], sub);
	if (sub == 0x01 || sub == 0x03) {
		uint8_t requested = sub == 0x01 ? 0x20 : 0x40;
		memset(reply + 8, 0, 4);
		memcpy(reply + 12, M28G_CHARGING_GRIP_FACTORY, requested);
		return (uint8_t)(12 + requested);
	}
	if (sub == 0x02) {
		g_m28GripButtonsEnabled[g_sw2SessionCtx] = n >= 9 && cmd[8] != 0;
		return 8;
	}
	return 8;
}

'''
src = replace_once(
    src,
    "\nstatic void sw2BuildVendorReply(void)\n",
    "\n" + grip_impl + "static void sw2BuildVendorReply(void)\n",
    "Charging Grip implementation",
)

src = replace_once(
    src,
    "\tcase 0x07:\n\t\treplyLen = sw2QueueDataHeader(id, seq, sub, reply);\n",
    "\tcase 0x08:\n\t\treplyLen = m28HandleChargingGrip(cmd, n, reply);\n\t\tbreak;\n"
    "\tcase 0x07:\n\t\treplyLen = sw2QueueDataHeader(id, seq, sub, reply);\n",
    "Charging Grip command dispatch",
)

# M23 exposed that the dual-session class driver could return from a
# session-specific endpoint callback while g_sw2SessionCtx still named session1.
# Rebuild open/xfer routing so shared/device-level work always resumes in session0.
open_pattern = r'''static uint16_t sw2DriverOpen\(uint8_t rhport, tusb_desc_interface_t const \*itf,\n\s+uint16_t maxLen\)\n\{.*?\n\}\n\n(?=static bool sw2DriverControl)'''
open_repl = r'''static uint16_t m28DriverOpenCurrent(uint8_t rhport,
				     tusb_desc_interface_t const *itf,
				     uint16_t maxLen)
{
	uint8_t local = (uint8_t)(itf->bInterfaceNumber % 5u);
	if (local == 0 && itf->bInterfaceClass == TUSB_CLASS_HID)
		return hidd_open(rhport, itf, maxLen);

	if (local == 1 && itf->bInterfaceClass == 0xff) {
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

	if (local == 2 && itf->bInterfaceClass == TUSB_CLASS_AUDIO)
		return maxLen;
	return 0;
}

static uint16_t sw2DriverOpen(uint8_t rhport, tusb_desc_interface_t const *itf,
			      uint16_t maxLen)
{
	if (g_usbMode != MODE_SW2_PRO)
		return 0;
	g_sw2Rhport = rhport;
	uint8_t s = (uint8_t)(itf->bInterfaceNumber / 5u);
	if (s >= M15_SW2_SESSION_COUNT)
		return 0;
	g_sw2SessionCtx = s;
	uint16_t result = m28DriverOpenCurrent(rhport, itf, maxLen);
	g_sw2SessionCtx = M15_SW2_PRO;
	return result;
}

'''
src = regex_once(src, open_pattern, open_repl, "session-safe driver open")

xfer_pattern = r'''static bool sw2DriverXfer\(uint8_t rhport, uint8_t ep, xfer_result_t result,\n\s+uint32_t transferred\)\n\{.*?\n\}\n\n(?=static const usbd_class_driver_t g_sw2Driver)'''
xfer_repl = r'''static bool sw2DriverXfer(uint8_t rhport, uint8_t ep, xfer_result_t result,
			  uint32_t transferred)
{
	for (uint8_t s = 0; s < M15_SW2_SESSION_COUNT; s++) {
		if (ep == g_sw2Sessions[s].vendorEpOut) {
			g_sw2SessionCtx = s;
			if (result == XFER_RESULT_SUCCESS) {
				g_sw2VendorCommandLen =
					(uint8_t)(transferred > 64 ? 64 : transferred);
				g_sw2VendorCommandPending = true;
			}
			g_sw2SessionCtx = M15_SW2_PRO;
			return true;
		}
		if (ep == g_sw2Sessions[s].vendorEpIn) {
			g_sw2SessionCtx = s;
			if (result == XFER_RESULT_SUCCESS && g_sw2VendorReplyLen > 64) {
				uint8_t tail = g_sw2VendorReplyLen - 64;
				g_sw2VendorReplyLen = tail;
				bool queued = usbd_edpt_xfer(rhport, g_sw2VendorEpIn,
							     g_sw2VendorOut, tail);
				g_sw2SessionCtx = M15_SW2_PRO;
				return queued;
			}
			g_sw2VendorReplyLen = 0;
			g_sw2VendorInFlight = false;
			bool armed = usbd_edpt_xfer(rhport, g_sw2VendorEpOut,
						   g_sw2VendorOut,
						   sizeof g_sw2VendorOut);
			g_sw2SessionCtx = M15_SW2_PRO;
			return armed;
		}
	}
	g_sw2SessionCtx = M15_SW2_PRO;
	return hidd_xfer_cb(rhport, ep, result, transferred);
}

'''
src = regex_once(src, xfer_pattern, xfer_repl, "session-safe driver xfer")

src = replace_once(
    src,
    "\t\tg_sw2LastRumbleRight = 0;\n\t}\n\tg_sw2SessionCtx = M15_SW2_PRO;\n}",
    "\t\tg_sw2LastRumbleRight = 0;\n"
    "\t\tg_m28GripButtonsEnabled[s] = false;\n"
    "\t}\n\tg_sw2SessionCtx = M15_SW2_PRO;\n}",
    "grip state reset",
)

src = replace_once(
    src,
    '\tasm volatile("" : : "r"(M27_BUILD_MARKER) : "memory");\n',
    '\tasm volatile("" : : "r"(M27_BUILD_MARKER) : "memory");\n'
    '\tasm volatile("" : : "r"(M28G_BUILD_MARKER) : "memory");\n',
    "retain marker",
)

MODE.write_text(src, encoding="utf-8")
print("F27-M28G M27-preserving Switch 2 Charging Grip context probe applied")
