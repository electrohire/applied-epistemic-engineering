"""Spec 004 R6/R8: the two lanes, reported as a pair, never blended.

Lane 1 is machine-speed verification: scores, checks, verified
evidence. Lane 2 is human-paced acceptance: lifecycle stage,
exposition by named humans, attribution state. The lanes answer
different questions — "has it been checked?" and "has anyone
understood and accepted it?" — so the assessment reports them side
by side and NEVER as one number. A green lane 1 with a lagging
lane 2 is the normal state of machine-checked work, and the report
says so wherever the lane-1 result is stated.

Everything here is derived from records the assessment already
carries (scores, stage caps, failure modes); this module computes
nothing new about the claims themselves.
"""

from __future__ import annotations

from typing import Any

from aee.model import STAGE_ORDER, Claim, ClaimStage, EvidenceKind
from aee.scoring import ClaimScore
from aee.stage import StageCap

LANE_1_LABEL = "machine verification"
LANE_2_LABEL = "human acceptance"


def build_lanes(
    claims: list[Claim],
    *,
    scores: dict[str, ClaimScore],
    caps: list[StageCap],
    verified_unexplained_claim_ids: set[str],
    contested_attribution_ids: set[str],
    overrides: dict[str, ClaimStage],
    outcome: str,
    threshold: float,
) -> dict[str, Any]:
    """Assemble the lane pair for one assessment.

    ``caps`` / ``overrides`` give effective stages and their
    reasons; ``verified_unexplained_claim_ids`` and
    ``contested_attribution_ids`` come from the failure records and
    the decomposition pass respectively.
    """
    caps_by_claim: dict[str, list[StageCap]] = {}
    for cap in caps:
        caps_by_claim.setdefault(cap.claim_id, []).append(cap)

    per_claim: dict[str, Any] = {}
    stage_counts: dict[str, int] = {stage.value: 0 for stage in ClaimStage}
    exposition_covered = 0
    for claim in claims:
        effective = overrides.get(claim.id, claim.stage)
        stage_counts[effective.value] += 1
        # R3.2/R3.3: only RESOLVED exposition counts — an item whose
        # source_id failed identity resolution on the lenient path
        # (claim.unresolved_exposition) confers no explanation
        # credit, and its author is not named as an explainer.
        explainers = sorted(
            {
                item.source_id
                for item in claim.evidence
                if item.kind == EvidenceKind.EXPOSITION
                and item.source_id
                and item.source_id not in claim.unresolved_exposition
            }
        )
        has_exposition = bool(explainers)
        exposition_covered += int(has_exposition)
        score = scores.get(claim.id)
        per_claim[claim.id] = {
            "lane_1": {
                "score": score.propagated_score if score else None,
                "direct_score": score.direct_score if score else None,
                "author_status": claim.status.value,
                "at_or_above_threshold": (bool(score and score.propagated_score >= threshold)),
            },
            "lane_2": {
                "stage": effective.value,
                "stored_stage": claim.stage.value,
                "stage_capped": claim.id in caps_by_claim,
                "cap_reasons": [cap.note for cap in caps_by_claim.get(claim.id, [])],
                "exposition": has_exposition,
                "explainers": explainers,
                "verified_unexplained": claim.id in verified_unexplained_claim_ids,
                "attribution_contested": claim.id in contested_attribution_ids,
            },
        }

    at_or_above = sum(1 for score in scores.values() if score.propagated_score >= threshold)
    lagging = sum(
        count
        for stage, count in stage_counts.items()
        if STAGE_ORDER[ClaimStage(stage)] < STAGE_ORDER[ClaimStage.EXPLAINED]
    )
    return {
        "lane_1": {
            "label": LANE_1_LABEL,
            "outcome": outcome,
            "threshold": threshold,
            "claims_at_or_above_threshold": at_or_above,
            "claims_below_threshold": len(scores) - at_or_above,
        },
        "lane_2": {
            "label": LANE_2_LABEL,
            "stage_counts": stage_counts,
            "claims_below_explained": lagging,
            "exposition_covered_claims": exposition_covered,
            "exposition_missing_claims": len(claims) - exposition_covered,
            "verified_unexplained_claims": len(verified_unexplained_claim_ids),
            "stage_capped_claims": len(caps_by_claim),
            "attribution_contested_claims": len(contested_attribution_ids),
        },
        "per_claim": per_claim,
    }


def lane_summary_lines(lanes: dict[str, Any]) -> tuple[str, str]:
    """The two summary sentences. Lane 2's sentence states its lag
    in counts whenever there is lag, and says so plainly when there
    is none — it is emitted unconditionally, so a green lane 1 never
    appears in a summary without its lane-2 counterpart (R6.3)."""
    lane_1 = lanes["lane_1"]
    lane_2 = lanes["lane_2"]
    line_1 = (
        f"Lane 1 ({LANE_1_LABEL}): outcome {lane_1['outcome']}; "
        f"{lane_1['claims_at_or_above_threshold']} claim(s) at or above the "
        f"{lane_1['threshold']:.2f} threshold, "
        f"{lane_1['claims_below_threshold']} below."
    )
    counts = ", ".join(
        f"{stage} {count}" for stage, count in lane_2["stage_counts"].items() if count
    )
    line_2 = f"Lane 2 ({LANE_2_LABEL}): stages by effective stage: {counts or 'none'}."
    lag_bits = []
    if lane_2["claims_below_explained"]:
        lag_bits.append(f"{lane_2['claims_below_explained']} claim(s) below explained")
    if lane_2["verified_unexplained_claims"]:
        lag_bits.append(f"{lane_2['verified_unexplained_claims']} verified but unexplained")
    if lane_2["stage_capped_claims"]:
        lag_bits.append(f"{lane_2['stage_capped_claims']} stage-capped")
    if lane_2["attribution_contested_claims"]:
        lag_bits.append(f"{lane_2['attribution_contested_claims']} with contested attribution")
    if lag_bits:
        line_2 += " Lane-2 lag: " + "; ".join(lag_bits) + "."
    else:
        line_2 += " No lane-2 lag: every claim is explained or beyond, with exposition."
    return line_1, line_2
