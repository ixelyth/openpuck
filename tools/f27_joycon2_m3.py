#!/usr/bin/env python3
"""Apply the F27-M3 Joy-Con 2 stationary-carrier experiment.

Run after tools/f27_joycon2_poc.py, tools/f27_joycon2_m1.py, and
tools/f27_joycon2_m2.py. M3 changes one thing relative to M2: whenever the
native optical-mouse surface is active, emit the 30-byte stationary motion
carrier even if negotiated IMU feature bit 0x04 is not set. The known-good
Joy-Con mouse implementation does this unconditionally while mouse mode is
active. All other M2/M1 behavior remains unchanged.
"""
from pathlib import Path

PATH = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M3 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
src = replace_once(
    src,
    "\tif (surface && (features & 0x04u)) {\n",
    "\t// M3 discriminator: genuine/known-good Joy-Con optical-mouse output\n"
    "\t// carries the stationary 30-byte motion block whenever mouse mode is\n"
    "\t// active, independently of the negotiated IMU-enable bit.\n"
    "\tif (surface) {\n",
    "stationary carrier gate",
)
PATH.write_text(src, encoding="utf-8")
print("F27-M3 Joy-Con 2 stationary-carrier hook applied")
