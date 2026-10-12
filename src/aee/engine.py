"""End-to-end AEE assessment orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from aee._version import __version__ as _ENGINE_VERSION
from aee.challenge import StressTester
from aee.decomposition import (
    attribution_contests,
    decomposition_failures,
    effective_stage_overrides,
    override_reasons,
)
from aee.lanes import build_lanes, lane_summary_lines
from aee.model import (
    STAGE_ORDER,
    Claim,
    ClaimStage,
    ClaimStatus,
    EvidenceDirection,
    EvidenceKind,
    FailureMode,
    Severity,
)
from aee.policy import (
    AssessmentPolicy,
    ClaimVerdict,
    Verdict,
    evaluate_policy,
    machine_only_overrides,
    machine_only_reason,
)
from aee.recovery import RecoveryOperator, RecoveryProposal
from aee.reliability import ReliabilityTable
from aee.scoring import ClaimScore, ScoringEngine, canonical_evidence_identity
from aee.sources import source_identity
from aee.stage import StageCap, below_explained, reported_statuses, stage_cap_for, stage_caps

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
    # Methodology version (Spec 002 FR-4 mechanism; Spec 003 FR-8.2
    # discipline: score-altering changes bump this, never ride
    # under an unchanged value). "2.0" is the ONE joint bump for
    # Spec 003 FR-8 (scoring/challenge/review semantics) implemented
    # together with Spec 004's model phases P0-P4, recorded in
    # specs/003-aee-red-team-remediation/implementation-fr8.md and
    # specs/004-tao-realignment/implementation-p4.md.
    methodology_version: str = "2.0"
    metadata: dict[str, Any] = field(default_factory=dict)
    # Spec 004 R1.3: the per-claim status as REPORTED (capped by
    # stage) and the cap records that lowered it. The claims' own
    # `status` fields keep the author-declared posture; the reported
    # vocabulary lives here so the cap is inspectable (R8.1/R8.2),
    # never a silent rewrite of the claim record.
    reported_statuses: dict[str, str] = field(default_factory=dict)
    stage_caps: list[StageCap] = field(default_factory=list)
    # Spec 004 R5.2: what this assessment does NOT establish, stated
    # from its own inspectable state. Always serialised (possibly
    # empty when nothing is open); an assessment without the field
    # is itself a finding at the gate (R5.3).
    not_understood: list[str] = field(default_factory=list)
    # Spec 004 R6/R8: the two lanes as a reported pair (lane 1
    # machine verification, lane 2 human acceptance), per claim and
    # per bundle. Serialised inside the assessment, so the record
    # is covered by the ledger's assessment hash like every other
    # realignment record.
    lanes: dict[str, Any] = field(default_factory=dict)
    # Spec 004 R3.3: per-claim digestion tracking — for every claim
    # its (effective) stage, whether RESOLVED exposition evidence is
    # present, and who the explainers are. Ported from the orphaned
    # P0-completion branch @ 5fa2fdf during the Spec 004 integration:
    # P2/P3 carried the flag and the lane pair, but the per-claim
    # explainer record the R3.3 text requires ("who the explainers
    # are") existed only on the orphan. Serialised like `lanes`, so
    # it is covered by the ledger's assessment hash (R8.1).
    digestion: dict[str, Any] = field(default_factory=dict)

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
            "reported_statuses": dict(self.reported_statuses),
            "stage_caps": [cap.to_dict() for cap in self.stage_caps],
            "not_understood": list(self.not_understood),
            "lanes": self.lanes,
            "digestion": dict(self.digestion),
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
        # Spec 004 P1 (R2.3/R4.3): decomposition and attribution rules
        # cap EFFECTIVE stages - an incomplete headline is treated as
        # `created`, a contested attribution caps its parent at
        # `checked`. Computed once, here, from the stress tester's
        # failures, and read by every surface below (caps, verdicts,
        # outcome, summary) so they can never disagree about a stage.
        overrides = effective_stage_overrides(items)
        override_notes = override_reasons(items, overrides)
        # Spec 004 R5.1: the machine-only gate caps the effective
        # stage at `checked` for claims carried exclusively by
        # machine-checkable evidence. Merged with the P1 overrides -
        # the lowest cap wins; the gate's reason is recorded wherever
        # it binds (alone or tied).
        machine = machine_only_overrides(items)
        for claim_id, stage in machine.items():
            current = overrides.get(claim_id)
            if current is None or STAGE_ORDER[stage] < STAGE_ORDER[current]:
                overrides[claim_id] = stage
            if overrides.get(claim_id) == stage:
                claim = next(item for item in items if item.id == claim_id)
                reason = machine_only_reason(claim)
                if reason:
                    override_notes[claim_id] = (
                        f"{override_notes[claim_id]}; {reason}"
                        if claim_id in override_notes
                        else reason
                    )
        # FR-6.2: the shared-evidence warning is an engine-level check
        # (it needs the whole bundle, like the stress tester's graph
        # checks) and folds in with caller-supplied failures below.
        extra_failures: list[FailureMode] = [*_shared_evidence_failures(items)]
        # FR-2.3: the draft outcome cap is visible per claim as a
        # failure record, not only as the aggregate outcome — see
        # _outcome for the cap rule itself.
        extra_failures.extend(_draft_cap_failures(items))
        # Spec 004 R1.3: a stage-capped claim carries a failure-mode
        # record (category `stage_cap`) naming the cap and the event
        # that would lift it - visible wherever failure modes are
        # reported, in the draft-cap precedent's shape (LOW: the cap
        # explains a lowered report; it must never escalate an
        # outcome beyond what the cap itself implies).
        extra_failures.extend(decomposition_failures(items))
        extra_failures.extend(_stage_cap_failures(items, overrides, override_notes))
        # Spec 004 R3.3: verified-but-unexplained is a named risk
        # state for claims at stage `checked`+ with no exposition
        # evidence. A risk record, not a correctness failure: it
        # never lowers a score and never routes the outcome (see
        # _NON_OUTCOME_CATEGORIES).
        # Spec 004 R3.2 (lenient half; ported from the orphaned
        # P0-completion branch @ 5fa2fdf): exposition items that
        # failed identity resolution at lenient load are re-emitted
        # here as claim-attributed failure modes — the load-time
        # record alone would be wiped by the stress tester's
        # wholesale replacement of claim.failures above.
        extra_failures.extend(_identity_resolution_failures(items))
        extra_failures.extend(_verified_unexplained_failures(items))
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
        # R1.3: the cap also lands on the score record as a note -
        # the score itself is NOT changed (the cap lowers reported
        # vocabulary only, never the lane-1 number).
        caps = stage_caps(items, overrides, override_notes)
        for cap in caps:
            scores[cap.claim_id].notes.append(cap.note)
        recoveries = self.recovery_operator.propose(failures)
        outcome = self._outcome(items, scores, overrides)
        verdicts: dict[str, ClaimVerdict] = {}
        if self.policy is not None:
            # Policy reads the EFFECTIVE stage: a claim capped by the
            # decomposition/attribution rules is judged at its capped
            # stage, not its stored one (R2.3/R4.3).
            verdicts = {
                claim.id: evaluate_policy(
                    (
                        replace(claim, stage=overrides[claim.id])
                        if claim.id in overrides
                        else claim
                    ),
                    scores[claim.id],
                    self.policy,
                    threshold=self.threshold,
                    # FR-8.4: verdicts are failure-aware - the
                    # claim's unresolved failure modes ride along so
                    # a HIGH/CRITICAL failure caps the verdict.
                    failures=claim.unresolved_failures,
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
                verdict.verdict in {Verdict.CHALLENGE, Verdict.UNJUDGED}
                for verdict in verdicts.values()
            ):
                outcome = "iterate"
        not_understood = _not_understood(
            items, caps, failures, scores, self.threshold, metadata
        )
        lanes = build_lanes(
            items,
            scores=scores,
            caps=caps,
            verified_unexplained_claim_ids={
                failure.claim_id
                for failure in failures
                if failure.category == "verified_unexplained"
            },
            contested_attribution_ids=set(attribution_contests(items)),
            overrides=overrides,
            outcome=outcome,
            threshold=self.threshold,
        )
        digestion = _digestion_tracking(items, overrides)
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
        # Spec 004 R1.3/R1.4: stage state is stated wherever the
        # outcome is — how many claims sit below `explained` (and so
        # block a settlement-worded pass), and how many reports were
        # lowered by a stage cap.
        # Renamed from `below` (the orphaned P0-completion branch's
        # mypy fix @ 3f4349b, ported in adapted form): `below` above
        # is the sub-threshold score count (an int); this is the
        # below-explained claim list.
        below_stage = below_explained(items, overrides)
        if below_stage:
            summary += (
                f" Stage cap: {len(below_stage)} claim(s) below stage 'explained'; "
                "the outcome cannot be 'pass' (Spec 004 R1.4)."
            )
        incomplete = [
            failure for failure in failures if failure.category == "decomposition_incomplete"
        ]
        if incomplete:
            summary += (
                f" Decomposition: {len(incomplete)} headline claim(s) incomplete "
                "(missing required sub-claim roles, Spec 004 R2); their stages "
                "are capped at 'created'."
            )
        contested_parents = {
            claim_id
            for claim_id, reason in override_notes.items()
            if "contested" in reason
        }
        if contested_parents:
            summary += (
                f" Attribution: {len(contested_parents)} claim(s) stage-capped "
                "by a contested attribution claim (Spec 004 R4.3)."
            )
        if caps:
            summary += (
                f" Stage caps applied: {len(caps)} claim(s) reported below "
                "their author-declared status or in qualified form (Spec 004 R1.3)."
            )
        stage_defaulted = [claim.id for claim in items if claim.stage_defaulted]
        if stage_defaulted:
            summary += (
                f" Stage default: {len(stage_defaulted)} claim(s) loaded without "
                "a stage defaulted to 'created' (lenient path, Spec 004 R1.1; "
                "recorded in metadata.stage_defaulted_claims)."
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
                if failure.category not in {"draft_cap", "stage_cap", "verified_unexplained"}
            )
            open_count = sum(
                1
                for claim in items
                for failure in claim.unresolved_failures
                if failure.category not in {"draft_cap", "stage_cap", "verified_unexplained"}
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
            if counts[Verdict.UNJUDGED]:
                summary += f" Unjudged (stage 'created'): {counts[Verdict.UNJUDGED]}."
        if not_understood:
            # R5.3/R6.3: the residual-unknowns statement travels with
            # the verdict wherever the verdict is rendered, starting
            # with the summary line itself.
            summary += (
                f" Not understood: {len(not_understood)} residual unknown(s) "
                "are recorded on this assessment (Spec 004 R5.2)."
            )
        # R6.3: the lanes travel together - wherever the lane-1
        # outcome is stated, the lane-2 state is stated with it.
        lane_1_line, lane_2_line = lane_summary_lines(lanes)
        summary += f" {lane_1_line} {lane_2_line}"
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
            reported_statuses=reported_statuses(items, overrides),
            stage_caps=caps,
            not_understood=not_understood,
            lanes=lanes,
            digestion=digestion,
            metadata={
                "threshold": self.threshold,
                **(metadata or {}),
                # R1.1: lenient stage defaults are on the record —
                # every claim whose stage was defaulted is named.
                **(
                    {"stage_defaulted_claims": [c.id for c in items if c.stage_defaulted]}
                    if any(c.stage_defaulted for c in items)
                    else {}
                ),
                "engine_version": _ENGINE_VERSION,
            },
        )

    def _outcome(
        self,
        claims: list[Claim],
        scores: dict[str, ClaimScore],
        overrides: dict[str, ClaimStage] | None = None,
    ) -> str:
        # Threshold rule (Spec 003 FR-8.13(b)): the threshold is
        # INCLUSIVE - a propagated score of exactly the threshold
        # passes - and the comparison is performed on the UNROUNDED
        # score. Scores are stored unrounded (see ClaimScore);
        # rounding is a display/serialisation concern only and can
        # never move a claim across the threshold (RT1-24: 0.6999996
        # used to round up to 0.70 and pass; it no longer does).
        # stage_cap records are EXPLANATORY (R1.3): they name why a
        # report was lowered. They never route the outcome - the
        # R1.4 stage rule below does that work - so an explained
        # claim whose only record is its qualified-supported cap can
        # still pass, exactly as R1.4 allows. (The draft_cap record
        # is different by design: FR-2.3's cap IS outcome-bearing.)
        outcome_failures = [
            failure
            for claim in claims
            for failure in claim.unresolved_failures
            if failure.category not in _NON_OUTCOME_CATEGORIES
        ]
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
        failures = outcome_failures
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
        if below_explained(claims, overrides):
            # Spec 004 R1.4: the bundle outcome inherits the stage
            # caps — `pass` is a settlement word, reported only when
            # every covered claim is at stage `explained` or beyond.
            # P0 implements the conservative rule (the lane-qualified
            # outcome form is P3/R6). Like the draft cap, this lives
            # in the outcome layer and is reached only when nothing
            # worse routed the outcome above.
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


def _stage_cap_failures(
    items: list[Claim],
    overrides: dict[str, ClaimStage] | None = None,
    reasons: dict[str, str] | None = None,
) -> list[FailureMode]:
    """Spec 004 R1.3 visibility record for stage caps.

    One LOW failure per capped claim, in the draft-cap precedent's
    shape: LOW so the record explains the lowered report without
    escalating the outcome beyond what the stage rules themselves
    imply (the R1.4 outcome cap in _outcome does that work). P1:
    caps are computed at EFFECTIVE stages (decomposition/attribution
    overrides), with the imposing rule named in the record.
    """
    failures: list[FailureMode] = []
    for claim in items:
        effective = (overrides or {}).get(claim.id)
        cap = stage_cap_for(
            claim,
            effective_stage=effective,
            reason=(reasons or {}).get(claim.id, ""),
        )
        if cap is None:
            continue
        failures.append(
            FailureMode(
                id=f"AEE-{claim.id}-STAGE-CAP",
                claim_id=claim.id,
                challenge="Stage cap",
                breakpoint=(f"{cap.note}; the cap lifts with {cap.lifting_event} (Spec 004 R1.3)"),
                severity=Severity.LOW,
                category="stage_cap",
                recovery_hint=(f"Record the stage event that lifts the cap: {cap.lifting_event}."),
            )
        )
    return failures


# Failure categories that EXPLAIN or FLAG a report rather than
# contest its correctness: the stage-cap record (R1.3), the
# verified-unexplained risk flag (R3.3). They are reported wherever
# failure modes are reported, but they never route the outcome and
# never lower a score - the rules that own them do their own work
# (stage caps in _outcome's R1.4 rule; the risk flag is a state, not
# a verdict).
_NON_OUTCOME_CATEGORIES = frozenset({"stage_cap", "verified_unexplained"})


def _resolved_explainers(claim: Claim) -> list[str]:
    """The claim's explainers: source_ids of exposition items that
    resolved to a named human. An exposition item whose source_id
    failed identity resolution on the lenient path (recorded in
    `unresolved_exposition`) confers NO explanation credit — it is
    not an explanation by a resolved named human (R3.2/R3.3)."""
    return sorted(
        {
            item.source_id
            for item in claim.evidence
            if item.kind == EvidenceKind.EXPOSITION
            and item.source_id
            and item.source_id not in claim.unresolved_exposition
        }
    )


def _digestion_tracking(
    items: list[Claim], overrides: dict[str, ClaimStage]
) -> dict[str, Any]:
    """Per-claim digestion tracking (Spec 004 R3.3): for every claim
    its effective stage, whether resolved exposition evidence is
    present, and who the explainers are."""
    return {
        claim.id: {
            "stage": overrides.get(claim.id, claim.stage).value,
            "exposition_present": bool(_resolved_explainers(claim)),
            "explainers": _resolved_explainers(claim),
        }
        for claim in items
    }


def _identity_resolution_failures(items: list[Claim]) -> list[FailureMode]:
    """Spec 004 R3.2 (lenient half), re-emitted at assessment time.

    One failure per (claim, unresolved exposition source_id),
    mirroring the load-time record in `Claim.from_dict` — re-emitted
    because the stress tester replaces claim.failures wholesale.
    Ported from the orphaned P0-completion branch @ 5fa2fdf.
    """
    failures: list[FailureMode] = []
    for claim in items:
        for index, source_id in enumerate(dict.fromkeys(claim.unresolved_exposition)):
            failures.append(
                FailureMode(
                    id=f"AEE-{claim.id}-IDENTITY-RESOLUTION-{index}",
                    claim_id=claim.id,
                    challenge="Exposition identity resolution (lenient load)",
                    breakpoint=(
                        f"Exposition evidence source_id {source_id!r} did not "
                        "resolve to a 'person' entry in the project identity "
                        "registry at load time (Spec 004 R3.2); the item "
                        "confers no explanation credit"
                    ),
                    severity=Severity.MEDIUM,
                    category="identity_resolution",
                    recovery_hint=(
                        "Name a 'person' entry of the project identity "
                        "registry as the exposition item's source_id, or "
                        "load strictly to see the FR-1 error shape."
                    ),
                )
            )
    return failures


def _verified_unexplained_failures(items: list[Claim]) -> list[FailureMode]:
    """Spec 004 R3.3: one MEDIUM risk record per claim at stage
    `checked` or beyond that carries no RESOLVED exposition
    evidence (unresolved exposition confers no credit, R3.2)."""
    failures: list[FailureMode] = []
    for claim in items:
        if STAGE_ORDER[claim.stage] < STAGE_ORDER[ClaimStage.CHECKED]:
            continue
        if _resolved_explainers(claim):
            continue
        failures.append(
            FailureMode(
                id=f"AEE-{claim.id}-VERIFIED-UNEXPLAINED",
                claim_id=claim.id,
                challenge="Verified but unexplained",
                breakpoint=(
                    "Claim is at stage 'checked' or beyond with no exposition "
                    "evidence: machines have checked it, no named human has "
                    "explained it (Spec 004 R3.3)"
                ),
                severity=Severity.MEDIUM,
                category="verified_unexplained",
                recovery_hint=(
                    "Record exposition evidence by a named human (an identity-"
                    "registry id) explaining the claim, why the evidence "
                    "supports it, and where its boundary lies."
                ),
            )
        )
    return failures


def _not_understood(
    items: list[Claim],
    caps: list[StageCap],
    failures: list[FailureMode],
    scores: dict[str, ClaimScore],
    threshold: float,
    metadata: dict[str, Any] | None,
) -> list[str]:
    """Spec 004 R5.2: the residual-unknowns statement, generated from
    inspectable assessment state - never a free-floating disclaimer.

    Sources: stage caps, verified-unexplained flags, incomplete
    decompositions, lenient stage defaults, open challenge categories,
    sub-threshold scores, and declared-but-unverified content hashes,
    plus any author-supplied entries carried in the assessment
    metadata under `not_understood`.
    """
    entries: list[str] = []
    for cap in caps:
        entries.append(f"{cap.claim_id}: {cap.note}")
    for failure in failures:
        if failure.category == "verified_unexplained":
            entries.append(
                f"{failure.claim_id}: verified but unexplained - no named human "
                "has explained this claim, so what the check establishes is "
                "narrower than the claim's wording suggests."
            )
        elif failure.category == "decomposition_incomplete":
            entries.append(f"{failure.claim_id}: {failure.challenge}")
    explained_categories = _NON_OUTCOME_CATEGORIES | {
        "draft_cap",
        "decomposition_incomplete",
    }
    for claim in items:
        if claim.stage_defaulted:
            entries.append(
                f"{claim.id}: its lifecycle stage was not recorded and "
                "defaulted to 'created' on load - its position in the "
                "lifecycle is unrecorded, not established."
            )
        elif claim.stage_derived:
            entries.append(
                f"{claim.id}: its lifecycle stage '{claim.stage.value}' was "
                "derived from its latest recorded stage event; the bundle "
                "recorded no stored stage (Spec 004 R1.2)."
            )
        open_categories = sorted(
            {
                failure.category
                for failure in claim.unresolved_failures
                if failure.category not in explained_categories
            }
        )
        if open_categories:
            entries.append(
                f"{claim.id}: open challenges this assessment does not "
                f"resolve: {', '.join(open_categories)}."
            )
        score = scores.get(claim.id)
        if score is not None and score.propagated_score < threshold:
            entries.append(
                f"{claim.id}: propagated score {score.propagated_score:.3f} is "
                f"below the {threshold:.2f} threshold - the claim is not "
                "established by its evidence as recorded."
            )
        unverified = sum(
            1
            for item in claim.evidence
            if item.content_hash is not None and item.content_hash_status is None
        )
        if unverified:
            entries.append(
                f"{claim.id}: {unverified} evidence item(s) declare a content "
                "hash that was not recomputed in this run - their contents "
                "are asserted, not inspected."
            )
    author = (metadata or {}).get("not_understood")
    if isinstance(author, list):
        entries.extend(str(entry) for entry in author)
    elif isinstance(author, str) and author.strip():
        entries.append(author)
    return entries


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
