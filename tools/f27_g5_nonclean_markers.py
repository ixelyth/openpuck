#!/usr/bin/env python3
"""Rename inherited G5 clean markers after the non-clean conversion."""
from pathlib import Path

p = Path("OpenPuck/mode_joycon2.cpp")
text = p.read_text(encoding="utf-8")
repls = {
    '"F27-G5-CLEAN-JCL-GRIP08"': '"F27-JC2-LATEST-NONCLEAN-JCL"',
    '"F27-G5-CLEAN-JCR-GRIP08"': '"F27-JC2-LATEST-NONCLEAN-JCR"',
}
for old, new in repls.items():
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"nonclean marker anchor {old}: {count}, expected 1")
    text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")
print("F27 Joy-Con 2 non-clean markers applied")
