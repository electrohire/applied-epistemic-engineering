"""The engine evaluation must reproduce the ledger's pre-registered
expectations exactly, and must bite when a citation stops carrying
its relation (pattern Amendment 1)."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "tools" / "evaluate.py"
LEDGER_DIR = ROOT / "program-ledger"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(EVAL), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def verdicts_by_id(stdout: str) -> dict[str, str]:
    out = {}
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "EVAL" and parts[1].startswith("SKA-"):
            out[parts[1]] = parts[2]
    return out


def test_shipped_ledger_evaluates_without_violations() -> None:
    proc = run("--no-write")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "violated=0" in proc.stdout
    verdicts = verdicts_by_id(proc.stdout)
    # The three pre-registered expectations must reproduce exactly.
    assert verdicts["SKA-002"] == "VERIFIED"
    assert verdicts["SKA-005"] == "VERIFIED"
    assert verdicts["SKA-015"] == "VERIFIED"


def test_tampered_expectation_is_violated(tmp_path: Path) -> None:
    data = json.loads((LEDGER_DIR / "expectations.json").read_text(encoding="utf-8"))
    for exp in data["expectations"]:
        if exp["claim"] == "SKA-005":
            exp["total"] += 1  # the cited record no longer produces the verdict
    tampered = tmp_path / "expectations.json"
    tampered.write_text(json.dumps(data), encoding="utf-8")
    proc = run("--no-write", "--expectations", str(tampered))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert verdicts_by_id(proc.stdout)["SKA-005"] == "VIOLATED"


def test_superseded_dependency_flags_the_dependent(tmp_path: Path) -> None:
    claims = [
        {
            "id": "TST-A",
            "text": "base claim",
            "kind": "observation",
            "status": "superseded",
            "evidence": [],
        },
        {
            "id": "TST-B",
            "text": "dependent claim",
            "kind": "inference",
            "status": "supported",
            "depends_on": ["TST-A"],
            "evidence": [],
        },
    ]
    ledger = tmp_path / "claims.jsonl"
    ledger.write_text("".join(json.dumps(c) + "\n" for c in claims), encoding="utf-8")
    empty_exp = tmp_path / "expectations.json"
    empty_exp.write_text(json.dumps({"expectations": []}), encoding="utf-8")
    proc = run("--no-write", "--ledger", str(ledger), "--expectations", str(empty_exp))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "TST-B VIOLATED" in proc.stdout
    assert "superseded claim TST-A" in proc.stdout


def test_series_ratio_and_multi_check_aggregation() -> None:
    ok, detail = evaluate_check(
        {"kind": "series_ratio", "series": [100, 300, 400], "stated_ratio": 2.0, "tolerance": 0.01}
    )
    assert ok, detail
    bad, _detail = evaluate_check(
        {"kind": "series_ratio", "series": [100, 300, 400], "stated_ratio": 3.0, "tolerance": 0.01}
    )
    assert not bad


def evaluate_check(exp: dict) -> tuple[bool, str]:
    import importlib.util

    spec = importlib.util.spec_from_file_location("evaluate_mod", EVAL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_expectation(exp)  # type: ignore[no-any-return]
