// mode_joycon2.cpp -- clean Nintendo Joy-Con 2 USB personality.
//
// F27-G5 deliberately starts from upstream OpenPuck rather than the Switch 2 Pro
// implementation. USB identity/descriptors come from captured Joy-Con 2 L/R
// descriptors published by ndeadly/switch2_controller_research. Nintendo bulk
// command framing, controller types, report IDs, feature selection and Charging
// Grip command 0x08 are cross-checked against novakpetya/linux-switch2 and the
// current Linux Switch 2 driver carried by martin-bts/hid-switch2-dkms.
//
// There are exactly two USB interfaces: IF0 HID interrupt IN/OUT and IF1
// Nintendo vendor bulk IN/OUT. There is intentionally no Pro2 report 0x09,
// audio function, WebUSB interface, wake mouse, or Switch2Pro source dependency.
#include "mode_joycon2.h"
#include "config.h"
#include "rf_link.h"
#include "triton.h"
#include "usb_tx.h"
#include <Adafruit_TinyUSB.h>
#include <Arduino.h>
#include <string.h>

extern "C" {
#include "class/hid/hid_device.h"
#include "device/usbd_pvt.h"
}

#ifndef OPK_G5_JOYCON_SIDE
#define OPK_G5_JOYCON_SIDE 2
#endif
#define G5_JOYCON_L 1
#define G5_JOYCON_R 2
#if OPK_G5_JOYCON_SIDE != G5_JOYCON_L && OPK_G5_JOYCON_SIDE != G5_JOYCON_R
#error "OPK_G5_JOYCON_SIDE must be 1 (L) or 2 (R)"
#endif

#if OPK_G5_JOYCON_SIDE == G5_JOYCON_L
#define JC2_PID 0x2067
#define JC2_PID_LOW 0x67
#define JC2_NATIVE_REPORT 0x07
#define JC2_CONTROLLER_TYPE 0x00
#define JC2_PRODUCT "Joy-Con 2 (L)"
#define JC2_BUILD_MARKER "F27-G5-CLEAN-JCL-GRIP08"
#else
#define JC2_PID 0x2066
#define JC2_PID_LOW 0x66
#define JC2_NATIVE_REPORT 0x08
#define JC2_CONTROLLER_TYPE 0x01
#define JC2_PRODUCT "Joy-Con 2 (R)"
#define JC2_BUILD_MARKER "F27-G5-CLEAN-JCR-GRIP08"
#endif

JoyCon2Controller g_joyCon2;
static const char g_jc2BuildMarker[] __attribute__((used)) = JC2_BUILD_MARKER;

// Captured Joy-Con 2 HID report descriptor. L and R are byte-identical except
// for the native side input report ID (0x07 L, 0x08 R). Both expose common 0x05
// and Joy-Con output report 0x01; descriptor length is exactly 100 bytes.
static const uint8_t JOYCON2_HID_DESC[] = {
	0x05, 0x01, 0x09, 0x05, 0xa1, 0x01, 0x85, 0x05, 0x05, 0xff, 0x09,
	0x01, 0x15, 0x00, 0x26, 0xff, 0x00, 0x95, 0x3f, 0x75, 0x08, 0x81,
	0x02, 0x85, JC2_NATIVE_REPORT, 0x09, 0x01, 0x95, 0x02, 0x81, 0x02,
	0x05, 0x09, 0x19, 0x01, 0x29, 0x10, 0x25, 0x01, 0x95, 0x10, 0x75,
	0x01, 0x81, 0x02, 0x05, 0xff, 0x09, 0x01, 0x26, 0xff, 0x00, 0x95,
	0x01, 0x75, 0x08, 0x81, 0x02, 0x05, 0x01, 0x09, 0x01, 0xa1, 0x00,
	0x09, 0x30, 0x09, 0x31, 0x26, 0xff, 0x0f, 0x95, 0x02, 0x75, 0x0c,
	0x81, 0x02, 0xc0, 0x05, 0xff, 0x09, 0x02, 0x26, 0xff, 0x00, 0x95,
	0x37, 0x75, 0x08, 0x81, 0x02, 0x85, 0x01, 0x09, 0x01, 0x95, 0x3f,
	0x91, 0x02, 0xc0,
};
static_assert(sizeof JOYCON2_HID_DESC == 100,
	      "Joy-Con 2 HID descriptor must remain byte-exact");

