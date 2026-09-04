#!/usr/bin/env python3
"""Apply the F27-M5 Joy-Con 2 R-stick source-path diagnostic.

Run after the F27 POC and M1/M2/M3 hooks. M5 branches from the hardware-working
M3 baseline and changes only right-side button construction: large Steam
right-stick axis deflections additionally assert already-proven Joy-Con face
button bits. The native 0x08 stick bytes remain exactly M3.

Diagnostic mapping at |axis| > 12000:
  rx positive -> same Joy-Con face bit produced by Steam A
  rx negative -> same Joy-Con face bit produced by Steam B
  ry positive -> same Joy-Con face bit produced by Steam X
  ry negative -> same Joy-Con face bit produced by Steam Y

This distinguishes a dead/wrong Steam source path from a Joy-Con stick-field or
console-calibration interpretation problem without perturbing the validated M3
mouse carrier, identity, feature negotiation, or stick encoding.
"""
from pathlib import Path

PATH = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M5 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
old = """\tif (b & TB_Y)\n\t\tb0 |= y;\n\n\tif (b & TB_R4)\n"""
new = """\tif (b & TB_Y)\n\t\tb0 |= y;\n\n\t// M5 discriminator: prove whether the Steam right-stick source reaches\n\t// the Joy-Con builder by translating large axis deflections into face\n\t// button bits whose console path is already hardware-validated.\n\tconst int16_t stickDiag = 12000;\n\tif (g_in[slot].rx > stickDiag)\n\t\tb0 |= a;\n\telse if (g_in[slot].rx < -stickDiag)\n\t\tb0 |= bb;\n\tif (g_in[slot].ry > stickDiag)\n\t\tb0 |= x;\n\telse if (g_in[slot].ry < -stickDiag)\n\t\tb0 |= y;\n\n\tif (b & TB_R4)\n"""
src = replace_once(src, old, new, "R-stick-to-face-button diagnostic")
PATH.write_text(src, encoding="utf-8")
print("F27-M5 Joy-Con 2 R-stick source diagnostic hook applied")
