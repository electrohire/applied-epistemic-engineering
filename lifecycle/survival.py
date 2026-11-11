#!/usr/bin/env python3
"""Compute hand-written line survival for one delivery in a git repo.

The delivery point is a commit. The snapshot is another commit (selected
explicitly, or the last commit at or before delivery time + horizon days).
Only files changed by the delivery commit and classified as hand-written
source are counted. A line counts as modified or deleted when a line in the
delivery version of one of those files is not present, by git blame origin,
in the snapshot version.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType


def _load_classifier() -> ModuleType:
    path = Path(__file__).resolve().parent / "classifier.py"
    spec = importlib.util.spec_from_file_location("lifecycle_classifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classifier = _load_classifier()


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _changed_files(repo: Path, delivery_commit: str) -> list[str]:
    out = _git(
        repo,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        "--root",
        delivery_commit,
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def _show(repo: Path, commit: str, path: str) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return proc.stdout.splitlines()


def _blame_origins(repo: Path, commit: str, path: str) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "blame", "--line-porcelain", commit, "--", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    origins: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and len(parts[0]) == 40 and parts[1].isdigit() and parts[2].isdigit():
            origins.append(parts[0])
    return origins


def _ancestors(repo: Path, commit: str) -> set[str]:
    out = _git(repo, "rev-list", commit)
    return set(out.splitlines())


def _snapshot_for_horizon(repo: Path, delivery_commit: str, horizon_days: int) -> tuple[str, str]:
    raw = _git(repo, "show", "-s", "--format=%cI", delivery_commit).strip()
    delivered = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    target = delivered + timedelta(days=horizon_days)
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "rev-list",
            "-1",
            f"--before={target.isoformat()}",
            "HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    commit = proc.stdout.strip()
    if proc.returncode != 0 or not commit:
        raise RuntimeError(f"no snapshot commit at horizon {horizon_days}")
    return commit, target.date().isoformat()


def compute_survival(
    repo: Path,
    delivery_commit: str,
    snapshot_commit: str,
    snapshot_at: str,
    horizon_days: int,
) -> dict:
    if horizon_days not in {30, 60, 90, 180}:
        raise ValueError("horizon_days must be one of 30, 60, 90, 180")
    ancestors = _ancestors(repo, delivery_commit)
    total = 0
    lost = 0
    for path in _changed_files(repo, delivery_commit):
        if not classifier.is_handwritten_source(path):
            continue
        delivery_lines = _show(repo, delivery_commit, path)
        total += len(delivery_lines)
        surviving = sum(
            1 for origin in _blame_origins(repo, snapshot_commit, path) if origin in ancestors
        )
        lost += max(0, len(delivery_lines) - surviving)
    standing = total > 0 and lost < (total / 2)
    return {
        "horizon_days": horizon_days,
        "snapshot_at": snapshot_at,
        "snapshot_commit": snapshot_commit,
        "lines_handwritten": total,
        "lines_modified_or_deleted": lost,
        "standing": standing,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("delivery_commit")
    parser.add_argument("--snapshot-commit")
    parser.add_argument("--horizon-days", type=int, required=True)
    args = parser.parse_args()
    if args.snapshot_commit:
        snapshot = args.snapshot_commit
        snapshot_at = _git(args.repo, "show", "-s", "--format=%cs", snapshot).strip()
    else:
        snapshot, snapshot_at = _snapshot_for_horizon(
            args.repo, args.delivery_commit, args.horizon_days
        )
    result = compute_survival(
        args.repo, args.delivery_commit, snapshot, snapshot_at, args.horizon_days
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
