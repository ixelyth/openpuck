#!/usr/bin/env python3
"""F27-M26: swap only periodic interrupt payload ownership over M25 R+R."""

from pathlib import Path

MODE = Path("OpenPuck/mode_switch2_pro.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"F27-M26 {label}: anchor count {count}, expected 1")
    return text.replace(old, new, 1)


src = MODE.read_text(encoding="utf-8")
if "F27-M22-HIDDEN-JCR-LEFT-MOUSE" not in src:
    raise SystemExit("F27-M26 requires the composed M22 hidden-left probe")
if "F27-M25-IDENTITY-SWAP-JCR" not in src:
    raise SystemExit("F27-M26 requires the composed M25 identity-only swap")
if "F27-M23-JCR-JCL-LEFT-MOUSE" in src:
    raise SystemExit("F27-M26 must not compose heterogeneous M23")
if "F27-M24-ROLE-SWAP-JCR" in src:
    raise SystemExit("F27-M26 must not compose full-role-swap M24")
if "F27-M26-INPUT-PAYLOAD-SWAP-JCR" in src:
    raise SystemExit("F27-M26 already applied")

src = replace_once(
    src,
    'static const char M25_BUILD_MARKER[] __attribute__((used)) =\n'
    '\t"F27-M25-IDENTITY-SWAP-JCR";\n',
    'static const char M25_BUILD_MARKER[] __attribute__((used)) =\n'
    '\t"F27-M25-IDENTITY-SWAP-JCR";\n'
    'static const char M26_BUILD_MARKER[] __attribute__((used)) =\n'
    '\t"F27-M26-INPUT-PAYLOAD-SWAP-JCR";\n',
    "build marker",
)

# M26 changes ONLY the periodic interrupt-IN payload builder ownership. M25
# address/serial roles stay fixed; M22 GET_REPORT, output/rumble ownership,
# descriptor order, report types, and input-enable behavior stay untouched.
old_drain = '''\t\tif (s == M15_SW2_JOYCON_R) {
\t\t\t// Force the unseen companion to native report 0x08.
\t\t\trid = 0x08;
\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);
\t\t} else if (rid == 0x05) {
\t\t\tsw2Build05((uint8_t)bond, p);
\t\t} else if (!f27JoyconBuildNative((uint8_t)bond, g_sw2Features, &rid, p)) {
\t\t\trid = 0x08;
\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);
\t\t}
'''
new_drain = '''\t\tif (s == M15_SW2_PRO) {
\t\t\t// M26 first function carries only the LEFT-pad mouse payload.
\t\t\trid = 0x08;
\t\t\tm22BuildHiddenLeftMouse((uint8_t)bond, p);
\t\t} else if (rid == 0x05) {
\t\t\t// M26 second function carries the unchanged live common payload.
\t\t\tsw2Build05((uint8_t)bond, p);
\t\t} else if (!f27JoyconBuildNative((uint8_t)bond, g_sw2Features, &rid, p)) {
\t\t\trid = 0x08;
\t\t\tsw2BuildJoyconRNeutral((uint8_t)bond, p);
\t\t}
'''
src = replace_once(src, old_drain, new_drain, "interrupt payload ownership")

src = replace_once(
    src,
    '\tasm volatile("" : : "r"(M25_BUILD_MARKER) : "memory");\n',
    '\tasm volatile("" : : "r"(M25_BUILD_MARKER) : "memory");\n'
    '\tasm volatile("" : : "r"(M26_BUILD_MARKER) : "memory");\n',
    "retain marker",
)

MODE.write_text(src, encoding="utf-8")
print("F27-M26 periodic interrupt payload-only Joy-Con-R swap applied")
