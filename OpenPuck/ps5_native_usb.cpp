// ps5_native_usb.cpp -- experimental exact wired DualSense composite.
//
// The physical 054C:0CE6 controller is a four-interface USB device:
// UAC1 control, speaker/haptic OUT, microphone IN, then HID. Fortnite
// rejects the older single-HID approximation even though Windows and
// DS4Windows accept it, so this POC reproduces the captured device and
// configuration descriptors while reusing OpenPuck's existing reports.
#include "ps5_native_usb.h"
#include "config.h"
#include "usb_tx.h"
#include <Arduino.h>
#include <string.h>

extern "C" {
#include "class/hid/hid_device.h"
#include "device/usbd_pvt.h"
}

static const uint8_t PS5_NATIVE_DEVICE_DESC[18] = {
	0x12, 0x01, 0x00, 0x02, 0x00, 0x00, 0x00, 0x40, 0x4c,
	0x05, 0xe6, 0x0c, 0x00, 0x01, 0x01, 0x02, 0x00, 0x01,
};

// Exact real-controller configuration descriptor after the 9-byte
// configuration header (wTotalLength=227, bNumInterfaces=4).
static const uint8_t PS5_NATIVE_CFG_BODY[] = {
	0x09, 0x04, 0x00, 0x00, 0x00, 0x01, 0x01, 0x00, 0x00, 0x0a, 0x24, 0x01,
	0x00, 0x01, 0x49, 0x00, 0x02, 0x01, 0x02, 0x0c, 0x24, 0x02, 0x01, 0x01,
	0x01, 0x06, 0x04, 0x33, 0x00, 0x00, 0x00, 0x0c, 0x24, 0x06, 0x02, 0x01,
	0x01, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x24, 0x03, 0x03, 0x01,
	0x03, 0x04, 0x02, 0x00, 0x0c, 0x24, 0x02, 0x04, 0x02, 0x04, 0x03, 0x02,
	0x03, 0x00, 0x00, 0x00, 0x09, 0x24, 0x06, 0x05, 0x04, 0x01, 0x03, 0x00,
	0x00, 0x09, 0x24, 0x03, 0x06, 0x01, 0x01, 0x01, 0x05, 0x00, 0x09, 0x04,
	0x01, 0x00, 0x00, 0x01, 0x02, 0x00, 0x00, 0x09, 0x04, 0x01, 0x01, 0x01,
	0x01, 0x02, 0x00, 0x00, 0x07, 0x24, 0x01, 0x01, 0x01, 0x01, 0x00, 0x0b,
	0x24, 0x02, 0x01, 0x04, 0x02, 0x10, 0x01, 0x80, 0xbb, 0x00, 0x09, 0x05,
	0x01, 0x09, 0x88, 0x01, 0x04, 0x00, 0x00, 0x07, 0x25, 0x01, 0x00, 0x00,
	0x00, 0x00, 0x09, 0x04, 0x02, 0x00, 0x00, 0x01, 0x02, 0x00, 0x00, 0x09,
	0x04, 0x02, 0x01, 0x01, 0x01, 0x02, 0x00, 0x00, 0x07, 0x24, 0x01, 0x06,
	0x01, 0x01, 0x00, 0x0b, 0x24, 0x02, 0x01, 0x02, 0x02, 0x10, 0x01, 0x80,
	0xbb, 0x00, 0x09, 0x05, 0x82, 0x05, 0xc4, 0x00, 0x04, 0x00, 0x00, 0x07,
	0x25, 0x01, 0x00, 0x00, 0x00, 0x00, 0x09, 0x04, 0x03, 0x00, 0x02, 0x03,
	0x00, 0x00, 0x00, 0x09, 0x21, 0x11, 0x01, 0x00, 0x01, 0x22, 0x11, 0x01,
	0x07, 0x05, 0x84, 0x03, 0x40, 0x00, 0x06, 0x07, 0x05, 0x03, 0x03, 0x40,
	0x00, 0x06,
};
static_assert(sizeof PS5_NATIVE_CFG_BODY == 218,
	      "DualSense configuration body must remain byte-exact");

