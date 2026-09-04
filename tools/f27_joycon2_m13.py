#!/usr/bin/env python3
"""Apply F27-M13: Pro identity over the hardware-working M3/R mouse contract.

Run after the F27 POC and M1/M2/M3 hooks. M13 changes exactly one logical
protocol variable relative to M3: the Nintendo logical PID exposed through the
vendor identity/factory data is restored from Joy-Con 2 R (0x2066) to Switch 2
Pro (0x2069). The native input stream remains the known-working Joy-Con 2 R
report 0x08 mouse contract, including the right Steam trackpad source, M2
forced local mouse generation, M3 stationary carrier, buttons, stick packing,
and cadence.

This is an isolated identity-acceptance discriminator. It is not production
Switch 2 Pro mouse integration and must remain outside PR #269.
"""
from pathlib import Path

PATH = Path("OpenPuck/f27_joycon2.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M13 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = PATH.read_text(encoding="utf-8")
src = replace_once(
    src,
    "#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_R\n\treturn 0x66;\n",
    "#elif OPK_F27_JOYCON_TARGET == F27_JOYCON_R\n"
    "\t// M13 discriminator: retain the complete R/report-0x08 mouse stream\n"
    "\t// while presenting the logical Switch 2 Pro PID to the host.\n"
    "\treturn 0x69;\n",
    "logical PID",
)
PATH.write_text(src, encoding="utf-8")
print("F27-M13 Pro identity over R/report-0x08 mouse contract applied")
