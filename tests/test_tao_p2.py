"""Spec 004 Phase P2 acceptance tests: the machine-only policy gate
(R5.1), mandatory `not_understood` (R5.2/R5.3), and the
verified-but-unexplained risk flag (R3.3).
"""

import json

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
from aee.cli import main as cli_main
from aee.policy import machine_only_reason
from aee.scoring import ScoringEngine

POLICY = AssessmentPolicy()


def machine_claim(stage=ClaimStage.ACCEPTED, **overrides) -> Claim:
    kwargs = dict(
        id="M",
        text="Latency is below 100 ms",
        status=ClaimStatus.SUPPORTED,
        stage=stage,
        boundary=["p95 in production"],
        falsification_tests=["Observe p95 at or above 100 ms in production"],
        evidence=[strong_evidence("one", "S1"), strong_evidence("two", "S2")],
    )
    kwargs.update(overrides)
    return Claim(**kwargs)


# -- R5.1: the machine-only cap -----------------------------------------


def test_machine_only_claim_is_capped_at_checked():
    claim = machine_claim()
    assert machine_only_reason(claim) is not None
    assessment = AEEEngine(policy=POLICY).assess([claim])
    # Stored stage is accepted; the gate caps the effective stage at
    # checked: no `supported` report, verdict ceiling challenge, and
    # the cap record names the evidence partition.
    assert assessment.reported_statuses == {"M": "partially_supported"}
    assert assessment.verdicts["M"].verdict.value == "challenge"
    cap = next(c for c in assessment.stage_caps if c.claim_id == "M")
    assert "machine-only" in cap.note
    assert "observed/test" in cap.note


def test_human_paced_support_lifts_the_machine_cap():
    claim = machine_claim()
    claim.evidence.append(
        Evidence(
            ref="review-note",
            kind=EvidenceKind.ASSERTED,
            source_quality=SourceQuality.HUMAN,
            source_id="jane-doe",
            description="A named human reviewed and stands behind this.",
        )
    )
    assert machine_only_reason(claim) is None
    assessment = AEEEngine(policy=POLICY).assess([claim])
    assert assessment.reported_statuses == {"M": "supported"}


def test_exposition_lifts_the_machine_cap():
    claim = machine_claim()
    claim.evidence.append(
        Evidence(
            ref="walkthrough",
            kind=EvidenceKind.EXPOSITION,
            source_quality=SourceQuality.HUMAN,
            source_id="jane-doe",
        )
    )
    assert machine_only_reason(claim) is None


def test_no_support_is_not_machine_only():
    claim = machine_claim(evidence=[])
    assert machine_only_reason(claim) is None


def test_machine_cap_never_touches_the_score():
    capped = ScoringEngine().score([machine_claim()])["M"]
    human = machine_claim()
    human.evidence.append(
        Evidence(
            ref="review-note",
            kind=EvidenceKind.ASSERTED,
            source_quality=SourceQuality.HUMAN,
            source_id="jane-doe",
        )
    )
    # Different evidence, so compare the capped claim against itself:
    # the cap lives in reporting, the lane-1 number is computed from
    # evidence alone and the gate adds nothing to scoring inputs.
    assert capped.direct_score > 0.0
    assessment = AEEEngine(policy=POLICY).assess([machine_claim()])
    assert assessment.scores["M"].propagated_score == capped.propagated_score


# -- R3.3: verified but unexplained ---------------------------------------


def test_verified_unexplained_flag_fires_without_exposition():
    assessment = AEEEngine(policy=POLICY).assess([machine_claim(stage=ClaimStage.CHECKED)])
    flags = [f for f in assessment.failures if f.category == "verified_unexplained"]
    assert len(flags) == 1
    assert flags[0].severity.value == "medium"


def test_exposition_clears_the_flag():
    claim = machine_claim(stage=ClaimStage.CHECKED)
    claim.evidence.append(
        Evidence(
            ref="walkthrough",
            kind=EvidenceKind.EXPOSITION,
            source_quality=SourceQuality.HUMAN,
            source_id="jane-doe",
        )
    )
    assessment = AEEEngine(policy=POLICY).assess([claim])
    assert not [f for f in assessment.failures if f.category == "verified_unexplained"]


def test_created_claims_are_not_flagged():
    assessment = AEEEngine(policy=POLICY).assess([machine_claim(stage=ClaimStage.CREATED)])
    assert not [f for f in assessment.failures if f.category == "verified_unexplained"]


def test_flag_does_not_route_the_outcome_or_score():
    # A bundle whose only blemish is the risk flag still passes:
    # accepted-stage claims, human-paced support (no machine cap),
    # but no exposition - flagged, counted, and still a pass, with
    # the lane-2 lag stated in the summary.
    claims = []
    for _index, suffix in enumerate(("A", "B")):
        claim = machine_claim(id=suffix)
        claim.evidence = [
            strong_evidence(f"{suffix}-one", f"{suffix}-S1"),
            Evidence(
                ref=f"{suffix}-review",
                kind=EvidenceKind.OBSERVED,
                source_quality=SourceQuality.PRIMARY,
                source_id=f"{suffix}-reviewer",
            ),
        ]
        claims.append(claim)
    assessment = AEEEngine(policy=POLICY).assess(claims)
    assert assessment.outcome == "pass"
    assert len([f for f in assessment.failures if f.category == "verified_unexplained"]) == 2
    assert "Not understood:" in assessment.summary


# -- R5.2/R5.3: not_understood ---------------------------------------------


def test_not_understood_is_always_serialised():
    empty = AEEEngine().assess([])
    assert empty.to_dict()["not_understood"] == []
    assessment = AEEEngine(policy=POLICY).assess([machine_claim()])
    entries = assessment.to_dict()["not_understood"]
    assert entries  # caps + flags guarantee content here
    assert any("machine-only" in entry for entry in entries)
    assert any("verified but unexplained" in entry for entry in entries)


def test_not_understood_includes_author_supplied_text():
    assessment = AEEEngine().assess(
        [machine_claim()], metadata={"not_understood": ["The staging lab was never inspected."]}
    )
    assert "The staging lab was never inspected." in assessment.to_dict()["not_understood"]


def test_gate_rejects_assessment_without_not_understood(tmp_path, capsys):
    assessment = AEEEngine(policy=POLICY).assess([machine_claim()])
    payload = assessment.to_dict()
    del payload["not_understood"]
    path = tmp_path / "assessment.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    exit_code = cli_main(["gate", "--input", str(path)])
    assert exit_code == 2
    assert "not_understood" in capsys.readouterr().err


def test_gate_accepts_engine_assessment_with_not_understood(tmp_path):
    assessment = AEEEngine(policy=POLICY).assess([machine_claim()])
    path = tmp_path / "assessment.json"
    path.write_text(json.dumps(assessment.to_dict()), encoding="utf-8")
    exit_code = cli_main(["gate", "--input", str(path)])
    assert exit_code == 1  # iterate (stage/machine caps), not a completeness error
