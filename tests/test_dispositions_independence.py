"""Spec 002 Phase 3 - FR-5 challenge dispositions (T501-T505) and
FR-6 independence on-ramps (T601-T603, T605).

FR-5: dispositions are bundle-persisted human judgments; a regenerated
challenge matching a stored disposition (key: claim + the failure's
``category``) reports resolved with the disposition inspectable.

FR-6: scoring consumes ``Evidence.independent_of``; the independence
basis is named in score notes; claims sharing supporting evidence
without declarations draw an ``independence_unmodeled`` warning.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aee import (
    AEEEngine,
    BundleValidationError,
    Claim,
    Disposition,
    DispositionKind,
    Evidence,
    EvidenceKind,
    ScoringEngine,
    SourceQuality,
)
from aee.challenge import StressTester
from aee.extract import load_claims
from aee.schemas import assessment_schema_path

IRREDUCIBLE_TEXT = "The valve opens and the gauge reads line pressure"


def _dispositioned_claim(**overrides: object) -> Claim:
    base: dict[str, object] = {
        "id": "CLM-D1",
        "text": IRREDUCIBLE_TEXT,
        "boundary": ["bench rig"],
        "falsification_tests": ["Observe the valve shut while pressure is applied"],
        "evidence": [
            Evidence(
                ref="bench-run-1.log",
                source_id="rig-1",
                kind=EvidenceKind.OBSERVED,
                source_quality=SourceQuality.TEST,
            ),
            Evidence(
                ref="bench-run-2.log",
                source_id="rig-2",
                kind=EvidenceKind.OBSERVED,
                source_quality=SourceQuality.TEST,
            ),
        ],
        "dispositions": [
            Disposition(
                challenge_category="coverage_gap",
                kind=DispositionKind.ACCEPTED_ATOMIC,
                reason="One mechanism, one observable: opening the valve is what "
                "pressurizes the gauge line; not two propositions.",
                author="reviewer@example.com",
                date="2026-10-12",
            )
        ],
    }
    base.update(overrides)
    return Claim(**base)  # type: ignore[arg-type]


# --- T501: model + strict loading ---------------------------------------------


def test_disposition_round_trip() -> None:
    claim = _dispositioned_claim()
    data = claim.to_dict()
    assert data["dispositions"][0]["kind"] == "accepted-atomic"
    assert data["dispositions"][0]["reason"].startswith("One mechanism")
    loaded = Claim.from_dict(data)
    assert loaded.dispositions[0].kind is DispositionKind.ACCEPTED_ATOMIC
    assert loaded.dispositions[0].author == "reviewer@example.com"
    assert loaded.disposition_for("coverage_gap") is loaded.dispositions[0]
    assert loaded.disposition_for("contradiction") is None


@pytest.mark.parametrize("bad_reason", ["", "   ", None])
def test_disposition_without_reason_fails_strict_load(bad_reason: object) -> None:
    row: dict[str, object] = {
        "id": "CLM-BAD",
        "text": "A claim",
        "dispositions": [
            {"challenge_category": "coverage_gap", "kind": "waived", "reason": bad_reason}
        ],
    }
    if bad_reason is None:
        del row["dispositions"][0]["reason"]  # type: ignore[index]
    with pytest.raises(BundleValidationError) as excinfo:
        Claim.from_dict(row)
    message = str(excinfo.value)
    assert "CLM-BAD" in message and "'reason'" in message


def test_disposition_bad_kind_lists_valid_values() -> None:
    with pytest.raises(BundleValidationError) as excinfo:
        Claim.from_dict(
            {
                "id": "CLM-BAD",
                "text": "A claim",
                "dispositions": [
                    {"challenge_category": "coverage_gap", "kind": "ignored", "reason": "r"}
                ],
            }
        )
    message = str(excinfo.value)
    assert "split" in message and "accepted-atomic" in message and "waived" in message


def test_disposition_unknown_field_fails_strict_load() -> None:
    with pytest.raises(BundleValidationError, match="unknown field 'verdict'"):
        Claim.from_dict(
            {
                "id": "CLM-BAD",
                "text": "A claim",
                "dispositions": [
                    {
                        "challenge_category": "coverage_gap",
                        "kind": "waived",
                        "reason": "r",
                        "verdict": "ok",
                    }
                ],
            }
        )


def test_reasonless_disposition_bundle_fails_load_claims(tmp_path: Path) -> None:
    path = tmp_path / "bundle.json"
    path.write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "CLM-BAD",
                        "text": "A claim",
                        "dispositions": [
                            {"challenge_category": "coverage_gap", "kind": "waived", "reason": ""}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(BundleValidationError):
        load_claims(path)


def test_programmatic_empty_reason_disposition_rejected() -> None:
    with pytest.raises(ValueError, match="reason must not be empty"):
        Disposition(challenge_category="coverage_gap", kind=DispositionKind.WAIVED, reason=" ")


# --- T502/T505: regeneration honors dispositions -------------------------------


def test_dispositioned_challenge_resolves_with_reason_visible() -> None:
    claim = _dispositioned_claim()
    failures = StressTester().run([claim])
    assert len(failures) == 1
    failure = failures[0]
    # History is not erased: the challenge was raised, and is answered.
    assert failure.challenge == "Irreducibility challenge"
    assert failure.resolved is True
    assert failure.disposition is not None
    assert failure.disposition.reason.startswith("One mechanism")
    assert failure.disposition.author == "reviewer@example.com"
    assert claim.unresolved_failures == []


def test_dispositioned_assessment_outcome_and_output() -> None:
    assessment = AEEEngine().assess([_dispositioned_claim()])
    assert assessment.outcome == "pass"
    data = assessment.to_dict()
    failure = data["claims"][0]["failures"][0]
    assert failure["resolved"] is True
    assert failure["disposition"]["kind"] == "accepted-atomic"
    assert "One mechanism" in failure["disposition"]["reason"]
    # T503 coverage is in the summary.
    assert "1 challenge(s) raised, 1 dispositioned, 0 open" in assessment.summary


def test_removing_disposition_reopens_challenge() -> None:
    claim = _dispositioned_claim(dispositions=[])
    failures = StressTester().run([claim])
    assert len(failures) == 1
    assert failures[0].resolved is False
    assert failures[0].disposition is None
    assessment = AEEEngine().assess([claim])
    assert assessment.outcome == "iterate"
    assert "Dispositions:" not in assessment.summary


def test_disposition_persists_across_runs_via_bundle(tmp_path: Path) -> None:
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps({"claims": [_dispositioned_claim().to_dict()]}), encoding="utf-8")
    for _ in range(2):  # two independent loads + runs: same verdict
        claims = load_claims(path)
        failures = StressTester().run(claims)
        assert failures[0].resolved is True


def test_disposition_for_other_category_does_not_resolve() -> None:
    claim = _dispositioned_claim(
        dispositions=[
            Disposition(
                challenge_category="contradiction",
                kind=DispositionKind.WAIVED,
                reason="Answered elsewhere.",
            )
        ]
    )
    failures = StressTester().run([claim])
    assert failures[0].resolved is False


# --- T502/FR-5.3: split successors --------------------------------------------


def test_split_disposition_with_existing_successors_is_quiet() -> None:
    claim = _dispositioned_claim(
        dispositions=[
            Disposition(
                challenge_category="coverage_gap",
                kind=DispositionKind.SPLIT,
                reason="Split into the valve claim and the gauge claim.",
                successors=["CLM-D2"],
            )
        ]
    )
    successor = Claim(id="CLM-D2", text="The gauge reads line pressure", boundary=["rig"])
    failures = StressTester().run([claim, successor])
    assert all(f.claim_id != "CLM-D1" or f.resolved for f in failures)
    assert not any(f.challenge == "Disposition successor challenge" for f in failures)


def test_split_disposition_with_missing_successor_warns() -> None:
    claim = _dispositioned_claim(
        dispositions=[
            Disposition(
                challenge_category="coverage_gap",
                kind=DispositionKind.SPLIT,
                reason="Split as planned.",
                successors=["CLM-GONE"],
            )
        ]
    )
    failures = StressTester().run([claim])
    warnings = [f for f in failures if f.challenge == "Disposition successor challenge"]
    assert len(warnings) == 1
    assert warnings[0].resolved is False
    assert "CLM-GONE" in warnings[0].breakpoint
    # The irreducibility challenge itself is still resolved by the split.
    assert any(f.resolved and f.challenge == "Irreducibility challenge" for f in failures)


def test_split_disposition_naming_no_successors_warns() -> None:
    claim = _dispositioned_claim(
        dispositions=[
            Disposition(
                challenge_category="coverage_gap",
                kind=DispositionKind.SPLIT,
                reason="Split as planned.",
            )
        ]
    )
    failures = StressTester().run([claim])
    warnings = [f for f in failures if f.challenge == "Disposition successor challenge"]
    assert len(warnings) == 1
    assert "names no successor claims" in warnings[0].breakpoint


# --- T503: coverage accounting ---------------------------------------------------


def test_coverage_counts_mixed_bundle() -> None:
    open_claim = Claim(
        id="CLM-OPEN",
        text=IRREDUCIBLE_TEXT,
        boundary=["bench rig"],
        falsification_tests=["Observe the valve shut while pressure is applied"],
    )
    assessment = AEEEngine().assess([_dispositioned_claim(), open_claim])
    assert "2 challenge(s) raised, 1 dispositioned, 1 open" in assessment.summary


# --- T504: _COMPOUND recalibration ------------------------------------------------

# Atomic prose that happens to contain commas/semicolons, each carrying
# exactly one falsification test: none of these may draw the
# irreducibility (coverage_gap) challenge.
ATOMIC_PROSE = [
    "The valve opens at 4 bar, measured at the inlet",
    "After the nightly run, the report lists every failed check",
    "The sensor reports temperature in degrees Celsius, as configured",
    "Given a valid token, the gateway accepts the request",
    "The cache entry expires after 60 seconds; stale reads are impossible",
]


@pytest.mark.parametrize("text", ATOMIC_PROSE)
def test_atomic_prose_with_commas_draws_no_irreducibility(text: str) -> None:
    claim = Claim(
        id="CLM-P",
        text=text,
        boundary=["production"],
        falsification_tests=["Observe a counter-instance on the bench rig"],
    )
    categories = {f.category for f in StressTester().run([claim])}
    assert "coverage_gap" not in categories


def test_punctuation_with_no_falsifier_still_draws_irreducibility() -> None:
    claim = Claim(
        id="CLM-P",
        text="The valve opens at 4 bar, measured at the inlet",
        boundary=["production"],
    )
    categories = {f.category for f in StressTester().run([claim])}
    assert "coverage_gap" in categories


def test_punctuation_with_two_falsifiers_still_draws_irreducibility() -> None:
    claim = Claim(
        id="CLM-P",
        text="The valve opens at 4 bar, measured at the inlet",
        boundary=["production"],
        falsification_tests=["first test", "second test"],
    )
    categories = {f.category for f in StressTester().run([claim])}
    assert "coverage_gap" in categories


def test_connective_still_draws_irreducibility_with_single_falsifier() -> None:
    claim = Claim(
        id="CLM-P",
        text="The valve opens and the pump starts",
        boundary=["production"],
        falsification_tests=["Observe either event not occurring"],
    )
    categories = {f.category for f in StressTester().run([claim])}
    assert "coverage_gap" in categories


# --- Schema conformance -----------------------------------------------------------


def test_assessment_with_dispositions_validates_against_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(assessment_schema_path().read_text(encoding="utf-8"))
    assessment = AEEEngine().assess([_dispositioned_claim()])
    jsonschema.validate(assessment.to_dict(), schema)


# --- T601/T602/T605: independence ---------------------------------------------------


def _observed(ref: str, source_id: str, **kwargs: object) -> Evidence:
    return Evidence(
        ref=ref,
        source_id=source_id,
        kind=EvidenceKind.OBSERVED,
        source_quality=SourceQuality.TEST,
        **kwargs,  # type: ignore[arg-type]
    )


def _claim(claim_id: str, evidence: list[Evidence]) -> Claim:
    return Claim(
        id=claim_id,
        text=f"Proposition {claim_id}",
        boundary=["lab"],
        falsification_tests=[f"Observe proposition {claim_id} failing"],
        evidence=evidence,
    )


def test_same_origin_different_refs_reports_inferred_basis_with_caveat() -> None:
    # T605: two items tracing to one study under different refs. The
    # numeric component is unchanged, but it is no longer UNQUALIFIED:
    # the basis is named inferred and the shared-origin caveat is on
    # the record.
    claim = _claim(
        "A",
        [
            _observed("study.pdf", "study-2026"),
            _observed("study-mirror.pdf", "study-2026"),
        ],
    )
    score = ScoringEngine().score([claim])["A"]
    assert score.independence_score == 0.5  # one distinct origin
    assert any(
        "Independence basis: inferred-from-references" in note
        and "may overstate independence when references share an origin" in note
        for note in score.notes
    )


def test_distinct_refs_score_full_but_qualified_as_inferred() -> None:
    claim = _claim("A", [_observed("a.pdf", "S1"), _observed("b.pdf", "S2")])
    score = ScoringEngine().score([claim])["A"]
    assert score.independence_score == 1.0
    assert any("Independence basis: inferred-from-references" in n for n in score.notes)
    assert not any("Independence basis: declared" in n for n in score.notes)


def test_independent_of_declaration_changes_computation() -> None:
    # T601/T605: same source_id, different refs — one source today.
    plain = _claim(
        "A",
        [_observed("run1.log", "lab-rig"), _observed("run2.log", "lab-rig")],
    )
    plain_score = ScoringEngine().score([plain])["A"]
    assert plain_score.independence_score == 0.5

    # Declaring the items independent of each other (by ref) separates
    # them into two sources and flips the basis to declared.
    declared = _claim(
        "A",
        [
            _observed("run1.log", "lab-rig", independent_of=["run2.log"]),
            _observed("run2.log", "lab-rig", independent_of=["run1.log"]),
        ],
    )
    declared_score = ScoringEngine().score([declared])["A"]
    assert declared_score.independence_score == 1.0
    assert declared_score.direct_score > plain_score.direct_score
    assert any("Independence basis: declared" in n for n in declared_score.notes)


def test_one_sided_declaration_by_source_id_also_separates() -> None:
    claim = _claim(
        "A",
        [
            _observed("run1.log", "rig-a", independent_of=["rig-b"]),
            _observed("run2.log", "rig-b"),
        ],
    )
    # Distinct ids already count separately; the declaration must at
    # least flip the basis to declared.
    score = ScoringEngine().score([claim])["A"]
    assert score.independence_score == 1.0
    assert any("Independence basis: declared" in n for n in score.notes)


def test_no_evidence_reports_basis_none() -> None:
    claim = _claim("A", [])
    score = ScoringEngine().score([claim])["A"]
    assert score.independence_score == 0.0
    assert any("Independence basis: none" in n for n in score.notes)


# --- T603/T605: shared-evidence warning ---------------------------------------------


def _all_failures(assessment: object) -> list:
    return [f for claim in assessment.claims for f in claim.failures]  # type: ignore[attr-defined]


def test_shared_evidence_warning_fires_on_overlap() -> None:
    claims = [
        _claim("A", [_observed("shared.pdf", "S1")]),
        _claim("B", [_observed("shared.pdf", "S1")]),
    ]
    assessment = AEEEngine().assess(claims)
    warnings = [f for f in _all_failures(assessment) if f.category == "independence_unmodeled"]
    assert {f.claim_id for f in warnings} == {"A", "B"}
    assert all("shared.pdf" in f.breakpoint for f in warnings)


def test_shared_evidence_warning_silent_on_disjoint() -> None:
    claims = [
        _claim("A", [_observed("a.pdf", "S1")]),
        _claim("B", [_observed("b.pdf", "S2")]),
    ]
    assessment = AEEEngine().assess(claims)
    assert not any(f.category == "independence_unmodeled" for f in _all_failures(assessment))


def test_shared_evidence_warning_silent_when_independence_declared() -> None:
    claims = [
        _claim("A", [_observed("shared.pdf", "S1", independent_of=["other.pdf"])]),
        _claim("B", [_observed("shared.pdf", "S1")]),
    ]
    assessment = AEEEngine().assess(claims)
    assert not any(f.category == "independence_unmodeled" for f in _all_failures(assessment))