// Captured configuration body (everything after the 9-byte config header):
// IF0 HID: EP81 interrupt IN + EP01 interrupt OUT
// IF1 vendor: EP02 bulk OUT + EP82 bulk IN
static const uint8_t JOYCON2_CFG_BODY[] = {
	0x08, 0x0b, 0x00, 0x01, 0x03, 0x00, 0x00, 0x00,
	0x09, 0x04, 0x00, 0x00, 0x02, 0x03, 0x00, 0x00, 0x05,
	0x09, 0x21, 0x11, 0x01, 0x00, 0x01, 0x22, 0x64, 0x00,
	0x07, 0x05, 0x81, 0x03, 0x40, 0x00, 0x04,
	0x07, 0x05, 0x01, 0x03, 0x40, 0x00, 0x04,
	0x08, 0x0b, 0x01, 0x01, 0xff, 0x00, 0x00, 0x00,
	0x09, 0x04, 0x01, 0x00, 0x02, 0xff, 0x00, 0x00, 0x06,
	0x07, 0x05, 0x02, 0x02, 0x40, 0x00, 0x00,
	0x07, 0x05, 0x82, 0x02, 0x40, 0x00, 0x00,
};
static_assert(sizeof JOYCON2_CFG_BODY == 71,
	      "Joy-Con 2 configuration body must remain byte-exact");

static volatile uint8_t g_jc2VendorEpOut = 0;
static volatile uint8_t g_jc2VendorEpIn = 0;
static volatile uint8_t g_jc2Rhport = 0;
static volatile bool g_jc2VendorCommandPending = false;
static volatile bool g_jc2VendorInFlight = false;
static volatile uint8_t g_jc2VendorCommandLen = 0;
static volatile uint8_t g_jc2VendorReplyLen = 0;
static uint8_t g_jc2VendorOut[64];
static uint8_t g_jc2VendorReply[64];
static uint8_t g_jc2ControlReply[64];
static volatile bool g_jc2InputEnabled = false;
static volatile uint8_t g_jc2ActiveReport = JC2_NATIVE_REPORT;
static volatile uint8_t g_jc2FeatureMask = 0;
static volatile uint8_t g_jc2Features = 0;
static bool g_jc2GripButtonsEnabled = false;
static uint8_t g_jc2NativeCounter = 0;
static uint32_t g_jc2CommonCounter = 0;
static unsigned long g_jc2LastReportMs = 0;
static int8_t g_jc2Bond = -1;
static bool g_jc2DrainRegistered = false;

class JoyCon2UsbInterface : public Adafruit_USBD_Interface {
    public:
	uint16_t getInterfaceDescriptor(uint8_t, uint8_t *buf,
					uint16_t bufsize) override
	{
		if (!buf)
			return sizeof JOYCON2_CFG_BODY;
		if (bufsize < sizeof JOYCON2_CFG_BODY)
			return 0;

		uint8_t first = TinyUSBDevice.allocInterface(2);
		uint8_t hidIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		uint8_t hidOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
		uint8_t vendorOut = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
		uint8_t vendorIn = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
		if (first != 0 || hidIn != 0x81 || hidOut != 0x01 ||
		    vendorOut != 0x02 || vendorIn != 0x82)
			return 0;

		uint8_t configStr = TinyUSBDevice.addStringDescriptor("Config_0");
		uint8_t hidStr = TinyUSBDevice.addStringDescriptor("If_Hid");
		uint8_t vendorStr = TinyUSBDevice.addStringDescriptor(JC2_PRODUCT);
		if (configStr != 4 || hidStr != 5 || vendorStr != 6)
			return 0;

		memcpy(buf, JOYCON2_CFG_BODY, sizeof JOYCON2_CFG_BODY);
		return sizeof JOYCON2_CFG_BODY;
	}
};
static JoyCon2UsbInterface g_jc2Usb;

static inline void put16(uint8_t *p, uint16_t v)
{
	p[0] = (uint8_t)v;
	p[1] = (uint8_t)(v >> 8);
}

static inline void put32(uint8_t *p, uint32_t v)
{
	p[0] = (uint8_t)v;
	p[1] = (uint8_t)(v >> 8);
	p[2] = (uint8_t)(v >> 16);
	p[3] = (uint8_t)(v >> 24);
}

static inline uint16_t stick12(int16_t v)
{
	return (uint16_t)(((int32_t)v + 32768) >> 4);
}

static void packStick(uint8_t out[3], int16_t x, int16_t y)
{
	uint16_t sx = stick12(x), sy = stick12(y);
	out[0] = (uint8_t)sx;
	out[1] = (uint8_t)((sx >> 8) | (sy << 4));
	out[2] = (uint8_t)(sy >> 4);
}

static void centerStick(uint8_t out[3])
{
	out[0] = 0x00;
	out[1] = 0x08;
	out[2] = 0x80;
}

static uint8_t powerInfo(uint8_t slot)
{
	uint8_t pct = slot < NSLOT ? g_battery[slot] : 0;
	uint8_t level = pct ? (uint8_t)(((uint16_t)pct * 9u + 50u) / 100u) : 0;
	if (level > 9)
		level = 9;
	return (uint8_t)(level << 2);
}

