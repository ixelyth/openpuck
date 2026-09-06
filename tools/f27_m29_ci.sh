#!/usr/bin/env bash
set -euo pipefail

ORDER="${1:?usage: f27_m29_ci.sh R-L|L-R r384|r385}"
REV="${2:?usage: f27_m29_ci.sh R-L|L-R r384|r385}"
case "$ORDER" in
  R-L) SESSION0=JCR; ROLE_TAG=JCR-JCL; TRACE_SOURCE="M27-M29-JCR-JCL-${REV}-raw"; TRACE_MAGIC=0x4c52344dUL ;;
  L-R) SESSION0=JCL; ROLE_TAG=JCL-JCR; TRACE_SOURCE="M27-M29-JCL-JCR-${REV}-raw"; TRACE_MAGIC=0x524c354dUL ;;
  *) echo "bad ORDER=$ORDER" >&2; exit 2 ;;
esac

M27_AUTH=ec35b5a1a1f454ca48e3b70e5fd973db32e608c3
M28G_AUTH=94242a5f36ba4664ecd66590aedc546bd8a8a62c
MDK_AUTH=96721b9bf50fbb92fc956853b8ef73dcf2ae973c

# Makerdiary build support only.
git fetch origin "$MDK_AUTH"
git cherry-pick --no-commit "$MDK_AUTH"
test -z "$(git diff --name-only --diff-filter=U)"

# Recover the exact pinned ingredients used by the accepted M27/M28G line.
git fetch origin \
  b6bce4d387433372f480593bd28de506ff0b5368 \
  1fecb47401ed9fb7bdb22b8c6fe4707575411250 \
  2f990e0f3e9401a734427e23e8223f2b9f1be799 \
  5bf3b6f7f57f1ba5c131ca7e1c393a7aa85bb0d8 \
  fb3ac5f57a2d379b8849d84637c956c05e4a204e \
  fee33e5e57263074a79f11c8e49382ab0c3a6005 \
  c2019a50b59098f3564c792ef017de3fe885d140
mkdir -p tools/f27_m15_parts

git show b6bce4d387433372f480593bd28de506ff0b5368:tools/f27_switch2pro_m15.py > tools/f27_switch2pro_m15.py
for n in 00 01 02 03 04 05 06 07; do
  git show b6bce4d387433372f480593bd28de506ff0b5368:tools/f27_m15_parts/part${n}.pyfrag > tools/f27_m15_parts/part${n}.pyfrag
done
git show 1fecb47401ed9fb7bdb22b8c6fe4707575411250:OpenPuck/f27_joycon2.cpp > OpenPuck/f27_joycon2.cpp
git show 1fecb47401ed9fb7bdb22b8c6fe4707575411250:OpenPuck/f27_joycon2.h > OpenPuck/f27_joycon2.h
git show 2f990e0f3e9401a734427e23e8223f2b9f1be799:tools/f27_switch2pro_m21.py > tools/f27_switch2pro_m21.py
git show 5bf3b6f7f57f1ba5c131ca7e1c393a7aa85bb0d8:tools/f27_switch2pro_m22.py > tools/f27_switch2pro_m22.py
git show fb3ac5f57a2d379b8849d84637c956c05e4a204e:tools/f27_switch2pro_m25.py > tools/f27_switch2pro_m25.py
git show fee33e5e57263074a79f11c8e49382ab0c3a6005:tools/f27_m27_persistent_trace.py > tools/f27_m27_persistent_trace.py
git show fee33e5e57263074a79f11c8e49382ab0c3a6005:tools/f27_m27_trace_transform_fixup.py > tools/f27_m27_trace_transform_fixup.py
git show fee33e5e57263074a79f11c8e49382ab0c3a6005:tools/f27_m27_r377_rf_gate_runtime.py > tools/f27_m27_r377_rf_gate_runtime.py
git show c2019a50b59098f3564c792ef017de3fe885d140:tools/f27_m27_r378_raw_trace.py > tools/f27_m27_r378_raw_trace.py

