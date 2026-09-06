#!/usr/bin/env python3
"""Add one inert Pro2-shaped Nintendo vendor function over exact r396 HORIPAD O FourSelect."""
from pathlib import Path

CPP = Path("OpenPuck/mode_switch_hori.cpp")
HDR = Path("OpenPuck/usb_app_drivers.h")
REG = Path("OpenPuck/usb_app_drivers.cpp")


def repl(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"r398 {label}: anchor count {n}, expected 1")
    return s.replace(old, new, 1)


s = CPP.read_text(encoding="utf-8")
for needle in (
    "USBDevice.setID(0x0F0D, 0x0202);",
    'USBDevice.setProductDescriptor("HORIPAD O");',
    "sizeof SWITCH_HID_DESC == 123",
    "TB_L4, TB_R4, TB_L5, TB_R5",
    "H4_TRACE_MAGIC = 0x36393448UL",
    "source=Switch2-HORIPAD-O-FourSelect-r396-raw",
    "usbTxHid(&g_switch[u], 0, p, 8)",
):
    if needle not in s:
        raise SystemExit(f"r398 missing exact r396 contract: {needle}")

s = repl(
    s,
    '#include "usb_tx.h"\n',
    '#include "usb_tx.h"\n#include "usb_app_drivers.h"\n',
    "custom-driver include",
)

vendor_block = r'''
// r398 admission-threshold probe: preserve the exact r396 HORIPAD O HID
// personality and append only one inert Nintendo/Pro2-shaped vendor function.
// It has the captured Pro2 IAD + FF/00/00 bulk-IN/bulk-OUT descriptor shape and
// interface string, but deliberately implements NO Nintendo commands, identity
// control replies, report selection, feature negotiation, pairing, or input.
static volatile uint8_t g_h4VendorItf = 0xff;
static volatile uint8_t g_h4VendorEpOut = 0;
static volatile uint8_t g_h4VendorEpIn = 0;
static volatile uint8_t g_h4VendorRhport = 0;
static uint8_t g_h4VendorSink[64];

class H4NintendoVendorInterface : public Adafruit_USBD_Interface {
    public:
	uint16_t getInterfaceDescriptor(uint8_t, uint8_t *buf,
					uint16_t bufsize) override
	{
		static constexpr uint16_t LEN = 31;
		if (!buf)
			return LEN;
		if (bufsize < LEN)
			return 0;
		uint8_t itf = TinyUSBDevice.allocInterface(1);
		uint8_t epOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
		uint8_t epIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		if (itf == 0xff || !epOut || !epIn)
			return 0;
		uint8_t str = TinyUSBDevice.addStringDescriptor("Switch 2 Pro Controller");
		if (!str)
			return 0;
		uint8_t d[LEN] = {
			0x08, 0x0b, itf, 0x01, 0xff, 0x00, 0x00, 0x00,
			0x09, 0x04, itf, 0x00, 0x02, 0xff, 0x00, 0x00, str,
			0x07, 0x05, epOut, 0x02, 0x40, 0x00, 0x00,
			0x07, 0x05, epIn, 0x02, 0x40, 0x00, 0x00,
		};
		memcpy(buf, d, LEN);
		g_h4VendorItf = itf;
		g_h4VendorEpOut = epOut;
		g_h4VendorEpIn = epIn;
		return LEN;
	}
};
static H4NintendoVendorInterface g_h4NintendoVendor;

static void h4VendorDriverInit()
{
	g_h4VendorRhport = 0;
}
static bool h4VendorDriverDeinit()
{
	return true;
}
static void h4VendorDriverReset(uint8_t rhport)
{
	(void)rhport;
	g_h4VendorRhport = 0;
}
static uint16_t h4VendorDriverOpen(uint8_t rhport,
				  tusb_desc_interface_t const *itf,
				  uint16_t maxLen)
{
	if (g_usbMode != MODE_SW_HORI || itf->bInterfaceNumber != g_h4VendorItf ||
	    itf->bInterfaceClass != 0xff)
		return 0;
	g_h4VendorRhport = rhport;
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
			opened++;
		}
		used += len;
		p += len;
	}
	if (opened != 2 || !g_h4VendorEpOut || !g_h4VendorEpIn)
		return 0;
	if (!usbd_edpt_xfer(rhport, g_h4VendorEpOut, g_h4VendorSink,
			    sizeof g_h4VendorSink))
		return 0;
	h4TraceAppend(0xff, 4, true, (int)g_h4VendorItf);
	return used;
}
static bool h4VendorDriverControl(uint8_t rhport, uint8_t stage,
				  tusb_control_request_t const *request)
{
	(void)rhport;
	(void)stage;
	(void)request;
	return false; // intentionally no Nintendo control-handshake implementation
}
static bool h4VendorDriverXfer(uint8_t rhport, uint8_t ep,
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
static const usbd_class_driver_t g_h4VendorDriver = {
#if CFG_TUSB_DEBUG >= 2
	.name = "H4-R398-VENDOR",
#endif
	.init = h4VendorDriverInit,
	.deinit = h4VendorDriverDeinit,
	.reset = h4VendorDriverReset,
	.open = h4VendorDriverOpen,
	.control_xfer_cb = h4VendorDriverControl,
	.xfer_cb = h4VendorDriverXfer,
	.sof = nullptr,
};
const usbd_class_driver_t *switchHoriInertVendorClassDriver(void)
{
	return &g_h4VendorDriver;
}

'''

