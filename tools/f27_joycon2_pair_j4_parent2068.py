#!/usr/bin/env python3
"""J4: expose USB parent PID 057E:2068 over the clean J1 JCL+JCR topology.

The two Nintendo-side logical/factory identities remain Joy-Con 2 R (2066)
and Joy-Con 2 L (2067). Only the physical USB device PID changes to 2068.
This is the closest single-address approximation of a Charging Grip parent
with complementary Joy-Con children without inventing undocumented hub data.
"""
from pathlib import Path

MODE = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"J4 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = MODE.read_text(encoding="utf-8")
if "F27-J1-JCL-JCR-PAIR" not in src:
    raise SystemExit("J4 requires the composed clean J1 JCL+JCR topology")
if "F27-J4-PARENT2068-JCLJCR" in src:
    raise SystemExit("J4 already applied")

src = replace_once(
    src,
    'static const char J1_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-J1-JCL-JCR-PAIR";\n',
    'static const char J1_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-J1-JCL-JCR-PAIR";\n'
    'static const char J4_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-J4-PARENT2068-JCLJCR";\n',
    "build marker",
)

# Change only the physical USB parent identity. J1's per-session Nintendo
# factory identities must remain 2066/2067 so this is not a repeat of J3.
src = replace_once(
    src,
    "\tUSBDevice.setID(0x057e, 0x2069);\n",
    "\tUSBDevice.setID(0x057e, 0x2068);\n",
    "physical parent VID/PID",
)

src = replace_once(
    src,
    '\tasm volatile("" : : "r"(J1_BUILD_MARKER) : "memory");\n',
    '\tasm volatile("" : : "r"(J1_BUILD_MARKER) : "memory");\n'
    '\tasm volatile("" : : "r"(J4_BUILD_MARKER) : "memory");\n',
    "retain J4 marker",
)

# Guard the causal contract: child identities remain distinct JCL/JCR.
if "block[pid - address] = g_sw2SessionCtx ? 0x67 : 0x66" not in src:
    raise SystemExit("J4 lost J1 2067/2066 per-session factory identity")
if 'Joy-Con 2 (L)' not in src:
    raise SystemExit("J4 lost JCL secondary identity")

MODE.write_text(src, encoding="utf-8")
print("J4 057E:2068 parent identity applied over clean JCL+JCR topology")