# Exact M27 reconstruction, then format before freezing reference text.
python3 tools/f27_switch2pro_m15.py
python3 tools/f27_switch2pro_m21.py
python3 tools/f27_switch2pro_m22.py
python3 tools/f27_switch2pro_m25.py
python3 tools/f27_switch2pro_m27.py
make format
make check
git add -N OpenPuck/f27_joycon2.cpp OpenPuck/f27_joycon2.h
git diff --check

# Apply the already hardware-positive r383/M28G delta exactly.
python3 tools/f27_m28g_grip_context.py
make format
make check
git add -N OpenPuck/f27_joycon2.cpp OpenPuck/f27_joycon2.h
git diff --check
cp OpenPuck/mode_switch2_pro.cpp /tmp/m28g-mode.cpp
cp OpenPuck/f27_joycon2.cpp /tmp/m28g-joy.cpp
cp OpenPuck/f27_joycon2.h /tmp/m28g-joy.h
cp OpenPuck/OpenPuck.ino /tmp/m28g-ino
cp OpenPuck/config.cpp /tmp/m28g-config
cp OpenPuck/bonds.cpp /tmp/m28g-bonds
cp Makefile /tmp/m28g-Makefile

# Convert only the conceptual session-side assignment.
python3 tools/f27_m29_pair_roles.py --session0 "$SESSION0"
make format
make check
git add -N OpenPuck/f27_joycon2.cpp OpenPuck/f27_joycon2.h
git diff --check
cp OpenPuck/mode_switch2_pro.cpp /tmp/m29-mode.cpp
cp OpenPuck/f27_joycon2.cpp /tmp/m29-joy.cpp

# Add the accepted RAM observer + isolated raw-page persistence mechanism.
python3 tools/f27_m27_trace_transform_fixup.py
python3 tools/f27_m27_persistent_trace.py
python3 tools/f27_m27_r377_rf_gate_runtime.py
python3 tools/f27_m27_r378_raw_trace.py
sed -i "s/M27-working-r378-raw/${TRACE_SOURCE}/g" OpenPuck/mode_switch2_pro.cpp
sed -i "s/0x3837544DUL/${TRACE_MAGIC}/g" OpenPuck/mode_switch2_pro.cpp
make format
make check
git add -N OpenPuck/f27_joycon2.cpp OpenPuck/f27_joycon2.h
git diff --check

# Scope and provenance proofs.
grep -q 'F27-M27-PROVEN-SESSION1-LEFT-JCR' OpenPuck/mode_switch2_pro.cpp
grep -q 'F27-M28G-GRIP-CONTEXT' OpenPuck/mode_switch2_pro.cpp
grep -q "F27-M29-${ROLE_TAG}-PAIR" OpenPuck/mode_switch2_pro.cpp
grep -q 'M28G_CHARGING_GRIP_FACTORY' OpenPuck/mode_switch2_pro.cpp
grep -q 'HDL50003485519' OpenPuck/mode_switch2_pro.cpp
grep -q 'm28HandleChargingGrip' OpenPuck/mode_switch2_pro.cpp
grep -q 'm29SessionNativeReport' OpenPuck/mode_switch2_pro.cpp
grep -q 'm29SessionPidLow' OpenPuck/mode_switch2_pro.cpp
grep -q 'm29SessionFirmwareType' OpenPuck/mode_switch2_pro.cpp
grep -q 'f27JoyconBuildM29Left' OpenPuck/f27_joycon2.cpp
grep -q "source=${TRACE_SOURCE}" OpenPuck/mode_switch2_pro.cpp
grep -q 'sess=%u' OpenPuck/mode_switch2_pro.cpp
grep -q 'M27_TRACE_RAW_PAGE = 0x000EB000UL' OpenPuck/mode_switch2_pro.cpp
grep -q "M27_TRACE_RAW_MAGIC = ${TRACE_MAGIC}" OpenPuck/mode_switch2_pro.cpp
grep -q 'strcmp(line, "JT")' OpenPuck/serial_console.cpp
grep -q 'strcmp(line, "JC")' OpenPuck/serial_console.cpp
! grep -q 'M27_TRACE_FILE' OpenPuck/mode_switch2_pro.cpp
! grep -q 'M27_TRACE_TAG' OpenPuck/mode_switch2_pro.cpp
! grep -q 'Adafruit_LittleFS' OpenPuck/mode_switch2_pro.cpp
! grep -q 'InternalFileSystem' OpenPuck/mode_switch2_pro.cpp
! grep -q 'InternalFS' OpenPuck/mode_switch2_pro.cpp
cmp -s /tmp/m28g-ino OpenPuck/OpenPuck.ino || { echo 'M29 changed OpenPuck.ino'; exit 1; }
cmp -s /tmp/m28g-config OpenPuck/config.cpp || { echo 'M29 changed config.cpp'; exit 1; }
cmp -s /tmp/m28g-bonds OpenPuck/bonds.cpp || { echo 'M29 changed bonds.cpp'; exit 1; }
cmp -s /tmp/m28g-Makefile Makefile || { echo 'M29 changed Makefile'; exit 1; }

