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


def test_evaluator_adapter_translates_exposition_evidence_refs() -> None:
    # Spec 006 deviation D1 (regression): a claim carrying exposition
    # evidence (the named-human explanation the `explained` stage
    # requires) AND an open failure could not be composed at all —
    # the adapter emitted the engine kind `exposition` verbatim into
    # findings[].evidence_refs[].kind, the shipped evaluator contract
    # (v1.1.2) allows only observed/inferred/asserted/contradicted/
    # unsupported there, and composition raised instead of returning
    # a result. The finding and its evidence must survive translation:
    # the ref stays, under the contract kind `asserted` (a named
    # human's recorded explanation is that human's assertion, and
    # `asserted` is the weakest support kind the contract offers, so
    # the translation can never overstate the evidence); the original
    # kind stays visible in state.aee.claims and every translation is
    # named in metadata.evidence_kind_translations.
    from aee import (
        Evidence,
        EvidenceDirection,
        EvidenceKind,
        SourceQuality,
        validate_evaluator_result,
    )
    from aee.adapters.evaluator import _validate_evaluator_result_structural

    claim = Claim(
        id="D1",
        text="Widget latency is 42 ms at p95 under load profile L",
        status=ClaimStatus.SUPPORTED,
        stage=ClaimStage.EXPLAINED,
        boundary=["load profile L"],
        falsification_tests=["Measure p95 latency and observe a reading above 42 ms"],
        evidence=[
            Evidence(
                ref="reports/d1-a.json",
                kind=EvidenceKind.OBSERVED,
                direction=EvidenceDirection.SUPPORTS,
                source_quality=SourceQuality.TEST,
                source_id="lab-a",
                description="First measurement",
            ),
            Evidence(
                ref="notes/d1-walkthrough.md",
                kind=EvidenceKind.EXPOSITION,
                direction=EvidenceDirection.SUPPORTS,
                source_quality=SourceQuality.HUMAN,
                source_id="jane-doe",
                description="The explainer's walkthrough",
            ),
        ],
    )
    assessment = AEEEngine().assess([claim])
    # Premise: the claim really is the Phase D shape — exposition on
    # record and at least one open failure for the adapter to express.
    assert claim.unresolved_failures
    result = EvaluatorAdapter().to_evaluator_result(assessment)
    assert result["findings"], "the open finding must survive composition"
    refs = [ref for finding in result["findings"] for ref in finding["evidence_refs"]]
    contract_kinds = {"observed", "inferred", "asserted", "contradicted", "unsupported"}
    assert all(ref["kind"] in contract_kinds for ref in refs)
    by_ref = {ref["ref"]: ref["kind"] for ref in refs}
    # The observed item keeps its kind; the exposition item is still
    # referenced — translated, not dropped.
    assert by_ref["reports/d1-a.json"] == "observed"
    assert by_ref["notes/d1-walkthrough.md"] == "asserted"
    # The translation is on the composed record, countable by a reader
    # who never opens the engine's own files.
    assert result["metadata"]["evidence_kind_translations"] == [
        {
            "ref": "notes/d1-walkthrough.md",
            "engine_kind": "exposition",
            "contract_kind": "asserted",
        }
    ]
    # The original kind is still visible in the composed result's own
    # claim record, keyed by the same ref.
    state_kinds = {
        item["ref"]: item["kind"] for item in result["state"]["aee"]["claims"][0]["evidence"]
    }
    assert state_kinds["notes/d1-walkthrough.md"] == "exposition"
    # Both validation paths accept the composed result: the public
    # validator (the shipped contract schema) and the structural
    # mirror used when jsonschema is unavailable.
    validate_evaluator_result(result)
    _validate_evaluator_result_structural(result)

    # A claim with no translated evidence reports an empty list —
    # the zero case is stated, not omitted.
    plain = Claim(id="D1-plain", text="The service is fast")
    plain_result = EvaluatorAdapter().to_evaluator_result(AEEEngine().assess([plain]))
    assert plain_result["metadata"]["evidence_kind_translations"] == []


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