static void buildNative(uint8_t slot, uint8_t out[63])
{
	memset(out, 0, 63);
	uint32_t b = g_in[slot].buttons;
	uint8_t b0 = 0, b1 = 0;

#if OPK_G5_JOYCON_SIDE == G5_JOYCON_R
	if (b & TB_R3)
		b0 |= 0x80;
	if (b & TB_MENU)
		b0 |= 0x40;
	if (g_in[slot].rt >= SW_TRIG_ON || (b & TB_R2))
		b0 |= 0x20;
	if (b & TB_RB)
		b0 |= 0x10;
	uint8_t a = g_abSwap ? 0x01 : 0x02;
	uint8_t bb = g_abSwap ? 0x02 : 0x01;
	uint8_t x = g_abSwap ? 0x04 : 0x08;
	uint8_t y = g_abSwap ? 0x08 : 0x04;
	if (b & TB_A)
		b0 |= a;
	if (b & TB_B)
		b0 |= bb;
	if (b & TB_X)
		b0 |= x;
	if (b & TB_Y)
		b0 |= y;
	if (b & TB_R4)
		b1 |= 0x80; // SL
	if (b & TB_R5)
		b1 |= 0x40; // SR
	if (b & TB_QAM)
		b1 |= 0x10; // C
	if (b & TB_STEAM)
		b1 |= 0x01; // Home
	packStick(out + 5, g_in[slot].rx, g_in[slot].ry);
#else
	if (b & TB_L3)
		b0 |= 0x80;
	if (b & TB_VIEW)
		b0 |= 0x40;
	if (g_in[slot].lt >= SW_TRIG_ON || (b & TB_L2))
		b0 |= 0x20;
	if (b & TB_LB)
		b0 |= 0x10;
	if (b & TB_DUP)
		b0 |= 0x08;
	if (b & TB_DLF)
		b0 |= 0x04;
	if (b & TB_DRT)
		b0 |= 0x02;
	if (b & TB_DDN)
		b0 |= 0x01;
	if (b & TB_L4)
		b1 |= 0x80; // SL
	if (b & TB_L5)
		b1 |= 0x40; // SR
	if (b & TB_QAM)
		b1 |= 0x01; // Capture
	packStick(out + 5, g_in[slot].lx, g_in[slot].ly);
#endif

	out[0] = g_jc2NativeCounter++;
	out[1] = powerInfo(slot);
	out[2] = b0;
	out[3] = b1;
	out[4] = 0x07;
	out[0x0e] = 0x00; // NFC idle; JCL has no NFC, JCR stays idle.
	out[0x0f] = 0x00; // no motion payload in the G5 discriminator.
}

static void buildCommon(uint8_t slot, uint8_t out[63])
{
	memset(out, 0, 63);
	uint32_t b = g_in[slot].buttons;
	uint8_t buttons[4] = { 0, 0, 0, 0 };
	put32(out, g_jc2CommonCounter++);

#if OPK_G5_JOYCON_SIDE == G5_JOYCON_R
	if (g_in[slot].rt >= SW_TRIG_ON || (b & TB_R2))
		buttons[0] |= 0x80;
	if (b & TB_RB)
		buttons[0] |= 0x40;
	if (b & TB_A)
		buttons[0] |= g_abSwap ? 0x04 : 0x08;
	if (b & TB_B)
		buttons[0] |= g_abSwap ? 0x08 : 0x04;
	if (b & TB_X)
		buttons[0] |= g_abSwap ? 0x01 : 0x02;
	if (b & TB_Y)
		buttons[0] |= g_abSwap ? 0x02 : 0x01;
	if (b & TB_R3)
		buttons[1] |= 0x04;
	if (b & TB_MENU)
		buttons[1] |= 0x02;
	if (b & TB_STEAM)
		buttons[1] |= 0x10;
	if (b & TB_QAM)
		buttons[1] |= 0x40;
	centerStick(out + 0x0a);
	packStick(out + 0x0d, g_in[slot].rx, g_in[slot].ry);
#else
	if (g_in[slot].lt >= SW_TRIG_ON || (b & TB_L2))
		buttons[2] |= 0x80;
	if (b & TB_LB)
		buttons[2] |= 0x40;
	if (b & TB_DLF)
		buttons[2] |= 0x08;
	if (b & TB_DRT)
		buttons[2] |= 0x04;
	if (b & TB_DUP)
		buttons[2] |= 0x02;
	if (b & TB_DDN)
		buttons[2] |= 0x01;
	if (b & TB_L3)
		buttons[1] |= 0x08;
	if (b & TB_VIEW)
		buttons[1] |= 0x01;
	if (b & TB_QAM)
		buttons[1] |= 0x20;
	packStick(out + 0x0a, g_in[slot].lx, g_in[slot].ly);
	centerStick(out + 0x0d);
#endif

	memcpy(out + 4, buttons, sizeof buttons);
	put16(out + 0x1f, 4000); // plausible powered USB voltage field.
	out[0x21] = 0x20; // externally powered / settled state.
	out[0x29] = 0x01;
	// Mouse, magnetometer and motion remain zero until separately adjudicated.
}

