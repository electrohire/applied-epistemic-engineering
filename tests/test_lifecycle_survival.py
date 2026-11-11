"""Survival computation on a synthetic git repository."""

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SURVIVAL_PATH = ROOT / "lifecycle" / "survival.py"


def load_survival() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lifecycle_survival", SURVIVAL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


survival = load_survival()


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def test_survival_counts_modified_and_deleted_lines(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    source = repo / "module.py"
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")
    git(repo, "add", "module.py")
    git(repo, "commit", "-qm", "delivery")
    delivery = git(repo, "rev-parse", "HEAD")

    source.write_text("one\nTWO\n", encoding="utf-8")
    git(repo, "add", "module.py")
    git(repo, "commit", "-qm", "later change")
    snapshot = git(repo, "rev-parse", "HEAD")

    result = survival.compute_survival(repo, delivery, snapshot, "2026-12-11", 30)
    assert result["lines_handwritten"] == 3
    assert result["lines_modified_or_deleted"] == 2
    assert result["standing"] is False
