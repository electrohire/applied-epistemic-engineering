"""Assessment policy gates, ported from the epistemic-ledger program.

The living epistemic ledger (AXIOVEX/epistemic-ledger) spent a
measurement program (REALWIRE-01, STANCE-01, STANCE-02) learning how
claim assessments fail on real-world material. Three of its rules
are stated as policy here, because each was measured, not intuited:

1. **Corroboration gate.** A claim carried by fewer than
   ``min_independent_sources`` independent supporting sources is
   CHALLENGEd, however strong its score looks. In the ledger's
   newsroom measurements, single-source claims were the dominant
   channel by which extraction noise hardened into asserted
   knowledge; the ledger's own scoring already rewards independence
   softly (ScoringEngine.independence_score) — this gate makes the
   requirement explicit instead of a weighted nudge.
2. **Forced abstention.** Where the support is absent, or consists
   solely of model self-attestation (``Evidence.is_model_self_
   attestation``), the honest verdict is ABSTAIN — the ledger's
   "unknown means ABSTAIN" rule. A low numeric score invites
   downstream tooling to treat the claim as measured-and-weak; an
   abstention says it was never measured at all.
3. **Contested gate.** A claim carrying counterevidence is
   CHALLENGEd at best: live contradiction must be resolved, not
   averaged away. Since Spec 003 FR-8.5 the gate reads the shared
   contested basis (``counterevidence_present``: any item directed
   against the claim, or a contradicted-kind item routed
   otherwise), with the ``contested_penalty_threshold`` magnitude
   route retained alongside it — the kind-weighted penalty alone
   used to let weak-kind contradictions ACCEPT standalone while
   the engine clarified.

Policies are opt-in. ``AEEEngine()`` without a policy preserves the
historical behavior exactly; supplying one adds a per-claim verdict
(ACCEPT / CHALLENGE / ABSTAIN, each with reasons) to the assessment
and lets the gates bound the outcome: an assessment containing an
ABSTAIN verdict cannot report ``pass``, and one containing a
CHALLENGE verdict cannot report ``pass`` either.

Verdicts layer above scores and never mutate them, so scoring
stays replayable: the same claims under the same policy always
produce the same verdicts.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

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
from aee.sources import source_identity
from aee.stage import LIFTING_EVENT, VERDICT_CEILING


def verdict_ceiling(stage: ClaimStage) -> str:
    """The policy verdict ceiling for a lifecycle stage (Spec 004 R1.3).

    The public, programmatic form of the stage -> verdict-ceiling
    table: ``created`` -> ``"unjudged"`` (no verdict is issued),
    ``checked``/``explained`` -> ``"challenge"``, ``accepted``/
    ``digested`` -> ``"accept"``. The table itself lives in
    ``aee.stage`` (the R1.3 table as data); this function is the
    policy layer's exposed accessor so downstream consumers read the
    ceiling from the policy module instead of duplicating the table.
    ``evaluate_policy`` enforces exactly what this function reports.

    Ported from the orphaned P0-completion branch
    impl/004-p0-vocabulary @ 5fa2fdf during the Spec 004 integration:
    the stack carried the table and the enforcement, but not this
    accessor or its ``aee`` export.
    """
    return VERDICT_CEILING[stage]

# Kind weights mirror aee.scoring._KIND_WEIGHTS for the sign test in
# corroboration_sources (positive contribution vs zero/negative). The
# scoring module owns the magnitudes; only the sign matters here, and
# importing scoring from policy would be circular (engine imports both,
# scoring imports neither).
_POSITIVE_KINDS = frozenset(
    {
        EvidenceKind.OBSERVED,
        EvidenceKind.INFERRED,
        EvidenceKind.ASSERTED,
        EvidenceKind.EXPOSITION,
    }
)

if TYPE_CHECKING:
    from aee.scoring import ClaimScore


class Verdict(StrEnum):
    ACCEPT = "accept"
    CHALLENGE = "challenge"
    ABSTAIN = "abstain"
    # Spec 004 R1.3: at stage `created` no verdict is issued - the
    # claim is reported as unjudged, a distinct statement from
    # abstention (abstention says judged-and-unmeasurable; unjudged
    # says not yet through the checking stage at all).
    UNJUDGED = "unjudged"


@dataclass(frozen=True, slots=True)
class AssessmentPolicy:
    """Gate thresholds for policy-checked assessments.

    Defaults are the ledger program's measured operating points,
    stated here so a deployment can tighten or relax them as data:
    corroboration at two independent sources mirrors the ledger's
    independence full-credit point, and the contested threshold
    sits at one strong observed contradiction (an OBSERVED item
    from a PRIMARY source contributes 0.71 of penalty, a SECONDARY
    one 0.49, an asserted MODEL contradiction 0.15 — so 0.25 trips
    on any observed contradiction and on paired weak ones).
    """

    min_independent_sources: int = 2
    contested_penalty_threshold: float = 0.25
    abstain_on_model_only: bool = True

    def __post_init__(self) -> None:
        if self.min_independent_sources < 1:
            raise ValueError("min_independent_sources must be >= 1")
        if not 0.0 <= self.contested_penalty_threshold <= 0.75:
            raise ValueError("contested_penalty_threshold must be between 0 and 0.75")


@dataclass(slots=True)
class ClaimVerdict:
    """One claim's policy verdict, with the reasons that produced it."""

    claim_id: str
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
        }