static void ackHeader(uint8_t *out, uint8_t cmd, uint8_t transport,
		      uint8_t sub)
{
	out[0] = cmd;
	out[1] = 0x01;
	out[2] = transport;
	out[3] = sub;
	out[4] = 0x00;
	out[5] = 0xf8;
	out[6] = 0x00;
	out[7] = 0x00;
}

static void dataHeader(uint8_t *out, uint8_t cmd, uint8_t transport,
		       uint8_t sub)
{
	out[0] = cmd;
	out[1] = 0x01;
	out[2] = transport;
	out[3] = sub;
	out[4] = 0x10;
	out[5] = 0x78;
	out[6] = 0x00;
	out[7] = 0x00;
}

static const uint8_t JOYCON2_FACTORY_ID[64] = {
	0x01, 0x00, '0',  '0',  0x00, 0x00, 0x00, 0x00,
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
	0x00, 0x00, 0x7e, 0x05, JC2_PID_LOW, 0x20, 0x01, 0x06,
	0x01, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
};
static_assert(sizeof JOYCON2_FACTORY_ID == 64,
	      "Joy-Con 2 factory identity must remain 64 bytes");

static const uint8_t JOYCON2_VENDOR_PROTOCOL[16] = {
	0x02, 0x01, 0x04, 0x00, 0x00, 0x00, 0x0c, 0x00,
	0x02, 0x03, 0x3d, 0x17, 0x69, 0xab, 0xa9, 0x3c,
};

// Captured Charging Grip factory block returned by Joy-Con command 0x08.
static const uint8_t CHARGING_GRIP_FACTORY[64] = {
	0x01, 0x00, 0x48, 0x44, 0x4c, 0x35, 0x30, 0x30,
	0x30, 0x33, 0x34, 0x38, 0x35, 0x35, 0x31, 0x39,
	0x00, 0x00, 0x7e, 0x05, 0x68, 0x20, 0x01, 0x03,
	0x01, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
};
static_assert(sizeof CHARGING_GRIP_FACTORY == 64,
	      "Charging Grip factory block must remain 64 bytes");

static void overlay(uint32_t address, uint8_t *out, uint8_t len,
		    uint32_t knownAddress, const uint8_t *known, uint8_t knownLen)
{
	uint32_t begin = address > knownAddress ? address : knownAddress;
	uint32_t end = address + len;
	uint32_t knownEnd = knownAddress + knownLen;
	if (end > knownEnd)
		end = knownEnd;
	if (begin >= end)
		return;
	memcpy(out + (begin - address), known + (begin - knownAddress),
	       end - begin);
}

static void fillFlash(uint32_t address, uint8_t *block, uint8_t len)
{
	memset(block, 0xff, len);
	overlay(address, block, len, 0x00013000, JOYCON2_FACTORY_ID,
		sizeof JOYCON2_FACTORY_ID);
	// Genuine captured Switch 2 primary-axis calibration sample. Calibration
	// values are unit-specific; only the format and validity matter here.
	static const uint8_t primaryCal[9] = {
		0xb3, 0x67, 0x83, 0x2e, 0x66, 0x5e, 0x3a, 0x06, 0x5f,
	};
	overlay(address, block, len, 0x000130a8, primaryCal, sizeof primaryCal);
}

static uint8_t handleFlash(const uint8_t *cmd, uint8_t n, uint8_t *reply)
{
	uint8_t sub = cmd[3];
	if (n < 16) {
		dataHeader(reply, 0x02, cmd[2], sub);
		return 8;
	}
	if (sub != 0x04 && sub != 0x01) {
		dataHeader(reply, 0x02, cmd[2], sub);
		return 8;
	}
	uint8_t requested = sub == 0x01 ? 0x40 : cmd[8];
	uint8_t copied = requested > 80 ? 80 : requested;
	uint32_t address = (uint32_t)cmd[12] | ((uint32_t)cmd[13] << 8) |
			   ((uint32_t)cmd[14] << 16) |
			   ((uint32_t)cmd[15] << 24);
	dataHeader(reply, 0x02, cmd[2], sub);
	reply[8] = copied;
	reply[12] = cmd[12];
	reply[13] = cmd[13];
	reply[14] = cmd[14];
	reply[15] = cmd[15];
	fillFlash(address, reply + 16, copied);
	return (uint8_t)(16 + copied);
}

static void featureInfo(uint8_t flags, uint8_t out[8])
{
	memset(out, 0, 8);
	if (flags & 0x01)
		out[0] = 0x07;
	if (flags & 0x02)
		out[1] = 0x07;
	if (flags & 0x04)
		out[2] = 0x01;
	if (flags & 0x80)
		out[3] = 0x01;
	if (flags & 0x10)
		out[4] = 0x01;
	if (flags & 0x20)
		out[5] = 0x03;
}