python3 - "$ORDER" <<'PY'
from pathlib import Path
import re, sys
order=sys.argv[1]
before=Path('/tmp/m28g-mode.cpp').read_text()
after=Path('OpenPuck/mode_switch2_pro.cpp').read_text()
joy_before=Path('/tmp/m28g-joy.cpp').read_text()
joy_after=Path('OpenPuck/f27_joycon2.cpp').read_text()

def compact(s): return re.sub(r'\s+', '', s)
def arr(src,name):
    m=re.search(r'static const uint8_t '+re.escape(name)+r'\[[^\]]*\] = \{.*?\n\};',src,re.S)
    if not m: raise SystemExit('missing array '+name)
    return compact(m.group(0))
for name in ('SWITCH2_PRO_HID_DESC','SWITCH2_PRO_CFG_BODY','SW2_VENDOR_IDENTITY','SW2_VENDOR_PROTOCOL','M28G_CHARGING_GRIP_FACTORY'):
    if arr(before,name) != arr(after,name):
        raise SystemExit('M29 changed frozen transport/grip array '+name)

def fn(src,name):
    m=re.search(r'bool\s+'+re.escape(name)+r'\([^\{]*\)\s*\{.*?\n\}',src,re.S)
    if not m: raise SystemExit('missing function '+name)
    return compact(m.group(0))
# The original hardware-positive native JCR builder and M27 helper stay textually unchanged.
for name in ('f27JoyconBuildNative','f27JoyconBuildM27Session1Left'):
    if fn(joy_before,name) != fn(joy_after,name):
        raise SystemExit('M29 changed frozen M27 Joy-Con builder '+name)
# Switch-2-only side facts.
if '0x01,0x00,0x0e,0x00,0x0c,0x00' not in compact(after):
    raise SystemExit('missing Joy-Con 2 firmware 1.0.14 response')
if order == 'R-L':
    checks=('returnsession==M15_SW2_PRO;', 'session0=')
    if 'returnsession==M15_SW2_PRO;' not in compact(after):
        raise SystemExit('R-L side assignment missing')
else:
    if 'returnsession==M15_SW2_JOYCON_R;' not in compact(after):
        raise SystemExit('L-R side assignment missing')
print('M29 pair scope/provenance PASS', order)
PY

SHORT="${GITHUB_SHA::8}"
OUT_BASE="OpenPuck-F27-M29-${REV}-${ROLE_TAG}-MDK"
OPK_BUILD_VERSION="F27-M29-${REV}-${ROLE_TAG}-${SHORT}" ./gen_version.sh
make build-mdk EXTRA_FLAGS="-DOPK_F27_JOYCON_TARGET=2"
./gen_uf2.sh build/mdk/OpenPuck.ino.hex "build/mdk/${OUT_BASE}.uf2"