static uint8_t g_ps5AudioAlt[3];
static uint8_t g_ps5AudioControl[2];
static uint8_t g_ps5AudioOut[392];
static uint8_t g_ps5AudioIn[196];
static uint8_t g_ps5NativeRhport;
static bool g_ps5AudioOutOpen;
static bool g_ps5AudioInOpen;
static bool g_ps5NativeDrainRegistered;
static unsigned long g_ps5NativeLastMs;

// Full UAC endpoint descriptors. usbd_edpt_open() consumes the standard
// endpoint prefix and tolerates the two audio-specific trailing bytes.
static const uint8_t PS5_AUDIO_OUT_EP[] = {
	0x09, 0x05, 0x01, 0x09, 0x88, 0x01, 0x04, 0x00, 0x00,
};
static const uint8_t PS5_AUDIO_IN_EP[] = {
	0x09, 0x05, 0x82, 0x05, 0xc4, 0x00, 0x04, 0x00, 0x00,
};

class Ps5NativeUsbInterface : public Adafruit_USBD_Interface {
    public:
	uint16_t getInterfaceDescriptor(uint8_t, uint8_t *buf,
					uint16_t bufsize) override
	{
		if (!buf)
			return sizeof PS5_NATIVE_CFG_BODY;
		if (bufsize < sizeof PS5_NATIVE_CFG_BODY)
			return 0;

		uint8_t first = TinyUSBDevice.allocInterface(4);
		uint8_t audioOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
		uint8_t reserveOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
		uint8_t hidOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
		uint8_t reserveIn1 = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		uint8_t audioIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		uint8_t reserveIn3 = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		uint8_t hidIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		(void)reserveOut;
		(void)reserveIn1;
		(void)reserveIn3;
		if (first != 0 || audioOut != 0x01 || hidOut != 0x03 ||
		    audioIn != 0x82 || hidIn != 0x84)
			return 0;
		memcpy(buf, PS5_NATIVE_CFG_BODY, sizeof PS5_NATIVE_CFG_BODY);
		return sizeof PS5_NATIVE_CFG_BODY;
	}
};
static Ps5NativeUsbInterface g_ps5NativeUsb;

static void ps5NativeAudioOpen(uint8_t interfaceNumber, uint8_t alt)
{
	if (interfaceNumber >= 3)
		return;
	g_ps5AudioAlt[interfaceNumber] = alt;
	if (alt != 1)
		return;

	if (interfaceNumber == 1 && !g_ps5AudioOutOpen) {
		auto ep = (tusb_desc_endpoint_t const *)PS5_AUDIO_OUT_EP;
		if (usbd_edpt_open(g_ps5NativeRhport, ep)) {
			g_ps5AudioOutOpen = true;
			usbd_edpt_xfer(g_ps5NativeRhport, 0x01, g_ps5AudioOut,
				       sizeof g_ps5AudioOut);
		}
	} else if (interfaceNumber == 2 && !g_ps5AudioInOpen) {
		auto ep = (tusb_desc_endpoint_t const *)PS5_AUDIO_IN_EP;
		if (usbd_edpt_open(g_ps5NativeRhport, ep)) {
			g_ps5AudioInOpen = true;
			memset(g_ps5AudioIn, 0, sizeof g_ps5AudioIn);
			usbd_edpt_xfer(g_ps5NativeRhport, 0x82, g_ps5AudioIn,
				       sizeof g_ps5AudioIn);
		}
	}
}

static int16_t ps5AudioValue(uint8_t entity, uint8_t request)
{
	if (entity == 2) {
		switch (request) {
		case 0x81:
		case 0x82:
			return -25600;
		case 0x83:
			return 0;
		case 0x84:
			return 256;
		default:
			return 0;
		}
	}
	if (entity == 5) {
		switch (request) {
		case 0x81:
			return 3809;
		case 0x82:
			return 0;
		case 0x83:
			return 12288;
		case 0x84:
			return 122;
		default:
			return 0;
		}
	}
	return 0;
}

