#!/usr/bin/env python3
"""F27-M25: swap only controller address/serial identity roles over M22 R+R."""

from pathlib import Path

MODE = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M25 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = MODE.read_text(encoding="utf-8")
if "F27-M22-HIDDEN-JCR-LEFT-MOUSE" not in src:
    raise SystemExit("F27-M25 requires the composed M22 R+R left-pad probe")
if "F27-M23-JCR-JCL-LEFT-MOUSE" in src:
    raise SystemExit("F27-M25 must not compose heterogeneous M23")
if "F27-M24-ROLE-SWAP-JCR" in src:
    raise SystemExit("F27-M25 must not compose full-role-swap M24")
if "F27-M25-IDENTITY-SWAP-JCR" in src:
    raise SystemExit("F27-M25 already applied")

src = replace_once(
    src,
    'static const char M22_BUILD_MARKER[] __attribute__((used)) =\n'
    '\t"F27-M22-HIDDEN-JCR-LEFT-MOUSE";\n',
    'static const char M22_BUILD_MARKER[] __attribute__((used)) =\n'
    '\t"F27-M22-HIDDEN-JCR-LEFT-MOUSE";\n'
    'static const char M25_BUILD_MARKER[] __attribute__((used)) =\n'
    '\t"F27-M25-IDENTITY-SWAP-JCR";\n',
    "build marker",
)

# M21/M22 put the distinct companion controller address on session 1. M25 moves
# ONLY this identity role to session 0; all M22 HID payload/report/output routing
# remains unchanged.
src = replace_once(
    src,
    "\tif (g_sw2SessionCtx == M15_SW2_JOYCON_R)\n\t\tout[5] ^= 0x01u;",
    "\tif (g_sw2SessionCtx == M15_SW2_PRO)\n\t\tout[5] ^= 0x01u;",
    "companion controller address role",
)

src = replace_once(
    src,
    "\tif (g_sw2SessionCtx == M15_SW2_JOYCON_R) {\n"
    "\t\tconst uint32_t serialTail = 0x0001300fu;\n"
    "\t\tif (address <= serialTail && serialTail < address + len)\n"
    "\t\t\tblock[serialTail - address] = '1';\n"
    "\t}",
    "\tif (g_sw2SessionCtx == M15_SW2_PRO) {\n"
    "\t\tconst uint32_t serialTail = 0x0001300fu;\n"
    "\t\tif (address <= serialTail && serialTail < address + len)\n"
    "\t\t\tblock[serialTail - address] = '1';\n"
    "\t}",
    "companion factory serial role",
)

src = replace_once(
    src,
    '\tasm volatile("" : : "r"(M22_BUILD_MARKER) : "memory");\n',
    '\tasm volatile("" : : "r"(M22_BUILD_MARKER) : "memory");\n'
    '\tasm volatile("" : : "r"(M25_BUILD_MARKER) : "memory");\n',
    "retain marker",
)

MODE.write_text(src, encoding="utf-8")
print("F27-M25 identity-only Joy-Con-R role swap applied")
