#!/usr/bin/env python3
"""Apply the F27-M8 Joy-Con 2 L mouse-feature discriminator.

Run after the F27 POC and M1/M2/M3 hooks. M8 branches from the hardware-working
M3 baseline and targets Joy-Con 2 L. It does not alter native report 0x07 mouse
bytes, carrier, identity, or negotiation. M7 hardware proved the LEFT Steam
trackpad source/surface and lpx/lpy -> dx/dy path are live, but the console UI
could not reliably adjudicate the held Capture feature-bit diagnostic.

M8 therefore encodes host mouse-feature state into the already-proven
movement-triggered D-pad path:

  * any non-zero left-pad mouse movement + feature bit 0x10 enabled -> D-pad Up
  * any non-zero left-pad mouse movement + feature bit 0x10 disabled -> D-pad Down

This is diagnostic-only and must not be carried into production mappings.
"""
from pathlib import Path

PATH = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M8 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
old = """\tif (right)\n\t\trightButtons(slot, out + 2, surface);\n\telse\n\t\tleftButtons(slot, out + 2, surface);\n\tout[4] = 0x07;\n"""
new = """\tif (right)\n\t\trightButtons(slot, out + 2, surface);\n\telse\n\t\tleftButtons(slot, out + 2, surface);\n\n\t// M8 discriminator: M7 already proved the left-pad movement path. Encode\n\t// only the host mouse-feature state through that same observable D-pad path.\n\tif (!right && surface && (dx || dy)) {\n\t\tif (features & 0x10u)\n\t\t\tout[2] |= 0x08; // Up: host enabled native mouse feature bit.\n\t\telse\n\t\t\tout[2] |= 0x01; // Down: host has not enabled native mouse feature bit.\n\t}\n\tout[4] = 0x07;\n"""
src = replace_once(src, old, new, "mouse feature discriminator")
PATH.write_text(src, encoding="utf-8")
print("F27-M8 Joy-Con 2 L mouse-feature discriminator applied")
