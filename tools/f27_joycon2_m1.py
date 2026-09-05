#!/usr/bin/env python3
"""Apply the F27-M1 Joy-Con 2 mouse-negotiation experiment.

Run after tools/f27_joycon2_poc.py. M1 intentionally changes only the
Joy-Con feature handshake and the captured steady-state byte immediately
before the native optical-mouse block. Trackpad scaling/surface/motion logic
remains unchanged so hardware results isolate negotiation/state fidelity.
"""
from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M1 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, repl: str, label: str) -> str:
    out, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"F27-M1 {label}: regex count {count}, expected 1")
    return out


joy = Path("OpenPuck/f27_joycon2.cpp")
src = joy.read_text(encoding="utf-8")
src = replace_once(
    src,
    "\tout[4] = 0x07;\n",
    "\tout[4] = 0x07;\n\t// Captured steady-state Joy-Con 2 native status byte immediately\n"
    "\t// before the optical-mouse block. Real captures use 0x30 during\n"
    "\t// initialization and 0x38 during normal streaming.\n\tout[8] = 0x38;\n",
    "steady-state byte",
)
joy.write_text(src, encoding="utf-8")

mode = Path("OpenPuck/mode_switch2_pro.cpp")
src = mode.read_text(encoding="utf-8")

feature_info = r'''static void sw2FeatureInfo\(uint8_t flags, uint8_t out\[8\]\)\n\{.*?\n\}\n\n(?=static uint8_t sw2HandleUsbCommand)'''
feature_info_repl = '''static void sw2FeatureInfo(uint8_t flags, uint8_t out[8])
{
\tmemset(out, 0, 8);
\tif (flags & 0x01)
\t\tout[0] = 0x07;
\tif (flags & 0x02)
\t\tout[1] = 0x07;
\tif (flags & 0x04)
\t\tout[2] = f27JoyconEnabled() ? 0x03 : 0x01;
\tif (flags & 0x80)
\t\tout[3] = f27JoyconEnabled() ? 0x03 : 0x01;
\tif (flags & 0x10)
\t\tout[4] = f27JoyconEnabled() ? 0x03 : 0x01;
\tif (flags & 0x20)
\t\tout[5] = 0x03;
}

'''
src = regex_once(src, feature_info, feature_info_repl, "feature info")

feature_handler = r'''static uint8_t sw2HandleFeatures\(const uint8_t \*cmd, uint8_t n, uint8_t \*reply\)\n\{.*?\n\}\n\n(?=static void sw2BuildVendorReply)'''
feature_handler_repl = '''static uint8_t sw2HandleFeatures(const uint8_t *cmd, uint8_t n, uint8_t *reply)
{
\tuint8_t sub = cmd[3], flags = n >= 9 ? cmd[8] : 0;
\tsw2DataHeader(reply, 0x0c, cmd[2], sub);
\tif (f27JoyconEnabled()) {
\t\t// Captured Joy-Con 2 feature-select replies use 10 78 rather than
\t\t// the generic 00 F8 command status used by the Pro Controller 2.
\t\treply[4] = 0x10;
\t\treply[5] = 0x78;
\t}
\tif (sub == 0x01) {
\t\tsw2FeatureInfo(flags, reply + 12);
\t\treturn 20;
\t}
\tif (f27JoyconEnabled() && sub == 0x06) {
\t\t// Configure Features response shape captured from Joy-Con 2.
\t\tmemset(reply + 8, 0, 40);
\t\tif (n > 12)
\t\t\treply[12] = cmd[12];
\t\treturn 48;
\t}
\tif (sub == 0x02)
\t\tg_sw2FeatureMask = flags;
\telse if (sub == 0x03) {
\t\tg_sw2FeatureMask &= (uint8_t)~flags;
\t\tg_sw2Features &= (uint8_t)~flags;
\t} else if (sub == 0x04) {
\t\tg_sw2Features |= flags & g_sw2FeatureMask;
\t} else if (sub == 0x05) {
\t\tg_sw2Features &= (uint8_t)~flags;
\t}
\treturn 12;
}

'''
src = regex_once(src, feature_handler, feature_handler_repl, "feature handler")
mode.write_text(src, encoding="utf-8")
print("F27-M1 Joy-Con 2 mouse-negotiation hooks applied")
