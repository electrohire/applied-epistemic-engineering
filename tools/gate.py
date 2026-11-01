#!/usr/bin/env python3
"""Verification gate (Winning Combination, Stage 4).

Recomputes every downstream layer from the ledger and fails on any
divergence. The gate NEVER writes: on red, every previously published
artifact stays byte-untouched (pattern Amendment 1, corollary 5), and
a failing check is repaired in the downstream layer or the ledger --
never by loosening this gate (corollary 4).

  G1 intake: the ledger must pass its own intake (0 rejected).
  G2 matrix freshness: regeneration is byte-identical to the
     committed matrix.json / matrix.md.
  G3 evaluation: engine verdicts recompute with 0 violated, and the
     committed evaluation.json is byte-identical to a fresh render.
  G4 lossless regeneration: two independent matrix generations in
     this run produce byte-identical output.

The map joins this gate as G5 when Stage 5 lands it.

Usage: python3 tools/gate.py   (exit 0 iff GATE_RESULT PASS)
Wired into CI (the quality job in .github/workflows/ci.yml) and run
before any suite release or publication step in this program.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "program-ledger"
sys.dont_write_bytecode = True  # the gate writes nothing, not even .pyc caches
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def load_tool(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


intake = load_tool("ledger_intake", LEDGER_DIR / "intake.py")
build_matrix = load_tool("build_matrix", ROOT / "tools" / "build_matrix.py")
evaluate_mod = load_tool("evaluate", ROOT / "tools" / "evaluate.py")


def main() -> int:
    failures: list[str] = []

    accepted, rejected = intake.validate(
        LEDGER_DIR / "claims.jsonl", LEDGER_DIR / "components.json"
    )
    g1_ok = not rejected
    g1_status = "OK" if g1_ok else "FAIL"
    print(f"GATE G1 intake accepted={len(accepted)} rejected={len(rejected)} {g1_status}")
    if not g1_ok:
        failures.extend(rejected)

    rc = build_matrix.main(["--check"])
    print(f"GATE G2 matrix freshness {'OK' if rc == 0 else 'FAIL'}")
    if rc != 0:
        failures.append("G2 matrix drift")

    rc = evaluate_mod.main(["--check"])
    print(f"GATE G3 evaluation {'OK' if rc == 0 else 'FAIL'}")
    if rc != 0:
        failures.append("G3 evaluation violated or stale")

    data1 = build_matrix.build(LEDGER_DIR / "claims.jsonl", LEDGER_DIR / "components.json")
    data2 = build_matrix.build(LEDGER_DIR / "claims.jsonl", LEDGER_DIR / "components.json")
    j1 = json.dumps(data1, indent=2, sort_keys=True) + "\n"
    j2 = json.dumps(data2, indent=2, sort_keys=True) + "\n"
    m1 = build_matrix.render_md(data1)
    m2 = build_matrix.render_md(data2)
    g4_ok = j1 == j2 and m1 == m2
    print(f"GATE G4 lossless regeneration {'OK' if g4_ok else 'FAIL'}")
    if not g4_ok:
        failures.append("G4 regeneration not deterministic")

    print(f"GATE_RESULT {'PASS' if not failures else 'FAIL'}")
    for failure in failures:
        print(f"GATE_FAILURE {failure}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
