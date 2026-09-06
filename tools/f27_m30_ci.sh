#!/usr/bin/env bash
set -euo pipefail

# Derive r386 from the same accepted r384 composition driver, then inject only
# the forced-session1 discriminator before the accepted raw observer is applied.
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
python3 - <<'PY' > "$tmp"
from pathlib import Path
s=Path('tools/f27_m29_ci.sh').read_text()

s=s.replace('python3 tools/f27_m29_pair_roles.py --session0 "$SESSION0"',
            'python3 tools/f27_m29_pair_roles_v3.py --session0 "$SESSION0"\npython3 tools/f27_m30_force_session1_jcl.py', 1)
s=s.replace("grep -q 'HDL50003485519' OpenPuck/mode_switch2_pro.cpp\n", '', 1)
s=s.replace('python3 tools/f27_m27_r378_raw_trace.py',
            'python3 tools/f27_m27_r378_raw_trace.py\npython3 tools/f27_m30_trace_session1.py', 1)

old='R-L) SESSION0=JCR; ROLE_TAG=JCR-JCL; TRACE_SOURCE="M27-M29-JCR-JCL-${REV}-raw"; TRACE_MAGIC=0x4c52344dUL ;;'
new='R-L) SESSION0=JCR; ROLE_TAG=JCR-JCL; TRACE_SOURCE="M27-M30-FORCE-JCL-${REV}-raw"; TRACE_MAGIC=0x30334d52UL ;;'
if old not in s: raise SystemExit('M30 driver missing R-L trace anchor')
s=s.replace(old,new,1)

# Build/output labels become M30 while the inherited M29 source authority marker
# deliberately remains present and validated.
s=s.replace('F27-M29-${REV}', 'F27-M30-${REV}')
s=s.replace("('F27-M29-'+rev+'-'+role+'-'+os.environ['GITHUB_SHA'][:8]).encode()",
            "('F27-M30-'+rev+'-'+role+'-'+os.environ['GITHUB_SHA'][:8]).encode()", 1)

anchor="grep -q \"F27-M29-${ROLE_TAG}-PAIR\" OpenPuck/mode_switch2_pro.cpp\n"
extra=(anchor+
       "grep -q 'F27-M30-FORCE-SESSION1-JCL' OpenPuck/mode_switch2_pro.cpp\n"
       "grep -q 'm30MirrorSession0ToJcl' OpenPuck/mode_switch2_pro.cpp\n"
       "grep -q 'm30TraceSession1Event' OpenPuck/mode_switch2_pro.cpp\n")
if anchor not in s: raise SystemExit('M30 driver missing source-proof anchor')
s=s.replace(anchor,extra,1)

binary_anchor="    ('F27-M29-'+role+'-PAIR').encode(), b'HDL50003485519',\n"
if binary_anchor not in s: raise SystemExit('M30 driver missing binary-proof anchor')
s=s.replace(binary_anchor,
            "    ('F27-M29-'+role+'-PAIR').encode(), b'F27-M30-FORCE-SESSION1-JCL', b'HDL50003485519',\n",1)

print(s,end='')
PY

bash "$tmp" R-L r386

# Add explicit experiment semantics to the generated manifest.
cat >> build/mdk/F27-M30-r386-JCR-JCL.manifest.txt <<'EOF'
M30_delta=mirror session0 inputEnabled/featureMask/features/native-report gating into session1 while forcing session1 native report 0x07; no synthetic session1 Nintendo vendor commands
M30_trace=one-shot persisted I events: phase1 first not-ready; phase2 first ready; phase3 first TX attempt; phase4 first successful TinyUSB queue; each records rid/input/features/mask/session
M30_question=does Switch 2 accept/address a valid JCL native stream on HID instance 1 when its state is force-enabled behind the same USB device address?
M30_interpretation=phase4 present + no second controller strongly supports console ignoring second Nintendo HID session on one USB address; absence of phase2/3 means second HID endpoint never became host-ready
EOF