def corroboration_sources(claim: Claim) -> set[str]:
    """The normalised sources that count toward corroboration (FR-2.4/2.5).

    Only direction-``supports`` items with POSITIVE evidence weight
    count: zero-weight kinds (``unsupported``, ``contradicted``)
    minted corroboration for free at red-team time (RT1-06), and
    ``context`` items are excluded by the direction filter by
    construction (FR-2.2). Identities are normalised through
    ``aee.sources`` — the same helper scoring's independence uses —
    so string variants of one origin count once in both gates
    (RT1-14). Empty identities (no ref, no source_id) never count.
    """
    return {
        source_identity(item)
        for item in claim.evidence
        if item.direction == EvidenceDirection.SUPPORTS and item.kind in _POSITIVE_KINDS
    } - {""}


def counterevidence_present(claim: Claim) -> int:
    """The shared contested basis (Spec 003 FR-8.5, RT1-25).

    Scoring and policy used to disagree about what "contested"
    means: the challenge layer routes a claim to `clarify` on ANY
    recorded counterevidence, while the policy gate read only the
    kind-weighted contradiction penalty, so a weak-kind
    contradiction (penalty 0.05) ACCEPTed standalone while the
    engine clarified. The shared basis, documented here and used
    by the gate below: a claim is contested when its record carries
    counterevidence — any evidence item directed `contradicts`
    (whatever its kind or source weight), or a contradicted-kind
    item routed in any other direction (the FR-2.2 polarity
    incoherence, which the challenge layer also fires on). Returns
    the number of counterevidence items.
    """
    count = 0
    for item in claim.evidence:
        if item.direction == EvidenceDirection.CONTRADICTS:
            count += 1
        elif item.kind == EvidenceKind.CONTRADICTED:
            count += 1
    return count


