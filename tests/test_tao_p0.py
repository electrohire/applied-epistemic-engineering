"""Spec 004 Phase P0 acceptance tests: lifecycle stage, stage caps,
exposition evidence, and the project-local identity registry.

Written against spec.md R1/R3 and plan.md Phase P0, with OD-T2/T3/T4
as ratified 2026-10-12: five stage terms verbatim; `supported` capped
by stage (R1.3 table); exposition resolves against a project-local
registry of named humans, enforced by shape.
"""

import json

import pytest
from test_scoring import strong_evidence

from aee import (
    AEEEngine,
    AssessmentPolicy,
    BundleValidationError,
    Claim,
    ClaimStage,
    ClaimStatus,
    Evidence,
    EvidenceKind,
    IdentityRegistry,
    Verdict,
)
from aee.extract import load_claims, migrate_bundle
from aee.policy import evaluate_policy
from aee.scoring import ScoringEngine
from aee.stage import VERDICT_CEILING, reported_status_for

POLICY = AssessmentPolicy()


def strong_claim(stage: ClaimStage, **overrides) -> Claim:
    kwargs = dict(
        id="A",
        text="Latency is below 100 ms",
        status=ClaimStatus.SUPPORTED,
        stage=stage,
        boundary=["p95 in production"],
        falsification_tests=["Observe p95 at or above 100 ms in production"],
        evidence=[strong_evidence("one", "S1"), strong_evidence("two", "S2")],
    )
    kwargs.update(overrides)
    return Claim(**kwargs)


def verdict_for(claim: Claim):
    score = ScoringEngine().score([claim])[claim.id]
    return evaluate_policy(claim, score, POLICY, threshold=0.70)


# -- R1.3: the cap table -------------------------------------------------


@pytest.mark.parametrize(
    "stage,expected_reported",
    [
        (ClaimStage.CREATED, ClaimStatus.DRAFT),
        (ClaimStage.CHECKED, ClaimStatus.PARTIALLY_SUPPORTED),
        (ClaimStage.EXPLAINED, ClaimStatus.SUPPORTED),
        (ClaimStage.ACCEPTED, ClaimStatus.SUPPORTED),
        (ClaimStage.DIGESTED, ClaimStatus.SUPPORTED),
    ],
)
def test_reported_status_capped_by_stage(stage, expected_reported):
    claim = strong_claim(stage)
    assert reported_status_for(claim.status, claim.stage) == expected_reported
    assessment = AEEEngine(policy=POLICY).assess([claim])
    assert assessment.reported_statuses == {"A": expected_reported.value}


@pytest.mark.parametrize(
    "stage,expected_verdict",
    [
        (ClaimStage.CREATED, Verdict.UNJUDGED),
        (ClaimStage.CHECKED, Verdict.CHALLENGE),
        (ClaimStage.EXPLAINED, Verdict.CHALLENGE),
        (ClaimStage.ACCEPTED, Verdict.ACCEPT),
        (ClaimStage.DIGESTED, Verdict.ACCEPT),
    ],
)
def test_verdict_ceiling_by_stage(stage, expected_verdict):
    assert verdict_for(strong_claim(stage)).verdict == expected_verdict
    assert VERDICT_CEILING[stage] == expected_verdict.value


def test_cap_binds_with_failure_mode_and_lifting_event():
    assessment = AEEEngine(policy=POLICY).assess([strong_claim(ClaimStage.CREATED)])
    assert len(assessment.stage_caps) == 1
    cap = assessment.stage_caps[0]
    assert cap.reported_status == "draft"
    assert cap.lifting_event  # names the event that would lift the cap
    cap_failures = [
        failure
        for claim_failures in (c.failures for c in assessment.claims)
        for failure in claim_failures
        if failure.category == "stage_cap"
    ]
    assert cap_failures, "a binding cap must surface as a stage_cap failure mode"


def test_explained_supported_is_qualified_not_settled():
    assessment = AEEEngine(policy=POLICY).assess([strong_claim(ClaimStage.EXPLAINED)])
    assert assessment.reported_statuses == {"A": "supported"}
    assert len(assessment.stage_caps) == 1
    assert assessment.stage_caps[0].qualified_supported is True


def test_accepted_supported_is_uncapped():
    assessment = AEEEngine(policy=POLICY).assess([strong_claim(ClaimStage.ACCEPTED)])
    assert assessment.reported_statuses == {"A": "supported"}
    assert assessment.stage_caps == []


def test_cap_never_raises_a_posture():
    # An unsupported claim at a late stage reports unsupported, not a
    # stage-flavoured upgrade.
    claim = strong_claim(ClaimStage.ACCEPTED, status=ClaimStatus.UNSUPPORTED)
    assert reported_status_for(claim.status, claim.stage) == ClaimStatus.UNSUPPORTED


# -- R1.4: the bundle outcome inherits the caps --------------------------


def test_outcome_cannot_pass_below_explained():
    claims = [strong_claim(ClaimStage.CREATED, id="A"), strong_claim(ClaimStage.CHECKED, id="B")]
    assessment = AEEEngine(policy=POLICY).assess(claims)
    assert assessment.outcome != "pass"


def test_outcome_can_pass_when_all_accepted():
    claims = [
        strong_claim(ClaimStage.ACCEPTED, id="A"),
        strong_claim(
            ClaimStage.ACCEPTED,
            id="B",
            evidence=[strong_evidence("three", "S3"), strong_evidence("four", "S4")],
        ),
    ]
    assessment = AEEEngine(policy=POLICY).assess(claims)
    assert assessment.outcome == "pass"


