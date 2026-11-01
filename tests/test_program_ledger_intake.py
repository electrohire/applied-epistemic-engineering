"""The shipped program ledger must always pass its own intake."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTAKE = ROOT / "program-ledger" / "intake.py"


def test_program_ledger_intake_accepts_shipped_claims() -> None:
    proc = subprocess.run(
        [sys.executable, str(INTAKE)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert "rejected=0" in proc.stdout, proc.stdout + proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr
