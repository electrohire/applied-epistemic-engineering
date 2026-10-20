"""Command-line interface for the dependency-free AEE engine."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from aee import __version__
from aee.adapters.evaluator import EvaluatorAdapter
from aee.engine import AEEEngine
from aee.evidence_check import check_evidence
from aee.extract import (
    duplicate_key_hook,
    load_claims,
    migrate_bundle,
    validate_bundle_structure,
)
from aee.gaps import GapEngine, GapRegister
from aee.graph import ClaimGraph
from aee.ledger import DEFAULT_LEDGER_PATH, HashChainLedger, assessment_content_digest
from aee.model import (
    STAGE_ORDER,
    Claim,
    ClaimKind,
    ClaimStage,
    ClaimStatus,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    FailureMode,
    IdentityKind,
    IdentityRegistry,
    Severity,
    SourceQuality,
    StageEvent,
    StageEventKind,
    Uncertainty,
    normalize_claim_id,
    validate_exposition_evidence,
)
from aee.policy import AssessmentPolicy, ClaimVerdict, Verdict, lane_1_challenge_applies
from aee.reliability import ReliabilityTable
from aee.review import build_review_queue
from aee.scoring import ClaimScore
from aee.stage import reported_status_for


def _parse_as_of(raw: str) -> datetime:
    """Parse the ``--as-of`` value (FR-5.8). A bad value is an
    argparse type error — usage error, exit 2, no traceback. A naive
    value is read as UTC, matching the scoring engine's treatment of
    a naive ``as_of``."""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--as-of value {raw!r} is not an ISO 8601 date/datetime"
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aee", description="Applied Epistemic Engineering")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    assess = sub.add_parser(
        "assess",
        help="Assess claims from JSON or Markdown. Ledgers by default "
        f"(Spec 002 FR-8.1): the assessment is appended to "
        f"{DEFAULT_LEDGER_PATH.as_posix()} under the project root unless "
        "--ledger selects another ledger or --no-ledger opts out. The "
        "ledger entry, which records the assessment's SHA-256, is the "
        "record of what was assessed; the assessment JSON is a working "
        "copy (FR-8.3). Verify the record with: aee verify-ledger "
        "--ledger <path>.",
    )
    assess.add_argument("--input", type=Path, required=True)
    assess.add_argument("--project", default="project")
    assess.add_argument("--phase", default="after_plan")
    assess.add_argument("--threshold", type=float, default=0.70)
    assess.add_argument("--output", type=Path)
    assess.add_argument("--evaluator-output", type=Path)
    assess.add_argument("--artifact", action="append", default=[])
    assess.add_argument("--model")
    assess.add_argument(
        "--ledger",
        type=Path,
        help="Ledger path to append the assessment to, instead of the "
        f"default {DEFAULT_LEDGER_PATH.as_posix()} under the project root.",
    )
    assess.add_argument(
        "--no-ledger",
        action="store_true",
        help="Opt out of ledgering this assessment (FR-8.1). The opt-out "
        "is echoed into the assessment metadata, never silent.",
    )
    assess.add_argument("--actor", default="aee")
    assess.add_argument(
        "--as-of",
        type=_parse_as_of,
        default=None,
        metavar="ISO8601",
        help="Pin the scoring clock (Spec 003 FR-5.8): freshness is "
        "judged as of this instant instead of the wall clock, so a "
        "replayed assessment is reproducible. A date or ISO 8601 "
        "datetime; a naive value is read as UTC.",
    )
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
    assess.add_argument(
        "--lenient",
        action="store_true",
        help="Compatibility mode (Spec 002 FR-1.3): load claims with the "
        "historical silent-default loader instead of strict validation. "
        "Its use is echoed into the assessment metadata.",
    )
    assess.add_argument(
        "--identity-registry",
        type=Path,
        help="Project-local identity registry JSON (Spec 004 R3.2/OD-T4): "
        "exposition evidence source_ids resolve against it. Without this, "
        "a bundle-adjacent identities.json beside the input is used if present.",
    )
    assess.add_argument(
        "--verify-evidence",
        action="store_true",
        help="Verify evidence refs inline (Spec 002 FR-3.5): refs are "
        "resolved inside the project root, content_hash values are "
        "recomputed, and findings fold into the assessment as failure modes.",
    )
    assess.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root: evidence refs resolve against it with "
        "--verify-evidence, and the default ledger path is rooted "
        "here (default: current working directory).",
    )

    verify_evidence = sub.add_parser(
        "verify-evidence",
        help="Resolve evidence refs, recompute content_hash values, and "
        "report declared-vs-derived source quality (Spec 002 FR-3)",
    )
    verify_evidence.add_argument("bundle", type=Path)
    verify_evidence.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root evidence refs resolve against (default: current working directory).",
    )
    verify_evidence.add_argument("--output", type=Path)

    validate = sub.add_parser(
        "validate",
        help="Strict-load a claims bundle and run structural checks, without assessing",
    )
    validate.add_argument("bundle", type=Path)
    validate.add_argument(
        "--identity-registry",
        type=Path,
        help="Project-local identity registry JSON (Spec 004 R3.2/OD-T4).",
    )

    migrate = sub.add_parser(
        "migrate",
        help="Convert a pre-engine legacy claims bundle to the current format",
    )
    migrate.add_argument("bundle", type=Path)
    migrate.add_argument("--output", type=Path)

    challenge = sub.add_parser(
        "challenge", help="Emit a deterministic failure-mode projection of an assessment"
    )
    challenge.add_argument("--input", type=Path, required=True)
    challenge.add_argument("--project", default="project")
    challenge.add_argument("--phase", default="after_plan")
    challenge.add_argument("--threshold", type=float, default=0.70)
    challenge.add_argument("--output", type=Path)
    challenge.add_argument("--actor", default="aee")
    challenge.add_argument(
        "--lenient",
        action="store_true",
        help="Compatibility mode (Spec 002 FR-1.3), as for assess: load "
        "claims with the historical silent-default loader instead of "
        "strict validation. Its use is echoed into the output metadata.",
    )
    challenge.add_argument(
        "--as-of",
        type=_parse_as_of,
        default=None,
        metavar="ISO8601",
        help="Pin the scoring clock (Spec 003 FR-5.8), as for assess.",
    )

    priority = sub.add_parser(
        "priority",
        help="Report claim priority records from a ledger (Spec 004 R7.1)",
    )
    priority.add_argument("--ledger", type=Path, required=True)
    priority.add_argument(
        "--claim",
        default=None,
        help="Only this claim id (exit 2 when it was never registered)",
    )

    verify = sub.add_parser("verify-ledger", help="Verify every hash-chain link")
    verify.add_argument("--ledger", type=Path, required=True)
    verify.add_argument(
        "--anchor",
        type=Path,
        help="Anchor file to check (default: <ledger>.anchor.json beside the ledger)",
    )
    verify.add_argument(
        "--expected-tip",
        "--expected-head",
        dest="expected_tip",
        help="Fail unless the ledger tip hash equals this retained anchor value",
    )
    verify.add_argument(
        "--expected-count",
        type=int,
        help="Fail unless the ledger entry count equals this retained anchor value",
    )
    verify.add_argument(
        "--require-anchor",
        action="store_true",
        help="Fail when no matching sidecar anchor is present (FR-4.1)",
    )
    verify.add_argument(
        "--write-anchor",
        action="store_true",
        help="After verifying the chain, (re)write its sidecar anchor — the "
        "migration path for ledgers written before FR-4 anchors existed",
    )

    gate = sub.add_parser("gate", help="Return a CI-friendly decision from an assessment")
    gate.add_argument("--input", type=Path, required=True)
    gate.add_argument(
        "--require-lane1-pass",
        action="store_true",
        help="Decide on lane 1 (machine verification) instead of the "
        "headline (Spec 006 A3): exit 0 when the recomputed lane-1 "
        "outcome is pass, 1 when it is iterate, clarify, "
        "gather_evidence, or abstain, and 2 when it is block or any "
        "integrity check refuses the file. All cross-checks, "
        "including the lane-1 recomputation, run either way.",
    )

    stage_cmd = sub.add_parser(
        "stage",
        help="Record a stage advance event on one claim in a bundle "
        "(Spec 006 A4): the recorded act that moves a claim's "
        "lifecycle stage, written back atomically and appended to "
        "the project ledger when one is present",
    )
    stage_cmd.add_argument("bundle", type=Path)
    stage_cmd.add_argument("--claim", required=True, help="Claim id to advance")
    stage_cmd.add_argument(
        "--to",
        required=True,
        help="Target stage: created, checked, explained, accepted, or digested "
        "(forward moves only; the model's recorded-event rule enforces it)",
    )
    stage_cmd.add_argument(
        "--basis",
        required=True,
        help="The basis for the advance; recorded on the stage event (an "
        "advance without a stated basis is not auditable and is refused)",
    )
    stage_cmd.add_argument(
        "--recorded-by",
        default=None,
        help="Who records this act. Required for accepted/digested, where "
        "the name must resolve to a person in the identity registry; "
        "for checked it defaults to 'aee'",
    )
    stage_cmd.add_argument(
        "--identity-registry",
        type=Path,
        help="Project-local identity registry JSON (default: a "
        "bundle-adjacent identities.json beside the bundle, when present)",
    )
    stage_cmd.add_argument(
        "--ledger",
        type=Path,
        help="Ledger to append the recorded event to (default: the "
        f"default ledger {DEFAULT_LEDGER_PATH.as_posix()} beside the "
        "bundle or under the working directory, when one is present)",
    )

    ratify = sub.add_parser(
        "ratify",
        help="Record a change to one claim's declared status in a bundle "
        "(Spec 006 A4): the recorded act that lifts (or lowers) a "
        "claim's author-declared posture, written back atomically and "
        "appended to the project ledger when one is present",
    )
    ratify.add_argument("bundle", type=Path)
    ratify.add_argument("--claim", required=True, help="Claim id to ratify")
    ratify.add_argument(
        "--status",
        required=True,
        help="New declared status: draft, supported, partially_supported, "
        "unsupported, contradicted, unverifiable, or superseded. "
        "'supported' is refused for a claim at stage 'created'",
    )
    ratify.add_argument(
        "--basis",
        required=True,
        help="The basis for the status change; recorded with the act",
    )
    ratify.add_argument(
        "--recorded-by",
        required=True,
        help="Who records this act; named on the ratification record",
    )
    ratify.add_argument(
        "--ledger",
        type=Path,
        help="Ledger to append the recorded act to (same default as 'stage')",
    )

    anchor = sub.add_parser(
        "anchor",
        help=(
            "Deposit an assessment's SHA-256 in an Axiomere .axmr ledger (optional, Spec 002 FR-8b)"
        ),
    )
    anchor.add_argument("--input", type=Path, required=True)
    anchor.add_argument(
        "--ledger",
        type=Path,
        required=True,
        help="Path to the .axmr ledger (created if absent)",
    )
    anchor.add_argument("--actor", default="aee-anchor")
    anchor.add_argument("--project")
    anchor.add_argument("--phase")
    anchor.add_argument(
        "--output",
        type=Path,
        help="Write the receipt-bearing assessment here instead of updating --input in place",
    )

    graph = sub.add_parser("graph", help="Render claim dependencies as Mermaid")
    graph.add_argument("--input", type=Path, required=True)
    graph.add_argument("--output", type=Path)
    graph.add_argument(
        "--lenient",
        action="store_true",
        help="Compatibility mode (Spec 002 FR-1.3), as for assess: load "
        "claims with the historical silent-default loader instead of "
        "strict validation.",
    )

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
    review.add_argument(
        "--baseline",
        type=Path,
        help="Last reviewed assessment: cumulative drift is measured from it (FR-8.11)",
    )
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
        if args.command == "validate":
            return _validate(args)
        if args.command == "verify-evidence":
            return _verify_evidence(args)
        if args.command == "migrate":
            return _migrate(args)
        if args.command == "challenge":
            return _challenge(args)
        if args.command == "verify-ledger":
            return _verify_ledger(args)
        if args.command == "priority":
            return _priority(args)
        if args.command == "gate":
            return _gate(args)
        if args.command == "stage":
            return _stage(args)
        if args.command == "ratify":
            return _ratify(args)
        if args.command == "anchor":
            return _anchor(args)
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
    except (RecursionError, OverflowError) as exc:
        # Spec 003 FR-5.3 (RT2-M6): input-driven parser/conversion
        # failures — JSON nested deeper than the interpreter stack, a
        # several-hundred-digit integer literal hitting float() — are
        # input errors (exit 2), never a traceback at exit 1, which
        # the contract reserves for scored soft verdicts.
        print(f"Error: input exceeds processing limits: {exc}", file=sys.stderr)
        return 2
    raise AssertionError("unreachable")


def _validate(args: argparse.Namespace) -> int:
    registry = (
        IdentityRegistry.from_path(str(args.identity_registry))
        if getattr(args, "identity_registry", None) is not None
        else None
    )
    claims = load_claims(args.bundle, identity_registry=registry)
    errors, warnings = validate_bundle_structure(claims)
    for warning in warnings:
        print(f"warning: {warning}")
    if errors:
        for error in errors:
            print(f"Error: {error}", file=sys.stderr)
        return 2
    print(f"valid: {len(claims)} claim(s) in {args.bundle.as_posix()}")
    return 0


def _verify_evidence(args: argparse.Namespace) -> int:
    claims = load_claims(args.bundle)
    root = args.project_root if args.project_root is not None else Path.cwd()
    report = check_evidence(claims, root)
    if args.output is not None:
        _guard_output_path(args.output, [(args.bundle, "the input bundle")])
    _write_or_print(report.to_dict(), args.output)
    if report.findings:
        for finding in report.findings:
            print(
                f"finding: claim '{finding.claim_id}' evidence[{finding.evidence_index}] "
                f"({finding.category}): {finding.message}",
                file=sys.stderr,
            )
        return 2
    print(
        f"verified: {report.checked} evidence item(s), "
        f"{report.unresolvable_offline} unresolvable offline",
        file=sys.stderr,
    )
    return 0


def _migrate(args: argparse.Namespace) -> int:
    if args.output is not None:
        _guard_output_path(args.output, [(args.bundle, "the input bundle")])
    value = _load_json_strict(args.bundle, what="bundle")
    migrated, report = migrate_bundle(value)
    for line in report:
        print(f"migrate: {line}", file=sys.stderr)
    if args.output:
        _write_json(migrated, args.output)
        print(f"migrated bundle written to {args.output.as_posix()}")
    else:
        print(_dumps(migrated, indent=2))
    return 0


def _assess(args: argparse.Namespace) -> int:
    if args.ledger is not None and args.no_ledger:
        print(
            "Error: --ledger and --no-ledger are mutually exclusive; "
            "choose a ledger path or opt out, not both",
            file=sys.stderr,
        )
        return 2
    # FR-8.1 ledger parity: the bare CLI adopts the runner's default.
    # Resolution: --ledger <path> wins (used as given); otherwise the
    # documented default path under the project root (--project-root
    # or the current working directory). --no-ledger is the explicit
    # opt-out. Whichever happened is echoed into the assessment
    # metadata (the FR-1.3 lenient-echo pattern): ledgering is never
    # silent in either direction.
    # Spec 003 FR-5.1 path-collision guards hook in here, where the
    # final ledger path is decided exactly once: no output of this run
    # may resolve (symlinks followed) onto the input bundle, the
    # reliability file, the ledger, or its anchor sidecar — the
    # artifacts the trust story rests on (RT2-H4). The refusal happens
    # before anything is written or appended.
    ledger_path: Path | None
    if args.no_ledger:
        ledger_path = None
        ledger_meta: dict[str, Any] = {"mode": "disabled", "path": None}
    elif args.ledger is not None:
        ledger_path = args.ledger
        ledger_meta = {"mode": "custom", "path": args.ledger.as_posix()}
    else:
        root = args.project_root if args.project_root is not None else Path.cwd()
        ledger_path = root / DEFAULT_LEDGER_PATH
        ledger_meta = {"mode": "default", "path": ledger_path.as_posix()}
    protected: list[tuple[Path, str]] = [(args.input, "the --input bundle")]
    if args.reliability is not None:
        protected.append((args.reliability, "the --reliability file"))
    if ledger_path is not None:
        protected.append((ledger_path, "the ledger"))
        protected.append(
            (
                ledger_path.with_name(ledger_path.name + ".anchor.json"),
                "the ledger anchor sidecar",
            )
        )
    if args.output is not None:
        _guard_output_path(args.output, protected)
    if args.evaluator_output is not None:
        evaluator_protected = list(protected)
        if args.output is not None:
            evaluator_protected.append((args.output, "the --output assessment"))
        _guard_output_path(args.evaluator_output, evaluator_protected, flag="--evaluator-output")
    # RT2-L3 (FR-5.1): writes that resolve outside the project root
    # are permitted (a local CLI has latitude) but never silent —
    # warn loudly on stderr; the paths themselves are already in the
    # run record (metadata.ledger / metadata.input).
    warn_root = args.project_root if args.project_root is not None else Path.cwd()
    if ledger_path is not None:
        _warn_if_outside_root(ledger_path, warn_root, flag="--ledger")
    if args.output is not None:
        _warn_if_outside_root(args.output, warn_root, flag="--output")
    if args.evaluator_output is not None:
        _warn_if_outside_root(args.evaluator_output, warn_root, flag="--evaluator-output")
    registry = (
        IdentityRegistry.from_path(str(args.identity_registry))
        if getattr(args, "identity_registry", None) is not None
        else None
    )
    claims = load_claims(args.input, strict=not args.lenient, identity_registry=registry)
    if not claims:
        # Spec 003 FR-1.1 (OD-2, CLI half): an explicitly empty bundle
        # is an input error (exit 2), never a pass — this is the
        # "bundle silently emptied" incident class one level up. The
        # engine independently returns a non-pass outcome for zero
        # claims, so API consumers are protected too (belt-and-braces;
        # the owner may reverse this CLI half of OD-2).
        print(
            "Error: input bundle contains zero claims: an empty bundle "
            "is an input error, never a pass (Spec 003 FR-1.1)",
            file=sys.stderr,
        )
        return 2
    policy = None
    if args.policy:
        policy = AssessmentPolicy(
            min_independent_sources=args.min_independent_sources,
            contested_penalty_threshold=args.contested_threshold,
        )
    reliability = None
    if args.reliability:
        # Spec 003 FR-3.3: a reliability file carrying bare NaN /
        # Infinity tokens is refused at load — Python's json accepts
        # them by default, so parse_constant rejects them loudly
        # (ValueError -> clean exit 2 via main). Range/finiteness of
        # the parsed values is validated by from_dict (FR-3.1).
        def _reject_constant(name: str) -> None:
            raise ValueError(
                f"reliability file {args.reliability}: non-finite number "
                f"{name!r} is not allowed (Spec 003 FR-3.3)"
            )

        reliability = ReliabilityTable.from_dict(
            json.loads(
                args.reliability.read_text(encoding="utf-8"),
                parse_constant=_reject_constant,
                object_pairs_hook=duplicate_key_hook(
                    f"reliability file {args.reliability.as_posix()}"
                ),
            ),
            # Spec 003 FR-3.7: a reliability file's claimed anchors
            # are verified against this run's ledger before they can
            # canonise anything; with --no-ledger there is nothing
            # to resolve against and the file's history stays
            # provisional. An unresolvable digest fails the load
            # loudly (BundleValidationError -> exit 2), like any
            # other poisoned reliability input.
            ledger=HashChainLedger(ledger_path) if ledger_path is not None else None,
        )
    engine = AEEEngine(
        args.threshold,
        policy=policy,
        reliability=reliability,
        reliability_alpha=args.reliability_alpha,
    )
    metadata: dict[str, Any] = {"input": args.input.as_posix(), "ledger": ledger_meta}
    if args.as_of is not None:
        # FR-5.8: a pinned scoring clock is part of the run record —
        # a replay that pins the same instant is the same assessment.
        metadata["as_of"] = args.as_of.isoformat().replace("+00:00", "Z")
    if args.lenient:
        # FR-1.3: lenient mode is never silent — its use is on the record.
        metadata["loading_mode"] = "lenient"
    evidence_failures: list[FailureMode] | None = None
    if args.verify_evidence:
        # FR-3.5: the same checks as `aee verify-evidence`, folded into
        # the assessment as failure modes and summarized in metadata.
        root = args.project_root if args.project_root is not None else Path.cwd()
        report = check_evidence(claims, root)
        evidence_failures = report.failure_modes()
        metadata["evidence_verification"] = {
            "checked": report.checked,
            "findings": len(report.findings),
            "unresolvable_offline": report.unresolvable_offline,
        }
    assessment = engine.assess(
        claims,
        project=args.project,
        phase=args.phase,
        metadata=metadata,
        as_of=args.as_of,
        additional_failures=evidence_failures,
    )
    value = assessment.to_dict()
    # Spec 003 FR-5.2 (RT2-M3): the artifacts are written BEFORE the
    # ledger append, so a failed write can never leave a ledger entry
    # attesting to an assessment file that was never produced. Writes
    # themselves are atomic (temp file + rename, see _write_json).
    _write_or_print(value, args.output)
    if args.evaluator_output:
        evaluator = EvaluatorAdapter().to_evaluator_result(
            assessment,
            artifacts=args.artifact,
            model=args.model,
            deterministic=args.model is None,
        )
        _write_json(evaluator, args.evaluator_output)
    if ledger_path is not None:
        HashChainLedger(ledger_path).append_assessment(assessment, actor=args.actor)
    return _exit_code(assessment.outcome)


def _challenge(args: argparse.Namespace) -> int:
    if args.output is not None:
        _guard_output_path(args.output, [(args.input, "the --input bundle")])
    claims = load_claims(args.input, strict=not args.lenient)
    if not claims:
        print(
            "Error: input bundle contains zero claims: an empty bundle "
            "is an input error, never a pass (Spec 003 FR-1.1)",
            file=sys.stderr,
        )
        return 2
    challenge_metadata: dict[str, Any] = {
        "input": args.input.as_posix(),
        "mode": "challenge",
    }
    if args.lenient:
        # FR-1.3: lenient mode is never silent — its use is on the record.
        challenge_metadata["loading_mode"] = "lenient"
    assessment = AEEEngine(args.threshold).assess(
        claims,
        project=args.project,
        phase=args.phase,
        metadata=challenge_metadata,
        as_of=args.as_of,
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


def _priority(args: argparse.Namespace) -> int:
    """Spec 004 R7.1: a claim's registration (priority) record is a
    read over the ledger - earliest entry whose assessment contains
    the claim id, with its timestamp and entry hash."""
    from aee.priority import claim_priority, priority_index

    ledger = HashChainLedger(args.ledger)
    if args.claim is not None:
        record = claim_priority(ledger, args.claim)
        if record is None:
            print(
                f"Error: claim {args.claim!r} was never registered in {args.ledger.as_posix()}",
                file=sys.stderr,
            )
            return 2
        print(_dumps(record, indent=2))
        return 0
    print(_dumps(priority_index(ledger), indent=2))
    return 0


def _verify_ledger(args: argparse.Namespace) -> int:
    ledger = HashChainLedger(args.ledger)
    if args.write_anchor:
        # FR-5.1: an anchor write aimed at the ledger itself would
        # destroy the chain it is meant to anchor (RT2-H4 class).
        anchor_path = args.anchor if args.anchor is not None else ledger.anchor_path
        if anchor_path.resolve() == args.ledger.resolve():
            print(
                f"Error: --anchor {anchor_path.as_posix()} resolves to the ledger "
                f"{args.ledger.as_posix()} itself; refusing to overwrite the ledger "
                "with an anchor",
                file=sys.stderr,
            )
            return 2
    written_anchor = None
    if args.write_anchor:
        written_anchor = ledger.write_anchor(args.anchor)
    result = ledger.verify(
        expected_tip_hash=args.expected_tip,
        expected_entry_count=args.expected_count,
        require_anchor=args.require_anchor,
        anchor_path=args.anchor,
    )
    output = result.to_dict()
    if written_anchor is not None:
        output["anchor_written"] = written_anchor.to_dict()
    print(_dumps(output, indent=2))
    return 0 if result.valid else 2


_GATE_OUTCOMES = {
    "pass",
    "warn",
    "iterate",
    "clarify",
    "gather_evidence",
    "abstain",
    "block",
}
_SUMMARY_COUNTS = re.compile(
    r"Assessed (\d+) claim\(s\); found (\d+) failure mode\(s\); "
    r"(\d+) claim\(s\) below the (\d+(?:\.\d+)?) confidence threshold\."
)


def _anchor(args: argparse.Namespace) -> int:
    """Spec 002 FR-8b (T804/T805): deposit the assessment's SHA-256
    in an Axiomere ledger and write the receipt back as
    `metadata.anchor`. When the optional axiomere package is absent
    this degrades to a clear "anchor unavailable" message (FR-8.6)
    and a non-zero exit - the assessment file is left untouched."""
    from aee.anchor import AnchorUnavailable, anchor_assessment

    value = _load_json_strict(args.input, what="assessment")
    if not isinstance(value, dict) or not isinstance(value.get("metadata"), dict):
        raise ValueError(
            f"anchor: {args.input.as_posix()} is not a complete assessment (missing metadata)"
        )
    try:
        receipt = anchor_assessment(
            value,
            ledger_path=args.ledger,
            actor=args.actor,
            project=args.project,
            phase=args.phase,
        )
    except AnchorUnavailable as exc:
        print(f"AEE anchor: {exc}", file=sys.stderr)
        return 2
    value["metadata"]["anchor"] = receipt
    target = args.output if args.output is not None else args.input
    target.write_text(_dumps(value, indent=2) + "\n", encoding="utf-8")
    print(
        "AEE anchor: deposited assessment SHA-256 "
        f"{receipt['assessment_sha256'][:16]}... in {receipt['ledger']} "
        f"(event #{receipt['event_seq']}, checkpoint root "
        f"{str(receipt['checkpoint_root'])[:16]}...)"
    )
    return 0


def _gate(args: argparse.Namespace) -> int:
    # Spec 003 FR-5.5 (RT2-L3/L4 seams): the gate parses strictly —
    # bare NaN/Infinity tokens are refused at load (parse_constant),
    # never reaching the cross-check, whose recompute only ever sees
    # finite numbers and whose digest serialisation refuses them.
    value = _load_json_strict(args.input, what="assessment")
    outcome = _gate_cross_check(value, source=args.input.as_posix())
    if getattr(args, "require_lane1_pass", False):
        # Spec 006 A3: the decision is lane 1's. The cross-check
        # above has already recomputed lane 1 from the file and
        # refused any mismatch, so this recomputation — the same
        # pure function over the same validated contents — is the
        # value the exit code now follows. The exit mapping is the
        # headline's contract applied to lane 1: pass/warn 0, the
        # iterate family (iterate, clarify, gather_evidence,
        # abstain) 1, block 2.
        lane_1 = _gate_lane_1_outcome(value, source=args.input.as_posix())
        print(f"AEE gate: {outcome} (lane 1: {lane_1})")
        return _exit_code(lane_1)
    print(f"AEE gate: {outcome}")
    return _exit_code(outcome)


def _gate_lane_1_outcome(value: dict[str, Any], *, source: str) -> str:
    """Recompute the lane-1 outcome from an assessment's contents
    (Spec 006 A3), mirroring ``AEEEngine._lane_1_outcome`` over the
    serialised record: the routing steps run over the unresolved
    failures EXCLUDING the draft-cap records (the draft cap is
    lane-2 state, and its records are its visible form), with no
    draft branch and no stage rule; verdict demotion applies for
    lane-1 reasons only (``lane_1_challenge_applies``), and an
    ABSTAIN verdict demotes a pass to abstain. The caller
    (_gate_cross_check) has already validated the file's structure;
    this function reads only the validated pieces.
    """
    claims = value.get("claims") or []
    scores = value.get("scores") or {}
    metadata = value.get("metadata") or {}
    threshold = float(metadata.get("threshold", 0.70))
    failures: list[dict[str, Any]] = []
    for claim in claims:
        if isinstance(claim, dict) and isinstance(claim.get("failures"), list):
            failures.extend(f for f in claim["failures"] if isinstance(f, dict))
    unresolved = [
        failure
        for failure in failures
        if not failure.get("resolved", False)
        and failure.get("category") not in {"stage_cap", "verified_unexplained", "draft_cap"}
    ]
    below = any(
        isinstance(score, dict)
        and isinstance(score.get("propagated_score"), (int, float))
        and float(score["propagated_score"]) < threshold
        for score in scores.values()
    )

    def _severity(failure: dict[str, Any]) -> str:
        return str(failure.get("severity", "")).lower()

    def _category(failure: dict[str, Any]) -> str:
        return str(failure.get("category", ""))

    if any(_severity(failure) == "critical" for failure in unresolved):
        recomputed = "block"
    elif any(
        _severity(failure) == "high" and _category(failure) == "contradiction"
        for failure in unresolved
    ):
        recomputed = "clarify"
    elif any(
        _severity(failure) == "high"
        and _category(failure) in {"missing_evidence", "unsupported_claim", "unverified_assertion"}
        for failure in unresolved
    ):
        recomputed = "gather_evidence"
    elif unresolved or below:
        recomputed = "iterate"
    else:
        recomputed = "pass"
    verdicts = value.get("verdicts")
    if recomputed == "pass" and isinstance(verdicts, dict) and verdicts:
        parsed: list[tuple[str, list[str]]] = []
        for verdict in verdicts.values():
            if not isinstance(verdict, dict):
                continue
            reasons_raw = verdict.get("reasons")
            reasons = (
                [str(reason) for reason in reasons_raw] if isinstance(reasons_raw, list) else []
            )
            parsed.append((str(verdict.get("verdict", "")).lower(), reasons))
        if any(verdict_value == "abstain" for verdict_value, _ in parsed):
            recomputed = "abstain"
        elif any(
            verdict_value == "challenge" and lane_1_challenge_applies(reasons)
            for verdict_value, reasons in parsed
        ):
            recomputed = "iterate"
    return recomputed


# -- Spec 006 A4: recorded stage and status acts ---------------------------


def _bundle_raw(path: Path) -> Any:
    """The bundle file's parsed JSON, read strictly, for write-back.

    Stage and ratify rewrite the bundle: the parsed top level is
    retained so keys the commands do not own (a spec bundle's spec,
    version, and date fields, for instance) survive the rewrite.
    Only JSON bundles are writable — a Markdown bundle is an
    extraction surface, not a record these commands amend.
    """
    if path.suffix.lower() != ".json":
        raise ValueError(
            f"{path.as_posix()} is not a JSON claims bundle; stage and "
            "ratify amend JSON bundles only"
        )
    return _load_json_strict(path, what="bundle")


def _registry_for(bundle: Path, explicit: Path | None) -> IdentityRegistry | None:
    """The identity registry for a bundle: an explicit path wins;
    otherwise a bundle-adjacent identities.json, when present — the
    same discovery the loader performs (Spec 004 R3.2/OD-T4)."""
    if explicit is not None:
        return IdentityRegistry.from_path(str(explicit))
    adjacent = bundle.parent / "identities.json"
    if adjacent.is_file():
        return IdentityRegistry.from_path(str(adjacent))
    return None


def _find_claim(claims: list[Claim], raw_id: str, *, command: str) -> Claim:
    wanted = normalize_claim_id(raw_id)
    matches = [claim for claim in claims if claim.id == wanted]
    if not matches:
        raise ValueError(f"{command}: no claim {raw_id!r} in this bundle")
    if len(matches) > 1:
        raise ValueError(
            f"{command}: bundle contains duplicate claim id {wanted!r}; "
            "refusing to amend an ambiguous record"
        )
    return matches[0]


def _write_bundle_back(path: Path, raw: Any, claims: list[Claim]) -> None:
    """Write the amended bundle atomically (temp file + rename, the
    FR-5.2 discipline): a failed write never leaves a partial bundle
    behind. Non-claims top-level keys are preserved from ``raw``."""
    serialized = [claim.to_dict() for claim in claims]
    if isinstance(raw, dict):
        value: Any = dict(raw)
        value["claims"] = serialized
    elif isinstance(raw, list):
        value = serialized
    else:
        value = {"schema_version": "1.0", "claims": serialized}
    _atomic_write_text(path, _dumps(value, indent=2) + "\n")


def _append_recorded_event(
    explicit_ledger: Path | None,
    bundle: Path,
    *,
    event_type: str,
    payload: dict[str, Any],
    actor: str,
) -> Path | None:
    """Append a recorded act to the project ledger, when one is present.

    An explicit --ledger path is used as given (the append creates
    it when absent, as the assess command's ledger is). Without one,
    the default ledger location is used when the file already
    exists — beside the bundle first (the bundle's own project),
    then under the working directory: the act joins the project's
    existing record, and no new ledger is invented for a project
    that keeps none. Returns the ledger path used, or None when no
    ledger was present.
    """
    ledger_path: Path | None = explicit_ledger
    if ledger_path is None:
        for candidate in (
            bundle.parent / DEFAULT_LEDGER_PATH,
            Path.cwd() / DEFAULT_LEDGER_PATH,
        ):
            if candidate.is_file():
                ledger_path = candidate
                break
    if ledger_path is None:
        return None
    HashChainLedger(ledger_path).append(event_type, payload, actor=actor)
    return ledger_path


def _stage(args: argparse.Namespace) -> int:
    raw = _bundle_raw(args.bundle)
    registry = _registry_for(args.bundle, getattr(args, "identity_registry", None))
    claims = load_claims(args.bundle, identity_registry=registry)
    claim = _find_claim(claims, args.claim, command="stage")
    try:
        target = ClaimStage(args.to)
    except ValueError:
        valid = ", ".join(stage.value for stage in ClaimStage)
        raise ValueError(
            f"stage: --to value {args.to!r} is not a stage; valid stages: {valid}"
        ) from None
    if not args.basis.strip():
        raise ValueError(
            "stage: --basis must not be empty; an advance without a stated basis is not auditable"
        )
    actor = args.recorded_by if args.recorded_by and args.recorded_by.strip() else "aee"
    if target == ClaimStage.EXPLAINED:
        # Spec 004 R1.2/R3: the explanation event is exposition
        # evidence by a named human. Every exposition item on the
        # claim is validated with the existing named-human rule; no
        # valid exposition, no advance.
        exposition = [item for item in claim.evidence if item.kind == EvidenceKind.EXPOSITION]
        if not exposition:
            raise ValueError(
                f"stage: claim {claim.id!r} cannot advance to 'explained': "
                "it carries no exposition evidence (an explanation by a "
                "named human, Spec 004 R3)"
            )
        for item in exposition:
            validate_exposition_evidence(
                item, registry, context=f"claim '{claim.id}' exposition evidence"
            )
    if target in {ClaimStage.ACCEPTED, ClaimStage.DIGESTED}:
        # Acceptance and digestion are human acts: the recorded-by
        # name must resolve to a person in the identity registry.
        if not args.recorded_by or not args.recorded_by.strip():
            raise ValueError(
                f"stage: advancing claim {claim.id!r} to {target.value!r} "
                "requires --recorded-by naming a person in the project "
                "identity registry"
            )
        if registry is None:
            raise ValueError(
                f"stage: no identity registry is available to resolve "
                f"--recorded-by {args.recorded_by!r}; supply a "
                "bundle-adjacent identities.json or --identity-registry"
            )
        entry = registry.resolve(args.recorded_by)
        if entry is None:
            raise ValueError(
                f"stage: --recorded-by {args.recorded_by!r} does not "
                "resolve in the identity registry"
            )
        if entry.kind != IdentityKind.PERSON:
            raise ValueError(
                f"stage: --recorded-by {args.recorded_by!r} resolves to "
                f"identity {entry.id!r} of kind {entry.kind.value!r}, not "
                f"'person'; {target.value} is a human act and only a "
                "named person can record it"
            )
    previous = claim.stage
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    # Forward-only, recorded, with a basis: the model's own rule
    # (advance_stage raises ValueError — a clean exit 2 via main —
    # for a backward or stationary move).
    event = claim.advance_stage(target, author=actor, date=timestamp, basis=args.basis)
    _write_bundle_back(args.bundle, raw, claims)
    ledger_path = _append_recorded_event(
        getattr(args, "ledger", None),
        args.bundle,
        event_type="stage_event",
        payload={
            "claim_id": claim.id,
            "bundle": args.bundle.as_posix(),
            "from_stage": previous.value,
            "to_stage": target.value,
            "basis": args.basis,
            "recorded_by": actor,
            "stage_event": event.to_dict(),
        },
        actor=actor,
    )
    note = f"; recorded in ledger {ledger_path.as_posix()}" if ledger_path is not None else ""
    print(
        f"stage: claim {claim.id} advanced from {previous.value} to {target.value} by {actor}{note}"
    )
    return 0


def _ratify(args: argparse.Namespace) -> int:
    raw = _bundle_raw(args.bundle)
    claims = load_claims(args.bundle)
    claim = _find_claim(claims, args.claim, command="ratify")
    try:
        status = ClaimStatus(args.status)
    except ValueError:
        valid = ", ".join(member.value for member in ClaimStatus)
        raise ValueError(
            f"ratify: --status value {args.status!r} is not a status; valid statuses: {valid}"
        ) from None
    if not args.basis.strip():
        raise ValueError(
            "ratify: --basis must not be empty; a status change "
            "without a stated basis is not auditable"
        )
    if not args.recorded_by.strip():
        raise ValueError("ratify: --recorded-by must name who records this act")
    if status == ClaimStatus.SUPPORTED and claim.stage == ClaimStage.CREATED:
        # Mirror of the stage table (aee.stage ALLOWED_STATUSES): at
        # stage 'created' the only reportable status is 'draft', so
        # ratifying straight to 'supported' would state a settlement
        # no recorded check has earned yet.
        raise ValueError(
            f"ratify: claim {claim.id!r} is at stage 'created' and "
            "cannot be ratified to 'supported': at stage 'created' "
            "the only reportable status is 'draft' (Spec 004 R1.3). "
            "Record a checking event first (aee stage --to checked), "
            "then ratify."
        )
    previous = claim.status
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    claim.status = status
    existing = claim.metadata.get("ratification_events")
    events: list[Any] = list(existing) if isinstance(existing, list) else []
    events.append(
        {
            "status": status.value,
            "previous_status": previous.value,
            "author": args.recorded_by,
            "date": timestamp,
            "basis": args.basis,
        }
    )
    claim.metadata["ratification_events"] = events
    _write_bundle_back(args.bundle, raw, claims)
    ledger_path = _append_recorded_event(
        getattr(args, "ledger", None),
        args.bundle,
        event_type="ratification",
        payload={
            "claim_id": claim.id,
            "bundle": args.bundle.as_posix(),
            "from_status": previous.value,
            "to_status": status.value,
            "basis": args.basis,
            "recorded_by": args.recorded_by,
        },
        actor=args.recorded_by,
    )
    note = f"; recorded in ledger {ledger_path.as_posix()}" if ledger_path is not None else ""
    print(
        f"ratify: claim {claim.id} status changed from {previous.value} "
        f"to {status.value} by {args.recorded_by}{note}"
    )
    return 0


def _gate_not_understood_check(value: dict[str, Any], *, source: str) -> None:
    """Spec 004 R5.2/R5.3: an assessment serialised without a
    `not_understood` statement - or with an empty one while the
    record carries open items (unresolved challenges, stage caps) -
    is itself a finding, and a finding does not gate. Pre-realignment
    assessments, which predate the field, fail here by design: the
    gate is where silence stops being a compatibility strategy."""
    if "not_understood" not in value:
        raise ValueError(
            f"gate: {source} carries no 'not_understood' statement "
            "(Spec 004 R5.2/R5.3); an assessment that does not state "
            "what it does not establish is incomplete"
        )
    entries = value["not_understood"]
    if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
        raise ValueError(
            f"gate: {source} has a malformed 'not_understood' statement "
            "(expected a list of strings, Spec 004 R5.2)"
        )
    if entries:
        return
    # "Open items" here means the same thing the engine's own
    # not_understood generation means (aee.engine._not_understood):
    # the cap records — stage_cap, verified_unexplained, and the
    # FR-2.3 draft_cap — are explanatory records the engine answers
    # with the cap itself, not with a residual-unknowns entry, so a
    # bundle whose only open records are draft caps legitimately
    # carries an empty statement and must not be refused here
    # (Spec 006 A3: the positive control is exactly that bundle).
    open_items = bool(value.get("stage_caps")) or any(
        isinstance(claim, dict)
        and any(
            isinstance(failure, dict)
            and not failure.get("resolved", False)
            and failure.get("category") not in {"stage_cap", "verified_unexplained", "draft_cap"}
            for failure in claim.get("failures", [])
            if isinstance(failure, dict)
        )
        for claim in value.get("claims", [])
        if isinstance(claim, dict)
    )
    if open_items:
        raise ValueError(
            f"gate: {source} states an empty 'not_understood' while its "
            "record carries open items (Spec 004 R5.3)"
        )


def _gate_cross_check(value: Any, *, source: str) -> str:
    """Spec 003 FR-1.2 (RT2-H1): the gate must not trust the outcome
    string. A gateable file is a structurally complete assessment —
    claims, per-claim scores, a summary carrying the engine's counts,
    and threshold metadata — whose stated outcome equals the outcome
    recomputed from its own contents under the engine's rules
    (including policy-verdict demotion). Where the assessment records
    a ledger, the assessment's SHA-256 must be present in that ledger
    and the chain must verify. Any failure raises ValueError, which
    main() reports as a clean input error (exit 2) — a fabricated or
    inconsistent file never gates as pass. Returns the stated outcome.
    """
    if not isinstance(value, dict):
        raise ValueError(f"gate: {source} is not an assessment (expected a JSON object)")
    outcome = value.get("outcome")
    if outcome not in _GATE_OUTCOMES:
        raise ValueError(f"gate: {source} has no valid assessment outcome: {outcome!r}")
    summary = value.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError(f"gate: {source} is not a complete assessment (missing summary)")
    _gate_not_understood_check(value, source=source)
    claims = value.get("claims")
    scores = value.get("scores")
    metadata = value.get("metadata")
    if (
        not isinstance(claims, list)
        or not isinstance(scores, dict)
        or not isinstance(metadata, dict)
    ):
        raise ValueError(
            f"gate: {source} is not a complete assessment (requires claims, scores, and metadata)"
        )
    threshold = metadata.get("threshold")
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not 0.0 <= float(threshold) <= 1.0
    ):
        raise ValueError(f"gate: {source} carries no valid threshold metadata")
    claim_ids: list[str] = []
    failures: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("id"), str):
            raise ValueError(f"gate: {source} has a claim without an id")
        if claim["id"] in claim_ids:
            raise ValueError(f"gate: {source} contains duplicate claim id {claim['id']!r}")
        claim_ids.append(claim["id"])
        claim_failures = claim.get("failures")
        if not isinstance(claim_failures, list) or not all(
            isinstance(failure, dict) for failure in claim_failures
        ):
            raise ValueError(f"gate: {source} claim {claim['id']!r} has no failure-mode record")
        failures.extend(claim_failures)
    if not claim_ids:
        raise ValueError(
            f"gate: {source} contains zero claims: an empty assessment "
            "never passes (Spec 003 FR-1.1)"
        )
    if set(scores) != set(claim_ids):
        raise ValueError(
            f"gate: {source} scores do not cover exactly its claims "
            f"(missing: {sorted(set(claim_ids) - set(scores))}, "
            f"extra: {sorted(set(scores) - set(claim_ids))})"
        )
    propagated: dict[str, float] = {}
    for claim_id, score in scores.items():
        if not isinstance(score, dict) or not isinstance(
            score.get("propagated_score"), (int, float)
        ):
            raise ValueError(f"gate: {source} score for {claim_id!r} has no propagated_score")
        propagated[claim_id] = float(score["propagated_score"])
    match = _SUMMARY_COUNTS.search(summary)
    if match is None:
        raise ValueError(f"gate: {source} summary does not carry the engine's assessment counts")
    n_claims, n_failures, n_below, summary_threshold = match.groups()
    # The summary counts failure INSTANCES (the stress run's list),
    # while serialization repeats a shared-id claim's failures on each
    # duplicate claim object (Spec 003 FR-1.3 makes such assessments
    # real). Count distinct failure ids when every failure carries
    # one, so a duplicate-id block assessment cross-checks cleanly.
    if failures and all(isinstance(failure.get("id"), str) for failure in failures):
        failure_count = len({failure["id"] for failure in failures})
    else:
        failure_count = len(failures)
    below = sum(1 for score in propagated.values() if score < float(threshold))
    if (
        int(n_claims) != len(claim_ids)
        or int(n_failures) != failure_count
        or int(n_below) != below
        or abs(float(summary_threshold) - float(threshold)) > 0.005
    ):
        raise ValueError(
            f"gate: {source} summary counts disagree with its contents "
            f"(summary: {n_claims} claim(s), {n_failures} failure mode(s), "
            f"{n_below} below {summary_threshold}; contents: {len(claim_ids)} "
            f"claim(s), {failure_count} failure mode(s), {below} below "
            f"the {float(threshold):.2f} threshold)"
        )
    # Spec 004 R1.3/R3.3: stage_cap and verified_unexplained records
    # are explanatory and never route the outcome (the R1.4 stage rule
    # below does that work), so the recompute excludes them, mirroring
    # AEEEngine._outcome's _NON_OUTCOME_CATEGORIES.
    unresolved = [
        failure
        for failure in failures
        if not failure.get("resolved", False)
        and failure.get("category") not in {"stage_cap", "verified_unexplained"}
    ]

    def _severity(failure: dict[str, Any]) -> str:
        return str(failure.get("severity", "")).lower()

    def _category(failure: dict[str, Any]) -> str:
        return str(failure.get("category", ""))

    if any(_severity(failure) == "critical" for failure in unresolved):
        recomputed = "block"
    elif any(
        _severity(failure) == "high" and _category(failure) == "contradiction"
        for failure in unresolved
    ):
        recomputed = "clarify"
    elif any(
        _severity(failure) == "high"
        and _category(failure) in {"missing_evidence", "unsupported_claim", "unverified_assertion"}
        for failure in unresolved
    ):
        recomputed = "gather_evidence"
    elif unresolved or below:
        recomputed = "iterate"
    else:
        recomputed = "pass"
    verdicts = value.get("verdicts")
    if recomputed == "pass" and isinstance(verdicts, dict) and verdicts:
        verdict_values = {
            str(verdict.get("verdict", "")).lower()
            for verdict in verdicts.values()
            if isinstance(verdict, dict)
        }
        if "abstain" in verdict_values:
            recomputed = "abstain"
        elif "challenge" in verdict_values or "unjudged" in verdict_values:
            recomputed = "iterate"
    if recomputed == "pass":
        # Spec 004 R1.4: `pass` requires every covered claim at
        # EFFECTIVE stage explained+ (the engine judges caps on the
        # effective stage; the gate mirrors it via the recorded
        # stage_caps). Claims in a pre-realignment record carry no
        # stage; the cap applies only where a stage is recorded (the
        # current engine always records one).
        effective_caps = {
            cap["claim_id"]: cap.get("stage")
            for cap in value.get("stage_caps", [])
            if isinstance(cap, dict) and isinstance(cap.get("claim_id"), str)
        }
        stages = [
            effective_caps.get(claim["id"], claim.get("stage"))
            for claim in claims
            if isinstance(claim, dict)
        ]
        if any(stage in {"created", "checked"} for stage in stages):
            recomputed = "iterate"
    reported = value.get("reported_statuses")
    if isinstance(reported, dict):
        # R1.3 cross-check: the reported (capped) status of every
        # claim must equal the cap of its recorded status and its
        # EFFECTIVE stage. The engine records effective-stage caps in
        # `stage_caps` (P1 decomposition/attribution overrides and the
        # P2 machine-only gate can lower the effective stage below
        # the stored one); where a record exists it governs, and the
        # record itself is validated against its own stage so a
        # fabricated record cannot launder a status. Without a
        # record, the stored stage governs (the P0 rule).
        recorded_caps = {
            cap["claim_id"]: cap
            for cap in value.get("stage_caps", [])
            if isinstance(cap, dict) and isinstance(cap.get("claim_id"), str)
        }
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            status_raw, stage_raw = claim.get("status"), claim.get("stage")
            if not isinstance(status_raw, str) or not isinstance(stage_raw, str):
                continue
            record = recorded_caps.get(claim["id"])
            effective_raw = record.get("stage") if record else stage_raw
            if not isinstance(effective_raw, str):
                raise ValueError(
                    f"gate: {source} claim {claim['id']!r} carries a malformed stage_caps record"
                )
            try:
                expected = reported_status_for(
                    ClaimStatus(status_raw), ClaimStage(effective_raw)
                ).value
            except ValueError:
                raise ValueError(
                    f"gate: {source} claim {claim.get('id')!r} carries an "
                    "unknown status or stage value"
                ) from None
            if record is not None:
                if STAGE_ORDER[ClaimStage(effective_raw)] > STAGE_ORDER[ClaimStage(stage_raw)]:
                    raise ValueError(
                        f"gate: cross-check failed for {source}: stage_caps "
                        f"record for claim {claim['id']!r} raises its stage "
                        f"from {stage_raw!r} to {effective_raw!r}; caps only lower"
                    )
                if record.get("reported_status") != expected:
                    raise ValueError(
                        f"gate: cross-check failed for {source}: stage_caps "
                        f"record for claim {claim['id']!r} states cap "
                        f"{record.get('reported_status')!r} but status {status_raw!r} "
                        f"at effective stage {effective_raw!r} requires "
                        f"{expected!r} (Spec 004 R1.3)"
                    )
            if reported.get(claim["id"]) != expected:
                raise ValueError(
                    f"gate: cross-check failed for {source}: reported status "
                    f"for claim {claim['id']!r} is {reported.get(claim['id'])!r}, "
                    f"but the stage cap (status {status_raw!r} at effective "
                    f"stage {effective_raw!r}) requires {expected!r} (Spec 004 R1.3)"
                )
    if outcome != recomputed and not (outcome == "warn" and recomputed == "pass" and failures):
        raise ValueError(
            f"gate: cross-check failed for {source}: stated outcome "
            f"{outcome!r} does not match the outcome {recomputed!r} "
            "recomputed from its scores, failures, and threshold"
        )
    # Spec 006 A3: the lane-1 outcome is cross-checked the same way.
    # A file whose recorded lanes.lane_1.outcome disagrees with the
    # lane-1 outcome recomputed from its own contents is refused
    # exactly like a forged headline — the lane pair is part of the
    # verdict, not decoration a file may restate at will. A file
    # with no lanes record at all records no lane-1 outcome, which
    # cannot match a recomputation and is refused on the same leg.
    lanes = value.get("lanes")
    recorded_lane_1: Any = None
    if isinstance(lanes, dict) and isinstance(lanes.get("lane_1"), dict):
        recorded_lane_1 = lanes["lane_1"].get("outcome")
    lane_1_recomputed = _gate_lane_1_outcome(value, source=source)
    if recorded_lane_1 != lane_1_recomputed:
        raise ValueError(
            f"gate: cross-check failed for {source}: recorded lane 1 "
            f"outcome {recorded_lane_1!r} does not match the lane 1 "
            f"outcome {lane_1_recomputed!r} recomputed from its "
            "scores, failures, verdicts, and threshold (Spec 006 A3)"
        )
    _gate_ledger_check(value, metadata, source=source)
    return str(outcome)


def _gate_ledger_check(value: dict[str, Any], metadata: dict[str, Any], *, source: str) -> None:
    """FR-1.2 ledger leg: where the assessment records a ledger
    (metadata.ledger from a CLI assess run), the chain must verify
    and must contain this assessment's SHA-256 (the digest
    HashChainLedger.append_assessment records). Assessments with no
    ledger record (API-produced, or an explicit --no-ledger run whose
    metadata says mode "disabled") carry nothing to check against."""
    ledger_meta = metadata.get("ledger")
    if not isinstance(ledger_meta, dict) or ledger_meta.get("mode") in {None, "disabled"}:
        return
    ledger_path_value = ledger_meta.get("path")
    if not isinstance(ledger_path_value, str) or not ledger_path_value:
        raise ValueError(f"gate: {source} records a ledger without a path")
    ledger_path = Path(ledger_path_value)
    if not ledger_path.exists():
        raise ValueError(
            f"gate: cross-check failed for {source}: recorded ledger "
            f"{ledger_path_value} does not exist"
        )
    ledger = HashChainLedger(ledger_path)
    verification = ledger.verify()
    if not verification.chain_valid:
        raise ValueError(
            f"gate: cross-check failed for {source}: ledger "
            f"{ledger_path_value} does not verify ({'; '.join(verification.errors)})"
        )
    # Spec 003 FR-4.1: the chain alone cannot see tail truncation, so
    # the gate additionally requires the ledger's head anchor to verify.
    # A ledger whose anchor is missing, stale, or mismatched fails here
    # even when its remaining chain is internally consistent.
    anchor_verification = ledger.verify(require_anchor=True)
    if not anchor_verification.valid:
        raise ValueError(
            f"gate: cross-check failed for {source}: ledger "
            f"{ledger_path_value} anchor check failed "
            f"(anchor_status={anchor_verification.anchor_status}): "
            f"{'; '.join(anchor_verification.errors)}"
        )
    if not verification.valid:
        raise ValueError(
            f"gate: cross-check failed for {source}: ledger "
            f"{ledger_path_value} does not verify ({'; '.join(verification.errors)})"
        )
    # FR-5.8: the digest is the ledger's own content digest
    # (aee.ledger.assessment_content_digest — assessment content with
    # the wall-clock created_at excluded), shared with
    # append_assessment so the gate checks exactly what was recorded.
    digest = assessment_content_digest(value)
    recorded = {
        entry.get("payload", {}).get("assessment_sha256")
        for entry in ledger.entries()
        if isinstance(entry, dict) and isinstance(entry.get("payload"), dict)
    }
    if digest not in recorded:
        raise ValueError(
            f"gate: cross-check failed for {source}: assessment hash "
            f"is not recorded in its ledger {ledger_path_value}"
        )


def _graph(args: argparse.Namespace) -> int:
    if args.output is not None:
        _guard_output_path(args.output, [(args.input, "the --input bundle")])
    rendered = ClaimGraph(load_claims(args.input, strict=not args.lenient)).to_mermaid()
    if args.output:
        _atomic_write_text(args.output, rendered)
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

    # Generate mode. FR-5.1: the register output must not resolve onto
    # the matrix it is generated from or the existing register it
    # preserves closures from. (--close above is the deliberate
    # exception: it updates the register artifact in place, read fully
    # before the atomic write replaces it.)
    if args.output is not None:
        gaps_protected: list[tuple[Path, str]] = [(args.matrix, "the --matrix file")]
        if args.existing is not None:
            gaps_protected.append((args.existing, "the --existing register"))
        _guard_output_path(args.output, gaps_protected)
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
    _atomic_write_text(output, register.to_markdown())


def _demo() -> int:
    # Spec 004: the demo walks the full realigned pipeline, not just
    # lane 1. The load-test result is machine verification; the claim
    # reaches stage `accepted` only through lane 2 - a named human
    # explains the result (exposition evidence, R3) and a recorded
    # human acceptance event advances the stage (R1.2). The explainer
    # is a declared `person` in an identity registry, and the
    # exposition item is resolved through the same R3.2 rule the
    # strict loader enforces, so the lane-2 support is genuine in the
    # model's own terms rather than a label: without it, R5.1 caps a
    # machine-only claim at `checked`, `supported` reports as
    # `partially_supported` (R1.3), and the demo exits 1 on
    # `iterate` - exactly as it should.
    explainer = "jane-doe"
    registry = IdentityRegistry.from_dict(
        {"identities": [{"id": explainer, "name": "Jane Doe", "kind": "person"}]}
    )
    exposition = Evidence(
        ref="notes/latency-walkthrough.md",
        kind=EvidenceKind.EXPOSITION,
        direction=EvidenceDirection.SUPPORTS,
        source_quality=SourceQuality.HUMAN,
        source_id=explainer,
        description=(
            "Jane Doe's walkthrough of the load test: what the observed "
            "83 ms p95 does and does not establish, and the boundary "
            "conditions the result depends on"
        ),
    )
    validate_exposition_evidence(exposition, registry, context="demo claim 'REQ-DEMO-001'")
    claim = Claim(
        id="REQ-DEMO-001",
        text="The API always returns within 100 ms",
        kind=ClaimKind.REQUIREMENT,
        status=ClaimStatus.SUPPORTED,
        stage=ClaimStage.ACCEPTED,
        stage_events=[
            StageEvent(
                kind=StageEventKind.CHECKED,
                author="aee demo",
                date="2026-09-04",
                basis="Demo claim: load test executed and its result assessed",
            ),
            StageEvent(
                kind=StageEventKind.EXPLAINED,
                author=explainer,
                date="2026-09-05",
                basis=(
                    "Demo claim: Jane Doe's exposition of the load-test "
                    "evidence (notes/latency-walkthrough.md)"
                ),
            ),
            StageEvent(
                kind=StageEventKind.ACCEPTED,
                author=explainer,
                date="2026-09-05",
                basis="Demo claim: recorded human acceptance of the explained load-test evidence",
            ),
        ],
        boundary=[
            "API requests in production region us-east-1",
            "p95 latency within the nominal load profile",
        ],
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
            ),
            exposition,
        ],
    )
    result = AEEEngine().assess([claim], project="demo", phase="after_specify")
    print(_dumps(result.to_dict(), indent=2))
    return _exit_code(result.outcome)


def _score_view(value: dict[str, Any], *, source: Path, claim_id: str) -> ClaimScore:
    """Rebuild one ClaimScore from its serialized form, validating as
    we go (Spec 003 FR-5.3): malformed-but-readable review inputs get
    a named error (file, claim, field), never a bare conversion
    traceback or an opaque AttributeError."""

    def _number(container: dict[str, Any], key: str) -> float:
        raw = container.get(key, 0.0)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(
                f"review: {source.as_posix()}: score field {key!r} for claim "
                f"{claim_id!r} must be a number, got {type(raw).__name__}"
            )
        try:
            number = float(raw)
        except OverflowError:
            raise ValueError(
                f"review: {source.as_posix()}: score field {key!r} for claim "
                f"{claim_id!r} is out of range"
            ) from None
        if not math.isfinite(number):
            raise ValueError(
                f"review: {source.as_posix()}: score field {key!r} for claim "
                f"{claim_id!r} must be finite"
            )
        return number

    components = value.get("components", {})
    if not isinstance(components, dict):
        raise ValueError(
            f"review: {source.as_posix()}: score 'components' for claim "
            f"{claim_id!r} must be an object"
        )
    notes = value.get("notes", [])
    if not isinstance(notes, list):
        raise ValueError(
            f"review: {source.as_posix()}: score 'notes' for claim {claim_id!r} must be a list"
        )
    return ClaimScore(
        claim_id=str(value.get("claim_id", claim_id)),
        direct_score=_number(value, "direct_score"),
        propagated_score=_number(value, "propagated_score"),
        evidence_score=_number(components, "evidence"),
        independence_score=_number(components, "independence"),
        falsifiability_score=_number(components, "falsifiability"),
        boundary_score=_number(components, "boundary"),
        contradiction_penalty=_number(components, "contradiction_penalty"),
        notes=[str(note) for note in notes],
        declared_state=(
            dict(value["declared_state"]) if isinstance(value.get("declared_state"), dict) else {}
        ),
        propagation_status=str(value.get("propagation", {}).get("status", "propagated"))
        if isinstance(value.get("propagation"), dict)
        else "propagated",
        cycle_component=[
            str(member) for member in value.get("propagation", {}).get("cycle_component", [])
        ]
        if isinstance(value.get("propagation"), dict)
        else [],
    )


@dataclass(frozen=True, slots=True)
class _AssessmentView:
    scores: dict[str, ClaimScore]
    verdicts: dict[str, ClaimVerdict]
    # FR-8.11(a): the failure channel - rebuilt from the serialised
    # claims' failure records so `aee review` sees failure movement,
    # not only score movement.
    failures: tuple[Any, ...] = ()


def _assessment_view(path: Path) -> _AssessmentView:
    """Rebuild the score/verdict views build_review_queue consumes
    from a serialized assessment (Assessment.to_dict output).

    The file is parsed as strict JSON (bare NaN/Infinity refused,
    FR-5.5) and structurally validated: any malformed-but-readable
    input raises a ValueError naming the file and the offending
    field, which main() reports as a clean exit 2 (FR-5.3)."""
    data = _load_json_strict(path, what="assessment")
    if not isinstance(data, dict):
        raise ValueError(f"review: {path.as_posix()} is not an assessment (expected a JSON object)")
    raw_scores = data.get("scores", {})
    if not isinstance(raw_scores, dict):
        raise ValueError(
            f"review: {path.as_posix()}: 'scores' must be an object mapping claim ids to scores"
        )
    scores: dict[str, ClaimScore] = {}
    for claim_id, score in raw_scores.items():
        if not isinstance(score, dict):
            raise ValueError(
                f"review: {path.as_posix()}: score for claim {claim_id!r} must be an object"
            )
        scores[claim_id] = _score_view(score, source=path, claim_id=claim_id)
    raw_verdicts = data.get("verdicts", {})
    if not isinstance(raw_verdicts, dict):
        raise ValueError(
            f"review: {path.as_posix()}: 'verdicts' must be an object mapping claim ids to verdicts"
        )
    verdicts: dict[str, ClaimVerdict] = {}
    for claim_id, verdict in raw_verdicts.items():
        if not isinstance(verdict, dict) or "verdict" not in verdict:
            raise ValueError(
                f"review: {path.as_posix()}: verdict for claim {claim_id!r} "
                "must be an object with a 'verdict' field"
            )
        try:
            parsed_verdict = Verdict(str(verdict["verdict"]))
        except ValueError:
            valid = ", ".join(member.value for member in Verdict)
            raise ValueError(
                f"review: {path.as_posix()}: verdict for claim {claim_id!r} "
                f"has invalid value {verdict['verdict']!r}; valid values: {valid}"
            ) from None
        reasons = verdict.get("reasons", [])
        if not isinstance(reasons, list):
            raise ValueError(
                f"review: {path.as_posix()}: verdict 'reasons' for claim "
                f"{claim_id!r} must be a list"
            )
        verdicts[claim_id] = ClaimVerdict(
            claim_id, parsed_verdict, [str(reason) for reason in reasons]
        )
    failures: list[Any] = []
    raw_claims = data.get("claims", [])
    if isinstance(raw_claims, list):
        for raw_claim in raw_claims:
            if not isinstance(raw_claim, dict):
                continue
            for raw_failure in raw_claim.get("failures", []):
                if not isinstance(raw_failure, dict):
                    continue
                try:
                    severity = Severity(str(raw_failure.get("severity", "low")))
                except ValueError:
                    continue
                failures.append(
                    SimpleNamespace(
                        claim_id=str(raw_failure.get("claim_id", raw_claim.get("id", ""))),
                        id=str(raw_failure.get("id", "")),
                        severity=severity,
                        category=str(raw_failure.get("category", "")),
                        resolved=bool(raw_failure.get("resolved", False)),
                    )
                )
    return _AssessmentView(scores=scores, verdicts=verdicts, failures=tuple(failures))


def _review(args: argparse.Namespace) -> int:
    if args.output is not None:
        _guard_output_path(
            args.output,
            [
                (args.previous, "the --previous assessment"),
                (args.current, "the --current assessment"),
            ],
        )
    current_data = _load_json_strict(args.current, what="assessment")
    current_metadata = current_data.get("metadata", {}) if isinstance(current_data, dict) else {}
    threshold = current_metadata.get("threshold")
    queue = build_review_queue(
        _assessment_view(args.previous),
        _assessment_view(args.current),
        materiality=args.materiality,
        limit=args.limit,
        baseline=_assessment_view(args.baseline) if args.baseline else None,
        threshold=float(threshold) if isinstance(threshold, (int, float)) else None,
    )
    _write_or_print(queue.to_dict(), args.output)
    return 0


def _dumps(value: Any, **kwargs: Any) -> str:
    """Spec 003 FR-5.5 (RT2-M11): every CLI JSON emission is strict
    JSON — ``allow_nan=False``, so a non-finite value fails loudly at
    serialisation time (ValueError -> clean exit 2) instead of
    landing on disk or stdout as a bare ``NaN``/``Infinity`` token
    that strict parsers (and non-Python tooling) reject."""
    return json.dumps(value, allow_nan=False, **kwargs)


def _load_json_strict(path: Path, *, what: str) -> Any:
    """Load a JSON file as strict JSON (Spec 003 FR-3.3/FR-5.5):
    bare ``NaN``/``Infinity`` tokens are refused at parse time with a
    named error — Python's json accepts them by default, and a gate
    or review that quietly parsed them would be reasoning over
    values its own outputs may never contain."""

    def _reject_constant(name: str) -> None:
        raise ValueError(
            f"{what} file {path.as_posix()}: non-finite number {name!r} "
            "is not allowed in strict JSON"
        )

    try:
        # Duplicate keys are refused here too (FR-5.4): a gate or
        # review reasoning over a last-wins parse of a doubled field
        # would be reasoning over whichever value came last.
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=duplicate_key_hook(f"{what} file {path.as_posix()}"),
        )
    except RecursionError:
        raise ValueError(
            f"{what} file {path.as_posix()}: JSON nesting too deep to process"
        ) from None


def _warn_if_outside_root(path: Path, root: Path, *, flag: str) -> None:
    """Spec 003 FR-5.1 (RT2-L3): a write target resolving outside the
    project root is permitted but never silent — scripted runs (the
    extension runner, CI) must be able to see the escape in the log."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        print(
            f"warning: {flag} {path.as_posix()} resolves outside the project "
            f"root ({resolved.as_posix()} is not under {root.resolve().as_posix()})",
            file=sys.stderr,
        )