def evaluate_policy(
    claim: Claim,
    score: ClaimScore,
    policy: AssessmentPolicy,
    *,
    threshold: float,
    failures: Iterable[FailureMode] | None = None,
) -> ClaimVerdict:
    """Judge one scored claim against the policy gates.

    Rule order is significant: abstention (the claim cannot be
    judged) is decided before challenge (the claim is judged and
    wanting), so a claim with no usable support abstains even if it
    is also contradicted.

    ``failures`` (Spec 003 FR-8.4, RT1-09): the claim's failure
    modes, when the caller has them (the engine always passes
    them). A claim carrying an unresolved HIGH or CRITICAL failure
    cannot receive ACCEPT; the demotion mirrors the engine's
    outcome demotion and the verdict's reasons name the failures
    that demoted it, so a verdict and an outcome for the same claim
    can no longer read ACCEPT alongside `clarify`. Standalone
    callers without failure records get the evidence-based gates
    only — the contested gate below is evidence-based for exactly
    that reason (FR-8.5).
    """
    if claim.stage == ClaimStage.CREATED:
        # R1.3 stage ceiling, first in rule order: a created claim
        # has not been through checking, so no verdict is issued -
        # reported unjudged, whatever the evidence looks like.
        return ClaimVerdict(
            claim.id,
            Verdict.UNJUDGED,
            [
                "stage cap (Spec 004 R1.3): claim is at stage 'created'; "
                "no policy verdict is issued (unjudged) until " + LIFTING_EVENT[ClaimStage.CREATED]
            ],
        )
    supporting = [item for item in claim.evidence if item.direction == EvidenceDirection.SUPPORTS]
    if not supporting:
        return ClaimVerdict(claim.id, Verdict.ABSTAIN, ["no supporting evidence"])
    if policy.abstain_on_model_only and all(item.is_model_self_attestation for item in supporting):
        return ClaimVerdict(claim.id, Verdict.ABSTAIN, ["support is model self-attestation only"])
    reasons: list[str] = []
    counterevidence = counterevidence_present(claim)
    if counterevidence:
        # FR-8.5: the contested gate trips on the shared basis -
        # counterevidence present - regardless of the contradicting
        # items' kind weights. The penalty threshold remains as a
        # second, magnitude-based route to the same gate.
        reasons.append(
            f"contested: {counterevidence} counterevidence item(s) on record "
            "(shared contested basis, FR-8.5)"
        )
    if score.contradiction_penalty >= policy.contested_penalty_threshold:
        reasons.append(
            f"contested: contradiction penalty "
            f"{score.contradiction_penalty:.3f} >= "
            f"{policy.contested_penalty_threshold:.3f}"
        )
    demoting = [
        failure
        for failure in (failures or [])
        if not failure.resolved
        and failure.severity in {Severity.HIGH, Severity.CRITICAL}
    ]
    for failure in demoting:
        reasons.append(
            f"failure-aware demotion (FR-8.4): unresolved "
            f"{failure.severity.value} failure {failure.id} "
            f"({failure.category}) caps the verdict below accept"
        )
    sources = corroboration_sources(claim)
    if len(sources) < policy.min_independent_sources:
        reasons.append(
            f"corroboration: {len(sources)} independent supporting "
            f"source(s) < {policy.min_independent_sources} required"
        )
    if score.propagated_score < threshold:
        reasons.append(
            f"propagated score {score.propagated_score:.3f} below "
            f"the {threshold:.2f} confidence threshold"
        )
    if claim.status == ClaimStatus.DRAFT:
        # FR-2.3 (policy half): verdicts are capped with outcomes — a
        # draft is not ACCEPT whatever its score says. The abstain
        # rules above still take precedence: no usable support is a
        # stronger statement than "not yet ratified".
        reasons.append("draft claim: policy verdict capped below accept (FR-2.3 draft cap)")
    if reasons:
        return ClaimVerdict(claim.id, Verdict.CHALLENGE, reasons)
    if claim.stage in {ClaimStage.CHECKED, ClaimStage.EXPLAINED}:
        # R1.3 stage ceiling: `accept` is reserved for claims at
        # stage accepted+ - a checked or explained claim that clears
        # every gate is CHALLENGEd by the stage cap alone (demote
        # only; the cap never touches the score).
        return ClaimVerdict(
            claim.id,
            Verdict.CHALLENGE,
            [
                f"stage cap (Spec 004 R1.3): claim is at stage "
                f"'{claim.stage.value}'; policy verdict ceiling is "
                f"'challenge' until {LIFTING_EVENT[claim.stage]}"
            ],
        )
    return ClaimVerdict(claim.id, Verdict.ACCEPT, [])


# -- Spec 004 R5.1: the machine-only evidence cap -------------------------
#
# A claim whose SUPPORTING evidence is exclusively machine-checkable
# - every supporting item has kind `observed` or `inferred` AND
# source quality `test`, `artifact`, or `model` - is capped at stage
# `checked` regardless of score. The gate is a policy gate in this
# module's sense: it produces a reasoned, inspectable cap record (via
# the engine's stage-cap machinery), it can only demote, and its
# reason names the evidence composition that triggered it. Human-paced
# support lifts the cap: exposition evidence (R3), or any supporting
# item outside the partition (an asserted item, or a human / primary
# / secondary quality source). The partition is part of the
# methodology: changing it is a methodology change (Spec 004 §8).

_MACHINE_KINDS = frozenset({EvidenceKind.OBSERVED, EvidenceKind.INFERRED})
_MACHINE_QUALITIES = frozenset({"test", "artifact", "model"})


def machine_only_reason(claim: Claim) -> str | None:
    """The R5.1 cap reason for this claim, or None when uncapped.

    A claim with no supporting evidence is NOT machine-only: absence
    of support is the abstention rules' territory, not this gate's.
    """
    supporting = [
        item for item in claim.evidence if item.direction == EvidenceDirection.SUPPORTS
    ]
    if not supporting:
        return None
    if all(
        item.kind in _MACHINE_KINDS and item.source_quality.value in _MACHINE_QUALITIES
        for item in supporting
    ):
        composition = ", ".join(
            sorted({f"{item.kind.value}/{item.source_quality.value}" for item in supporting})
        )
        return (
            "machine-only evidence (Spec 004 R5.1): every supporting item is "
            f"machine-checkable ({composition}); the stage is capped at "
            "'checked' until human-paced support (exposition, or a human / "
            "primary / secondary source) is recorded"
        )
    return None


def machine_only_overrides(claims: list[Claim]) -> dict[str, ClaimStage]:
    """Effective-stage caps imposed by the machine-only gate (R5.1)."""
    overrides: dict[str, ClaimStage] = {}
    for claim in claims:
        if machine_only_reason(claim) is not None and STAGE_ORDER[
            claim.stage
        ] > STAGE_ORDER[ClaimStage.CHECKED]:
            overrides[claim.id] = ClaimStage.CHECKED
    return overrides
