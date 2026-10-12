"""End-to-end AEE assessment orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aee._version import __version__ as _ENGINE_VERSION
from aee.challenge import StressTester
from aee.model import Claim, ClaimStatus, EvidenceDirection, FailureMode, Severity
from aee.policy import AssessmentPolicy, ClaimVerdict, Verdict, evaluate_policy
from aee.recovery import RecoveryOperator, RecoveryProposal
from aee.reliability import ReliabilityTable
from aee.scoring import ClaimScore, ScoringEngine, canonical_evidence_identity
from aee.sources import source_identity

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
        # FR-2.3: the draft outcome cap is visible per claim as a
        # failure record, not only as the aggregate outcome — see
        # _outcome for the cap rule itself.
        extra_failures.extend(_draft_cap_failures(items))
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
        if not items:
            # Spec 003 FR-1.1 (OD-2, belt-and-braces half): an empty
            # bundle is never a pass. _outcome already returns block
            # for zero claims; the summary says so explicitly so the
            # record cannot be mistaken for a healthy empty result.
            summary += (
                " Empty bundle: zero claims were assessed; an empty "
                "bundle never passes (Spec 003 FR-1.1)."
            )
        # FR-2.8 (RT1-21): bundle-level shared-evidence picture. The
        # per-claim FR-6.2 warnings say WHICH claims share; this says
        # how much of the bundle's support is one shared set. Reporting
        # only — no outcome effect in this phase; whether sharing also
        # caps the outcome is FR-8's decision (OD-1), deliberately not
        # taken here.
        report = _shared_evidence_report(items)
        if report is not None:
            shared_sources, involved, total = report
            summary += (
                f" Shared evidence: {shared_sources} supporting source(s) "
                f"shared across {involved} of {total} claim(s); the same "
                "evidence set supports multiple claims (FR-2.8, reporting "
                "only, no outcome effect in this phase)."
            )
        draft_capped = sum(1 for claim in items if claim.status == ClaimStatus.DRAFT)
        if draft_capped:
            summary += (
                f" Draft cap: {draft_capped} draft claim(s) capped at "
                "gather_evidence/iterate (FR-2.3)."
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
            # Coverage counts CHALLENGES: the FR-2.3 draft-cap records
            # are outcome-cap explanations, not challenges, and are not
            # dispositionable — counting them here would misreport the
            # challenge coverage this sentence exists to state.
            raised = sum(
                1
                for claim in items
                for failure in claim.failures
                if failure.category != "draft_cap"
            )
            open_count = sum(
                1
                for claim in items
                for failure in claim.unresolved_failures
                if failure.category != "draft_cap"
            )
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
        if not claims:
            # Spec 003 FR-1.1 (RT1-01): vacuity is not success. Over
            # empty collections every check below is trivially true,
            # which used to yield "pass", healthy, exit 0 for a bundle
            # that had lost all its claims. The engine returns block
            # so API consumers are protected even where a caller
            # bypasses the CLI, which additionally refuses an empty
            # bundle as an input error (exit 2) — OD-2 implemented as
            # belt-and-braces; the owner may reverse the CLI half.
            return "block"
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
        if any(claim.status == ClaimStatus.DRAFT for claim in claims):
            # FR-2.3 draft cap (RT1-04): a bundle containing drafts
            # cannot pass, whatever the scores say — a draft is by
            # definition unratified, and Spec 002 FR-2's drafting relies
            # on this guarantee. The cap lives here, in the outcome
            # layer, NOT in scoring: the draft's score stays what the
            # evidence earns, so the record shows both what the claim
            # scored and why the outcome stopped at iterate. Reached
            # only when nothing worse routed the outcome above, so the
            # cap never MASKS a gather_evidence/clarify/block verdict.
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


def _draft_cap_failures(items: list[Claim]) -> list[FailureMode]:
    """FR-2.3 visibility record for the draft outcome cap.

    One LOW failure per draft claim: LOW by design — the capped outcome
    (iterate) has exactly the consequences a LOW failure would produce,
    and the record must never escalate a draft bundle's outcome beyond
    the cap the claim exists to explain (a draft with otherwise-clean
    evidence belongs at iterate, not gather_evidence).
    """
    return [
        FailureMode(
            id=f"AEE-{claim.id}-DRAFT-CAP",
            claim_id=claim.id,
            challenge="Draft outcome cap",
            breakpoint=(
                "Claim status is draft: the assessment outcome is capped at "
                "gather_evidence/iterate and policy verdicts below accept "
                "regardless of score (Spec 003 FR-2.3); a human ratification "
                "(status change) lifts the cap"
            ),
            severity=Severity.LOW,
            category="draft_cap",
            recovery_hint="Ratify the claim (change its status from draft) to lift the cap.",
        )
        for claim in items
        if claim.status == ClaimStatus.DRAFT
    ]


def _support_set(claim: Claim) -> frozenset[tuple[str, str, str, str, str]]:
    return frozenset(
        canonical_evidence_identity(item)
        for item in claim.evidence
        if item.direction == EvidenceDirection.SUPPORTS and item.ref.strip()
    )


def _shared_evidence_report(items: list[Claim]) -> tuple[int, int, int] | None:
    """Bundle-level shared-evidence picture (FR-2.8), or None.

    Two lenses, either sufficient to report: a source identity counted
    by more than one claim (the FR-6.2 lens, on NORMALISED identity so
    string variants cannot hide sharing), or two claims whose
    canonical supporting SETS are identical (the split-claim lens of
    RT1-21 — the lens that still fires when a split bundle declares
    independence for its shared items). Returns (shared sources,
    involved claims, total claims).
    """
    if len(items) < 2:
        return None
    by_source: dict[str, set[str]] = {}
    for claim in items:
        for item in claim.evidence:
            if item.direction != EvidenceDirection.SUPPORTS or not item.ref.strip():
                continue
            key = source_identity(item)
            if key:
                by_source.setdefault(key, set()).add(claim.id)
    shared_sources = {key for key, ids in by_source.items() if len(ids) > 1}
    involved: set[str] = set()
    for key in shared_sources:
        involved.update(by_source[key])
    seen_sets: dict[frozenset[tuple[str, str, str, str, str]], str] = {}
    for claim in items:
        support = _support_set(claim)
        if not support:
            continue
        other = seen_sets.setdefault(support, claim.id)
        if other != claim.id:
            involved.update({other, claim.id})
    if not involved:
        return None
    return len(shared_sources), len(involved), len(items)


def highest_severity(claims: Iterable[Claim]) -> Severity:
    failures = [failure for claim in claims for failure in claim.unresolved_failures]
    if not failures:
        return Severity.INFO
    return max((failure.severity for failure in failures), key=_SEVERITY_ORDER.__getitem__)
