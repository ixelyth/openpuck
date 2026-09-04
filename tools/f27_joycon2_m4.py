#!/usr/bin/env python3
"""Apply the F27-M4 Joy-Con 2 R-stick encoding experiment.

Run after tools/f27_joycon2_poc.py and the M1/M2/M3 hooks. M4 changes only
how the native Joy-Con 0x07/0x08 analog-stick field is encoded: use the
calibration-compatible 0x200..0xE00 range around 0x800 and the native Joy-Con
Y orientation used by the working reference implementation. Mouse/button/
identity/feature/carrier behavior remains exactly M3.
"""
from pathlib import Path

PATH = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M4 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
old = """static void packStick(uint8_t out[3], int16_t x, int16_t y)
{
\tuint16_t sx = (uint16_t)(((int32_t)x + 32768) >> 4);
\tuint16_t sy = (uint16_t)(((int32_t)y + 32768) >> 4);
\tout[0] = (uint8_t)sx;
\tout[1] = (uint8_t)((sx >> 8) | (sy << 4));
\tout[2] = (uint8_t)(sy >> 4);
}
"""
new = """static uint16_t joyconStick12(int16_t v, bool invert)
{
\tint32_t delta = invert ? -(int32_t)v : (int32_t)v;
\tint32_t scaled = 0x800;
\tif (delta > 0)
\t\tscaled += (delta * 0x600) / 32767;
\telse if (delta < 0)
\t\tscaled += (delta * 0x600) / 32768;
\tif (scaled < 0x200)
\t\tscaled = 0x200;
\telse if (scaled > 0xe00)
\t\tscaled = 0xe00;
\treturn (uint16_t)scaled;
}

static void packStick(uint8_t out[3], int16_t x, int16_t y)
{
\tuint16_t sx = joyconStick12(x, false);
\tuint16_t sy = joyconStick12(y, true);
\tout[0] = (uint8_t)sx;
\tout[1] = (uint8_t)((sx >> 8) | (sy << 4));
\tout[2] = (uint8_t)(sy >> 4);
}
"""
src = replace_once(src, old, new, "stick encoder")
PATH.write_text(src, encoding="utf-8")
print("F27-M4 Joy-Con 2 R-stick encoding hook applied")
