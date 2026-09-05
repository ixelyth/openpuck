#!/usr/bin/env python3
"""Fix the diagnostic mode-name table for F27 Joy-Con 2 S1N.

The S1 integration adds MODE_JOYCON2_REBUILD=13 and MODE_MAX=13.  The
existing MODE_NAME table covers indices 0..12, so the forced diagnostic
mode would read MODE_NAME[13] out of bounds after USB attach.  This stage
changes only that table entry.
"""
from pathlib import Path

p = Path("OpenPuck/OpenPuck.ino")
text = p.read_text(encoding="utf-8")
old = '\t\t"SINPUT(sdl-native)"\n\t};'
new = '\t\t"SINPUT(sdl-native)",\n\t\t"JOYCON2-REBUILD(diagnostic)"\n\t};'
count = text.count(old)
if count != 1:
    raise SystemExit(f"S1N MODE_NAME anchor count {count}, expected 1")
p.write_text(text.replace(old, new, 1), encoding="utf-8")
print("F27 Joy-Con 2 S1N mode-table fix applied")
