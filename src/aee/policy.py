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

from aee.model import Claim, EvidenceDirection

if TYPE_CHECKING:
    from aee.scoring import ClaimScore


class Verdict(StrEnum):
    ACCEPT = "accept"
    CHALLENGE = "challenge"
    ABSTAIN = "abstain"


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
    source_ids = {item.source_id or item.ref for item in supporting if item.ref}
    if len(source_ids) < policy.min_independent_sources:
        reasons.append(
            f"corroboration: {len(source_ids)} independent supporting "
            f"source(s) < {policy.min_independent_sources} required"
        )
    if score.propagated_score < threshold:
        reasons.append(
            f"propagated score {score.propagated_score:.3f} below "
            f"the {threshold:.2f} confidence threshold"
        )
    if reasons:
        return ClaimVerdict(claim.id, Verdict.CHALLENGE, reasons)
    return ClaimVerdict(claim.id, Verdict.ACCEPT, [])
