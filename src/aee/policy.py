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
3. **Contested gate.** A claim whose contradiction penalty meets
   ``contested_penalty_threshold`` is CHALLENGEd at best: live
   contradiction must be resolved, not averaged away.

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

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from aee.model import Claim, ClaimStage, ClaimStatus, EvidenceDirection, EvidenceKind
from aee.sources import source_identity
from aee.stage import LIFTING_EVENT, VERDICT_CEILING


def verdict_ceiling(stage: ClaimStage) -> str:
    """The policy verdict ceiling for a lifecycle stage (Spec 004 R1.3).

    The public, programmatic form of the stage -> verdict-ceiling
    table: ``created`` -> ``"unjudged"`` (no verdict is issued),
    ``checked``/``explained`` -> ``"challenge"``, ``accepted``/
    ``digested`` -> ``"accept"``. The table itself lives in
    ``aee.stage`` (the R1.3 table as data); this function is the
    policy layer's exposed accessor so later phases (P2/P3) and
    downstream consumers read the ceiling from the policy module
    instead of duplicating the table. ``evaluate_policy`` enforces
    exactly what this function reports.
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


def evaluate_policy(
    claim: Claim,
    score: ClaimScore,
    policy: AssessmentPolicy,
    *,
    threshold: float,
) -> ClaimVerdict:
    """Judge one scored claim against the policy gates.

    Rule order is significant: abstention (the claim cannot be
    judged) is decided before challenge (the claim is judged and
    wanting), so a claim with no usable support abstains even if it
    is also contradicted.
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
    if score.contradiction_penalty >= policy.contested_penalty_threshold:
        reasons.append(
            f"contested: contradiction penalty "
            f"{score.contradiction_penalty:.3f} >= "
            f"{policy.contested_penalty_threshold:.3f}"
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
