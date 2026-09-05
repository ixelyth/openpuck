#!/usr/bin/env python3
"""Refresh F27-G5 with Joy-Con-specific protocol evidence.

G5 intentionally keeps uncertain behavior out of the hardware discriminator.
This pass removes values inherited from the earlier Pro2 transport scaffold and
uses only the currently published Joy-Con/Charging-Grip contracts.
"""
from pathlib import Path
import re

PATH = Path("OpenPuck/mode_joycon2.cpp")
src = PATH.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global src
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"G5 RE refresh {label}: anchor count {count}, expected 1")
    src = src.replace(old, new, 1)


# A wired Joy-Con reports external power in native report byte 1. Keep the
# battery-level nibble derived from the Steam controller, but set only the
# documented external-power flag; charging itself remains unknown.
replace_once(
    "\treturn (uint8_t)(level << 2);",
    "\treturn (uint8_t)((level << 2) | 0x01);",
    "native external-power flag",
)

# The public 0x130A8 calibration example is from a 057E:2069 factory block.
# Do not use it in a clean Joy-Con build. Unknown/user calibration reads remain
# erased (0xFF), which is preferable to fabricating side-specific values.
old_cal = """\t// Genuine captured Switch 2 primary-axis calibration sample. Calibration
\t// values are unit-specific; only the format and validity matter here.
\tstatic const uint8_t primaryCal[9] = {
\t\t0xb3, 0x67, 0x83, 0x2e, 0x66, 0x5e, 0x3a, 0x06, 0x5f,
\t};
\toverlay(address, block, len, 0x000130a8, primaryCal, sizeof primaryCal);
"""
replace_once(old_cal, "", "remove Pro2 calibration sample")

# Published Charging Grip 08/01, 08/02 and 08/03 replies use the normal ACK
# header (00 F8), even though the payload-bearing flash/FW replies use 10 78.
replace_once(
    "\tdataHeader(reply, 0x08, cmd[2], sub);",
    "\tackHeader(reply, 0x08, cmd[2], sub);",
    "Charging Grip reply header",
)

# Observed Joy-Con 2 R firmware-info payload: 1.0.14, controller type 1, no DSP
# version. Keep only controller_type side-dependent for the matching JCL build.
old_fw = """\t\t\tstatic const uint8_t info[12] = {
\t\t\t\t0x02, 0x01, 0x04, JC2_CONTROLLER_TYPE,
\t\t\t\t0x0c, 0x00, 0x00, 0x00,
\t\t\t\t0x02, 0x03, 0x00, 0x00,
\t\t\t};
"""
new_fw = """\t\t\tstatic const uint8_t info[12] = {
\t\t\t\t0x01, 0x00, 0x0e, JC2_CONTROLLER_TYPE,
\t\t\t\t0x0c, 0x00, 0x00, 0x00,
\t\t\t\t0xff, 0xff, 0xff, 0xff,
\t\t\t};
"""
replace_once(old_fw, new_fw, "Joy-Con firmware info")

# The previous proof-of-concept carried a Pro2-era device-level vendor-control
# blob and BT pairing responder. Neither is part of the published Joy-Con USB
# initialization sequence. Remove them rather than infer Joy-Con values.
proto_re = re.compile(
    r"\nstatic const uint8_t JOYCON2_VENDOR_PROTOCOL\[16\] = \{.*?\n\};\n",
    re.S,
)
src, n = proto_re.subn("\n", src, count=1)
if n != 1:
    raise SystemExit("G5 RE refresh: vendor-protocol block anchor mismatch")

pair_re = re.compile(
    r"\nstatic uint8_t g_jc2PairLtk\[16\];.*?\nstatic void buildVendorReply\(\)\n",
    re.S,
)
src, n = pair_re.subn("\nstatic void buildVendorReply()\n", src, count=1)
if n != 1:
    raise SystemExit("G5 RE refresh: pairing block anchor mismatch")

replace_once(
    "\tcase 0x15:\n\t\treplyLen = handlePairing(cmd, n, reply);\n\t\tbreak;\n",
    "",
    "remove USB pairing dispatch",
)

control_re = re.compile(
    r"bool joyCon2VendorControlXfer\(uint8_t rhport, uint8_t stage,\n"
    r"\s*const tusb_control_request_t \*request\)\n\{.*?\n\}\n\nstatic void driverInit\(\)",
    re.S,
)
control_stub = """bool joyCon2VendorControlXfer(uint8_t rhport, uint8_t stage,
                              const tusb_control_request_t *request)
{
\t(void)rhport;
\t(void)stage;
\t(void)request;
\treturn false;
}

static void driverInit()"""
src, n = control_re.subn(control_stub, src, count=1)
if n != 1:
    raise SystemExit("G5 RE refresh: device vendor-control anchor mismatch")

replace_once(
    "\tg_jc2GripButtonsEnabled = false;\n\tg_jc2PairLtkValid = false;\n\tg_jc2Bond = -1;",
    "\tg_jc2GripButtonsEnabled = false;\n\tg_jc2Bond = -1;",
    "pair reset removal",
)

PATH.write_text(src, encoding="utf-8")
print("F27-G5 current Joy-Con RE refresh applied")
