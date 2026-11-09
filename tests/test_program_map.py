"""The layered map must be a pure, traceable render of generated data."""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "tools" / "build_map.py"
LEDGER = ROOT / "program-ledger"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MAP), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_map_check_passes_on_committed_map() -> None:
    proc = run("--check")
    assert "MAP_CHECK OK" in proc.stdout, proc.stdout + proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_map_is_deterministic(tmp_path: Path) -> None:
    import shutil

    for name in ("claims.jsonl", "components.json", "matrix.json", "evaluation.json"):
        shutil.copy(LEDGER / name, tmp_path / name)
    first = run("--ledger-dir", str(tmp_path))
    assert first.returncode == 0, first.stdout + first.stderr
    snapshot = (tmp_path / "map.html").read_bytes()
    second = run("--ledger-dir", str(tmp_path))
    assert second.returncode == 0, second.stdout + second.stderr
    assert (tmp_path / "map.html").read_bytes() == snapshot


def test_every_claim_is_traceable_in_the_map() -> None:
    text = (LEDGER / "map.html").read_text(encoding="utf-8")
    matrix = json.loads((LEDGER / "matrix.json").read_text(encoding="utf-8"))
    for claim in matrix["claims"]:
        assert f"data-claim-id='{claim['id']}'" in text, claim["id"]
    # Header carries the headline state: counts by status from the matrix.
    for status, count in matrix["counts"]["by_status"].items():
        assert f"{status}: {count}" in text
    # No unescaped angle brackets from claim text leak into markup.
    assert "<script" not in text.lower()
    assert len(re.findall(r"<tr data-claim-id=", text)) >= len(matrix["claims"])
