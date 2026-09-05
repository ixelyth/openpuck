#!/usr/bin/env python3
"""Remove the PR #249 raw-IMU reconnect write from legacy Switch Pro only.

This is a hardware diagnostic. Switch 2 Pro keeps the current PR #249 behavior;
all other reconnect, haptic, USB, report, and controller behavior is unchanged.
"""
from pathlib import Path

PATH = Path("OpenPuck/haptics.cpp")
OLD = "\tif (g_usbMode == MODE_SW_PRO || g_usbMode == MODE_SW2_PRO) {\n"
NEW = "\tif (g_usbMode == MODE_SW2_PRO) {\n"

src = PATH.read_text(encoding="utf-8")
count = src.count(OLD)
if count != 1:
    raise SystemExit(
        f"Switch Pro no-PR249 diagnostic: expected one reconnect gate, found {count}"
    )
PATH.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print("Switch Pro no-PR249 IMU reconnect diagnostic applied")