# -- R1.1/R1.2: stage as a stored, event-advanced record -----------------


def test_stage_advance_is_recorded_and_forward_only():
    claim = strong_claim(ClaimStage.CREATED)
    event = claim.advance_stage(
        ClaimStage.CHECKED, author="assessor", date="2026-10-12", basis="assessment run #1"
    )
    assert claim.stage == ClaimStage.CHECKED
    assert claim.stage_events == [event]
    assert claim.to_dict()["stage"] == "checked"
    assert claim.to_dict()["stage_events"][0]["basis"] == "assessment run #1"
    with pytest.raises(ValueError):
        claim.advance_stage(ClaimStage.CREATED, basis="rewind")


def _bundle_json(claims: list[dict]) -> dict:
    return {"spec": "p0-test", "schema_version": "1.0", "version": "0", "claims": claims}


def _claim_json(**overrides) -> dict:
    row = {
        "id": "A",
        "text": "Latency is below 100 ms",
        "kind": "assumption",
        "status": "supported",
        "boundary": ["p95 in production"],
        "falsification_tests": ["Observe p95 at or above 100 ms in production"],
        "evidence": [
            {"ref": "one", "kind": "observed", "source_quality": "test", "source_id": "S1"},
            {"ref": "two", "kind": "observed", "source_quality": "test", "source_id": "S2"},
        ],
    }
    row.update(overrides)
    return row


def _write(tmp_path, payload: dict, name: str = "claims.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_strict_load_rejects_unknown_stage(tmp_path):
    path = _write(tmp_path, _bundle_json([_claim_json(stage="settled")]))
    with pytest.raises(BundleValidationError) as excinfo:
        load_claims(path)
    assert "stage" in str(excinfo.value)


def test_strict_load_names_missing_stage(tmp_path):
    path = _write(tmp_path, _bundle_json([_claim_json()]))
    with pytest.raises(BundleValidationError) as excinfo:
        load_claims(path)
    assert "stage" in str(excinfo.value)


def test_lenient_load_defaults_stage_and_records_it(tmp_path):
    path = _write(tmp_path, _bundle_json([_claim_json()]))
    claims = load_claims(path, strict=False)
    assert claims[0].stage == ClaimStage.CREATED
    assert claims[0].stage_defaulted is True
    assessment = AEEEngine().assess(claims)
    assert assessment.metadata["stage_defaulted_claims"] == ["A"]


def test_migrate_backfills_stage_and_reports_it():
    migrated, report = migrate_bundle(_bundle_json([_claim_json()]))
    assert migrated["claims"][0]["stage"] == "created"
    assert any("stage" in line and "A" in line for line in report)


# -- R3.1/R3.2 + OD-T4: exposition and the identity registry -------------


def _exposition_claim_json(source_id: str) -> dict:
    return _claim_json(
        stage="checked",
        evidence=[
            {
                "ref": "walkthrough",
                "kind": "exposition",
                "source_quality": "human",
                "source_id": source_id,
                "description": "Named human explained the claim and its boundary.",
            }
        ],
    )


def test_exposition_kind_exists():
    item = Evidence(ref="x", kind=EvidenceKind.EXPOSITION, source_id="jane-doe")
    assert item.kind.value == "exposition"


def test_exposition_resolves_against_person_entry(tmp_path):
    (tmp_path / "identities.json").write_text(
        json.dumps({"identities": [{"id": "jane-doe", "name": "Jane Doe", "kind": "person"}]}),
        encoding="utf-8",
    )
    path = _write(tmp_path, _bundle_json([_exposition_claim_json("jane-doe")]))
    claims = load_claims(path)
    assert claims[0].evidence[0].kind == EvidenceKind.EXPOSITION


def test_exposition_without_registry_is_a_strict_error(tmp_path):
    path = _write(tmp_path, _bundle_json([_exposition_claim_json("jane-doe")]))
    with pytest.raises(BundleValidationError) as excinfo:
        load_claims(path)
    assert "registry" in str(excinfo.value)


@pytest.mark.parametrize("kind", ["tool", "model", "team"])
def test_exposition_rejects_non_person_registry_entries(tmp_path, kind):
    registry = IdentityRegistry.from_dict(
        {"identities": [{"id": "helper", "name": "Helper", "kind": kind}]}
    )
    path = _write(tmp_path, _bundle_json([_exposition_claim_json("helper")]))
    with pytest.raises(BundleValidationError) as excinfo:
        load_claims(path, identity_registry=registry)
    assert "not 'person'" in str(excinfo.value)


def test_exposition_rejects_unknown_id_and_empty_source(tmp_path):
    registry = IdentityRegistry.from_dict(
        {"identities": [{"id": "jane-doe", "name": "Jane Doe", "kind": "person"}]}
    )
    unknown = _write(tmp_path, _bundle_json([_exposition_claim_json("nobody")]), "unknown.json")
    with pytest.raises(BundleValidationError):
        load_claims(unknown, identity_registry=registry)
    empty = _write(tmp_path, _bundle_json([_exposition_claim_json("")]), "empty.json")
    with pytest.raises(BundleValidationError):
        load_claims(empty, identity_registry=registry)


def test_registry_shapes_and_duplicate_ids():
    from_list = IdentityRegistry.from_dict([{"id": "a", "kind": "person"}])
    assert from_list.resolve("a") is not None
    from_map = IdentityRegistry.from_dict({"b": {"kind": "model"}})
    assert from_map.resolve("b").kind.value == "model"
    with pytest.raises(BundleValidationError):
        IdentityRegistry.from_dict([{"id": "a"}, {"id": "a"}])
