#!/usr/bin/env python3
from pathlib import Path

parts = sorted((Path(__file__).parent / "f27_m15_parts").glob("part*.pyfrag"))
if not parts:
    raise SystemExit("M15 script fragments missing")
code = "".join(p.read_text(encoding="utf-8") for p in parts)
exec(compile(code, "f27_switch2pro_m15.py", "exec"))