def _guard_output_path(
    output: Path,
    protected: Iterable[tuple[Path, str]],
    *,
    flag: str = "--output",
) -> None:
    """Spec 003 FR-5.1 (RT2-H4): refuse, before anything is written,
    when an output path resolves onto a path the run reads.

    Resolution is symlink-aware (``Path.resolve``), so an output aimed
    through a symlink at the input bundle, the ledger, or its anchor
    sidecar is refused under its real target's name. When the output
    path itself passes through a symlink to somewhere unprotected, the
    resolved target is reported on stderr before writing — a scripted
    run never silently writes somewhere other than the path it named.
    Raises ValueError (main reports it as a clean exit-2 error).
    """
    resolved_output = output.resolve()
    for path, description in protected:
        if resolved_output == path.resolve():
            raise ValueError(
                f"{flag} {output.as_posix()} resolves to {resolved_output.as_posix()}, "
                f"which is {description}; refusing to overwrite it (Spec 003 FR-5.1)"
            )
    if Path(os.path.abspath(output)) != resolved_output:
        print(
            f"note: {flag} {output.as_posix()} resolves through a symlink "
            f"to {resolved_output.as_posix()}",
            file=sys.stderr,
        )


def _atomic_write_text(path: Path, text: str) -> None:
    """Spec 003 FR-5.2 (RT2-M3): write via a temp file in the same
    directory + rename, so a failed or interrupted write never leaves
    a truncated artifact behind. The rename does not follow a symlink
    at the final path component: it replaces the link itself, so a
    symlinked output can never truncate its target (RT2-H4)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_or_print(value: dict[str, object], output: Path | None) -> None:
    if output:
        _write_json(value, output)
    else:
        print(_dumps(value, indent=2))


def _write_json(value: dict[str, object], output: Path) -> None:
    _atomic_write_text(output, _dumps(value, indent=2) + "\n")


def _exit_code(outcome: str) -> int:
    if outcome in {"pass", "warn"}:
        return 0
    if outcome in {"iterate", "clarify", "gather_evidence", "abstain"}:
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
