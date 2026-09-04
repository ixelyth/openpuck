#!/usr/bin/env python3
"""Apply F27-M12: feed the proven Joy-Con 2 R mouse contract from the LEFT Steam trackpad.

Run after the F27 POC and M1/M2/M3 hooks. M12 branches directly from the
hardware-working M3 Joy-Con 2 R baseline and changes only the mouse input source
inside buildSide(): the native Joy-Con 2 R report 0x08 personality, identity,
feature handling, mouse packet layout, stationary carrier, buttons, and cadence
remain unchanged, but touch/coordinates come from TB_LPADT + lpx/lpy instead of
the R-pad source.

This isolates whether the already-proven left Steam trackpad source can drive the
known-good R optical-mouse contract. It is diagnostic only.
"""
from pathlib import Path

PATH = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M12 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
src = replace_once(
    src,
    "\tbool touch = requestedMouse &&\n"
    "\t\t     (buttons & (right ? TB_RPADT : TB_LPADT));\n"
    "\tint16_t dx, dy;\n"
    "\tbool surface = padMouse(state, touch,\n"
    "\t\t\t\t right ? g_in[slot].rpx : g_in[slot].lpx,\n"
    "\t\t\t\t right ? g_in[slot].rpy : g_in[slot].lpy,\n"
    "\t\t\t\t &dx, &dy);",
    "\tbool touch = requestedMouse && (buttons & TB_LPADT);\n"
    "\tint16_t dx, dy;\n"
    "\tbool surface = padMouse(state, touch, g_in[slot].lpx,\n"
    "\t\t\t\t g_in[slot].lpy, &dx, &dy);",
    "left-pad source transplant",
)
PATH.write_text(src, encoding="utf-8")
print("F27-M12 left-pad source transplant applied")
