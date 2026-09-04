#!/usr/bin/env python3
"""Apply the F27-M9 Joy-Con 2 R mouse-feature control discriminator.

Run after the F27 POC and M1/M2/M3 hooks. M9 branches directly from the
hardware-working M3 Joy-Con 2 R baseline. M8 established that the analogous
Joy-Con 2 L session keeps tracked feature bit 0x10 clear while its native mouse
pointer remains absent, but the working R session's feature state had never
been measured.

M9 therefore leaves the proven R native report 0x08 mouse path unchanged and
encodes only the tracked host mouse-feature state into face buttons while the
right Steam trackpad is actively producing mouse movement:

  * non-zero right-pad mouse movement + feature bit 0x10 enabled -> A
  * non-zero right-pad mouse movement + feature bit 0x10 disabled -> B

The actual M3 mouse pointer should continue to operate. This is diagnostic-only
and must not be carried into production mappings.
"""
from pathlib import Path

PATH = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M9 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
old = """\tif (right)\n\t\trightButtons(slot, out + 2, surface);\n\telse\n\t\tleftButtons(slot, out + 2, surface);\n\tout[4] = 0x07;\n"""
new = """\tif (right)\n\t\trightButtons(slot, out + 2, surface);\n\telse\n\t\tleftButtons(slot, out + 2, surface);\n\n\t// M9 control discriminator: compare tracked feature-bit state against the\n\t// hardware-working M3/R mouse session without changing its native payload.\n\tif (right && surface && (dx || dy)) {\n\t\tif (features & 0x10u)\n\t\t\tout[2] |= 0x02; // A: host enabled native mouse feature bit.\n\t\telse\n\t\t\tout[2] |= 0x01; // B: host has not enabled native mouse feature bit.\n\t}\n\tout[4] = 0x07;\n"""
src = replace_once(src, old, new, "R mouse feature discriminator")
PATH.write_text(src, encoding="utf-8")
print("F27-M9 Joy-Con 2 R mouse-feature control discriminator applied")
