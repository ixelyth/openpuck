#include "ps5_topology.h"
#include "config.h"
#include <Adafruit_TinyUSB.h>
#include <Arduino.h>
#include <string.h>
extern "C" {
#include "tusb.h"
}

// Exact physical DualSense interfaces 0..2 from a 054C:0CE6 USB capture.
// The existing DualSense HID is appended as interface 3. The nRF52840 DCD
// only has hardware ISO support on endpoint 8, so the Sony 0x01/0x82 ISO
// endpoints are descriptor-only in this classification POC. We ACK audio
// alternate-setting/control traffic but never arm those ISO endpoints.
static const uint8_t PS5_AUDIO_CFG_BODY[] = {
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
	0x25, 0x01, 0x00, 0x00, 0x00, 0x00,
};
static_assert(sizeof PS5_AUDIO_CFG_BODY == 186,
	      "DualSense audio descriptor body must remain byte-exact");

class Ps5AudioTopology : public Adafruit_USBD_Interface {
    public:
	uint16_t getInterfaceDescriptor(uint8_t, uint8_t *buf,
					uint16_t bufsize) override
	{
		if (!buf)
			return sizeof PS5_AUDIO_CFG_BODY;
		if (bufsize < sizeof PS5_AUDIO_CFG_BODY)
			return 0;

		// Shape subsequent HID allocation to match the real controller:
		// audio OUT=01, audio IN=82, HID OUT=03, HID IN=84.
		uint8_t first = TinyUSBDevice.allocInterface(3);
		uint8_t reserveIn1 = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		uint8_t audioOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
		uint8_t audioIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		uint8_t reserveOut2 = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
		uint8_t reserveIn3 = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		if (first != 0 || reserveIn1 != 0x81 || audioOut != 0x01 ||
		    audioIn != 0x82 || reserveOut2 != 0x02 ||
		    reserveIn3 != 0x83)
			return 0;
		memcpy(buf, PS5_AUDIO_CFG_BODY, sizeof PS5_AUDIO_CFG_BODY);
		return sizeof PS5_AUDIO_CFG_BODY;
	}
};
static Ps5AudioTopology g_ps5AudioTopology;

void ps5TopologyAddInterface(void)
{
	if (g_usbMode == MODE_PS5_GAME)
		USBDevice.addInterface(g_ps5AudioTopology);
}

static uint8_t g_audioAlt[3] = {};
static uint8_t g_audioCtrl[64] = {};

static void ps5AudioInit(void)
{
	memset(g_audioAlt, 0, sizeof g_audioAlt);
	memset(g_audioCtrl, 0, sizeof g_audioCtrl);
}
static bool ps5AudioDeinit(void)
{
	return true;
}
static void ps5AudioReset(uint8_t)
{
	ps5AudioInit();
}

static uint16_t ps5AudioOpen(uint8_t, tusb_desc_interface_t const *itf,
			     uint16_t maxLen)
{
	if (g_usbMode != MODE_PS5_GAME || itf->bInterfaceNumber != 0 ||
	    itf->bInterfaceClass != TUSB_CLASS_AUDIO)
		return 0;
	// TinyUSB binds every interface/endpoint occurring within drv_len
	// to this driver, including IF1/IF2, without opening the ISO pipes.
	return maxLen >= sizeof PS5_AUDIO_CFG_BODY ? sizeof PS5_AUDIO_CFG_BODY :
						     0;
}

static void putLe16(uint8_t *p, int16_t v)
{
	p[0] = (uint8_t)v;
	p[1] = (uint8_t)((uint16_t)v >> 8);
}

static uint16_t ps5AudioFeatureValue(uint8_t request, uint8_t unit,
				     uint8_t selector, uint8_t *buf)
{
	if (selector == 0x01) {
		buf[0] = 0;
		return 1;
	}
	if (selector != 0x02)
		return 0;

	int16_t v;
	if (unit == 2) {
		if (request == 0x81 || request == 0x82)
			v = -25600;
		else if (request == 0x83)
			v = 0;
		else if (request == 0x84)
			v = 256;
		else
			return 0;
	} else if (unit == 5) {
		if (request == 0x81)
			v = 3809;
		else if (request == 0x82)
			v = 0;
		else if (request == 0x83)
			v = 12288;
		else if (request == 0x84)
			v = 122;
		else
			return 0;
	} else {
		return 0;
	}
	putLe16(buf, v);
	return 2;
}

static bool ps5AudioControl(uint8_t rhport, uint8_t stage,
			    tusb_control_request_t const *req)
{
	if (g_usbMode != MODE_PS5_GAME || !req)
		return false;
	uint8_t itf = (uint8_t)req->wIndex;
	if (itf > 2)
		return false;
	if (stage != CONTROL_STAGE_SETUP)
		return true;

	uint8_t type = req->bmRequestType & 0x60;
	if (type == 0x00 && req->bRequest == TUSB_REQ_GET_INTERFACE) {
		g_audioCtrl[0] = g_audioAlt[itf];
		return tud_control_xfer(rhport, req, g_audioCtrl, 1);
	}
	if (type == 0x00 && req->bRequest == TUSB_REQ_SET_INTERFACE) {
		// Descriptor-faithful only: accept alt 0/1, but do not arm
		// 0x01/0x82 as ISO on nRF52840 (its hardware ISO EP is fixed at 8).
		uint8_t alt = (uint8_t)req->wValue;
		if ((itf == 0 && alt != 0) || (itf > 0 && alt > 1))
			return false;
		g_audioAlt[itf] = alt;
		return tud_control_status(rhport, req);
	}
	if (type != 0x20)
		return false;

	uint8_t unit = (uint8_t)(req->wIndex >> 8);
	uint8_t selector = (uint8_t)(req->wValue >> 8);
	if (req->bmRequestType & 0x80) {
		memset(g_audioCtrl, 0, sizeof g_audioCtrl);
		uint16_t n = ps5AudioFeatureValue(req->bRequest, unit, selector,
						  g_audioCtrl);
		if (!n)
			n = req->wLength < sizeof g_audioCtrl ?
				    req->wLength :
				    sizeof g_audioCtrl;
		return tud_control_xfer(rhport, req, g_audioCtrl, n);
	}
	uint16_t n = req->wLength < sizeof g_audioCtrl ? req->wLength :
							 sizeof g_audioCtrl;
	return tud_control_xfer(rhport, req, g_audioCtrl, n);
}

static bool ps5AudioXfer(uint8_t, uint8_t, xfer_result_t, uint32_t)
{
	return true;
}

static const usbd_class_driver_t g_ps5AudioDriver = {
#if CFG_TUSB_DEBUG >= 2
	.name = "PS5-AUDIO",
#endif
	.init = ps5AudioInit,
	.deinit = ps5AudioDeinit,
	.reset = ps5AudioReset,
	.open = ps5AudioOpen,
	.control_xfer_cb = ps5AudioControl,
	.xfer_cb = ps5AudioXfer,
	.sof = nullptr,
};

const usbd_class_driver_t *ps5TopologyClassDriver(void)
{
	return &g_ps5AudioDriver;
}