static uint8_t handleInit(const uint8_t *cmd, uint8_t n, uint8_t *reply)
{
	uint8_t sub = cmd[3];
	ackHeader(reply, 0x03, cmd[2], sub);
	if (sub == 0x03) {
		g_jc2InputEnabled = n >= 9 && cmd[8] != 0;
		reply[8] = 0x01;
		return 12;
	}
	if (sub == 0x0d) {
		g_jc2InputEnabled = true;
		reply[8] = 0x01;
		return 12;
	}
	if (sub == 0x0f) {
		reply[8] = 0x05;
		return 12;
	}
	if (sub == 0x0a && n >= 9 &&
	    (cmd[8] == 0x05 || cmd[8] == JC2_NATIVE_REPORT))
		g_jc2ActiveReport = cmd[8];
	if (sub == 0x07 || sub == 0x09) {
		dataHeader(reply, 0x03, cmd[2], sub);
		return 8;
	}
	return 8;
}

static uint8_t handleFeatures(const uint8_t *cmd, uint8_t n, uint8_t *reply)
{
	uint8_t sub = cmd[3], flags = n >= 9 ? cmd[8] : 0;
	dataHeader(reply, 0x0c, cmd[2], sub);
	if (sub == 0x01) {
		featureInfo(flags, reply + 12);
		return 20;
	}
	if (sub == 0x02)
		g_jc2FeatureMask = flags;
	else if (sub == 0x03) {
		g_jc2FeatureMask = 0;
		g_jc2Features = 0;
	} else if (sub == 0x04)
		g_jc2Features |= flags & g_jc2FeatureMask;
	else if (sub == 0x05)
		g_jc2Features &= (uint8_t) ~(flags & g_jc2FeatureMask);
	return 12;
}

static uint8_t handleGrip(const uint8_t *cmd, uint8_t n, uint8_t *reply)
{
	uint8_t sub = cmd[3];
	dataHeader(reply, 0x08, cmd[2], sub);
	if (sub == 0x01 || sub == 0x03) {
		uint8_t requested = sub == 0x01 ? 0x20 : 0x40;
		memset(reply + 8, 0, 4);
		memcpy(reply + 12, CHARGING_GRIP_FACTORY, requested);
		return (uint8_t)(12 + requested);
	}
	if (sub == 0x02) {
		if (n >= 9)
			g_jc2GripButtonsEnabled = cmd[8] != 0;
		return 8;
	}
	return 8;
}

static uint8_t g_jc2PairLtk[16];
static bool g_jc2PairLtkValid = false;
static const uint8_t PAIR_PUBLIC[16] = {
	0x5c, 0xf6, 0xee, 0x79, 0x2c, 0xdf, 0x05, 0xe1,
	0xba, 0x2b, 0x63, 0x25, 0xc4, 0x1a, 0x5f, 0x10,
};

struct EcbBlock {
	uint8_t key[16];
	uint8_t clear[16];
	uint8_t cipher[16];
} __attribute__((aligned(4)));

static bool aes128Ecb(const uint8_t key[16], const uint8_t clear[16],
		      uint8_t cipher[16])
{
	static EcbBlock block;
	memcpy(block.key, key, 16);
	memcpy(block.clear, clear, 16);
	NRF_ECB->TASKS_STOPECB = 1;
	NRF_ECB->EVENTS_ENDECB = 0;
	NRF_ECB->EVENTS_ERRORECB = 0;
	NRF_ECB->ECBDATAPTR = (uint32_t)&block;
	NRF_ECB->TASKS_STARTECB = 1;
	while (!NRF_ECB->EVENTS_ENDECB && !NRF_ECB->EVENTS_ERRORECB) {
	}
	if (NRF_ECB->EVENTS_ERRORECB)
		return false;
	memcpy(cipher, block.cipher, 16);
	return true;
}

static void controllerAddress(uint8_t out[6])
{
	uint32_t a = NRF_FICR->DEVICEID[0], b = NRF_FICR->DEVICEID[1];
	out[0] = (uint8_t)a;
	out[1] = (uint8_t)(a >> 8);
	out[2] = (uint8_t)(a >> 16);
	out[3] = (uint8_t)(a >> 24);
	out[4] = (uint8_t)b;
	out[5] = (uint8_t)(b >> 8);
}

static void pairResponse(const uint8_t challenge[16], uint8_t out[16])
{
	uint8_t key[16], clear[16], cipher[16];
	for (uint8_t i = 0; i < 16; i++) {
		key[i] = g_jc2PairLtk[15 - i];
		clear[i] = challenge[15 - i];
	}
	if (!g_jc2PairLtkValid || !aes128Ecb(key, clear, cipher)) {
		memset(out, 0, 16);
		return;
	}
	memcpy(out, cipher, 16);
}