static bool ps5NativeAudioControl(uint8_t rhport, uint8_t stage,
				  tusb_control_request_t const *req)
{
	if (stage != CONTROL_STAGE_SETUP)
		return true;
	uint8_t interfaceNumber = (uint8_t)req->wIndex;

	if (req->bmRequestType == 0x81 && req->bRequest == 0x0a &&
	    interfaceNumber < 3) {
		g_ps5AudioControl[0] = g_ps5AudioAlt[interfaceNumber];
		return tud_control_xfer(rhport, req, g_ps5AudioControl, 1);
	}
	if (req->bmRequestType == 0x01 && req->bRequest == 0x0b &&
	    interfaceNumber < 3) {
		ps5NativeAudioOpen(interfaceNumber, (uint8_t)req->wValue);
		return tud_control_status(rhport, req);
	}

	// UAC1 mixer controls. Windows asks these while binding the real
	// device; answer the captured speaker/microphone ranges rather than
	// stalling the whole composite device.
	if ((req->bmRequestType & 0x60u) == 0x20u) {
		bool input = (req->bmRequestType & 0x80u) != 0;
		if (input) {
			uint8_t selector = (uint8_t)(req->wValue >> 8);
			uint8_t entity = (uint8_t)(req->wIndex >> 8);
			uint16_t n = req->wLength > 2 ? 2 : req->wLength;
			memset(g_ps5AudioControl, 0, sizeof g_ps5AudioControl);
			if (selector == 2 && n >= 2) {
				uint16_t v = (uint16_t)ps5AudioValue(
					entity, req->bRequest);
				g_ps5AudioControl[0] = (uint8_t)v;
				g_ps5AudioControl[1] = (uint8_t)(v >> 8);
			}
			return tud_control_xfer(rhport, req, g_ps5AudioControl,
						n);
		}
		if (req->wLength) {
			uint16_t n = req->wLength > 2 ? 2 : req->wLength;
			memset(g_ps5AudioControl, 0, sizeof g_ps5AudioControl);
			return tud_control_xfer(rhport, req, g_ps5AudioControl,
						n);
		}
		return tud_control_status(rhport, req);
	}
	return false;
}

static void ps5NativeDrain(void)
{
	if (g_usbMode != MODE_PS5_GAME || !tud_hid_n_ready(0))
		return;
	if ((uint32_t)(millis() - g_ps5NativeLastMs) < USB_STREAM_MS)
		return;
	uint8_t report[63];
	if (!ps5NativeBuildInput(report))
		return;
	if (tud_hid_n_report(0, 0x01, report, sizeof report))
		g_ps5NativeLastMs = millis();
}

static void ps5NativeDriverInit(void)
{
	memset(g_ps5AudioAlt, 0, sizeof g_ps5AudioAlt);
	g_ps5AudioOutOpen = false;
	g_ps5AudioInOpen = false;
}

static bool ps5NativeDriverDeinit(void)
{
	return true;
}

static void ps5NativeDriverReset(uint8_t rhport)
{
	(void)rhport;
	ps5NativeDriverInit();
}

static uint16_t ps5NativeDriverOpen(uint8_t rhport,
				    tusb_desc_interface_t const *itf,
				    uint16_t maxLen)
{
	if (g_usbMode != MODE_PS5_GAME)
		return 0;
	g_ps5NativeRhport = rhport;
	if (itf->bInterfaceNumber == 3 &&
	    itf->bInterfaceClass == TUSB_CLASS_HID)
		return hidd_open(rhport, itf, maxLen);

	if (itf->bInterfaceNumber != 0 ||
	    itf->bInterfaceClass != TUSB_CLASS_AUDIO)
		return 0;

	uint8_t const *start = (uint8_t const *)itf;
	uint8_t const *p = start;
	uint8_t const *end = p + maxLen;
	while (p < end) {
		uint8_t len = p[0];
		uint8_t type = p[1];
		if (!len)
			return 0;
		if (p != start && type == TUSB_DESC_INTERFACE) {
			auto next = (tusb_desc_interface_t const *)p;
			if (next->bInterfaceNumber == 3)
				break;
		}
		p += len;
	}
	return (uint16_t)(p - start);
}

