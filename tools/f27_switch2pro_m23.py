#!/usr/bin/env python3
"""F27-M23: convert the hidden M22 companion from Joy-Con 2 R to Joy-Con 2 L."""
from pathlib import Path

MODE = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M23 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = MODE.read_text(encoding="utf-8")
if "F27-M22-HIDDEN-JCR-LEFT-MOUSE" not in src:
    raise SystemExit("F27-M23 requires the composed M22 hidden companion route")
if "F27-M23-JCR-JCL-LEFT-MOUSE" in src:
    raise SystemExit("F27-M23 already applied")

src = replace_once(
    src,
    'static const char M22_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M22-HIDDEN-JCR-LEFT-MOUSE";\n',
    'static const char M22_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M22-HIDDEN-JCR-LEFT-MOUSE";\n'
    'static const char M23_BUILD_MARKER[] __attribute__((used)) =\n\t"F27-M23-JCR-JCL-LEFT-MOUSE";\n',
    "build marker",
)

# Exactly two sessions exist in this probe: index 0 is R, index 1 is L.
src = replace_once(
    src,
    "\t\t\tblock[pid - address] = 0x66;\n",
    "\t\t\tblock[pid - address] = g_sw2SessionCtx ? 0x67 : 0x66;\n",
    "companion factory PID 2067",
)

src = replace_once(
    src,
    '''\t\tif (sw2JoyconR()) {
\t\t\tif (cmd[8] == 0x05)
\t\t\t\tg_sw2ActiveReport = 0x05;
\t\t\telse if (cmd[8] == 0x08 || cmd[8] == 0x09)
\t\t\t\tg_sw2ActiveReport = 0x08;
\t\t} else if (cmd[8] == 0x05 || cmd[8] == 0x09) {
''',
    '''\t\tif (sw2JoyconR()) {
\t\t\tif (cmd[8] == 0x05)
\t\t\t\tg_sw2ActiveReport = 0x05;
\t\t\telse if (g_sw2SessionCtx == M15_SW2_JOYCON_R &&
\t\t\t\t (cmd[8] == 0x07 || cmd[8] == 0x09))
\t\t\t\tg_sw2ActiveReport = 0x07;
\t\t\telse if (g_sw2SessionCtx == M15_SW2_PRO &&
\t\t\t\t (cmd[8] == 0x08 || cmd[8] == 0x09))
\t\t\t\tg_sw2ActiveReport = 0x08;
\t\t} else if (cmd[8] == 0x05 || cmd[8] == 0x09) {
''',
    "session-aware report selection",
)

src = replace_once(
    src,
    "\t\tg_sw2ActiveReport = sw2JoyconR() ? 0x08 : 0x09;\n",
    "\t\tg_sw2ActiveReport = g_sw2SessionCtx ? 0x07 : 0x08;\n",
    "reset report default",
)

src = replace_once(
    src,
    "\t\tg_sw2Sessions[s].activeReport = 0x08;\n",
    "\t\tg_sw2Sessions[s].activeReport = s ? 0x07 : 0x08;\n",
    "beginPool report defaults",
)

src = replace_once(
    src,
    '''\t\tif (s == M15_SW2_JOYCON_R) {
\t\t\t// Force the unseen companion to native report 0x08.
\t\t\trid = 0x08;
\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);
''',
    '''\t\tif (s == M15_SW2_JOYCON_R) {
\t\t\t// M23 companion is Joy-Con 2 L, native report 0x07.
\t\t\trid = 0x07;
\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);
''',
    "hidden interrupt report 07",
)

src = replace_once(
    src,
    '''\t} else if (itf == M15_SW2_JOYCON_R) {
\t\tif (reportId == 0x08 || reportId == 0x09)
\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);
''',
    '''\t} else if (itf == M15_SW2_JOYCON_R) {
\t\tif (reportId == 0x07 || reportId == 0x09)
\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);
''',
    "hidden GET_REPORT 07",
)

src = replace_once(
    src,
    '\tasm volatile("" : : "r"(M22_BUILD_MARKER) : "memory");\n',
    '\tasm volatile("" : : "r"(M22_BUILD_MARKER) : "memory");\n'
    '\tasm volatile("" : : "r"(M23_BUILD_MARKER) : "memory");\n',
    "retain marker",
)

MODE.write_text(src, encoding="utf-8")
print("F27-M23 mixed Joy-Con-R + Joy-Con-L topology applied")
