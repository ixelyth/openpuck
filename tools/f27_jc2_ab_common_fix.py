#!/usr/bin/env python3
"""Common fix shared by both JC2 A/B variants.

Applied after f27_g5_integrate.py and f27_g5_re_refresh.py.  It fixes the
MODE_NAME[13] out-of-bounds read and replaces the old permanent forced mode
with a once-per-build Joy-Con startup so subsequent mode changes work normally.
"""
from pathlib import Path

p = Path("OpenPuck/OpenPuck.ino")
text = p.read_text(encoding="utf-8")

old = '\t\t"SINPUT(sdl-native)"\n\t};'
new = '\t\t"SINPUT(sdl-native)",\n\t\t"JOYCON2(jcr/jcl)"\n\t};'
count = text.count(old)
if count != 1:
    raise SystemExit(f"JC2 A/B MODE_NAME anchor count {count}, expected 1")
text = text.replace(old, new, 1)

old = (
    "\tloadCfg();\n"
    "#if defined(OPK_G5_FORCE_JOYCON2) && OPK_G5_FORCE_JOYCON2\n"
    "\tg_usbMode = MODE_JOYCON2;\n"
    "#endif\n"
    "\tloadBonds();\n"
)
new = (
    "\tloadCfg();\n"
    "#if defined(OPK_JC2_START_ONCE) && OPK_JC2_START_ONCE\n"
    "\t{\n"
    "\t\tstatic const char tagPath[] = \"/jc2mode\";\n"
    "\t\tchar tag[24] = { 0 };\n"
    "\t\tbool startJoyCon2 = true;\n"
    "\t\tFile f(InternalFS);\n"
    "\t\tif (f.open(tagPath, FILE_O_READ)) {\n"
    "\t\t\tint n = f.read((uint8_t *)tag, sizeof tag - 1);\n"
    "\t\t\tif (n > 0)\n"
    "\t\t\t\ttag[n] = 0;\n"
    "\t\t\tf.close();\n"
    "\t\t\tstartJoyCon2 = strncmp(tag, OPK_GIT_HASH, sizeof tag - 1) != 0;\n"
    "\t\t}\n"
    "\t\tif (startJoyCon2) {\n"
    "\t\t\tg_usbMode = MODE_JOYCON2;\n"
    "\t\t\tapplyActiveType();\n"
    "\t\t\tInternalFS.remove(tagPath);\n"
    "\t\t\tFile g(InternalFS);\n"
    "\t\t\tif (g.open(tagPath, FILE_O_WRITE)) {\n"
    "\t\t\t\tg.write((const uint8_t *)OPK_GIT_HASH, strlen(OPK_GIT_HASH));\n"
    "\t\t\t\tg.close();\n"
    "\t\t\t}\n"
    "\t\t}\n"
    "\t}\n"
    "#endif\n"
    "\tloadBonds();\n"
)
count = text.count(old)
if count != 1:
    raise SystemExit(f"JC2 A/B force-mode anchor count {count}, expected 1")
text = text.replace(old, new, 1)

p.write_text(text, encoding="utf-8")
print("F27 JC2 A/B common fix applied")
