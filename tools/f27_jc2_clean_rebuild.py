#!/usr/bin/env python3
"""Compose one Joy-Con 2 rebuild stage from pristine upstream runtime sources.

This is intentionally NOT a mutation of G5/G5-R1/G5-R2.  CI checks out the
29f4d1e8 upstream-equivalent branch, applies only the Makerdiary build-support
commit, then runs this generator for exactly one stage.

Stages in the first hardware batch:
  0 - upstream HORIPAD control, forced at boot; no Joy-Con source at all.
  1 - clean JCR 057E:2066, one stock Adafruit HID using a generic gamepad
      descriptor; no descriptor wrappers and no custom TinyUSB class driver.
  2 - stage 1, but replace only the HID report descriptor with the captured
      100-byte Joy-Con 2 R descriptor (native 0x08/common 0x05/output 0x01).
  3 - stage 2, plus only a device-descriptor callback wrapper that changes
      bDeviceClass/SubClass/Protocol to EF/02/01.  Still one stock HID; no
      configuration wrapper, no custom class driver, no vendor interface.

The next batch (vendor interface -> endpoint open -> protocol) is intentionally
not composed until hardware identifies the first stable/failing boundary here.
"""

from argparse import ArgumentParser
from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: anchor count {count}, expected 1 in {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


ap = ArgumentParser()
ap.add_argument("--stage", type=int, required=True, choices=range(0, 4))
stage = ap.parse_args().stage

# Stage 0 is as close to pristine upstream runtime as possible.  The sole
# behavioral change is a build-only forced selection of the already-existing,
# historically hardware-positive HORIPAD mode so persisted config cannot make
# the control enumerate as some unrelated personality.
if stage == 0:
    replace_once(
        "OpenPuck/OpenPuck.ino",
        "\tloadCfg();\n\tloadBonds();\n",
        "\tloadCfg();\n"
        "#if defined(OPK_JC2_REBUILD_STAGE) && OPK_JC2_REBUILD_STAGE == 0\n"
        "\t// F27 clean rebuild S0: force an existing upstream USB personality only.\n"
        "\tg_usbMode = MODE_SW_HORI;\n"
        "\tapplyActiveType();\n"
        "#endif\n"
        "\tloadBonds();\n",
        "S0 force-control mode",
    )
    print("F27 Joy-Con clean rebuild stage 0 composed")
    raise SystemExit(0)

# Stages 1-3 add a NEW diagnostic mode, but do not copy the G5 implementation.
# Start with only the generic controller plumbing necessary to select it.
replace_once(
    "OpenPuck/config.h",
    "#define MODE_SINPUT 12\n#define MODE_MAX 12\n",
    "#define MODE_SINPUT 12\n"
    "// F27 clean Joy-Con 2 staged rebuild; diagnostics only.\n"
    "#define MODE_JOYCON2_REBUILD 13\n"
    "#define MODE_MAX 13\n",
    "mode id",
)
replace_once(
    "OpenPuck/config.h",
    "\tcase MODE_SW_HORI:\n\tcase MODE_SW_PRO:\n\t\treturn ET_SWITCH;\n",
    "\tcase MODE_SW_HORI:\n"
    "\tcase MODE_SW_PRO:\n"
    "\tcase MODE_JOYCON2_REBUILD:\n"
    "\t\treturn ET_SWITCH;\n",
    "switch emulated type",
)
replace_once(
    "OpenPuck/controllers.cpp",
    '#include "mode_xbox_og.h"\n',
    '#include "mode_xbox_og.h"\n#include "mode_joycon2_rebuild.h"\n',
    "controller include",
)
replace_once(
    "OpenPuck/controllers.cpp",
    "\tcase MODE_SINPUT:\n\t\treturn &g_sinputCtl;\n",
    "\tcase MODE_SINPUT:\n"
    "\t\treturn &g_sinputCtl;\n"
    "\tcase MODE_JOYCON2_REBUILD:\n"
    "\t\treturn &g_joyCon2Rebuild;\n",
    "controller dispatch",
)

# Keep the USB presentation clean (no wake mouse / WebUSB), force the new mode
# after config load, and extend the mode-serial suffix table.  Configuration
# attributes are deliberately left at upstream defaults in S1-S3; exact
# self-powered/500mA semantics belong to a later stage.
p = Path("OpenPuck/OpenPuck.ino")
text = p.read_text(encoding="utf-8")
old = "static const char MODE_SUFFIX[] = { 'X', 'N', 'L', 'P', 'S', 'G',\n\t\t\t\t    'Q', 'D', '3', 'O', 'J', 'I' };"
new = "static const char MODE_SUFFIX[] = { 'X', 'N', 'L', 'P', 'S', 'G',\n\t\t\t\t    'Q', 'D', '3', 'O', 'J', 'I', '2' };"
if text.count(old) != 1:
    raise SystemExit("mode suffix anchor mismatch")
text = text.replace(old, new, 1)
old = "\tloadCfg();\n\tloadBonds();\n"
new = (
    "\tloadCfg();\n"
    "#if defined(OPK_JC2_REBUILD_STAGE) && OPK_JC2_REBUILD_STAGE >= 1\n"
    "\t// F27 clean rebuild: deterministic staged JCR boot, independent of persisted mode.\n"
    "\tg_usbMode = MODE_JOYCON2_REBUILD;\n"
    "\tapplyActiveType();\n"
    "#endif\n"
    "\tloadBonds();\n"
)
if text.count(old) != 1:
    raise SystemExit("force-mode anchor mismatch")
text = text.replace(old, new, 1)
old = "\tconst bool psClean = modeIsCleanPS(g_usbMode);\n\tconst bool dynamic = g_active->dynamicMount();\n"
new = (
    "\tconst bool psClean = modeIsCleanPS(g_usbMode);\n"
    "\tconst bool joyConRebuildClean = g_usbMode == MODE_JOYCON2_REBUILD;\n"
    "\tconst bool dynamic = g_active->dynamicMount();\n"
)
if text.count(old) != 1:
    raise SystemExit("clean-mode anchor mismatch")
text = text.replace(old, new, 1)
old = "\t\tif (!puckMode && !keepCdc && !psClean)\n\t\t\twakeHidBegin();\n"
new = "\t\tif (!puckMode && !keepCdc && !psClean && !joyConRebuildClean)\n\t\t\twakeHidBegin();\n"
if text.count(old) != 1:
    raise SystemExit("wake-HID anchor mismatch")
text = text.replace(old, new, 1)
old = "\t\tif (!puckMode && !psClean)\n\t\t\tusb_web.begin();\n"
new = "\t\tif (!puckMode && !psClean && !joyConRebuildClean)\n\t\t\tusb_web.begin();\n"
if text.count(old) != 1:
    raise SystemExit("WebUSB anchor mismatch")
text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

header = r'''#pragma once
#include "controllers.h"

class JoyCon2RebuildController : public IController {
    public:
	void begin() override;
};

extern JoyCon2RebuildController g_joyCon2Rebuild;
'''
Path("OpenPuck/mode_joycon2_rebuild.h").write_text(header, encoding="utf-8")

source = r'''// mode_joycon2_rebuild.cpp -- clean staged Joy-Con 2 R reconstruction.
//
// This file is generated from upstream main for the F27 hardware bisect.  It is
// intentionally independent of the G5 implementation and adds one USB layer at
// a time.  S1/S2/S3 all use Adafruit_USBD_HID directly; there is no custom
// TinyUSB class driver and no Nintendo vendor interface in this first batch.
#include "mode_joycon2_rebuild.h"
#include "config.h"
#include <Adafruit_TinyUSB.h>
#include <Arduino.h>
#include <string.h>

#ifndef OPK_JC2_REBUILD_STAGE
#error "OPK_JC2_REBUILD_STAGE is required"
#endif
#if OPK_JC2_REBUILD_STAGE < 1 || OPK_JC2_REBUILD_STAGE > 3
#error "this source is only for clean rebuild stages 1..3"
#endif

JoyCon2RebuildController g_joyCon2Rebuild;

#define STR2(x) #x
#define STR(x) STR2(x)
static const char g_jc2RebuildMarker[] __attribute__((used)) =
	"F27-JC2-CLEAN-REBUILD-S" STR(OPK_JC2_REBUILD_STAGE);

// S1 intentionally uses a conventional, already-proven gamepad HID descriptor.
// This asks only whether a clean one-interface Adafruit HID survives under the
// JCR VID/PID/product identity.  It does NOT claim Joy-Con protocol behavior.
#if OPK_JC2_REBUILD_STAGE == 1
static const uint8_t JC2_STAGE_HID_DESC[] = {
	0x05, 0x01, 0x09, 0x05, 0xA1, 0x01, 0x15, 0x00, 0x25, 0x01, 0x35, 0x00,
	0x45, 0x01, 0x75, 0x01, 0x95, 0x10, 0x05, 0x09, 0x19, 0x01, 0x29, 0x10,
	0x81, 0x02, 0x05, 0x01, 0x25, 0x07, 0x46, 0x3B, 0x01, 0x75, 0x04, 0x95,
	0x01, 0x65, 0x14, 0x09, 0x39, 0x81, 0x42, 0x65, 0x00, 0x95, 0x01, 0x81,
	0x01, 0x26, 0xFF, 0x00, 0x46, 0xFF, 0x00, 0x09, 0x30, 0x09, 0x31, 0x09,
	0x32, 0x09, 0x35, 0x75, 0x08, 0x95, 0x04, 0x81, 0x02, 0x06, 0x00, 0xFF,
	0x09, 0x20, 0x95, 0x01, 0x81, 0x02, 0x0A, 0x21, 0x26, 0x95, 0x08, 0x91,
	0x02, 0xC0
};
#else
// S2+ replaces ONLY the report descriptor with the byte-exact published JCR
// descriptor: common input 0x05, native JCR input 0x08, output 0x01, 100 bytes.
static const uint8_t JC2_STAGE_HID_DESC[] = {
	0x05, 0x01, 0x09, 0x05, 0xa1, 0x01, 0x85, 0x05, 0x05, 0xff, 0x09,
	0x01, 0x15, 0x00, 0x26, 0xff, 0x00, 0x95, 0x3f, 0x75, 0x08, 0x81,
	0x02, 0x85, 0x08, 0x09, 0x01, 0x95, 0x02, 0x81, 0x02,
	0x05, 0x09, 0x19, 0x01, 0x29, 0x10, 0x25, 0x01, 0x95, 0x10, 0x75,
	0x01, 0x81, 0x02, 0x05, 0xff, 0x09, 0x01, 0x26, 0xff, 0x00, 0x95,
	0x01, 0x75, 0x08, 0x81, 0x02, 0x05, 0x01, 0x09, 0x01, 0xa1, 0x00,
	0x09, 0x30, 0x09, 0x31, 0x26, 0xff, 0x0f, 0x95, 0x02, 0x75, 0x0c,
	0x81, 0x02, 0xc0, 0x05, 0xff, 0x09, 0x02, 0x26, 0xff, 0x00, 0x95,
	0x37, 0x75, 0x08, 0x81, 0x02, 0x85, 0x01, 0x09, 0x01, 0x95, 0x3f,
	0x91, 0x02, 0xc0,
};
static_assert(sizeof JC2_STAGE_HID_DESC == 100,
	      "captured Joy-Con 2 R HID descriptor must remain 100 bytes");
#endif

static Adafruit_USBD_HID g_jc2StageHid;

#if OPK_JC2_REBUILD_STAGE >= 3
// S3 adds ONLY this wrapper.  Configuration descriptor generation, HID class
// ownership and all endpoints remain stock Adafruit/TinyUSB.
extern "C" uint8_t const *__real_tud_descriptor_device_cb(void);
extern "C" uint8_t const *__wrap_tud_descriptor_device_cb(void)
{
	uint8_t const *real = __real_tud_descriptor_device_cb();
	if (g_usbMode != MODE_JOYCON2_REBUILD || !real)
		return real;
	static tusb_desc_device_t d;
	memcpy(&d, real, sizeof d);
	d.bDeviceClass = 0xef;
	d.bDeviceSubClass = 0x02;
	d.bDeviceProtocol = 0x01;
	return (uint8_t const *)&d;
}
#endif

void JoyCon2RebuildController::begin()
{
	asm volatile("" : : "r"(g_jc2RebuildMarker) : "memory");
	USBDevice.setID(0x057e, 0x2066);
	USBDevice.setVersion(0x0200);
	USBDevice.setDeviceVersion(0x0100);
	USBDevice.setManufacturerDescriptor("Nintendo");
	USBDevice.setProductDescriptor("Joy-Con 2 (R)");
	USBDevice.setSerialDescriptor("00");
	g_jc2StageHid.enableOutEndpoint(true);
	g_jc2StageHid.setReportDescriptor(JC2_STAGE_HID_DESC,
					   sizeof JC2_STAGE_HID_DESC);
	g_jc2StageHid.setPollInterval(4);
	g_jc2StageHid.begin();
	USBDevice.addInterface(g_jc2StageHid);
}
'''
Path("OpenPuck/mode_joycon2_rebuild.cpp").write_text(source, encoding="utf-8")

if stage >= 3:
    replace_once(
        "Makefile",
        "OPENPUCK_LINK_FLAGS ?= -Wl,--wrap=tud_vendor_control_xfer_cb\n",
        "OPENPUCK_LINK_FLAGS ?= -Wl,--wrap=tud_vendor_control_xfer_cb "
        "-Wl,--wrap=tud_descriptor_device_cb\n",
        "S3 device descriptor wrapper",
    )

print(f"F27 Joy-Con clean rebuild stage {stage} composed")
