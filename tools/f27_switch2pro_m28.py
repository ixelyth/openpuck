#!/usr/bin/env python3
"""F27-M28: synthetic native Joy-Con-R mouse source for distinct-device topology proof.

Run only after the exact hardware-positive M20/M3 Joy-Con-R composition. This
changes no Nintendo identity, report layout, negotiation, carrier, or session
semantics. It replaces only the physical Steam-pad source with a deterministic
left/right native mouse delta so the companion USB device needs no RF input.
"""

from pathlib import Path

PATH = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M28 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
if "bool requestedMouse = true;" not in src:
    raise SystemExit("F27-M28 requires the exact M20/M3 forced-mouse composition")
if "if (surface) {" not in src:
    raise SystemExit("F27-M28 requires the M3 unconditional stationary carrier")
if "F27-M28-DISTINCT-USB-JCR-SYNTH" in src:
    raise SystemExit("F27-M28 already applied")

src = replace_once(
    src,
    "static bool g_bothRight;\n",
    "static bool g_bothRight;\n"
    "static const char M28_BUILD_MARKER[] __attribute__((used)) =\n"
    "\t\"F27-M28-DISTINCT-USB-JCR-SYNTH\";\n",
    "build marker",
)

old = """\tbool requestedMouse = true;\n\tbool touch = requestedMouse &&\n\t\t     (buttons & (right ? TB_RPADT : TB_LPADT));\n\tint16_t dx, dy;\n\tbool surface = padMouse(state, touch,\n\t\t\t\t right ? g_in[slot].rpx : g_in[slot].lpx,\n\t\t\t\t right ? g_in[slot].rpy : g_in[slot].lpy,\n\t\t\t\t &dx, &dy);\n"""
new = """\tbool requestedMouse = true;\n\tint16_t dx, dy;\n#if defined(OPK_F27_M28_SYNTH_MOUSE) && OPK_F27_M28_SYNTH_MOUSE\n\t// M28 topology discriminator: keep the exact M20/M3 Joy-Con-R native\n\t// mouse contract, but make its motion source independent of RF input.\n\t// A slow quarter-second left/right sweep is unmistakable on HOME and\n\t// requires no second Steam Controller or inter-MCU transport yet.\n\tbool surface = right && requestedMouse;\n\tdx = surface ? ((state.counter & 0x40u) ? 1 : -1) : 0;\n\tdy = 0;\n#else\n\tbool touch = requestedMouse &&\n\t\t     (buttons & (right ? TB_RPADT : TB_LPADT));\n\tbool surface = padMouse(state, touch,\n\t\t\t\t right ? g_in[slot].rpx : g_in[slot].lpx,\n\t\t\t\t right ? g_in[slot].rpy : g_in[slot].lpy,\n\t\t\t\t &dx, &dy);\n#endif\n"""
src = replace_once(src, old, new, "mouse source")

src = replace_once(
    src,
    "\tif (!f27JoyconEnabled() || !reportId || !out || slot >= NSLOT)\n\t\treturn false;\n",
    "\tif (!f27JoyconEnabled() || !reportId || !out || slot >= NSLOT)\n\t\treturn false;\n"
    "\tasm volatile(\"\" : : \"r\"(M28_BUILD_MARKER) : \"memory\");\n",
    "retain marker",
)

PATH.write_text(src, encoding="utf-8")
print("F27-M28 distinct-device synthetic Joy-Con-R mouse source applied")
