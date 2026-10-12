"""Spec 004 Phase P3 acceptance tests: lane-separated reporting
(R6/R8). Lane 1 (machine verification) and lane 2 (human
acceptance) are reported as a pair, per claim and per bundle, and
never blended into one number.
"""

from test_scoring import strong_evidence

from aee import (
    AEEEngine,
    AssessmentPolicy,
    Claim,
    ClaimStage,
    ClaimStatus,
    Evidence,
    EvidenceKind,
    SourceQuality,
)

POLICY = AssessmentPolicy()


def human_claim(claim_id="H", stage=ClaimStage.ACCEPTED) -> Claim:
    return Claim(
        id=claim_id,
        text="Latency is below 100 ms",
        status=ClaimStatus.SUPPORTED,
        stage=stage,
        boundary=["p95 in production"],
        falsification_tests=["Observe p95 at or above 100 ms in production"],
        evidence=[
            strong_evidence("one", "S1"),
            Evidence(
                ref="review",
                source_id="reviewer-1",
                kind=EvidenceKind.OBSERVED,
                source_quality=SourceQuality.PRIMARY,
            ),
            Evidence(
                ref="walkthrough",
                source_id="reviewer-1",
                kind=EvidenceKind.EXPOSITION,
                source_quality=SourceQuality.HUMAN,
            ),
        ],
    )


def machine_claim(claim_id="M") -> Claim:
    return Claim(
        id=claim_id,
        text="Latency is below 100 ms",
        status=ClaimStatus.SUPPORTED,
        stage=ClaimStage.ACCEPTED,
        boundary=["p95 in production"],
        falsification_tests=["Observe p95 at or above 100 ms in production"],
        evidence=[strong_evidence("one", "S1"), strong_evidence("two", "S2")],
    )


def _all_keys(value) -> set:
    keys = set()
    if isinstance(value, dict):
        for key, sub in value.items():
            keys.add(key)
            keys |= _all_keys(sub)
    elif isinstance(value, list):
        for sub in value:
            keys |= _all_keys(sub)
    return keys


def test_lanes_are_serialised_as_a_pair():
    assessment = AEEEngine(policy=POLICY).assess([human_claim()])
    lanes = assessment.to_dict()["lanes"]
    assert lanes["lane_1"]["label"] == "machine verification"
    assert lanes["lane_2"]["label"] == "human acceptance"
    assert lanes["lane_1"]["outcome"] == assessment.outcome
    pair = lanes["per_claim"]["H"]
    assert pair["lane_1"]["score"] == assessment.scores["H"].propagated_score
    assert pair["lane_2"]["stage"] == "accepted"
    assert pair["lane_2"]["exposition"] is True


def test_lane_2_is_state_never_a_score():
    assessment = AEEEngine(policy=POLICY).assess([human_claim(), machine_claim()])
    lanes = assessment.to_dict()["lanes"]
    assert "score" not in _all_keys(lanes["lane_2"])
    for pair in lanes["per_claim"].values():
        assert "score" not in _all_keys(pair["lane_2"])


def test_machine_claim_shows_green_lane_1_and_lagging_lane_2():
    assessment = AEEEngine(policy=POLICY).assess([machine_claim()])
    lanes = assessment.to_dict()["lanes"]
    pair = lanes["per_claim"]["M"]
    # Lane 1 is genuinely strong; lane 2 states the cap, the
    # effective stage, and the missing exposition - side by side.
    assert pair["lane_1"]["score"] >= 0.70
    assert pair["lane_2"]["stage"] == "checked"
    assert pair["lane_2"]["stored_stage"] == "accepted"
    assert pair["lane_2"]["stage_capped"] is True
    assert any("machine-only" in reason for reason in pair["lane_2"]["cap_reasons"])
    assert pair["lane_2"]["verified_unexplained"] is True
    assert lanes["lane_2"]["stage_counts"]["checked"] == 1
    assert lanes["lane_2"]["verified_unexplained_claims"] == 1


def test_summary_always_pairs_the_lanes():
    assessment = AEEEngine(policy=POLICY).assess([human_claim()])
    assert assessment.outcome == "pass"
    # Lane 1 is green; the lane-2 sentence still appears and states
    # its state (here: exposition present, stage accepted).
    assert "Lane 1 (machine verification): outcome pass" in assessment.summary
    assert "Lane 2 (human acceptance):" in assessment.summary
    assert "accepted 1" in assessment.summary


def test_summary_states_lane_2_lag_when_lane_1_is_green():
    assessment = AEEEngine(policy=POLICY).assess([machine_claim()])
    assert "Lane 2 (human acceptance):" in assessment.summary
    assert "Lane-2 lag:" in assessment.summary
    assert "verified but unexplained" in assessment.summary


def test_empty_assessment_still_reports_both_lanes():
    assessment = AEEEngine().assess([])
    lanes = assessment.to_dict()["lanes"]
    assert lanes["lane_1"]["claims_at_or_above_threshold"] == 0
    assert lanes["lane_2"]["stage_counts"]["created"] == 0
    assert "Lane 1 (machine verification)" in assessment.summary
    assert "Lane 2 (human acceptance)" in assessment.summary