# Place the vendor function after the r396 trace helpers so driver-open can log
# through the same persistent raw trace without changing HORIPAD task behavior.
s = repl(
    s,
    "void SwitchHoriController::task()\n{",
    vendor_block + "void SwitchHoriController::task()\n{",
    "vendor block insertion",
)

# Extend the trace format only enough to persist the vendor-interface open event.
s = repl(
    s,
    '''\tif (hid >= 4 || phase < 1 || phase > 3)\n\t\treturn;\n\tuint16_t bit = (uint16_t)(1u << (hid * 3u + phase - 1u));\n''',
    '''\tif (phase == 4 && hid == 0xff) {\n\t\tif (g_h4Seen & 0x8000u)\n\t\t\treturn;\n\t\tg_h4Seen |= 0x8000u;\n\t} else {\n\t\tif (hid >= 4 || phase < 1 || phase > 3)\n\t\t\treturn;\n\t\tuint16_t bit = (uint16_t)(1u << (hid * 3u + phase - 1u));\n\t\tif (g_h4Seen & bit)\n\t\t\treturn;\n\t\tg_h4Seen |= bit;\n\t}\n\tuint16_t bit = 0; // retained only to keep the old observer body structurally narrow\n''',
    "trace special-event gate",
)
s = repl(
    s,
    '''\tif (g_h4Seen & bit)\n\t\treturn;\n\tg_h4Seen |= bit;\n\tif (g_h4TraceCount >= 32)\n''',
    '''\t(void)bit;\n\tif (g_h4TraceCount >= 32)\n''',
    "trace old seen body",
)

s = repl(s, "H4_TRACE_MAGIC = 0x36393448UL", "H4_TRACE_MAGIC = 0x38393448UL",
         "trace magic")
s = repl(
    s,
    "source=Switch2-HORIPAD-O-FourSelect-r396-raw",
    "source=Switch2-HORIPAD-O-FourSelect-r398-inertvendor",
    "trace source",
)

# Dump vendor-open records distinctly; the existing 8-byte record layout is unchanged.
old_dump = '''\tfor (uint32_t i = 0; i < count; i++)\n\t\tSerial.printf("# JT %lu I t=%lu hid=%u phase=%u ready=%u selected=%d\\n",\n\t\t\t      (unsigned long)i, (unsigned long)r[i].ms, r[i].hid,\n\t\t\t      r[i].phase, r[i].ready, r[i].selected);\n'''
new_dump = '''\tfor (uint32_t i = 0; i < count; i++) {\n\t\tif (r[i].phase == 4 && r[i].hid == 0xff)\n\t\t\tSerial.printf("# JT %lu V t=%lu opened=1 itf=%d\\n",\n\t\t\t\t      (unsigned long)i, (unsigned long)r[i].ms,\n\t\t\t\t      r[i].selected);\n\t\telse\n\t\t\tSerial.printf("# JT %lu I t=%lu hid=%u phase=%u ready=%u selected=%d\\n",\n\t\t\t\t      (unsigned long)i, (unsigned long)r[i].ms, r[i].hid,\n\t\t\t\t      r[i].phase, r[i].ready, r[i].selected);\n\t}\n'''
s = repl(s, old_dump, new_dump, "trace dump")

old_mount = '''void SwitchHoriController::mountSlots(uint8_t k)\n{\n\t(void)k;\n\tfor (uint8_t u = 0; u < maxSlots(); u++)\n\t\tUSBDevice.addInterface(g_switch[u]);\n}\n'''
new_mount = '''void SwitchHoriController::mountSlots(uint8_t k)\n{\n\t(void)k;\n\tfor (uint8_t u = 0; u < maxSlots(); u++)\n\t\tUSBDevice.addInterface(g_switch[u]);\n\tUSBDevice.addInterface(g_h4NintendoVendor);\n}\n'''
s = repl(s, old_mount, new_mount, "append inert vendor interface")
CPP.write_text(s, encoding="utf-8")

h = HDR.read_text(encoding="utf-8")
if "switchHoriInertVendorClassDriver" in h:
    raise SystemExit("r398 driver declaration already present")
h += "\n// r398 HORIPAD O admission-threshold diagnostic driver.\nconst usbd_class_driver_t *switchHoriInertVendorClassDriver(void);\n"
HDR.write_text(h, encoding="utf-8")

reg = REG.read_text(encoding="utf-8")
reg = repl(
    reg,
    '''\t\t*xboxOgClassDriver(),\n''',
    '''\t\t*xboxOgClassDriver(),\n\t\t*switchHoriInertVendorClassDriver(),\n''',
    "app-driver registration",
)
REG.write_text(reg, encoding="utf-8")

out = CPP.read_text(encoding="utf-8")
for needle in (
    "USBDevice.setID(0x0F0D, 0x0202);",
    'USBDevice.setProductDescriptor("HORIPAD O");',
    "sizeof SWITCH_HID_DESC == 123",
    "usbTxHid(&g_switch[u], 0, p, 8)",
    "Switch 2 Pro Controller",
    "switchHoriInertVendorClassDriver",
    "H4_TRACE_MAGIC = 0x38393448UL",
    "source=Switch2-HORIPAD-O-FourSelect-r398-inertvendor",
):
    if needle not in out and needle not in HDR.read_text() and needle not in REG.read_text():
        raise SystemExit(f"r398 missing output contract: {needle}")
print("r398 exact r396 HORIPAD O FourSelect + inert Nintendo vendor descriptor shell applied")
