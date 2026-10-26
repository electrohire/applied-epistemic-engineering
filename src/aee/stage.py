"""Stage-gated vocabulary caps (Spec 004 R1.3/R1.4, OD-T3 ratified).

The assessment reports a claim's status and policy verdict CAPPED by
its lifecycle stage, per the ratified table:

| Stage     | Status values the assessment may report                    | Ceiling   |
|-----------|------------------------------------------------------------|-----------|
| created   | draft only                                                 | unjudged  |
| checked   | draft, partially_supported, unsupported, contradicted,     | challenge |
|           | unverifiable                                               |           |
| explained | the above, plus supported (qualified - not yet accepted)   | challenge |
| accepted  | the above, plus supported unqualified                      | accept    |
| digested  | the above, plus superseded as a terminal state             | accept    |

The cap only lowers the reported vocabulary; it never raises a
posture, never touches the claim's stored (author-declared) status,
and never changes a score - mirroring the policy layer's demote-only
rule. A capped claim carries a score note and a failure mode
(category ``stage_cap``) naming the cap and the stage event that
would lift it; both are produced by the engine from the pure
functions here, so the CLI gate's cross-check recomputes exactly the
same caps from the serialized record.

The bundle outcome inherits the caps (R1.4): ``pass`` is reported
only when every covered claim is at stage ``explained`` or beyond.
Lane-qualified outcomes (R6) are P3; P0 implements the conservative
rule and says so.
"""

from __future__ import annotations

from dataclasses import dataclass

from aee.model import STAGE_ORDER, Claim, ClaimStage, ClaimStatus

# Status values reportable at each stage (R1.3 table, verbatim).
ALLOWED_STATUSES: dict[ClaimStage, frozenset[ClaimStatus]] = {
    ClaimStage.CREATED: frozenset({ClaimStatus.DRAFT}),
    ClaimStage.CHECKED: frozenset(
        {
            ClaimStatus.DRAFT,
            ClaimStatus.PARTIALLY_SUPPORTED,
            ClaimStatus.UNSUPPORTED,
            ClaimStatus.CONTRADICTED,
            ClaimStatus.UNVERIFIABLE,
        }
    ),
    ClaimStage.EXPLAINED: frozenset(
        {
            ClaimStatus.DRAFT,
            ClaimStatus.PARTIALLY_SUPPORTED,
            ClaimStatus.UNSUPPORTED,
            ClaimStatus.CONTRADICTED,
            ClaimStatus.UNVERIFIABLE,
            ClaimStatus.SUPPORTED,
        }
    ),
    ClaimStage.ACCEPTED: frozenset(
        {
            ClaimStatus.DRAFT,
            ClaimStatus.PARTIALLY_SUPPORTED,
            ClaimStatus.UNSUPPORTED,
            ClaimStatus.CONTRADICTED,
            ClaimStatus.UNVERIFIABLE,
            ClaimStatus.SUPPORTED,
        }
    ),
    ClaimStage.DIGESTED: frozenset(
        {
            ClaimStatus.DRAFT,
            ClaimStatus.PARTIALLY_SUPPORTED,
            ClaimStatus.UNSUPPORTED,
            ClaimStatus.CONTRADICTED,
            ClaimStatus.UNVERIFIABLE,
            ClaimStatus.SUPPORTED,
            ClaimStatus.SUPERSEDED,
        }
    ),
}

# Policy verdict ceiling per stage (R1.3): "unjudged" = no verdict is
# issued at all (reported as Verdict.UNJUDGED).
VERDICT_CEILING: dict[ClaimStage, str] = {
    ClaimStage.CREATED: "unjudged",
    ClaimStage.CHECKED: "challenge",
    ClaimStage.EXPLAINED: "challenge",
    ClaimStage.ACCEPTED: "accept",
    ClaimStage.DIGESTED: "accept",
}

# The recorded event that lifts a claim out of each stage (R1.2).
LIFTING_EVENT: dict[ClaimStage, str] = {
    ClaimStage.CREATED: "a recorded checking event (an assessment run recorded as a stage event)",
    ClaimStage.CHECKED: (
        "a recorded explanation event (exposition evidence by a named human, Spec 004 R3)"
    ),
    ClaimStage.EXPLAINED: "a recorded human acceptance event",
    ClaimStage.ACCEPTED: (
        "a recorded digestion event (exposition by a human other than the claim's "
        "author, Spec 004 R3.4)"
    ),
    ClaimStage.DIGESTED: "none (digested is the terminal stage)",
}

# Fallback chain when a status is not reportable at a stage: the
# strongest reportable posture that does not overstate the claim.
_CAP_FALLBACK = (ClaimStatus.PARTIALLY_SUPPORTED, ClaimStatus.DRAFT)


def reported_status_for(status: ClaimStatus, stage: ClaimStage) -> ClaimStatus:
    """The status the assessment may report for (author status, stage)."""
    allowed = ALLOWED_STATUSES[stage]
    if status in allowed:
        return status
    for fallback in _CAP_FALLBACK:
        if fallback in allowed:
            return fallback
    return ClaimStatus.DRAFT


