import json

from aee import AEEEngine, Claim, ClaimStage, ClaimStatus, EvaluatorAdapter


def test_clean_assessment_passes() -> None:
    from test_scoring import strong_evidence

    from aee import Evidence, EvidenceKind, SourceQuality

    claim = Claim(
        id="A",
        text="Latency is below 100 ms",
        status=ClaimStatus.SUPPORTED,
        boundary=["p95 in production"],
        falsification_tests=["Observe p95 at or above 100 ms"],
        evidence=[
            strong_evidence("one", "S1"),
            strong_evidence("two", "S2"),
            # Spec 004 R5.1 (P2): human-paced support, so this clean
            # fixture is not capped at `checked` by the machine-only
            # gate.
            Evidence(
                ref="review",
                source_id="reviewer-1",
                kind=EvidenceKind.OBSERVED,
                source_quality=SourceQuality.PRIMARY,
            ),
        ],
        stage=ClaimStage.ACCEPTED,
    )
    result = AEEEngine().assess([claim])
    assert result.outcome == "pass"


def test_missing_evidence_pauses() -> None:
    claim = Claim(
        id="A",
        text="Latency is below 100 ms",
        status=ClaimStatus.SUPPORTED,
        boundary=["p95 in production"],
        falsification_tests=["Observe p95 at or above 100 ms"],
    )
    result = AEEEngine().assess([claim])
    assert result.outcome == "gather_evidence"


def test_evaluator_adapter_contract() -> None:
    claim = Claim(id="A", text="The service is fast")
    assessment = AEEEngine().assess([claim], phase="plan")
    result = EvaluatorAdapter().to_evaluator_result(assessment, artifacts=["plan.md"])
    assert result["schema_version"] == "1.0"
    assert result["evaluator"]["id"] == "aee"
    assert result["phase"] == "after_plan"
    assert result["outcome"] in {
        "pass",
        "warn",
        "iterate",
        "clarify",
        "gather_evidence",
        "block",
    }
    assert result["findings"]
    assert result["state"]["aee"]["claims"]
    json.dumps(result)


def test_evaluator_result_carries_lanes_and_not_understood() -> None:
    # Spec 004 P5: the Evaluator Contract result carries the lane
    # pair and the residual-unknowns statement in metadata, so the
    # composition layer can present the lanes side by side.
    from test_scoring import strong_evidence

    claim = Claim(
        id="A",
        text="Latency is below 100 ms",
        status=ClaimStatus.SUPPORTED,
        boundary=["p95 in production"],
        falsification_tests=["Observe p95 at or above 100 ms"],
        evidence=[strong_evidence("one", "S1"), strong_evidence("two", "S2")],
        stage=ClaimStage.ACCEPTED,
    )
    assessment = AEEEngine().assess([claim])
    result = EvaluatorAdapter().to_evaluator_result(assessment)
    metadata = result["metadata"]
    assert metadata["lanes"]["lane_1"]["label"] == "machine verification"
    assert metadata["lanes"]["lane_2"]["label"] == "human acceptance"
    assert "score" not in str(metadata["lanes"]["lane_2"].keys())
    assert metadata["not_understood"] == assessment.not_understood
    assert metadata["reported_statuses"] == assessment.reported_statuses