static uint8_t handlePairing(const uint8_t *cmd, uint8_t n, uint8_t *reply)
{
	uint8_t sub = cmd[3];
	dataHeader(reply, 0x15, cmd[2], sub);
	if (sub == 0x01) {
		uint8_t addr[6];
		controllerAddress(addr);
		reply[8] = 0x01;
		reply[9] = 0x04;
		reply[10] = 0x01;
		memcpy(reply + 11, addr, sizeof addr);
		return 17;
	}
	if (sub == 0x04 && n >= 25) {
		reply[8] = 0x01;
		memcpy(reply + 9, PAIR_PUBLIC, sizeof PAIR_PUBLIC);
		for (uint8_t i = 0; i < 16; i++)
			g_jc2PairLtk[i] = cmd[9 + i] ^ PAIR_PUBLIC[i];
		g_jc2PairLtkValid = true;
		return 25;
	}
	if (sub == 0x02 && n >= 25) {
		reply[8] = 0x01;
		pairResponse(cmd + 9, reply + 9);
		return 25;
	}
	reply[8] = 0x01;
	return 9;
}

static void buildVendorReply()
{
	uint8_t cmd[64];
	uint8_t reply[96];
	uint8_t n;
	uint32_t pm = __get_PRIMASK();
	__disable_irq();
	n = g_jc2VendorCommandLen;
	if (n > sizeof cmd)
		n = sizeof cmd;
	memcpy(cmd, g_jc2VendorOut, n);
	g_jc2VendorCommandPending = false;
	__set_PRIMASK(pm);

	memset(reply, 0, sizeof reply);
	if (n < 8 || cmd[1] != 0x91) {
		g_jc2VendorReplyLen = 0;
		return;
	}
	uint8_t id = cmd[0], sub = cmd[3], seq = cmd[2];
	ackHeader(reply, id, seq, sub);
	uint8_t replyLen = 8;

	switch (id) {
	case 0x02:
		replyLen = handleFlash(cmd, n, reply);
		break;
	case 0x03:
		replyLen = handleInit(cmd, n, reply);
		break;
	case 0x08:
		replyLen = handleGrip(cmd, n, reply);
		break;
	case 0x0c:
		replyLen = handleFeatures(cmd, n, reply);
		break;
	case 0x10:
		if (sub == 0x01) {
			static const uint8_t info[12] = {
				0x02, 0x01, 0x04, JC2_CONTROLLER_TYPE,
				0x0c, 0x00, 0x00, 0x00,
				0x02, 0x03, 0x00, 0x00,
			};
			dataHeader(reply, id, seq, sub);
			memcpy(reply + 8, info, sizeof info);
			replyLen = 20;
		}
		break;
	case 0x15:
		replyLen = handlePairing(cmd, n, reply);
		break;
	case 0x01:
		if (sub == 0x0c) {
			dataHeader(reply, id, seq, sub);
			reply[8] = 0x61;
			reply[9] = 0x12;
			reply[10] = 0x50;
			reply[11] = 0x0d;
			replyLen = 12;
		}
		break;
	case 0x07:
	case 0x09:
	case 0x0a:
	case 0x0b:
	case 0x0d:
	case 0x11:
	case 0x16:
	case 0x17:
	case 0x18:
		dataHeader(reply, id, seq, sub);
		break;
	case 0x06:
		if (sub == 0x02) {
			g_jc2VendorReplyLen = 0;
			return;
		}
		dataHeader(reply, id, seq, sub);
		break;
	default:
		dataHeader(reply, id, seq, sub);
		break;
	}

	uint8_t first = replyLen > sizeof g_jc2VendorReply ?
				sizeof g_jc2VendorReply :
				replyLen;
	memcpy(g_jc2VendorReply, reply, first);
	if (replyLen > first)
		memcpy(g_jc2VendorOut, reply + first, replyLen - first);
	g_jc2VendorReplyLen = replyLen;
}

static void joyCon2Drain()
{
	if (g_usbMode != MODE_JOYCON2)
		return;
	asm volatile("" : : "r"(g_jc2BuildMarker), "r"(g_jc2GripButtonsEnabled) :
		     "memory");

	if (g_jc2VendorCommandPending && !g_jc2VendorInFlight) {
		buildVendorReply();
		uint8_t n = g_jc2VendorReplyLen;
		uint8_t first = n > sizeof g_jc2VendorReply ?
					sizeof g_jc2VendorReply :
					n;
		if (first && g_jc2VendorEpIn &&
		    usbd_edpt_xfer(g_jc2Rhport, g_jc2VendorEpIn,
				   g_jc2VendorReply, first))
			g_jc2VendorInFlight = true;
	}

	if (!g_jc2InputEnabled || !tud_hid_n_ready(0))
		return;
	if ((uint32_t)(millis() - g_jc2LastReportMs) < USB_STREAM_MS)
		return;
	uint8_t slot = g_jc2Bond >= 0 && g_jc2Bond < NSLOT ?
			       (uint8_t)g_jc2Bond :
			       0;
	uint8_t p[63];
	uint8_t rid = g_jc2ActiveReport;
	if (rid == 0x05)
		buildCommon(slot, p);
	else {
		rid = JC2_NATIVE_REPORT;
		buildNative(slot, p);
	}
	if (tud_hid_n_report(0, rid, p, sizeof p))
		g_jc2LastReportMs = millis();
}

