"""Spec 004 Phase P0 - vocabulary and model (R1.1-R1.4, R3.1/R3.2).

Fixtures under tests/fixtures/stage/: one strong claim (two
independent observed sources, boundary, falsifier, author status
`supported`) authored identically at each of the five stages, an
exposition bundle, and a project-local identity registry carrying
two persons, a tool, a model, and a team alias.

The cap table under test is the ratified R1.3 table (OD-T3):

| stage     | reported status of a `supported` claim | verdict ceiling |
|-----------|----------------------------------------|-----------------|
| created   | draft                                  | unjudged        |
| checked   | partially_supported                    | challenge       |
| explained | supported (qualified)                  | challenge       |
| accepted  | supported                              | accept          |
| digested  | supported (+ superseded terminal)      | accept          |
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aee import (
    AEEEngine,
    AssessmentPolicy,
    BundleValidationError,
    Claim,
    ClaimStage,
    ClaimStatus,
    IdentityRegistry,
    Verdict,
)
from aee.cli import main
from aee.extract import load_claims, migrate_bundle
from aee.model import Evidence, EvidenceKind

FIXTURES = Path(__file__).parent / "fixtures" / "stage"
STAGES = ["created", "checked", "explained", "accepted", "digested"]


def _assess(stage: str, *, policy: bool = False):
    claims = load_claims(FIXTURES / f"bundle-stage-{stage}.json")
    engine = AEEEngine(policy=AssessmentPolicy() if policy else None)
    return engine.assess(claims, project="stage-fixtures", phase="p0")


# --- R1.1: stage field, strict loading, serialisation -------------------------


@pytest.mark.parametrize("stage", STAGES)
def test_stage_fixture_loads_strict_and_round_trips(stage: str) -> None:
    claims = load_claims(FIXTURES / f"bundle-stage-{stage}.json")
    assert claims[0].stage is ClaimStage(stage)
    assert claims[0].stage_defaulted is False
    value = claims[0].to_dict()
    assert value["stage"] == stage
    assert value["stage_events"] == claims[0].to_dict()["stage_events"]
    reloaded = Claim.from_dict(value)
    assert reloaded.stage is ClaimStage(stage)
    assert [e.kind.value for e in reloaded.stage_events] == [
        e.kind.value for e in claims[0].stage_events
    ]


def test_unknown_stage_value_is_a_loud_error() -> None:
    row = {"id": "X", "text": "t", "stage": "settled"}
    with pytest.raises(BundleValidationError) as excinfo:
        Claim.from_dict(row)
    message = str(excinfo.value)
    assert "'stage'" in message and "created" in message and "digested" in message


def test_missing_stage_strict_names_the_field() -> None:
    with pytest.raises(BundleValidationError) as excinfo:
        Claim.from_dict({"id": "X", "text": "t"})
    message = str(excinfo.value)
    assert "field 'stage' is required but missing" in message
    assert "aee migrate" in message  # the migration path is named


def test_missing_stage_lenient_defaults_created_and_records_it(tmp_path: Path) -> None:
    bundle = tmp_path / "old.json"
    bundle.write_text(json.dumps({"claims": [{"id": "OLD-1", "text": "t"}]}))
    claims = load_claims(bundle, strict=False)
    assert claims[0].stage is ClaimStage.CREATED
    assert claims[0].stage_defaulted is True
    assessment = AEEEngine().assess(claims)
    assert assessment.metadata["stage_defaulted_claims"] == ["OLD-1"]
    assert "Stage default:" in assessment.summary


def test_migrate_backfills_stage_and_reports_every_claim() -> None:
    raw = {
        "claims": [
            {"id": "M-1", "text": "one"},
            {"id": "M-2", "text": "two", "stage": "checked"},
        ]
    }
    migrated, report = migrate_bundle(raw)
    assert migrated["claims"][0]["stage"] == "created"
    assert migrated["claims"][1]["stage"] == "checked"  # present stage untouched
    joined = "\n".join(report)
    assert joined.count("stage missing -> backfilled 'created'") == 1
    assert "M-1" in joined
    # The migrated bundle strict-loads (migrate's own guarantee).
    assert Claim.from_dict(migrated["claims"][0]).stage is ClaimStage.CREATED


def test_migrate_refuses_unknown_stage_value() -> None:
    with pytest.raises(BundleValidationError):
        migrate_bundle({"claims": [{"id": "M-1", "text": "t", "stage": "settled"}]})


# --- R1.2: stage events are the only way stage moves --------------------------


def test_advance_stage_records_the_event() -> None:
    claim = Claim(id="E-1", text="t")
    event = claim.advance_stage(
        ClaimStage.CHECKED, author="aee", date="2026-10-12", basis="assessment run recorded"
    )
    assert claim.stage is ClaimStage.CHECKED
    assert claim.stage_events == [event]
    assert event.kind.value == "checked" and event.author == "aee"
    assert claim.to_dict()["stage_events"][0]["basis"] == "assessment run recorded"


def test_advance_stage_is_forward_only_and_needs_a_basis() -> None:
    claim = Claim(id="E-2", text="t", stage=ClaimStage.EXPLAINED)
    with pytest.raises(ValueError, match="forward"):
        claim.advance_stage(ClaimStage.CHECKED, basis="rewind")
    with pytest.raises(ValueError, match="basis"):
        claim.advance_stage(ClaimStage.ACCEPTED, basis="  ")


def test_stage_event_without_basis_fails_strict_load() -> None:
    row = {
        "id": "E-3",
        "text": "t",
        "stage": "checked",
        "stage_events": [{"kind": "checked", "author": "aee"}],
    }
    with pytest.raises(BundleValidationError, match="'basis'"):
        Claim.from_dict(row)


def test_assessment_never_advances_stage_by_score() -> None:
    claims = load_claims(FIXTURES / "bundle-stage-created.json")
    assert claims[0].confidence is None
    assessment = AEEEngine().assess(claims)
    assert assessment.scores["STG-1"].propagated_score >= 0.70  # it scored well
    assert claims[0].stage is ClaimStage.CREATED  # and did not move


# --- R1.3/R1.4: the cap table, exactly -----------------------------------------

# stage -> (reported status, policy verdict, outcome without policy)
CAP_TABLE = {
    "created": ("draft", "unjudged", "iterate"),
    "checked": ("partially_supported", "challenge", "iterate"),
    "explained": ("supported", "challenge", "pass"),
    "accepted": ("supported", "accept", "pass"),
    "digested": ("supported", "accept", "pass"),
}


@pytest.mark.parametrize("stage", STAGES)
def test_cap_table_reported_status_verdict_and_outcome(stage: str) -> None:
    expected_status, expected_verdict, expected_outcome = CAP_TABLE[stage]
    assessment = _assess(stage, policy=True)
    value = assessment.to_dict()
    assert value["reported_statuses"]["STG-1"] == expected_status
    assert assessment.verdicts["STG-1"].verdict is Verdict(expected_verdict)
    # With a policy attached, an explained claim's challenge-ceiling
    # verdict demotes its outcome to iterate; without a policy the
    # R1.4 rule alone decides (checked in the next test).
    if stage == "explained":
        assert assessment.outcome == "iterate"
    else:
        assert assessment.outcome == expected_outcome
    # The author-declared status is never rewritten by the cap.
    assert value["claims"][0]["status"] == "supported"
    assert value["claims"][0]["stage"] == stage


@pytest.mark.parametrize("stage", STAGES)
def test_cap_table_outcome_without_policy(stage: str) -> None:
    _status, _verdict, expected_outcome = CAP_TABLE[stage]
    assert _assess(stage).outcome == expected_outcome


@pytest.mark.parametrize("stage", ["created", "checked", "explained"])
def test_capped_claim_carries_note_failure_and_cap_record(stage: str) -> None:
    assessment = _assess(stage)
    caps = [f for f in assessment.failures if getattr(f, "category", "") == "stage_cap"]
    assert caps, "expected a stage_cap failure mode"
    assert "Spec 004 R1.3" in caps[0].breakpoint
    assert any("Stage cap (Spec 004 R1.3)" in note for note in assessment.scores["STG-1"].notes)
    records = assessment.to_dict()["stage_caps"]
    assert len(records) == 1
    assert records[0]["claim_id"] == "STG-1"
    assert records[0]["lifting_event"]  # the event that would lift it is named


@pytest.mark.parametrize("stage", ["accepted", "digested"])
def test_uncapped_stages_carry_no_cap_record(stage: str) -> None:
    assessment = _assess(stage)
    assert assessment.to_dict()["stage_caps"] == []
    assert not any(getattr(f, "category", "") == "stage_cap" for f in assessment.failures)


def test_explained_supported_is_qualified_not_unqualified() -> None:
    records = _assess("explained").to_dict()["stage_caps"]
    assert records[0]["qualified_supported"] is True
    assert records[0]["verdict_ceiling"] == "challenge"


def test_digested_superseded_is_terminal_and_reportable() -> None:
    claims = load_claims(FIXTURES / "bundle-stage-digested-superseded.json")
    assessment = AEEEngine().assess(claims)
    assert assessment.to_dict()["reported_statuses"]["STG-1"] == "superseded"


def test_superseded_below_digested_is_capped() -> None:
    claims = load_claims(FIXTURES / "bundle-stage-accepted.json")
    claims[0].status = ClaimStatus.SUPERSEDED
    assessment = AEEEngine().assess(claims)
    assert assessment.to_dict()["reported_statuses"]["STG-1"] == "partially_supported"


def test_cap_never_changes_the_score() -> None:
    checked = _assess("checked").scores["STG-1"]
    accepted = _assess("accepted").scores["STG-1"]
    assert checked.propagated_score == accepted.propagated_score
    assert checked.direct_score == accepted.direct_score


def test_created_claim_verdict_reason_names_the_cap() -> None:
    verdict = _assess("created", policy=True).verdicts["STG-1"]
    assert verdict.verdict is Verdict.UNJUDGED
    assert any("stage cap" in reason for reason in verdict.reasons)


# --- R3.1/R3.2: exposition and the named-human registry ------------------------


def _exposition_bundle(tmp_path: Path, source_id: str, *, adjacent_registry: bool = False) -> Path:
    if adjacent_registry:
        (tmp_path / "identities.json").write_text(
            (FIXTURES / "identities.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
    row = {
        "id": "EXP-1",
        "text": "The widget holds",
        "stage": "explained",
        "evidence": [
            {
                "ref": "notes/explained.md",
                "kind": "exposition",
                "source_quality": "human",
                "source_id": source_id,
            }
        ],
    }
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps({"claims": [row]}), encoding="utf-8")
    return bundle


def test_exposition_kind_exists_and_scores() -> None:
    assert EvidenceKind.EXPOSITION.value == "exposition"
    claims = load_claims(FIXTURES / "bundle-exposition-ok.json")
    item = claims[0].evidence[-1]
    assert item.kind is EvidenceKind.EXPOSITION
    assert item.source_id == "ada-lovelace"


def test_exposition_loads_with_bundle_adjacent_registry() -> None:
    # The fixture directory carries identities.json beside the bundle.
    claims = load_claims(FIXTURES / "bundle-exposition-ok.json")
    assert claims[0].stage is ClaimStage.EXPLAINED


def test_exposition_loads_with_explicit_registry(tmp_path: Path) -> None:
    bundle = _exposition_bundle(tmp_path, "grace-hopper")
    registry = IdentityRegistry.from_path(str(FIXTURES / "identities.json"))
    claims = load_claims(bundle, identity_registry=registry)
    assert claims[0].evidence[0].kind is EvidenceKind.EXPOSITION


def test_exposition_cli_identity_registry_flag(tmp_path: Path) -> None:
    bundle = _exposition_bundle(tmp_path, "ada-lovelace")
    out = tmp_path / "assessment.json"
    code = main(
        [
            "assess",
            "--input",
            str(bundle),
            "--identity-registry",
            str(FIXTURES / "identities.json"),
            "--no-ledger",
            "--output",
            str(out),
        ]
    )
    assert code in (0, 1)
    assert json.loads(out.read_text())["claims"][0]["evidence"][0]["kind"] == "exposition"


def test_exposition_missing_registry_is_a_load_error(tmp_path: Path) -> None:
    bundle = _exposition_bundle(tmp_path, "ada-lovelace")  # no adjacent registry in tmp_path
    with pytest.raises(BundleValidationError, match="no identity registry"):
        load_claims(bundle)


def test_exposition_unknown_id_is_a_load_error(tmp_path: Path) -> None:
    bundle = _exposition_bundle(tmp_path, "nobody-known", adjacent_registry=True)
    with pytest.raises(BundleValidationError, match="does not resolve"):
        load_claims(bundle)


@pytest.mark.parametrize(
    "source_id,kind",
    [("load-runner", "tool"), ("qwen3-8b", "model"), ("widget-team", "team")],
)
def test_exposition_non_person_entries_are_rejected(
    tmp_path: Path, source_id: str, kind: str
) -> None:
    bundle = _exposition_bundle(tmp_path, source_id, adjacent_registry=True)
    with pytest.raises(BundleValidationError) as excinfo:
        load_claims(bundle)
    message = str(excinfo.value)
    assert f"'{kind}'" in message and "not 'person'" in message


def test_exposition_empty_source_id_is_a_load_error(tmp_path: Path) -> None:
    bundle = _exposition_bundle(tmp_path, "", adjacent_registry=True)
    with pytest.raises(BundleValidationError, match="must not be empty"):
        load_claims(bundle)


def test_exposition_lenient_load_is_the_compat_path(tmp_path: Path) -> None:
    bundle = _exposition_bundle(tmp_path, "ada-lovelace")
    claims = load_claims(bundle, strict=False)  # no registry needed leniently
    assert claims[0].evidence[0].kind is EvidenceKind.EXPOSITION


def test_registry_rejects_duplicate_ids_and_bad_kinds() -> None:
    with pytest.raises(BundleValidationError, match="duplicate identity id"):
        IdentityRegistry.from_dict({"identities": [{"id": "a"}, {"id": "a"}]})
    with pytest.raises(BundleValidationError, match="'kind'"):
        IdentityRegistry.from_dict({"identities": [{"id": "a", "kind": "robot"}]})


def test_programmatic_exposition_evidence_constructible() -> None:
    item = Evidence(ref="notes/x.md", kind=EvidenceKind.EXPOSITION, source_id="ada-lovelace")
    assert item.to_dict()["kind"] == "exposition"
