#!/usr/bin/env python3
"""Fix the S1/S1P diagnostic mode-name table for MODE_JOYCON2_REBUILD=13.

The clean rebuild integration raised MODE_MAX to 13 and extended MODE_SUFFIX,
but left setup()'s MODE_NAME[] at entries 0..12. Because setup() indexes
MODE_NAME[g_usbMode] when g_usbMode <= MODE_MAX, forced mode 13 performed an
out-of-bounds read after USB attach. This transform adds exactly one entry for
mode 13 and changes no USB descriptor or controller behavior.
"""
from pathlib import Path

p = Path("OpenPuck/OpenPuck.ino")
text = p.read_text(encoding="utf-8")
old = (
    '\t\t"XBOX-OG(controller s)", "DINPUT(joystick+motion)",\n'
    '\t\t"SINPUT(sdl-native)"\n'
    '\t};\n'
)
new = (
    '\t\t"XBOX-OG(controller s)", "DINPUT(joystick+motion)",\n'
    '\t\t"SINPUT(sdl-native)",\n'
    '\t\t"JOYCON2-REBUILD(diag)"\n'
    '\t};\n'
)
count = text.count(old)
if count != 1:
    raise SystemExit(f"S1P mode-name anchor count {count}, expected 1")
p.write_text(text.replace(old, new, 1), encoding="utf-8")
print("F27 JC2 rebuild S1P mode-name table fix applied")