bool joyCon2VendorControlXfer(uint8_t rhport, uint8_t stage,
			      const tusb_control_request_t *request)
{
	if (g_usbMode != MODE_JOYCON2 || !request)
		return false;
	bool identity = request->bmRequestType == 0xc0 &&
			request->bRequest == 0x03 && request->wLength >= 64;
	bool protocol = request->bmRequestType == 0xc0 &&
			request->bRequest == 0x02 && request->wLength >= 16;
	bool commit = request->bmRequestType == 0x40 &&
		      request->bRequest == 0x04 && request->wLength == 0;
	if (!identity && !protocol && !commit)
		return false;
	if (stage != CONTROL_STAGE_SETUP)
		return true;
	if (commit)
		return tud_control_status(rhport, request);
	if (identity) {
		memcpy(g_jc2ControlReply, JOYCON2_FACTORY_ID,
		       sizeof JOYCON2_FACTORY_ID);
		return tud_control_xfer(rhport, request, g_jc2ControlReply,
					sizeof JOYCON2_FACTORY_ID);
	}
	memcpy(g_jc2ControlReply, JOYCON2_VENDOR_PROTOCOL,
	       sizeof JOYCON2_VENDOR_PROTOCOL);
	return tud_control_xfer(rhport, request, g_jc2ControlReply,
				sizeof JOYCON2_VENDOR_PROTOCOL);
}

static void driverInit()
{
	g_jc2VendorEpOut = g_jc2VendorEpIn = 0;
}

static bool driverDeinit()
{
	return true;
}

static void driverReset(uint8_t rhport)
{
	(void)rhport;
	g_jc2VendorEpOut = g_jc2VendorEpIn = 0;
	g_jc2VendorCommandPending = false;
	g_jc2VendorInFlight = false;
	g_jc2InputEnabled = false;
	g_jc2ActiveReport = JC2_NATIVE_REPORT;
	g_jc2FeatureMask = 0;
	g_jc2Features = 0;
	g_jc2GripButtonsEnabled = false;
	g_jc2PairLtkValid = false;
	g_jc2Bond = -1;
}

static uint16_t driverOpen(uint8_t rhport, tusb_desc_interface_t const *itf,
			   uint16_t maxLen)
{
	if (g_usbMode != MODE_JOYCON2)
		return 0;
	g_jc2Rhport = rhport;
	if (itf->bInterfaceNumber == 0 &&
	    itf->bInterfaceClass == TUSB_CLASS_HID)
		return hidd_open(rhport, itf, maxLen);
	if (itf->bInterfaceNumber == 1 && itf->bInterfaceClass == 0xff) {
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
					g_jc2VendorEpIn = ep->bEndpointAddress;
				else
					g_jc2VendorEpOut = ep->bEndpointAddress;
				opened++;
			}
			used += len;
			p += len;
		}
		if (opened != 2 || !g_jc2VendorEpOut || !g_jc2VendorEpIn)
			return 0;
		if (!usbd_edpt_xfer(rhport, g_jc2VendorEpOut, g_jc2VendorOut,
				    sizeof g_jc2VendorOut))
			return 0;
		return used;
	}
	return 0;
}

static bool driverControl(uint8_t rhport, uint8_t stage,
			  tusb_control_request_t const *req)
{
	if (g_usbMode != MODE_JOYCON2)
		return false;
	if (req->wIndex == 0)
		return hidd_control_xfer_cb(rhport, stage, req);
	return stage != CONTROL_STAGE_SETUP;
}

static bool driverXfer(uint8_t rhport, uint8_t ep, xfer_result_t result,
		       uint32_t transferred)
{
	if (ep == g_jc2VendorEpOut) {
		if (result == XFER_RESULT_SUCCESS) {
			g_jc2VendorCommandLen =
				(uint8_t)(transferred > 64 ? 64 : transferred);
			g_jc2VendorCommandPending = true;
		}
		return true;
	}
	if (ep == g_jc2VendorEpIn) {
		if (result == XFER_RESULT_SUCCESS && g_jc2VendorReplyLen > 64) {
			uint8_t tail = g_jc2VendorReplyLen - 64;
			g_jc2VendorReplyLen = tail;
			return usbd_edpt_xfer(rhport, g_jc2VendorEpIn,
					      g_jc2VendorOut, tail);
		}
		g_jc2VendorReplyLen = 0;
		g_jc2VendorInFlight = false;
		return usbd_edpt_xfer(rhport, g_jc2VendorEpOut, g_jc2VendorOut,
				      sizeof g_jc2VendorOut);
	}
	return hidd_xfer_cb(rhport, ep, result, transferred);
}

