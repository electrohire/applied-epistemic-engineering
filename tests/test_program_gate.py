"""The verification gate: green on the shipped tree, red on drift,
and it never writes -- a red gate leaves every published artifact
byte-untouched (pattern Amendment 1, corollaries 4 and 5)."""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "gate.py"


def run_gate(cwd: Path, gate: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(gate)],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def tree_hashes(base: Path) -> dict[str, str]:
    return {
        str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(base.rglob("*"))
        if p.is_file()
    }


def test_gate_passes_on_shipped_tree() -> None:
    proc = run_gate(ROOT, GATE)
    assert "GATE_RESULT PASS" in proc.stdout, proc.stdout + proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_gate_fails_on_drift_and_writes_nothing(tmp_path: Path) -> None:
    for name in ("tools", "program-ledger", "src"):
        shutil.copytree(
            ROOT / name,
            tmp_path / name,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    victim = tmp_path / "program-ledger" / "matrix.md"
    victim.write_bytes(victim.read_bytes() + b" ")
    before = tree_hashes(tmp_path / "program-ledger")
    proc = run_gate(tmp_path, tmp_path / "tools" / "gate.py")
    after = tree_hashes(tmp_path / "program-ledger")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "GATE_RESULT FAIL" in proc.stdout
    assert "G2" in proc.stdout and "FAIL" in proc.stdout
    assert before == after, "a red gate must leave published artifacts byte-untouched"
