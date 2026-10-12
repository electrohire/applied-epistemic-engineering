"""End-to-end AEE assessment orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aee._version import __version__ as _ENGINE_VERSION
from aee.challenge import StressTester
from aee.model import Claim, EvidenceDirection, FailureMode, Severity
from aee.policy import AssessmentPolicy, ClaimVerdict, Verdict, evaluate_policy
from aee.recovery import RecoveryOperator, RecoveryProposal
from aee.reliability import ReliabilityTable
from aee.scoring import ClaimScore, ScoringEngine

_SEVERITY_ORDER = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


@dataclass(slots=True)
class Assessment:
    """Complete, serializable result of one AEE run."""

    project: str
    phase: str
    claims: list[Claim]
    scores: dict[str, ClaimScore]
    recoveries: list[RecoveryProposal]
    outcome: str
    summary: str
    created_at: str
    verdicts: dict[str, ClaimVerdict] = field(default_factory=dict)
    methodology_version: str = "1.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def failures(self) -> list[object]:
        return [failure for claim in self.claims for failure in claim.failures]

    @property
    def healthy(self) -> bool:
        return self.outcome in {"pass", "warn"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "methodology_version": self.methodology_version,
            "project": self.project,
            "phase": self.phase,
            "outcome": self.outcome,
            "summary": self.summary,
            "created_at": self.created_at,
            "claims": [claim.to_dict() for claim in self.claims],
            "scores": {key: score.to_dict() for key, score in self.scores.items()},
            "verdicts": {key: verdict.to_dict() for key, verdict in self.verdicts.items()},
            "recoveries": [item.to_dict() for item in self.recoveries],
            "metadata": dict(self.metadata),
        }


class AEEEngine:
    """Run stress testing, scoring, and recovery in a deterministic order."""

    def __init__(
        self,
        threshold: float = 0.70,
        policy: AssessmentPolicy | None = None,
        reliability: ReliabilityTable | None = None,
        *,
        reliability_alpha: float = 0.5,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        self.threshold = threshold
        self.policy = policy
        self.stress_tester = StressTester()
        self.scoring_engine = ScoringEngine(reliability, reliability_alpha=reliability_alpha)
        self.recovery_operator = RecoveryOperator()

    def assess(
        self,
        claims: Iterable[Claim],
        *,
        project: str = "project",
        phase: str = "after_plan",
        metadata: dict[str, Any] | None = None,
        as_of: datetime | None = None,
        additional_failures: Iterable[FailureMode] | None = None,
    ) -> Assessment:
        items = list(claims)
        failures = self.stress_tester.run(items)
        # FR-6.2: the shared-evidence warning is an engine-level check
        # (it needs the whole bundle, like the stress tester's graph
        # checks) and folds in with caller-supplied failures below.
        extra_failures: list[FailureMode] = [*_shared_evidence_failures(items)]
        if additional_failures:
            extra_failures.extend(additional_failures)
        if extra_failures:
            # Caller-supplied failure modes (e.g. evidence verification,
            # Spec 002 FR-3.5) fold in AFTER the stress tester — which
            # replaces claim.failures wholesale — and BEFORE recovery,
            # outcome, and summary, so they count everywhere the
            # regenerated challenges count. A failure naming a claim
            # outside this assessment is a caller error, not a verdict.
            by_id = {claim.id: claim for claim in items}
            for failure in extra_failures:
                target = by_id.get(failure.claim_id)
                if target is None:
                    raise ValueError(
                        f"additional failure {failure.id!r} names claim "
                        f"{failure.claim_id!r}, which is not in this assessment"
                    )
                target.failures.append(failure)
                failures.append(failure)
        scores = self.scoring_engine.score(items, as_of=as_of)
        recoveries = self.recovery_operator.propose(failures)
        outcome = self._outcome(items, scores)
        verdicts: dict[str, ClaimVerdict] = {}
        if self.policy is not None:
            verdicts = {
                claim.id: evaluate_policy(
                    claim, scores[claim.id], self.policy, threshold=self.threshold
                )
                for claim in items
            }
            # The gates bound the outcome from above only: they can
            # demote a pass, never promote a failure-driven outcome.
            if outcome == "pass" and any(
                verdict.verdict == Verdict.ABSTAIN for verdict in verdicts.values()
            ):
                outcome = "abstain"
            elif outcome == "pass" and any(
                verdict.verdict == Verdict.CHALLENGE for verdict in verdicts.values()
            ):
                outcome = "iterate"
        below = sum(score.propagated_score < self.threshold for score in scores.values())
        summary = (
            f"Assessed {len(items)} claim(s); found {len(failures)} failure mode(s); "
            f"{below} claim(s) below the {self.threshold:.2f} confidence threshold."
        )
        # FR-5.4: disposition coverage — how many of the challenges
        # raised were answered by a stored disposition, and how many
        # remain open. Reported whenever dispositions are in play (a
        # failure resolved by one, or any claim carrying them).
        dispositioned = sum(
            1
            for claim in items
            for failure in claim.failures
            if failure.resolved and failure.disposition is not None
        )
        if dispositioned or any(claim.dispositions for claim in items):
            raised = sum(len(claim.failures) for claim in items)
            open_count = sum(len(claim.unresolved_failures) for claim in items)
            summary += (
                f" Dispositions: {raised} challenge(s) raised, "
                f"{dispositioned} dispositioned, {open_count} open."
            )
        if verdicts:
            counts = {
                verdict: sum(1 for item in verdicts.values() if item.verdict == verdict)
                for verdict in Verdict
            }
            summary += (
                f" Policy verdicts: {counts[Verdict.ACCEPT]} accept, "
                f"{counts[Verdict.CHALLENGE]} challenge, "
                f"{counts[Verdict.ABSTAIN]} abstain."
            )
        return Assessment(
            project=project,
            phase=phase,
            claims=items,
            scores=scores,
            recoveries=recoveries,
            verdicts=verdicts,
            outcome=outcome,
            summary=summary,
            created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            # FR-4.1: the engine version stamp is authoritative — it is
            # applied after caller metadata so it cannot be overridden
            # or fabricated by the caller. methodology_version (on the
            # Assessment itself) is a DISTINCT, separately-versioned
            # field and is never conflated with this stamp.
            metadata={
                "threshold": self.threshold,
                **(metadata or {}),
                "engine_version": _ENGINE_VERSION,
            },
        )

    def _outcome(self, claims: list[Claim], scores: dict[str, ClaimScore]) -> str:
        failures = [failure for claim in claims for failure in claim.unresolved_failures]
        if any(failure.severity == Severity.CRITICAL for failure in failures):
            return "block"
        if any(
            failure.severity == Severity.HIGH and failure.category == "contradiction"
            for failure in failures
        ):
            return "clarify"
        if any(
            failure.severity == Severity.HIGH
            and failure.category
            in {"missing_evidence", "unsupported_claim", "unverified_assertion"}
            for failure in failures
        ):
            return "gather_evidence"
        if failures or any(score.propagated_score < self.threshold for score in scores.values()):
            return "iterate"
        return "pass"


def _shared_evidence_failures(items: list[Claim]) -> list[FailureMode]:
    """FR-6.2 shared-evidence warning (category ``independence_unmodeled``).

    When two claims' SUPPORTING evidence overlaps on the same ref or
    source_id, the same item can be counted as corroboration in both
    claims. If none of the overlapping items (in either claim) carries
    an ``independent_of`` declaration, the independence behind those
    scores is unmodeled and each affected claim is warned. Overlap
    keys are the same keys scoring uses for source identity:
    ``source_id or ref``.
    """
    by_key: dict[str, dict[str, list[tuple[str, bool]]]] = {}
    for claim in items:
        for item in claim.evidence:
            if item.direction != EvidenceDirection.SUPPORTS or not item.ref:
                continue
            key = item.source_id or item.ref
            by_key.setdefault(key, {}).setdefault(claim.id, []).append(
                (item.ref, bool(item.independent_of))
            )
    failures: list[FailureMode] = []
    id_counts: dict[str, int] = {}
    for key, per_claim in sorted(by_key.items()):
        if len(per_claim) < 2:
            continue
        if any(declared for entries in per_claim.values() for _, declared in entries):
            continue  # independence is declared for this shared item
        refs = sorted({ref for entries in per_claim.values() for ref, _ in entries})
        for claim_id in sorted(per_claim):
            others = ", ".join(sorted(c for c in per_claim if c != claim_id))
            id_counts[claim_id] = id_counts.get(claim_id, 0) + 1
            suffix = f"-{id_counts[claim_id]}" if id_counts[claim_id] > 1 else ""
            failures.append(
                FailureMode(
                    id=f"AEE-{claim_id}-INDEPENDENCE-UNMODELED{suffix}",
                    claim_id=claim_id,
                    challenge="Shared-evidence independence challenge",
                    breakpoint=(
                        f"Supporting evidence '{key}' (ref(s): {', '.join(refs)}) "
                        f"is shared with claim(s) {others} and no independence "
                        "is declared for it; the same evidence may be counted "
                        "as independent corroboration in each claim"
                    ),
                    severity=Severity.MEDIUM,
                    category="independence_unmodeled",
                    recovery_hint=(
                        "Declare independent_of between the evidence items, or "
                        "record that the corroboration is shared."
                    ),
                )
            )
    return failures


def highest_severity(claims: Iterable[Claim]) -> Severity:
    failures = [failure for claim in claims for failure in claim.unresolved_failures]
    if not failures:
        return Severity.INFO
    return max((failure.severity for failure in failures), key=_SEVERITY_ORDER.__getitem__)