static bool ps5NativeDriverControl(uint8_t rhport, uint8_t stage,
				   tusb_control_request_t const *req)
{
	if (g_usbMode != MODE_PS5_GAME)
		return false;
	if ((uint8_t)req->wIndex == 3)
		return hidd_control_xfer_cb(rhport, stage, req);
	return ps5NativeAudioControl(rhport, stage, req);
}

static bool ps5NativeDriverXfer(uint8_t rhport, uint8_t ep,
				xfer_result_t result, uint32_t transferred)
{
	(void)transferred;
	if (ep == 0x01 && g_ps5AudioOutOpen) {
		if (result == XFER_RESULT_SUCCESS)
			return usbd_edpt_xfer(rhport, 0x01, g_ps5AudioOut,
					      sizeof g_ps5AudioOut);
		return true;
	}
	if (ep == 0x82 && g_ps5AudioInOpen) {
		if (result == XFER_RESULT_SUCCESS) {
			memset(g_ps5AudioIn, 0, sizeof g_ps5AudioIn);
			return usbd_edpt_xfer(rhport, 0x82, g_ps5AudioIn,
					      sizeof g_ps5AudioIn);
		}
		return true;
	}
	return hidd_xfer_cb(rhport, ep, result, transferred);
}

static const usbd_class_driver_t g_ps5NativeDriver = {
#if CFG_TUSB_DEBUG >= 2
	.name = "PS5-NATIVE",
#endif
	.init = ps5NativeDriverInit,
	.deinit = ps5NativeDriverDeinit,
	.reset = ps5NativeDriverReset,
	.open = ps5NativeDriverOpen,
	.control_xfer_cb = ps5NativeDriverControl,
	.xfer_cb = ps5NativeDriverXfer,
	.sof = nullptr,
};

const usbd_class_driver_t *ps5NativeClassDriver(void)
{
	return &g_ps5NativeDriver;
}

void ps5NativeUsbBegin(void)
{
	if (!g_ps5NativeDrainRegistered) {
		usbTxRegisterDrain(ps5NativeDrain);
		g_ps5NativeDrainRegistered = true;
	}
}

void ps5NativeUsbMount(void)
{
	USBDevice.addInterface(g_ps5NativeUsb);
}

extern "C" uint8_t const *__real_tud_descriptor_device_cb(void);
extern "C" uint8_t const *__wrap_tud_descriptor_device_cb(void)
{
	if (g_usbMode == MODE_PS5_GAME)
		return PS5_NATIVE_DEVICE_DESC;
	return __real_tud_descriptor_device_cb();
}

extern "C" uint8_t const *__real_tud_hid_descriptor_report_cb(uint8_t itf);
extern "C" uint8_t const *__wrap_tud_hid_descriptor_report_cb(uint8_t itf)
{
	if (g_usbMode == MODE_PS5_GAME && itf == 0)
		return ps5NativeReportDescriptor();
	return __real_tud_hid_descriptor_report_cb(itf);
}

extern "C" uint16_t __real_tud_hid_get_report_cb(uint8_t itf, uint8_t reportId,
						 hid_report_type_t reportType,
						 uint8_t *buffer,
						 uint16_t reqLen);
extern "C" uint16_t __wrap_tud_hid_get_report_cb(uint8_t itf, uint8_t reportId,
						 hid_report_type_t reportType,
						 uint8_t *buffer,
						 uint16_t reqLen)
{
	if (g_usbMode == MODE_PS5_GAME && itf == 0)
		return ps5NativeGetReport(reportId, reportType, buffer, reqLen);
	return __real_tud_hid_get_report_cb(itf, reportId, reportType, buffer,
					    reqLen);
}

extern "C" void __real_tud_hid_set_report_cb(uint8_t itf, uint8_t reportId,
					     hid_report_type_t reportType,
					     uint8_t const *buffer,
					     uint16_t size);
extern "C" void __wrap_tud_hid_set_report_cb(uint8_t itf, uint8_t reportId,
					     hid_report_type_t reportType,
					     uint8_t const *buffer,
					     uint16_t size)
{
	if (g_usbMode == MODE_PS5_GAME && itf == 0) {
		ps5NativeSetReport(reportId, reportType, buffer, size);
		return;
	}
	__real_tud_hid_set_report_cb(itf, reportId, reportType, buffer, size);
}
