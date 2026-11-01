"""The generated matrix must be a pure function of the ledger."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "tools" / "build_matrix.py"
LEDGER = ROOT / "program-ledger"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GEN), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_matrix_check_passes_on_committed_artifacts() -> None:
    proc = run("--check")
    assert "MATRIX_CHECK OK" in proc.stdout, proc.stdout + proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_matrix_is_deterministic(tmp_path: Path) -> None:
    first = run("--out-dir", str(tmp_path))
    assert first.returncode == 0, first.stdout + first.stderr
    snapshot = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    second = run("--out-dir", str(tmp_path))
    assert second.returncode == 0, second.stdout + second.stderr
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == snapshot


def test_matrix_covers_every_ledger_claim() -> None:
    data = json.loads((LEDGER / "matrix.json").read_text(encoding="utf-8"))
    ledger_ids = [
        json.loads(line)["id"]
        for line in (LEDGER / "claims.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [c["id"] for c in data["claims"]] == ledger_ids
    assert data["generated_from"]["claims"] == len(ledger_ids)
    total = sum(data["counts"]["by_status"].values())
    assert total == len(ledger_ids)
