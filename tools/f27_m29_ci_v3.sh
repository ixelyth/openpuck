#!/usr/bin/env bash
set -euo pipefail

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sed 's#python3 tools/f27_m29_pair_roles.py --session0#python3 tools/f27_m29_pair_roles_v3.py --session0#' \
  tools/f27_m29_ci.sh > "$tmp"
bash -x "$tmp" "$@"