static const usbd_class_driver_t g_jc2Driver = {
#if CFG_TUSB_DEBUG >= 2
	.name = "JOYCON2",
#endif
	.init = driverInit,
	.deinit = driverDeinit,
	.reset = driverReset,
	.open = driverOpen,
	.control_xfer_cb = driverControl,
	.xfer_cb = driverXfer,
	.sof = nullptr,
};

const usbd_class_driver_t *joyCon2ClassDriver(void)
{
	return &g_jc2Driver;
}

extern "C" uint8_t const *__real_tud_descriptor_device_cb(void);
extern "C" uint8_t const *__wrap_tud_descriptor_device_cb(void)
{
	uint8_t const *real = __real_tud_descriptor_device_cb();
	if (g_usbMode != MODE_JOYCON2)
		return real;
	static tusb_desc_device_t d;
	memcpy(&d, real, sizeof d);
	d.bDeviceClass = 0xef;
	d.bDeviceSubClass = 0x02;
	d.bDeviceProtocol = 0x01;
	return (uint8_t const *)&d;
}

extern "C" uint8_t const *__real_tud_descriptor_configuration_cb(uint8_t index);
extern "C" uint8_t const *__wrap_tud_descriptor_configuration_cb(uint8_t index)
{
	uint8_t const *real = __real_tud_descriptor_configuration_cb(index);
	if (g_usbMode != MODE_JOYCON2 || !real)
		return real;
	static uint8_t cfg[80];
	memcpy(cfg, real, sizeof cfg);
	// Captured header: total 80 bytes, 2 interfaces, iConfiguration=4,
	// self-powered, 500 mA.
	cfg[2] = 0x50;
	cfg[3] = 0x00;
	cfg[4] = 0x02;
	cfg[6] = 0x04;
	cfg[7] = 0xc0;
	cfg[8] = 0xfa;
	return cfg;
}

extern "C" uint8_t const *__real_tud_hid_descriptor_report_cb(uint8_t itf);
extern "C" uint8_t const *__wrap_tud_hid_descriptor_report_cb(uint8_t itf)
{
	if (g_usbMode == MODE_JOYCON2 && itf == 0)
		return JOYCON2_HID_DESC;
	return __real_tud_hid_descriptor_report_cb(itf);
}

extern "C" uint16_t __real_tud_hid_get_report_cb(uint8_t itf,
						 uint8_t reportId,
						 hid_report_type_t reportType,
						 uint8_t *buffer,
						 uint16_t reqLen);
extern "C" uint16_t __wrap_tud_hid_get_report_cb(uint8_t itf,
						 uint8_t reportId,
						 hid_report_type_t reportType,
						 uint8_t *buffer,
						 uint16_t reqLen)
{
	if (g_usbMode != MODE_JOYCON2 || itf != 0)
		return __real_tud_hid_get_report_cb(itf, reportId, reportType,
						    buffer, reqLen);
	(void)reportType;
	if (!buffer || !reqLen)
		return 0;
	uint8_t slot = g_jc2Bond >= 0 && g_jc2Bond < NSLOT ?
			       (uint8_t)g_jc2Bond :
			       0;
	uint8_t p[63];
	if (reportId == 0x05)
		buildCommon(slot, p);
	else if (reportId == JC2_NATIVE_REPORT)
		buildNative(slot, p);
	else
		return 0;
	uint16_t n = reqLen < sizeof p ? reqLen : sizeof p;
	memcpy(buffer, p, n);
	return n;
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
	if (g_usbMode == MODE_JOYCON2 && itf == 0) {
		// Joy-Con output report 0x01 is accepted but intentionally not translated
		// to Steam haptics in G5; rumble is a later isolated hardware gate.
		(void)reportId;
		(void)reportType;
		(void)buffer;
		(void)size;
		return;
	}
	__real_tud_hid_set_report_cb(itf, reportId, reportType, buffer, size);
}

void JoyCon2Controller::begin()
{
	USBDevice.setID(0x057e, JC2_PID);
	USBDevice.setVersion(0x0200);
	USBDevice.setDeviceVersion(0x0100);
	USBDevice.setManufacturerDescriptor("Nintendo");
	USBDevice.setProductDescriptor(JC2_PRODUCT);
	USBDevice.setSerialDescriptor("00");
	USBDevice.setConfigurationAttribute(0xc0);
	USBDevice.setConfigurationMaxPower(500);
	USBDevice.addInterface(g_jc2Usb);
	if (!g_jc2DrainRegistered) {
		usbTxRegisterDrain(joyCon2Drain);
		g_jc2DrainRegistered = true;
	}
}

void JoyCon2Controller::onReport45(int slot, const uint8_t *rep, bool fresh,
				  uint8_t bodyTlen)
{
	(void)rep;
	(void)fresh;
	(void)bodyTlen;
	if (slot >= 0 && slot < NSLOT)
		g_jc2Bond = (int8_t)slot;
}

void JoyCon2Controller::task()
{
	// Raw HID/vendor sends are drained through usbTxPump via joyCon2Drain().
}
