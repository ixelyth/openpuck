#!/usr/bin/env python3
"""Apply the F27-M11 paired Joy-Con 2 R mouse-feature discriminator.

Run after the F27 POC and M1/M2/M3 hooks. M11 branches directly from the
hardware-working M3 Joy-Con 2 R baseline and changes only one diagnostic
observable: while the right Steam trackpad is actively producing non-zero mouse
movement, assert the already mouse-compatible Joy-Con R action only when the
tracked native mouse feature bit 0x10 matches the build-selected state.

The workflow builds two otherwise-identical firmware images:

  * M11-ON  (OPK_F27_M11_TRIGGER_ON_FEATURE=1): movement -> R only if 0x10 is ON
  * M11-OFF (OPK_F27_M11_TRIGGER_ON_FEATURE=0): movement -> R only if 0x10 is OFF

The actual M3 report 0x08 pointer path remains unchanged in both images. This is
strictly diagnostic and must not be carried into production mappings.
"""
from pathlib import Path

PATH = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M11 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
old = """\tif (right)\n\t\trightButtons(slot, out + 2, surface);\n\telse\n\t\tleftButtons(slot, out + 2, surface);\n\tout[4] = 0x07;\n"""
new = """\tif (right)\n\t\trightButtons(slot, out + 2, surface);\n\telse\n\t\tleftButtons(slot, out + 2, surface);\n\n\t// M11 paired discriminator: each build asserts the known mouse-compatible\n\t// R action only when tracked feature bit 0x10 matches that build's state.\n\tif (right && surface && (dx || dy)) {\n\t\tbool mouseFeatureOn = (features & 0x10u) != 0;\n\t\tbool triggerOnFeature = OPK_F27_M11_TRIGGER_ON_FEATURE != 0;\n\t\tif (mouseFeatureOn == triggerOnFeature)\n\t\t\tout[2] |= 0x10; // R diagnostic action.\n\t}\n\tout[4] = 0x07;\n"""
src = replace_once(src, old, new, "paired mouse feature discriminator")
PATH.write_text(src, encoding="utf-8")
print("F27-M11 paired Joy-Con 2 R mouse-feature discriminator applied")
