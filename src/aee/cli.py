"""Command-line interface for the dependency-free AEE engine."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from aee import __version__
from aee.adapters.evaluator import EvaluatorAdapter
from aee.engine import AEEEngine
from aee.extract import load_claims
from aee.gaps import GapEngine, GapRegister
from aee.graph import ClaimGraph
from aee.ledger import HashChainLedger
from aee.model import (
    Claim,
    ClaimKind,
    ClaimStatus,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    FailureMode,
    SourceQuality,
    Uncertainty,
)
from aee.policy import AssessmentPolicy, ClaimVerdict, Verdict
from aee.reliability import ReliabilityTable
from aee.review import build_review_queue
from aee.scoring import ClaimScore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aee", description="Applied Epistemic Engineering")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
    assess.add_argument(
        "--policy",
        action="store_true",
        help="Attach the assessment policy gates (aee.policy): per-claim "
        "ACCEPT / CHALLENGE / ABSTAIN verdicts in the output",
    )
    assess.add_argument("--min-independent-sources", type=int, default=2)
    assess.add_argument("--contested-threshold", type=float, default=0.25)
    assess.add_argument(
        "--reliability",
        type=Path,
        help="ReliabilityTable JSON (aee.reliability): measured per-source "
        "reliability blends into scoring",
    )
    assess.add_argument("--reliability-alpha", type=float, default=0.5)

    challenge = sub.add_parser(
        "challenge", help="Emit a deterministic failure-mode projection of an assessment"
    )
    challenge.add_argument("--input", type=Path, required=True)
    challenge.add_argument("--project", default="project")
    challenge.add_argument("--phase", default="after_plan")
    challenge.add_argument("--threshold", type=float, default=0.70)
    challenge.add_argument("--output", type=Path)
    challenge.add_argument("--actor", default="aee")

    verify = sub.add_parser("verify-ledger", help="Verify every hash-chain link")
    verify.add_argument("--ledger", type=Path, required=True)

    gate = sub.add_parser("gate", help="Return a CI-friendly decision from an assessment")
    gate.add_argument("--input", type=Path, required=True)

    graph = sub.add_parser("graph", help="Render claim dependencies as Mermaid")
    graph.add_argument("--input", type=Path, required=True)
    graph.add_argument("--output", type=Path)

    gaps = sub.add_parser(
        "gaps", help="Generate or update a gap register from a verification matrix"
    )
    gaps.add_argument(
        "--matrix", type=Path, required=True, help="Path to verification matrix markdown"
    )
    gaps.add_argument(
        "--evidence", type=Path, required=True, help="Directory containing test evidence JSON files"
    )
    gaps.add_argument(
        "--output", type=Path, help="Output path for GAPS.md (default: print to stdout)"
    )
    gaps.add_argument("--close", help="Close a specific gap by ID (e.g., GAP-001)")
    gaps.add_argument(
        "--existing", type=Path, help="Path to existing GAPS.md to preserve closed gaps"
    )

    review = sub.add_parser("review", help="Diff two assessment JSON files into a review queue")
    review.add_argument("--previous", type=Path, required=True)
    review.add_argument("--current", type=Path, required=True)
    review.add_argument("--materiality", type=float, default=0.05)
    review.add_argument("--limit", type=int)
    review.add_argument("--output", type=Path)

    sub.add_parser("demo", help="Run a self-contained AEE demonstration")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Exit-code contract (README): 0 = pass/warn, 1 = soft outcome
    # (iterate/clarify/gather_evidence/abstain), 2 = block/error. Input and
    # usage errors must land on 2 with a clean message — previously a
    # malformed input crashed with a traceback and Python's exit 1,
    # indistinguishable from a legitimate soft verdict in CI.
    try:
        if args.command == "assess":
            return _assess(args)
        if args.command == "challenge":
            return _challenge(args)
        if args.command == "verify-ledger":
            return _verify_ledger(args)
        if args.command == "gate":
            return _gate(args)
        if args.command == "graph":
            return _graph(args)
        if args.command == "gaps":
            return _gaps(args)
        if args.command == "review":
            return _review(args)
        if args.command == "demo":
            return _demo()
    except (ValueError, KeyError, AttributeError, TypeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    raise AssertionError("unreachable")


def _assess(args: argparse.Namespace) -> int:
    claims = load_claims(args.input)
    policy = None
    if args.policy:
        policy = AssessmentPolicy(
            min_independent_sources=args.min_independent_sources,
            contested_penalty_threshold=args.contested_threshold,
        )
    reliability = None
    if args.reliability:
        reliability = ReliabilityTable.from_dict(
            json.loads(args.reliability.read_text(encoding="utf-8"))
        )
    engine = AEEEngine(
        args.threshold,
        policy=policy,
        reliability=reliability,
        reliability_alpha=args.reliability_alpha,
    )
    assessment = engine.assess(
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


def _challenge(args: argparse.Namespace) -> int:
    claims = load_claims(args.input)
    assessment = AEEEngine(args.threshold).assess(
        claims,
        project=args.project,
        phase=args.phase,
        metadata={"input": args.input.as_posix(), "mode": "challenge"},
    )
    failures = [cast(FailureMode, failure).to_dict() for failure in assessment.failures]
    value: dict[str, object] = {
        "schema_version": "1.0",
        "mode": "challenge",
        "project": assessment.project,
        "phase": assessment.phase,
        "outcome": assessment.outcome,
        "summary": assessment.summary,
        "created_at": assessment.created_at,
        "failures": failures,
        "recoveries": [item.to_dict() for item in assessment.recoveries],
    }
    _write_or_print(value, args.output)
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


def _gaps(args: argparse.Namespace) -> int:
    engine = GapEngine()

    # --close mode: load existing register, close a gap, write back
    if args.close:
        if not args.output:
            print("Error: --output is required when using --close", file=sys.stderr)
            return 2
        if not args.output.is_file():
            print(
                f"Error: {args.output} not found. Run 'aee gaps' first to generate it.",
                file=sys.stderr,
            )
            return 2
        register = engine.load_register(args.output)
        try:
            register = engine.close_gap(register, args.close)
        except KeyError:
            print(f"Error: no such gap: {args.close}", file=sys.stderr)
            return 2
        _write_gaps(register, args.output)
        print(f"Closed {args.close}")
        return 0

    # Generate mode
    try:
        register = engine.generate(
            matrix_path=args.matrix,
            evidence_dir=args.evidence,
            existing_gaps_path=args.existing,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.output:
        _write_gaps(register, args.output)
        print(f"Gap register written to {args.output}")
    else:
        print(register.to_markdown(), end="")

    print(f"\nOpen: {register.open_count} | Closed: {register.closed_count}")
    return 0


def _write_gaps(register: GapRegister, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(register.to_markdown(), encoding="utf-8")


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


def _score_view(value: dict[str, Any]) -> ClaimScore:
    components = value.get("components", {})
    return ClaimScore(
        claim_id=str(value.get("claim_id", "")),
        direct_score=float(value.get("direct_score", 0.0)),
        propagated_score=float(value.get("propagated_score", 0.0)),
        evidence_score=float(components.get("evidence", 0.0)),
        independence_score=float(components.get("independence", 0.0)),
        falsifiability_score=float(components.get("falsifiability", 0.0)),
        boundary_score=float(components.get("boundary", 0.0)),
        contradiction_penalty=float(components.get("contradiction_penalty", 0.0)),
        notes=[str(note) for note in value.get("notes", [])],
    )


@dataclass(frozen=True, slots=True)
class _AssessmentView:
    scores: dict[str, ClaimScore]
    verdicts: dict[str, ClaimVerdict]


def _assessment_view(path: Path) -> _AssessmentView:
    """Rebuild the score/verdict views build_review_queue consumes
    from a serialized assessment (Assessment.to_dict output)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    scores = {claim_id: _score_view(score) for claim_id, score in data.get("scores", {}).items()}
    verdicts = {
        claim_id: ClaimVerdict(
            claim_id,
            Verdict(str(verdict["verdict"])),
            [str(reason) for reason in verdict.get("reasons", [])],
        )
        for claim_id, verdict in data.get("verdicts", {}).items()
    }
    return _AssessmentView(scores=scores, verdicts=verdicts)


def _review(args: argparse.Namespace) -> int:
    queue = build_review_queue(
        _assessment_view(args.previous),
        _assessment_view(args.current),
        materiality=args.materiality,
        limit=args.limit,
    )
    _write_or_print(queue.to_dict(), args.output)
    return 0


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
    if outcome in {"iterate", "clarify", "gather_evidence", "abstain"}:
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