@dataclass(slots=True)
class StageCap:
    """One claim's stage cap, as reported (R1.3/R8.1)."""

    claim_id: str
    stage: str
    author_status: str
    reported_status: str
    verdict_ceiling: str
    qualified_supported: bool = False
    note: str = ""
    lifting_event: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "stage": self.stage,
            "author_status": self.author_status,
            "reported_status": self.reported_status,
            "verdict_ceiling": self.verdict_ceiling,
            "qualified_supported": self.qualified_supported,
            "note": self.note,
            "lifting_event": self.lifting_event,
        }


def stage_cap_for(
    claim: Claim,
    *,
    effective_stage: ClaimStage | None = None,
    reason: str = "",
) -> StageCap | None:
    """The cap binding this claim, or None when no cap binds.

    A cap binds when (a) the author-declared status is not reportable
    at the claim's stage (reported status is lowered), or (b) the
    status is ``supported`` at stage ``explained`` - reportable, but
    only in qualified form: the verdict ceiling is still
    ``challenge`` and ``supported`` must not read as settled until a
    recorded acceptance event lands. The verdict ceiling for stages
    ``created``/``checked``/``explained`` is enforced in the policy
    layer (aee.policy) whenever a verdict would exceed it; the cap
    record here names it in every case.

    ``effective_stage`` (Spec 004 P1: decomposition/attribution caps)
    replaces the stored stage for cap purposes when another rule
    caps the stage further - an incomplete headline is treated as
    ``created`` (R2.3), a contested attribution caps at ``checked``
    (R4.3). A cap also binds when the effective stage is below the
    stored one even if the status remains reportable, because the
    verdict ceiling dropped; ``reason`` names the imposing rule and
    is appended to the note.
    """
    stage = effective_stage if effective_stage is not None else claim.stage
    reported = reported_status_for(claim.status, stage)
    qualified = claim.status == ClaimStatus.SUPPORTED and stage == ClaimStage.EXPLAINED
    stage_lowered = stage != claim.stage
    if reported == claim.status and not qualified and not stage_lowered:
        return None
    ceiling = VERDICT_CEILING[stage]
    lifting = LIFTING_EVENT[stage]
    if qualified and not stage_lowered:
        note = (
            "Stage cap (Spec 004 R1.3): claim at stage 'explained' reports "
            "'supported' in qualified form only - the policy verdict ceiling "
            "is 'challenge' until a recorded human acceptance event lands"
        )
    else:
        note = (
            f"Stage cap (Spec 004 R1.3): claim at stage '{stage.value}' "
            f"may not report status '{claim.status.value}'; reported as "
            f"'{reported.value}' (policy verdict ceiling: {ceiling})"
        )
        if stage_lowered:
            note += f"; stored stage '{claim.stage.value}' is capped to '{stage.value}'"
    if reason:
        note += f" [{reason}]"
    return StageCap(
        claim_id=claim.id,
        stage=stage.value,
        author_status=claim.status.value,
        reported_status=reported.value,
        verdict_ceiling=ceiling,
        qualified_supported=qualified,
        note=note,
        lifting_event=lifting,
    )


def _effective(claim: Claim, overrides: dict[str, ClaimStage] | None) -> ClaimStage:
    if overrides and claim.id in overrides:
        return overrides[claim.id]
    return claim.stage


def reported_statuses(
    claims: list[Claim], overrides: dict[str, ClaimStage] | None = None
) -> dict[str, str]:
    """Per-claim reported (capped) status for an assessment."""
    return {
        claim.id: reported_status_for(claim.status, _effective(claim, overrides)).value
        for claim in claims
    }


def stage_caps(
    claims: list[Claim],
    overrides: dict[str, ClaimStage] | None = None,
    reasons: dict[str, str] | None = None,
) -> list[StageCap]:
    """All binding caps in a bundle, in claim order."""
    caps: list[StageCap] = []
    for claim in claims:
        cap = stage_cap_for(
            claim,
            effective_stage=_effective(claim, overrides),
            reason=(reasons or {}).get(claim.id, ""),
        )
        if cap is not None:
            caps.append(cap)
    return caps


def below_explained(
    claims: list[Claim], overrides: dict[str, ClaimStage] | None = None
) -> list[Claim]:
    """Claims whose stage blocks a settlement-worded outcome (R1.4)."""
    return [
        claim
        for claim in claims
        if STAGE_ORDER[_effective(claim, overrides)] < STAGE_ORDER[ClaimStage.EXPLAINED]
    ]


__all__ = [
    "ALLOWED_STATUSES",
    "LIFTING_EVENT",
    "VERDICT_CEILING",
    "StageCap",
    "below_explained",
    "reported_status_for",
    "reported_statuses",
    "stage_cap_for",
    "stage_caps",
]
