"""Spec 004 P0 completion tests (coordinator addendum).

Covers the P0 requirements that sit on top of the stage vocabulary
itself: digestion tracking per claim (R3.3), the
verified-but-unexplained risk state, the `not_understood`
residual-unknowns statement (R5.2 P0 form), summary stage counts and
lane-2 lag visibility, the policy layer's programmatic verdict
ceiling, lenient identity-resolution failure modes (R3.2), stage
derivation from recorded events (R1.2), the registry's explicit-kind
shape rule (OD-T4), and assessment content-digest stability.

INTEGRATION PORT NOTE (2026-10-12, integration/004-stack): this file
is the orphaned branch impl/004-p0-vocabulary @ 5fa2fdf's test module,
ported when the Spec 004 stack was integrated with main. Fourteen of
its nineteen tests pass verbatim against the integrated tree. Five
asserted P0-era SURFACE forms that the stack's later phases
deliberately superseded; those five are adapted in place, each with a
comment naming the superseding surface:

- summary stage counts / verified-unexplained count: the P0
  ``Stages: ...`` / ``Verified but unexplained: N`` sentences are
  superseded by P3's lane pair (``Lane 2 (human acceptance): stages
  by effective stage: ...`` + the lane-2 lag clause);
- metadata ``stage_defaults`` / ``stage_counts`` keys: superseded by
  P0-stack's ``metadata.stage_defaulted_claims`` and P3's
  ``lanes.lane_2.stage_counts``;
- `not_understood` entry wording: superseded by P1/P2's cap-note and
  open-challenges phrasings (same sources, richer text).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import aee
from aee.cli import main
from aee.engine import AEEEngine
from aee.extract import load_claims
from aee.ledger import assessment_content_digest
from aee.model import (
    BundleValidationError,
    Claim,
    ClaimKind,
    ClaimStage,
    ClaimStatus,
    Evidence,
    EvidenceKind,
    IdentityRegistry,
    Severity,
    SourceQuality,
)
from aee.policy import verdict_ceiling
from aee.scoring import ScoringEngine
from aee.stage import VERDICT_CEILING

FIXTURES = Path(__file__).parent / "fixtures" / "stage"


def _strong_claim(
    claim_id: str, stage: str, *, exposition_by: str | None = None
) -> Claim:
    evidence = [
        Evidence(
            ref="reports/t.json",
            kind=EvidenceKind.OBSERVED,
            source_quality=SourceQuality.TEST,
            source_id="lab-1",
            independent_of=["lab-2"],
        ),
        Evidence(
            ref="reports/u.json",
            kind=EvidenceKind.OBSERVED,
            source_quality=SourceQuality.PRIMARY,
            source_id="lab-2",
        ),
    ]
    if exposition_by is not None:
        evidence.append(
            Evidence(
                ref="notes/explanation.md",
                kind=EvidenceKind.EXPOSITION,
                source_quality=SourceQuality.HUMAN,
                source_id=exposition_by,
                description="A named human explains the claim and its boundary.",
            )
        )
    return Claim(
        id=claim_id,
        text="The widget holds for 10 s under load profile L",
        kind=ClaimKind.REQUIREMENT,
        status=ClaimStatus.SUPPORTED,
        stage=ClaimStage(stage),
        boundary=["load profile L"],
        falsification_tests=["drop the widget and observe failure"],
        evidence=evidence,
    )


def _failures(assessment, category: str):  # type: ignore[no-untyped-def]
    return [
        failure
        for claim in assessment.claims
        for failure in claim.failures
        if failure.category == category
    ]


# --- Policy layer exposes the ceiling programmatically -----------------------


@pytest.mark.parametrize(
    ("stage", "ceiling"),
    [
        ("created", "unjudged"),
        ("checked", "challenge"),
        ("explained", "challenge"),
        ("accepted", "accept"),
        ("digested", "accept"),
    ],
)
def test_verdict_ceiling_function_matches_r1_3_table(stage: str, ceiling: str) -> None:
    assert verdict_ceiling(ClaimStage(stage)) == ceiling
    # The policy accessor reads the one R1.3 table, never a copy.
    assert verdict_ceiling(ClaimStage(stage)) == VERDICT_CEILING[ClaimStage(stage)]
    assert aee.verdict_ceiling is verdict_ceiling


# --- Digestion tracking + verified_unexplained (R3.3) ------------------------


def test_verified_unexplained_flagged_at_checked_without_exposition() -> None:
    assessment = AEEEngine().assess([_strong_claim("C-1", "checked")])
    flags = _failures(assessment, "verified_unexplained")
    assert len(flags) == 1
    assert flags[0].severity is Severity.MEDIUM
    assert flags[0].claim_id == "C-1"
    entry = assessment.to_dict()["digestion"]["C-1"]
    assert entry == {"stage": "checked", "exposition_present": False, "explainers": []}


def test_verified_unexplained_absent_when_exposition_present() -> None:
    claim = _strong_claim("C-1", "explained", exposition_by="ada-lovelace")
    assessment = AEEEngine().assess([claim])
    assert _failures(assessment, "verified_unexplained") == []
    entry = assessment.to_dict()["digestion"]["C-1"]
    assert entry["exposition_present"] is True
    assert entry["explainers"] == ["ada-lovelace"]
    assert entry["stage"] == "explained"


def test_verified_unexplained_not_flagged_at_created() -> None:
    assessment = AEEEngine().assess([_strong_claim("C-1", "created")])
    assert _failures(assessment, "verified_unexplained") == []


def test_verified_unexplained_has_no_score_effect_and_does_not_route_outcome() -> None:
    claim = _strong_claim("C-1", "accepted")
    direct = ScoringEngine().score([claim])["C-1"].propagated_score
    assessment = AEEEngine().assess([claim])
    assert _failures(assessment, "verified_unexplained") != []
    assert assessment.scores["C-1"].propagated_score == direct
    # The flag is a risk state, not a correctness failure: a clean,
    # strongly-evidenced accepted claim still passes, with the lag
    # visible in the summary.
    assert assessment.outcome == "pass"
    # Adapted (see port note): the P0 summary sentence was superseded
    # by P3's lane-2 lag clause, which states the same count.
    assert "1 verified but unexplained" in assessment.summary


def test_gate_accepts_passing_assessment_with_verified_unexplained(
    tmp_path: Path,
) -> None:
    assessment = AEEEngine().assess([_strong_claim("C-1", "accepted")])
    assert assessment.outcome == "pass"
    output = tmp_path / "assessment.json"
    output.write_text(json.dumps(assessment.to_dict()), encoding="utf-8")
    assert main(["gate", "--input", str(output)]) == 0


# --- not_understood (R5.2, P0 form) ------------------------------------------


def test_not_understood_collects_caps_unexplained_and_open_failures() -> None:
    capped = _strong_claim("CAP-1", "created")
    unexplained = _strong_claim("CHK-1", "checked")
    open_claim = Claim(
        id="OPEN-1",
        text="An unsupported assertion with no evidence at all",
        kind=ClaimKind.REQUIREMENT,
        status=ClaimStatus.DRAFT,
        stage=ClaimStage.CREATED,
    )
    assessment = AEEEngine().assess([capped, unexplained, open_claim])
    entries = assessment.to_dict()["not_understood"]
    # Adapted (see port note): P1/P2's not_understood entries carry
    # the same three sources in their evolved phrasings — the cap
    # record's own note ("Stage cap (Spec 004 R1.3): ..."), the
    # verified-but-unexplained entry, and the open-challenges entry.
    assert any("Stage cap" in e and "CAP-1" in e for e in entries)
    assert any("verified but unexplained" in e and "CHK-1" in e for e in entries)
    assert any("open challenges" in e and "OPEN-1" in e for e in entries)
    assert entries == assessment.not_understood


def test_not_understood_records_stage_default_and_metadata_names_it(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "old.json"
    bundle.write_text(json.dumps({"claims": [{"id": "OLD-1", "text": "t"}]}))
    claims = load_claims(bundle, strict=False)
    assessment = AEEEngine().assess(claims)
    # Adapted (see port note): the orphan's `stage_defaults` /
    # metadata `stage_counts` keys were superseded by the stack's
    # `stage_defaulted_claims` metadata key and the P3 lane pair's
    # stage counts; the not_understood notice is unchanged in
    # substance ("defaulted to 'created' on load").
    assert assessment.metadata["stage_defaulted_claims"] == ["OLD-1"]
    assert assessment.lanes["lane_2"]["stage_counts"]["created"] == 1
    assert assessment.to_dict()["digestion"]["OLD-1"]["stage"] == "created"
    assert any(
        "defaulted to 'created'" in e and "OLD-1" in e
        for e in assessment.not_understood
    )


def test_summary_counts_claims_by_stage() -> None:
    claims = [
        _strong_claim("S-1", "created"),
        _strong_claim("S-2", "checked"),
        _strong_claim("S-3", "accepted", exposition_by="ada-lovelace"),
    ]
    assessment = AEEEngine().assess(claims)
    # Adapted (see port note): the P0 "Stages: ..." sentence was
    # superseded by P3's lane-2 line, which states counts by
    # EFFECTIVE stage (nonzero stages only) wherever the outcome is
    # stated. S-3's exposition lifts nothing here; all three claims
    # report at their stored stages.
    assert (
        "Lane 2 (human acceptance): stages by effective stage: "
        "created 1, checked 1, accepted 1." in assessment.summary
    )
    assert assessment.lanes["lane_2"]["stage_counts"] == {
        "created": 1,
        "checked": 1,
        "explained": 0,
        "accepted": 1,
        "digested": 0,
    }


def test_pass_with_stage_cap_shows_cap_and_lag() -> None:
    claims = load_claims(FIXTURES / "bundle-stage-explained.json")
    assessment = AEEEngine().assess(claims, project="stage-fixtures", phase="p0")
    assert assessment.outcome == "pass"
    assert assessment.stage_caps  # qualified-supported cap binds
    assert "Stage caps applied:" in assessment.summary
    # Adapted (see port note): stage counts ride the P3 lane-2 line.
    assert "stages by effective stage: explained 1" in assessment.summary
    assert any("Stage cap" in e for e in assessment.not_understood)


# --- Lenient identity resolution (R3.2) ---------------------------------------


def _exposition_bundle(tmp_path: Path, source_id: str) -> Path:
    bundle = tmp_path / "bundle.json"
    bundle.write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "EXP-1",
                        "text": "The widget holds",
                        "stage": "explained",
                        "evidence": [
                            {
                                "ref": "notes/explanation.md",
                                "kind": "exposition",
                                "source_id": source_id,
                            }
                        ],
                    }
                ]
            }
        )
    )
    return bundle


def test_lenient_unresolved_exposition_becomes_identity_failure(tmp_path: Path) -> None:
    bundle = _exposition_bundle(tmp_path, "ghost")
    claims = load_claims(bundle, strict=False)  # no registry anywhere
    claim = claims[0]
    assert claim.unresolved_exposition == ["ghost"]
    assert any(f.category == "identity_resolution" for f in claim.failures)
    assessment = AEEEngine().assess(claims)
    # The failure survives the stress tester's wholesale replacement.
    assert _failures(assessment, "identity_resolution") != []
    # And the unresolved item confers no explanation credit.
    entry = assessment.to_dict()["digestion"]["EXP-1"]
    assert entry["exposition_present"] is False
    assert entry["explainers"] == []


def test_lenient_tool_entry_never_resolves_but_person_does(tmp_path: Path) -> None:
    bundle = _exposition_bundle(tmp_path, "helper")
    tool_registry = IdentityRegistry.from_dict(
        {"identities": [{"id": "helper", "kind": "tool"}]}
    )
    claims = load_claims(bundle, strict=False, identity_registry=tool_registry)
    assert claims[0].unresolved_exposition == ["helper"]
    person_registry = IdentityRegistry.from_dict(
        {"identities": [{"id": "helper", "kind": "person"}]}
    )
    claims = load_claims(bundle, strict=False, identity_registry=person_registry)
    assert claims[0].unresolved_exposition == []
    assessment = AEEEngine().assess(claims)
    assert assessment.to_dict()["digestion"]["EXP-1"]["explainers"] == ["helper"]


# --- Stage derivation from recorded events (R1.2) -----------------------------


def test_lenient_stage_derives_from_latest_event(tmp_path: Path) -> None:
    bundle = tmp_path / "events.json"
    bundle.write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "EV-1",
                        "text": "t",
                        "stage_events": [
                            {"kind": "checked", "basis": "assessment run"},
                            {"kind": "explained", "basis": "exposition recorded"},
                        ],
                    }
                ]
            }
        )
    )
    claims = load_claims(bundle, strict=False)
    assert claims[0].stage is ClaimStage.EXPLAINED
    assert claims[0].stage_derived is True
    assert claims[0].stage_defaulted is False
    assessment = AEEEngine().assess(claims)
    assert any(
        "derived from its latest recorded stage event" in e
        for e in assessment.not_understood
    )


# --- Registry shape rules (OD-T4) ---------------------------------------------


def test_registry_entry_must_declare_its_kind() -> None:
    with pytest.raises(BundleValidationError, match="'kind' is required"):
        IdentityRegistry.from_dict([{"id": "a"}])
    with pytest.raises(BundleValidationError, match="duplicate identity id"):
        # Duplicate ids are reported before per-entry shape problems.
        IdentityRegistry.from_dict([{"id": "a"}, {"id": "a"}])


# --- Content-digest stability ---------------------------------------------------


def test_assessment_content_digest_is_stable_across_runs() -> None:
    first = AEEEngine().assess(load_claims(FIXTURES / "bundle-stage-accepted.json"))
    second = AEEEngine().assess(load_claims(FIXTURES / "bundle-stage-accepted.json"))
    assert assessment_content_digest(first.to_dict()) == assessment_content_digest(
        second.to_dict()
    )
