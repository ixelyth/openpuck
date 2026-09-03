#!/usr/bin/env python3
"""Apply the F27-M2 Joy-Con 2 forced-mouse experiment.

Run after tools/f27_joycon2_poc.py and tools/f27_joycon2_m1.py. M2 changes
only the local mouse-generation gate: the native mouse payload is generated
from the Steam trackpad even if negotiated feature bit 0x10 is not enabled.
All M1 feature-negotiation/status behavior and mouse payload encoding remain
unchanged so the hardware result isolates the feature-enable gate.
"""
from pathlib import Path

PATH = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M2 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
src = replace_once(
    src,
    "\tbool requestedMouse = (features & 0x10u) != 0;\n",
    "\t// M2 discriminator: generate the native mouse block regardless of\n"
    "\t// whether the console enabled feature bit 0x10. Negotiation state is\n"
    "\t// still tracked normally; only this local generation gate is bypassed.\n"
    "\tbool requestedMouse = true;\n",
    "mouse feature gate",
)
PATH.write_text(src, encoding="utf-8")
print("F27-M2 Joy-Con 2 forced-mouse hook applied")
