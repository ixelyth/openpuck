#!/usr/bin/env python3
"""Replace r374's filesystem-backed one-shot mode tag with a RAM-only JCR start.

Apply after f27_jc2_ab_common_fix.py. The r374 Joy-Con protocol/runtime remains
unchanged; only the experimental mode-selection mechanism changes. No trace,
filesystem tag, raw flash writer, or persistence helper is introduced here.
"""
from pathlib import Path

p = Path("OpenPuck/OpenPuck.ino")
s = p.read_text(encoding="utf-8")

start = s.find("#if defined(OPK_JC2_START_ONCE) && OPK_JC2_START_ONCE\n")
if start < 0:
    raise SystemExit("R379: r374 OPK_JC2_START_ONCE block not found")
end_marker = "#endif\n\tloadBonds();\n"
end = s.find(end_marker, start)
if end < 0:
    raise SystemExit("R379: end of r374 startup block not found")
end += len("#endif\n")

replacement = (
    "#if defined(OPK_JC2_VOLATILE_START) && OPK_JC2_VOLATILE_START\n"
    "\t// R379 adjudication: enter JCR mode for this boot in RAM only.\n"
    "\t// Do not create/remove/write any persistent startup tag or save this override.\n"
    "\tg_usbMode = MODE_JOYCON2;\n"
    "\tapplyActiveType();\n"
    "#endif\n"
)
s = s[:start] + replacement + s[end:]

for forbidden in (
    '"/jc2mode"',
    "OPK_JC2_START_ONCE",
    "OPK_JC2_START_VARIANT",
):
    if forbidden in s:
        raise SystemExit(f"R379: forbidden filesystem-backed startup residue: {forbidden}")

if "OPK_JC2_VOLATILE_START" not in s:
    raise SystemExit("R379: volatile-start marker missing")

p.write_text(s, encoding="utf-8")
print("F27 JC2 r379 RAM-only r374 startup applied")
