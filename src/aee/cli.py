"""Command-line interface for the dependency-free AEE engine."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from aee.adapters.evaluator import EvaluatorAdapter
from aee.engine import AEEEngine
from aee.extract import load_claims
from aee.graph import ClaimGraph
from aee.ledger import HashChainLedger
from aee.model import (
    Claim,
    ClaimKind,
    ClaimStatus,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    SourceQuality,
    Uncertainty,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aee", description="Applied Epistemic Engineering")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    sub = parser.add_subparsers(dest="command", required=True)

    assess = sub.add_parser("assess", help="Assess claims from JSON or Markdown")
    assess.add_argument("--input", type=Path, required=True)
    assess.add_argument("--project", default="project")
    assess.add_argument("--phase", default="after_plan")
    assess.add_argument("--threshold", type=float, default=0.70)
    assess.add_argument("--output", type=Path)
    assess.add_argument("--evaluator-output", type=Path)
    assess.add_argument("--artifact", action="append", default=[])
    assess.add_argument("--model")
    assess.add_argument("--ledger", type=Path)
    assess.add_argument("--actor", default="aee")

    verify = sub.add_parser("verify-ledger", help="Verify every hash-chain link")
    verify.add_argument("--ledger", type=Path, required=True)

    gate = sub.add_parser("gate", help="Return a CI-friendly decision from an assessment")
    gate.add_argument("--input", type=Path, required=True)

    graph = sub.add_parser("graph", help="Render claim dependencies as Mermaid")
    graph.add_argument("--input", type=Path, required=True)
    graph.add_argument("--output", type=Path)

    sub.add_parser("demo", help="Run a self-contained AEE demonstration")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "assess":
        return _assess(args)
    if args.command == "verify-ledger":
        return _verify_ledger(args)
    if args.command == "gate":
        return _gate(args)
    if args.command == "graph":
        return _graph(args)
    if args.command == "demo":
        return _demo()
    raise AssertionError("unreachable")


def _assess(args: argparse.Namespace) -> int:
    claims = load_claims(args.input)
    assessment = AEEEngine(args.threshold).assess(
        claims,
        project=args.project,
        phase=args.phase,
        metadata={"input": args.input.as_posix()},
    )
    if args.ledger:
        HashChainLedger(args.ledger).append_assessment(assessment, actor=args.actor)
    value = assessment.to_dict()
    _write_or_print(value, args.output)
    if args.evaluator_output:
        evaluator = EvaluatorAdapter().to_evaluator_result(
            assessment,
            artifacts=args.artifact,
            model=args.model,
            deterministic=args.model is None,
        )
        _write_json(evaluator, args.evaluator_output)
    return _exit_code(assessment.outcome)


def _verify_ledger(args: argparse.Namespace) -> int:
    result = HashChainLedger(args.ledger).verify()
    print(
        json.dumps(
            {
                "valid": result.valid,
                "entries": result.entries,
                "head_hash": result.head_hash,
                "errors": list(result.errors),
            },
            indent=2,
        )
    )
    return 0 if result.valid else 2


def _gate(args: argparse.Namespace) -> int:
    value = json.loads(args.input.read_text(encoding="utf-8"))
    outcome = str(value.get("outcome", "block"))
    print(f"AEE gate: {outcome}")
    return _exit_code(outcome)


def _graph(args: argparse.Namespace) -> int:
    rendered = ClaimGraph(load_claims(args.input)).to_mermaid()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def _demo() -> int:
    claim = Claim(
        id="REQ-DEMO-001",
        text="The API always returns within 100 ms",
        kind=ClaimKind.REQUIREMENT,
        status=ClaimStatus.SUPPORTED,
        boundary=["Production region us-east-1", "p95 under nominal load"],
        falsification_tests=["Run a 30-minute load test and observe p95 latency above 100 ms"],
        uncertainty=Uncertainty.LOW,
        source_ref="spec.md#REQ-DEMO-001",
        evidence=[
            Evidence(
                ref="reports/load-test.json",
                kind=EvidenceKind.OBSERVED,
                direction=EvidenceDirection.SUPPORTS,
                source_quality=SourceQuality.TEST,
                source_id="load-test-2026-09-04",
                description="Observed p95 was 83 ms",
            )
        ],
    )
    result = AEEEngine().assess([claim], project="demo", phase="after_specify")
    print(json.dumps(result.to_dict(), indent=2))
    return _exit_code(result.outcome)


def _write_or_print(value: dict[str, object], output: Path | None) -> None:
    if output:
        _write_json(value, output)
    else:
        print(json.dumps(value, indent=2))


def _write_json(value: dict[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _exit_code(outcome: str) -> int:
    if outcome in {"pass", "warn"}:
        return 0
    if outcome in {"iterate", "clarify", "gather_evidence"}:
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
