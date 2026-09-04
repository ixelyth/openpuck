#!/usr/bin/env python3
"""Apply the F27-M10 Joy-Con 2 R axis-coded mouse-feature discriminator.

Run after the F27 POC and M1/M2/M3 hooks. M10 branches directly from the
hardware-working M3 Joy-Con 2 R baseline. M9 used A/B as the observable, but
hardware showed synthesized face buttons are not observable during pointer
movement even though the pointer itself remains functional. The user confirmed
that the Joy-Con R shoulder action remains observable while mouse mode is active.

M10 therefore uses one known-observable button (R) and encodes tracked host
mouse-feature state by movement axis while leaving the proven native report 0x08
mouse payload unchanged:

  * feature bit 0x10 enabled  + predominantly HORIZONTAL right-pad movement -> R
  * feature bit 0x10 disabled + predominantly VERTICAL right-pad movement   -> R

The opposite axis intentionally produces no diagnostic R action. Test clean
horizontal and vertical swipes separately without pressing physical R/ZR.
This is diagnostic-only and must not be carried into production mappings.
"""
from pathlib import Path

PATH = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M10 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
old = """\tif (right)\n\t\trightButtons(slot, out + 2, surface);\n\telse\n\t\tleftButtons(slot, out + 2, surface);\n\tout[4] = 0x07;\n"""
new = """\tif (right)\n\t\trightButtons(slot, out + 2, surface);\n\telse\n\t\tleftButtons(slot, out + 2, surface);\n\n\t// M10 discriminator: use one mouse-compatible observable (R) and encode\n\t// tracked feature state by which movement axis is allowed to assert it.\n\tif (right && surface && (dx || dy)) {\n\t\tint32_t ax = dx < 0 ? -(int32_t)dx : (int32_t)dx;\n\t\tint32_t ay = dy < 0 ? -(int32_t)dy : (int32_t)dy;\n\t\tbool horizontal = ax > ay;\n\t\tbool vertical = ay > ax;\n\t\tif (((features & 0x10u) && horizontal) ||\n\t\t    (!(features & 0x10u) && vertical))\n\t\t\tout[2] |= 0x10; // R diagnostic action.\n\t}\n\tout[4] = 0x07;\n"""
src = replace_once(src, old, new, "axis-coded R mouse feature discriminator")
PATH.write_text(src, encoding="utf-8")
print("F27-M10 Joy-Con 2 R axis-coded mouse-feature discriminator applied")
