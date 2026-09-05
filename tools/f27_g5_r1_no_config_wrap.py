#!/usr/bin/env python3
"""F27-G5-R1: remove only the configuration-descriptor callback wrapper.

The clean G5 interface body still supplies the captured Joy-Con 2 two-interface
USB shape. This diagnostic leaves device/HID wrappers and all Joy-Con protocol
behavior unchanged, but lets Adafruit TinyUSB return its own completed
configuration header instead of copying/rewriting 80 bytes in a second wrapper.
"""
from pathlib import Path

p = Path("Makefile")
s = p.read_text(encoding="utf-8")
needle = " -Wl,--wrap=tud_descriptor_configuration_cb"
if s.count(needle) != 1:
    raise SystemExit(f"G5-R1 config-wrapper flag count {s.count(needle)}, expected 1")
s = s.replace(needle, "", 1)
p.write_text(s, encoding="utf-8")

print("F27-G5-R1 removed only tud_descriptor_configuration_cb link wrapper")
