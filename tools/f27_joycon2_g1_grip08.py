#!/usr/bin/env python3
"""G1: add authentic Joy-Con 2 Charging Grip command 0x08 behavior.

Run after the hardware-positive JCR composition and J2 full-common-report
transform. This experiment intentionally leaves USB PID, logical JCR identity,
report 0x05 payload, mouse suppression, motion suppression, and descriptors
unchanged. The only causal delta is the published Charging Grip vendor-command
family: 0x08/0x01, 0x08/0x02, and 0x08/0x03.
"""
from pathlib import Path

PATH = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"G1 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")

src = replace_once(
    src,
    "static volatile bool g_sw2VendorCommandPending = false;\n",
    "static const char G1_BUILD_MARKER[] __attribute__((used)) =\n"
    "\t\"F27-G1-JCR-FULL05-GRIP08\";\n"
    "static volatile bool g_sw2VendorCommandPending = false;\n"
    "static bool g_sw2GripButtonsEnabled = false;\n",
    "state/marker",
)

anchor = "static void sw2BuildVendorReply(void)\n{\n"
handler = r'''static const uint8_t SW2_CHARGING_GRIP_FACTORY[64] = {
	0x01, 0x00, 0x48, 0x44, 0x4c, 0x35, 0x30, 0x30,
	0x30, 0x33, 0x34, 0x38, 0x35, 0x35, 0x31, 0x39,
	0x00, 0x00, 0x7e, 0x05, 0x68, 0x20, 0x01, 0x03,
	0x01, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
	0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
};
static_assert(sizeof SW2_CHARGING_GRIP_FACTORY == 64,
	      "Charging Grip factory block must remain 64 bytes");

static uint8_t sw2HandleChargingGrip(const uint8_t *cmd, uint8_t n,
				      uint8_t *reply)
{
	const uint8_t sub = cmd[3];
	sw2DataHeader(reply, 0x08, cmd[2], sub);
	if (sub == 0x01 || sub == 0x03) {
		const uint8_t requested = sub == 0x01 ? 0x20 : 0x40;
		memset(reply + 8, 0, 4);
		memcpy(reply + 12, SW2_CHARGING_GRIP_FACTORY, requested);
		return (uint8_t)(12 + requested);
	}
	if (sub == 0x02) {
		if (n >= 9)
			g_sw2GripButtonsEnabled = cmd[8] != 0;
		return 8;
	}
	return 8;
}

static void sw2BuildVendorReply(void)
{
'''
src = replace_once(src, anchor, handler, "charging-grip handler")

src = replace_once(
    src,
    "\tcase 0x07:\n\t\treplyLen = sw2QueueDataHeader(id, seq, sub, reply);\n",
    "\tcase 0x08:\n"
    "\t\treplyLen = sw2HandleChargingGrip(cmd, n, reply);\n"
    "\t\tbreak;\n"
    "\tcase 0x07:\n"
    "\t\treplyLen = sw2QueueDataHeader(id, seq, sub, reply);\n",
    "vendor dispatch",
)

src = replace_once(
    src,
    "\tg_sw2FeatureMask = F27_JOYCON_INITIAL_FEATURE_MASK;\n"
    "\tg_sw2LastRumbleBond = -1;\n",
    "\tg_sw2FeatureMask = F27_JOYCON_INITIAL_FEATURE_MASK;\n"
    "\tg_sw2GripButtonsEnabled = false;\n"
    "\tg_sw2LastRumbleBond = -1;\n",
    "reset grip state",
)

src = replace_once(
    src,
    "\tif (g_usbMode != MODE_SW2_PRO || g_usbMountCount == 0)\n\t\treturn;\n\n"
    "\tif (g_sw2VendorCommandPending && !g_sw2VendorInFlight) {\n",
    "\tif (g_usbMode != MODE_SW2_PRO || g_usbMountCount == 0)\n"
    "\t\treturn;\n\n"
    "\tasm volatile(\"\" : : \"r\"(G1_BUILD_MARKER) : \"memory\");\n"
    "\tif (g_sw2VendorCommandPending && !g_sw2VendorInFlight) {\n",
    "retain marker",
)

PATH.write_text(src, encoding="utf-8")
print("F27-G1 Charging Grip 0x08 emulation applied")
