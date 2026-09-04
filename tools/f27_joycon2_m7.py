#!/usr/bin/env python3
"""Apply the F27-M7 Joy-Con 2 L mouse-path diagnostic.

Run after the F27 POC and M1/M2/M3 hooks. M7 branches from the hardware-working
M3 baseline and targets Joy-Con 2 L. It does not alter the native mouse payload,
carrier, identity, or negotiation. Instead it mirrors left-trackpad state into
already-working Joy-Con L buttons so hardware can distinguish three questions:

  * touch/source path: while the left pad is on-surface, hold Joy-Con L.
  * motion source: non-zero mouse dx/dy additionally assert D-pad directions.
  * host mouse feature state: while on-surface, feature bit 0x10 additionally
    asserts Capture.

The native 0x07 mouse fields remain exactly M3. This is diagnostic-only and must
not be carried into a production mapping.
"""
from pathlib import Path

PATH = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M7 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
old = """\tif (right)\n\t\trightButtons(slot, out + 2, surface);\n\telse\n\t\tleftButtons(slot, out + 2, surface);\n\tout[4] = 0x07;\n"""
new = """\tif (right)\n\t\trightButtons(slot, out + 2, surface);\n\telse\n\t\tleftButtons(slot, out + 2, surface);\n\n\t// M7 discriminator: expose the Joy-Con 2 L mouse source/feature state\n\t// through button paths already validated by hardware. Keep the native\n\t// 0x07 mouse payload itself untouched.\n\tif (!right && surface) {\n\t\tout[2] |= 0x10; // L: left-pad touch reached the builder.\n\t\tif (dx > 0)\n\t\t\tout[2] |= 0x02; // Right: positive mouse X delta.\n\t\telse if (dx < 0)\n\t\t\tout[2] |= 0x04; // Left: negative mouse X delta.\n\t\tif (dy > 0)\n\t\t\tout[2] |= 0x01; // Down: positive mouse Y delta.\n\t\telse if (dy < 0)\n\t\t\tout[2] |= 0x08; // Up: negative mouse Y delta.\n\t\tif (features & 0x10u)\n\t\t\tout[3] |= 0x01; // Capture: host enabled mouse feature bit.\n\t}\n\tout[4] = 0x07;\n"""
src = replace_once(src, old, new, "left mouse diagnostic")
PATH.write_text(src, encoding="utf-8")
print("F27-M7 Joy-Con 2 L mouse diagnostic hook applied")
