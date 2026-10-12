#!/usr/bin/env python3
"""Path-safe Spec Kit adapter for the external ``aee`` command."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--project-root", type=Path, default=Path.cwd())
    sub = root.add_subparsers(dest="command", required=True)

    assess = sub.add_parser("assess")
    assess.add_argument("--input", type=Path, required=True)
    assess.add_argument("--phase", default="after_plan")
    assess.add_argument("--threshold", type=float, default=0.70)
    assess.add_argument("--project")
    assess.add_argument("--actor", default="spec-kit-aee")
    assess.add_argument("--no-ledger", action="store_true")
    assess.add_argument("--policy", action="store_true")
    assess.add_argument("--min-independent-sources", type=int, default=2)
    assess.add_argument("--contested-threshold", type=float, default=0.25)
    assess.add_argument("--reliability", type=Path)
    assess.add_argument("--reliability-alpha", type=float, default=0.5)

    challenge = sub.add_parser("challenge")
    challenge.add_argument("--input", type=Path, required=True)
    challenge.add_argument("--phase", default="after_plan")
    challenge.add_argument("--threshold", type=float, default=0.70)
    challenge.add_argument("--project")
    challenge.add_argument("--actor", default="spec-kit-aee")

    graph = sub.add_parser("graph")
    graph.add_argument("--input", type=Path, required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--ledger", type=Path)

    gate = sub.add_parser("gate")
    gate.add_argument("--input", type=Path, required=True)

    gaps = sub.add_parser("gaps")
    gaps.add_argument("--matrix", type=Path, required=True)
    gaps.add_argument("--evidence", type=Path, required=True)
    gaps.add_argument("--output", type=Path)
    gaps.add_argument("--close")
    gaps.add_argument("--existing", type=Path)

    review = sub.add_parser("review")
    review.add_argument("--previous", type=Path, required=True)
    review.add_argument("--current", type=Path, required=True)
    review.add_argument("--materiality", type=float, default=0.05)
    review.add_argument("--limit", type=int)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = args.project_root.resolve(strict=True)
    _reject_symlink_chain(root, root)
    executable = shutil.which("aee")
    if executable is None:
        print(
            "Missing required 'aee' command. Install applied-epistemic-engineering>=1.4.0,<2.",
            file=sys.stderr,
        )
        return 2
    if args.command == "assess":
        return _assess(executable, root, args)
    if args.command == "challenge":
        return _challenge(executable, root, args)
    if args.command == "graph":
        return _graph(executable, root, args)
    if args.command == "verify":
        return _verify(executable, root, args)
    if args.command == "gate":
        value = _safe_existing(root, args.input)
        return subprocess.run(
            [executable, "gate", "--input", str(value)], check=False
        ).returncode
    if args.command == "gaps":
        return _gaps(executable, root, args)
    if args.command == "review":
        return _review(executable, root, args)
    raise AssertionError("unreachable")


def _review(executable: str, root: Path, args: argparse.Namespace) -> int:
    previous = _safe_existing(root, args.previous)
    current = _safe_existing(root, args.current)
    command = [
        executable,
        "review",
        "--previous",
        str(previous),
        "--current",
        str(current),
        "--materiality",
        str(args.materiality),
    ]
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])
    return subprocess.run(command, check=False).returncode


def _gaps(executable: str, root: Path, args: argparse.Namespace) -> int:
    matrix = _safe_existing(root, args.matrix)
    evidence = _safe_dir(root, args.evidence)
    command = [
        executable,
        "gaps",
        "--matrix",
        str(matrix),
        "--evidence",
        str(evidence),
    ]
    if args.close:
        command.extend(["--close", args.close])
    if args.existing:
        existing = _safe_existing(root, args.existing)
        command.extend(["--existing", str(existing)])
    if args.output:
        output = _safe_output(root, args.output)
        command.extend(["--output", str(output)])
    completed = subprocess.run(command, check=False)
    if args.output:
        print(
            json.dumps(
                {
                    "gaps": output.relative_to(root).as_posix(),
                    "aee_exit_code": completed.returncode,
                },
                indent=2,
            )
        )
    return completed.returncode


def _assess(executable: str, root: Path, args: argparse.Namespace) -> int:
    source = _safe_existing(root, args.input)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    phase = _safe_segment(args.phase)
    assessment = _safe_output(
        root, Path(f".specify/extensions/aee/assessments/aee-{phase}-{stamp}.json")
    )
    evaluator = _safe_output(
        root, Path(f".specify/extensions/evaluator/results/aee-{phase}-{stamp}.json")
    )
    command = [
        executable,
        "assess",
        "--input",
        str(source),
        "--project",
        args.project or root.name,
        "--phase",
        phase,
        "--threshold",
        str(args.threshold),
        "--output",
        str(assessment),
        "--evaluator-output",
        str(evaluator),
        "--artifact",
        source.relative_to(root).as_posix(),
        "--actor",
        args.actor,
    ]
    if args.policy:
        command.extend([
            "--policy",
            "--min-independent-sources",
            str(args.min_independent_sources),
            "--contested-threshold",
            str(args.contested_threshold),
        ])
    if args.reliability:
        table = _safe_existing(root, args.reliability)
        command.extend([
            "--reliability",
            str(table),
            "--reliability-alpha",
            str(args.reliability_alpha),
        ])
    ledger: Path | None = None
    if not args.no_ledger:
        ledger = _safe_output(
            root, Path(".specify/extensions/aee/ledger/epistemic-ledger.jsonl")
        )
        command.extend(["--ledger", str(ledger)])
    completed = subprocess.run(command, check=False)
    print(
        json.dumps(
            {
                "assessment": assessment.relative_to(root).as_posix(),
                "evaluator_result": evaluator.relative_to(root).as_posix(),
                "ledger": ledger.relative_to(root).as_posix() if ledger else None,
                "aee_exit_code": completed.returncode,
            },
            indent=2,
        )
    )
    return completed.returncode


def _challenge(executable: str, root: Path, args: argparse.Namespace) -> int:
    source = _safe_existing(root, args.input)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    phase = _safe_segment(args.phase)
    output = _safe_output(
        root, Path(f".specify/extensions/aee/challenges/aee-{phase}-{stamp}.json")
    )
    command = [
        executable,
        "challenge",
        "--input",
        str(source),
        "--project",
        args.project or root.name,
        "--phase",
        phase,
        "--threshold",
        str(args.threshold),
        "--output",
        str(output),
        "--actor",
        args.actor,
    ]
    completed = subprocess.run(command, check=False)
    print(
        json.dumps(
            {
                "challenge": output.relative_to(root).as_posix(),
                "aee_exit_code": completed.returncode,
            },
            indent=2,
        )
    )
    return completed.returncode


def _graph(executable: str, root: Path, args: argparse.Namespace) -> int:
    source = _safe_existing(root, args.input)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = _safe_output(
        root, Path(f".specify/extensions/aee/graphs/aee-claims-{stamp}.mmd")
    )
    completed = subprocess.run(
        [executable, "graph", "--input", str(source), "--output", str(output)],
        check=False,
    )
    print(json.dumps({"graph": output.relative_to(root).as_posix()}, indent=2))
    return completed.returncode


def _verify(executable: str, root: Path, args: argparse.Namespace) -> int:
    ledger_arg = args.ledger or Path(
        ".specify/extensions/aee/ledger/epistemic-ledger.jsonl"
    )
    ledger = _safe_existing(root, ledger_arg)
    return subprocess.run(
        [executable, "verify-ledger", "--ledger", str(ledger)], check=False
    ).returncode


def _safe_existing(root: Path, value: Path) -> Path:
    candidate = value if value.is_absolute() else root / value
    _reject_symlink_chain(root, candidate)
    resolved = candidate.resolve(strict=True)
    _require_inside(root, resolved)
    if not resolved.is_file():
        raise ValueError(f"not a regular file: {value}")
    return resolved


def _safe_dir(root: Path, value: Path) -> Path:
    candidate = value if value.is_absolute() else root / value
    _reject_symlink_chain(root, candidate)
    resolved = candidate.resolve(strict=True)
    _require_inside(root, resolved)
    if not resolved.is_dir():
        raise ValueError(f"not a directory: {value}")
    return resolved


def _safe_output(root: Path, value: Path) -> Path:
    candidate = value if value.is_absolute() else root / value
    _require_inside(root, candidate.resolve(strict=False))
    _reject_symlink_chain(root, candidate)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_chain(root, candidate)
    return candidate


def _require_inside(root: Path, candidate: Path) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {candidate}") from exc


def _reject_symlink_chain(root: Path, candidate: Path) -> None:
    absolute = candidate if candidate.is_absolute() else root / candidate
    _require_inside(root, absolute.resolve(strict=False))
    current = root
    try:
        parts = absolute.relative_to(root).parts
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {absolute}") from exc
    for part in parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError(f"symlinked path component refused: {current}")


def _safe_segment(value: str) -> str:
    if not value or any(
        char not in "abcdefghijklmnopqrstuvwxyz0123456789_" for char in value
    ):
        raise ValueError(f"invalid phase: {value!r}")
    return value if value.startswith("after_") else f"after_{value}"


if __name__ == "__main__":
    sys.exit(main())