python3 - "$ORDER" "$REV" "$OUT_BASE" "$TRACE_SOURCE" <<'PY'
from pathlib import Path
import hashlib, struct, sys, os
order,rev,out_base,source=sys.argv[1:]
p=Path('build/mdk')/(out_base+'.uf2')
data=p.read_bytes(); image=bytearray(); seen=[]; total=None; fam=None; lo=0xffffffff; hi=0
if len(data)%512: raise SystemExit('bad UF2 length')
for off in range(0,len(data),512):
    b=data[off:off+512]
    m0,m1,flags,addr,size,no,nblocks,family=struct.unpack_from('<IIIIIIII',b,0)
    if (m0,m1)!=(0x0A324655,0x9E5D5157): raise SystemExit('bad UF2 magic')
    if total is None: total=nblocks; fam=family
    if nblocks!=total or family!=fam: raise SystemExit('UF2 metadata mismatch')
    seen.append(no); lo=min(lo,addr); hi=max(hi,addr+size)
    if addr>=0x26000: image += b[32:32+size]
if seen != list(range(total)): raise SystemExit('nonsequential UF2')
if hi > 0xEB000: raise SystemExit(f'UF2 reaches raw trace page: {hi:#x}')
role='JCR-JCL' if order=='R-L' else 'JCL-JCR'
short=os.environ['GITHUB_SHA'][:8].encode()
need=[
    ('F27-M29-'+rev+'-'+role+'-'+os.environ['GITHUB_SHA'][:8]).encode(),
    b'F27-M27-PROVEN-SESSION1-LEFT-JCR', b'F27-M28G-GRIP-CONTEXT',
    ('F27-M29-'+role+'-PAIR').encode(), b'HDL50003485519',
    source.encode(), b'# JT begin', b'Switch 2 Pro Controller'
]
for needle in need:
    if needle not in image: raise SystemExit('missing binary marker '+repr(needle))
for bad in (b'/jc2trace',b'/jc2mode'):
    if bad in image: raise SystemExit('forbidden persistence path '+repr(bad))
print('sha256',hashlib.sha256(data).hexdigest())
print('blocks',total,'family',hex(fam),'bytes',len(data),'range',hex(lo)+'..'+hex(hi))
PY

MANIFEST="build/mdk/F27-M29-${REV}-${ROLE_TAG}.manifest.txt"
cat > "$MANIFEST" <<EOF
source_commit=${GITHUB_SHA}
frozen_hardware_authority=${M27_AUTH}
hardware_positive_grip_baseline=${M28G_AUTH}
makerdiary_build_authority=${MDK_AUTH}
composition=M27 exact pinned recipe + hardware-positive M28G session hardening/grip context + M29 coherent Joy-Con 2 role assignment
session_order=${ROLE_TAG}
physical_usb_shell=Switch 2 Pro 057E:2069 (unchanged M27 transport)
logical_session0=${SESSION0}
logical_session1=$([ "$SESSION0" = JCR ] && echo JCL || echo JCR)
joycon2_side_semantics=PID 2066/2067; native report 08/07; command 10 firmware 1.0.14 type R=1 L=0; Switch-2-specific sources only
joycon1_authority=NONE
charging_grip_context=hardware-positive r383 responder; serial HDL50003485519; VID:PID 057E:2068
trace=S/R/C/B/G/O raw page 0xEB000; source ${TRACE_SOURCE}; no experimental filesystem writes
purpose=test whether complementary JCR/JCL sessions behind proven M27 shell cause Switch 2 to address/unify both sides; compare reversed role order separately
required_test=verify Steam bond; note visible controller type/input; exercise both trackpads; leave >=20s; retrieve JT before JC; return to control and verify bond survives
do_not=do not use staged WebUSB firmware update; do not run JC before JT
EOF
sha256sum "build/mdk/${OUT_BASE}.uf2" >> "$MANIFEST"

echo "OUT_BASE=${OUT_BASE}" >> "$GITHUB_ENV"
echo "MANIFEST=${MANIFEST}" >> "$GITHUB_ENV"
