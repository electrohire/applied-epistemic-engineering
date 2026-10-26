"""Spec 003 Phase 3 - FR-3, reliability validation and credit
assignment (T301-T306).

Every test inverts a red-team probe: RT1 p6 §E (unbounded
``from_dict``: brier_sum=-99 -> reliability 34.0, evidence_score
8.5), RT2 p07 (NaN reliability file -> perfect score, bare NaN in
emitted JSON), RT1 p4 §E (direct record() farming), §F (coattail
farming: zero-weight junk canonised at 1.0 in 3 observations),
§G (framing: a victim source destroyed by claims it was attached
to).

Held behaviour is pinned too: an honest table's reliability and
blended weights are asserted at the exact values captured from
main @ 574531e before this phase (lab 0.79 -> blended TEST 0.895;
M 1.0 -> blended MODEL 0.60).

FR-3.6 addendum note (2026-10-12): canonisation now requires
verified anchored provenance, and the pre-addendum honest table
was built from the self-asserted string PROV — such records earn
provisional credit only under the addendum. The honest table
below is therefore built from anchored resolution records
(``record_resolution`` against a hash-chained ledger) with
identical observations; the pinned values are unchanged because
the observations are. Tests that pinned canonisation from bare
loaded or legacy records were re-pinned to the addendum's
semantics where they appear below.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from test_scoring import strong_evidence

from aee import (
    Claim,
    Evidence,
    EvidenceKind,
    HashChainLedger,
    ReliabilityTable,
    ScoringEngine,
    SourceQuality,
)
from aee.cli import main
from aee.model import BundleValidationError
from aee.reliability import (
    LEGACY_PROVENANCE,
    OBSERVE_CLAIM_PROVENANCE,
    UNATTRIBUTED_PROVENANCE,
    SourceRecord,
    blended_weight,
)
from aee.scoring import ClaimScore

PROV = "unit-test-resolver"


def honest_table() -> ReliabilityTable:
    # Anchored since the FR-3.6 addendum: each resolution is
    # appended to a hash-chained ledger and recorded against its
    # entry. Observations identical to the pre-addendum table.
    ledger_dir = tempfile.mkdtemp(prefix="aee-honest-table-")
    table = ReliabilityTable(ledger=HashChainLedger(Path(ledger_dir) / "ledger.jsonl"))
    for outcome in [True, True, False, True]:
        table.record_resolution("lab", 0.9, outcome, provenance=PROV)
    for _ in range(5):
        table.record_resolution("M", 1.0, True, provenance=PROV)
    return table


def ledger_table(tmp_path) -> ReliabilityTable:
    return ReliabilityTable(ledger=HashChainLedger(tmp_path / "resolutions.jsonl"))


# ------------------------------------------------------------------
# T301 - from_dict validation (inverts RT1 p6 §E, RT2 p07 load half)
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "record",
    [
        {"observations": 3, "brier_sum": -99.0},  # RT1 p6 §E: was reliability 34.0
        {"observations": 3, "brier_sum": 100.0},  # RT1 p6 §E: was reliability -32.0
        {"observations": 5, "brier_sum": float("nan")},  # RT2-C1 / p07
        {"observations": 5, "brier_sum": float("inf")},
        {"observations": 5, "brier_sum": float("-inf")},
        {"observations": -1, "brier_sum": 0.0},
        {"observations": 2.5, "brier_sum": 0.5},
        {"observations": "3", "brier_sum": 0.5},
        {"observations": 3, "brier_sum": True},
        {"observations": 3, "brier_sum": 0.5, "credit_weight": 4.0},
        {"observations": 3, "brier_sum": 0.5, "credit_weight": 0.25},
        {"observations": 3, "brier_sum": 0.5, "credit_weight": float("nan")},
        {"observations": 3, "brier_sum": 0.5, "provenance": ""},
        {"observations": 3, "brier_sum": 0.5, "provenance": 7},
    ],
)
def test_from_dict_rejects_poisoned_records(record) -> None:
    with pytest.raises(BundleValidationError, match="lab"):
        ReliabilityTable.from_dict({"records": {"lab": record}})


def test_from_dict_rejects_bad_table_shape() -> None:
    with pytest.raises(BundleValidationError):
        ReliabilityTable.from_dict({"min_observations": 0, "records": {}})
    with pytest.raises(BundleValidationError):
        ReliabilityTable.from_dict({"min_observations": 2.5, "records": {}})
    with pytest.raises(BundleValidationError):
        ReliabilityTable.from_dict({"records": ["not", "a", "dict"]})
    with pytest.raises(BundleValidationError):
        ReliabilityTable.from_dict(["not a dict"])


def test_from_dict_accepts_boundary_values() -> None:
    # brier_sum == observations is the worst legitimate record
    # (every prediction maximally wrong), not poison — the file
    # loads. Since the FR-3.6 addendum, though, a bare file record
    # carries no anchors: it canonises nothing, and its
    # measurement is reported on the provisional track only.
    table = ReliabilityTable.from_dict({"records": {"lab": {"observations": 3, "brier_sum": 3.0}}})
    assert table.reliability("lab") is None
    assert table.provisional_reliability("lab") == 0.0
    perfect = ReliabilityTable.from_dict(
        {"records": {"lab": {"observations": 3, "brier_sum": 0.0}}}
    )
    assert perfect.reliability("lab") is None
    # The raw measurement is 1.0; the provisional cap binds it.
    assert perfect.provisional_reliability("lab") == 0.5


# ------------------------------------------------------------------
# T302 - range guarantees (inverts RT1 p6 §E score half)
# ------------------------------------------------------------------


def test_honest_table_control_values_unchanged() -> None:
    """Captured from main @ 574531e before this phase."""
    table = honest_table()
    assert table.reliability("lab") == pytest.approx(0.79)
    assert table.reliability("M") == 1.0
    lab_item = Evidence(
        ref="r", source_id="lab", kind=EvidenceKind.OBSERVED, source_quality=SourceQuality.TEST
    )
    assert blended_weight(lab_item, 1.0, table, 0.5) == (pytest.approx(0.895), pytest.approx(0.79))
    model_item = Evidence(
        ref="r", source_id="M", kind=EvidenceKind.ASSERTED, source_quality=SourceQuality.MODEL
    )
    assert blended_weight(model_item, 0.20, table, 0.5) == (pytest.approx(0.60), 1.0)


def test_blended_weight_and_evidence_score_stay_in_range() -> None:
    table = honest_table()
    for alpha in (0.0, 0.5, 1.0):
        for source, static in (("lab", 1.0), ("M", 0.20)):
            item = Evidence(
                ref="r",
                source_id=source,
                kind=EvidenceKind.OBSERVED,
                source_quality=SourceQuality.TEST,
            )
            weight, _ = blended_weight(item, static, table, alpha)
            assert 0.0 <= weight <= 1.0
    # The strongest legitimate lift: one model item whose source
    # has a perfect measured record at alpha=1 (RT1 p6 §E reached
    # evidence_score 8.5 here via the poisoned table).
    claim = Claim(
        id="A",
        text="A",
        boundary=["x"],
        falsification_tests=["not A"],
        evidence=[
            Evidence(
                ref="m1",
                source_id="M",
                kind=EvidenceKind.ASSERTED,
                source_quality=SourceQuality.MODEL,
            )
        ],
    )
    score = ScoringEngine(reliability=table, reliability_alpha=1.0).score([claim])["A"]
    assert 0.0 <= score.evidence_score <= 1.0
    assert 0.0 <= score.direct_score <= 1.0


def test_nonfinite_internal_state_degrades_to_unmeasured() -> None:
    # State built by hand, bypassing the validated loaders, must
    # still never surface a non-finite or out-of-range number.
    table = ReliabilityTable()
    table.records["lab"] = SourceRecord(observations=5, brier_sum=float("nan"))
    assert table.reliability("lab") is None
    item = Evidence(
        ref="r", source_id="lab", kind=EvidenceKind.OBSERVED, source_quality=SourceQuality.TEST
    )
    weight, measured = blended_weight(item, 1.0, table, 0.5)
    assert weight == 1.0 and measured is None


# ------------------------------------------------------------------
# T303 - CLI rejects non-finite / poisoned reliability files
# (inverts RT2 p07 end to end)
# ------------------------------------------------------------------


def _write_claims(tmp_path) -> str:
    claims = {
        "claims": [
            {
                "id": "A",
                "text": "Latency is below 100 ms",
                "status": "supported",
                "stage": "accepted",
                "boundary": ["p95 in production"],
                "falsification_tests": ["Observe p95 at or above 100 ms"],
                "evidence": [
                    {
                        "ref": "run-lab",
                        "source_id": "lab",
                        "kind": "observed",
                        "source_quality": "test",
                        "direction": "supports",
                    }
                ],
            }
        ]
    }
    path = tmp_path / "claims.json"
    path.write_text(json.dumps(claims), encoding="utf-8")
    return str(path)


def _assess_with_reliability(tmp_path, reliability_text: str):
    rel = tmp_path / "reliability.json"
    rel.write_text(reliability_text, encoding="utf-8")
    output = tmp_path / "assessment.json"
    code = main(
        [
            "assess",
            "--input",
            _write_claims(tmp_path),
            "--output",
            str(output),
            "--no-ledger",
            "--reliability",
            str(rel),
        ]
    )
    return code, output


@pytest.mark.parametrize(
    "reliability_text",
    [
        '{"records": {"lab": {"observations": 5, "brier_sum": NaN}}}',  # RT2 p07 verbatim class
        '{"records": {"lab": {"observations": 5, "brier_sum": Infinity}}}',
        '{"records": {"lab": {"observations": 3, "brier_sum": -99}}}',
        '{"records": {"lab": {"observations": 3, "brier_sum": 1e999}}}',
    ],
)
def test_cli_refuses_poisoned_reliability_file(tmp_path, reliability_text) -> None:
    code, output = _assess_with_reliability(tmp_path, reliability_text)
    assert code == 2
    assert not output.exists()


def test_cli_clean_reliability_file_emits_strict_json(tmp_path) -> None:
    code, output = _assess_with_reliability(tmp_path, json.dumps(honest_table().to_dict()))
    assert code in (0, 1)
    text = output.read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text

    def _reject(name: str) -> None:
        raise ValueError(name)

    json.loads(text, parse_constant=_reject)  # strict-JSON parseable


# ------------------------------------------------------------------
# T304 - contribution-weighted credit (inverts RT1 p4 §§F-G)
# ------------------------------------------------------------------


def _claim(claim_id: str, evidence: list[Evidence]) -> Claim:
    return Claim(
        id=claim_id,
        text="The widget holds",
        boundary=["lab"],
        falsification_tests=["drop it"],
        evidence=evidence,
    )


def _fake_score(claim_id: str, propagated: float) -> ClaimScore:
    return ClaimScore(
        claim_id=claim_id,
        direct_score=propagated,
        propagated_score=propagated,
        evidence_score=1.0,
        independence_score=1.0,
        falsifiability_score=1.0,
        boundary_score=1.0,
        contradiction_penalty=0.0,
    )


def test_coattail_zero_weight_junk_earns_no_record(tmp_path) -> None:
    """RT1 p4 §F: junk UNSUPPORTED item rode three claims carried
    by a real test source and reached reliability 1.0."""
    table = ledger_table(tmp_path)
    for i in range(3):
        claim = _claim(
            f"F{i}",
            [
                strong_evidence("real-ref", "real-test"),
                Evidence(
                    ref="evil-junk",
                    source_id="evil",
                    kind=EvidenceKind.UNSUPPORTED,
                    source_quality=SourceQuality.UNKNOWN,
                ),
            ],
        )
        score = ScoringEngine().score([claim])["F" + str(i)]
        credited = table.observe_claim_resolution(claim, score, True)
        assert credited == ["real-test"]
    assert "evil" not in table.records
    assert table.reliability("evil") is None
    assert table.reliability("real-test") is not None


def test_coattail_tiny_share_never_reaches_cold_start() -> None:
    """A positive-but-tiny share is not a loophole: three claims at
    a ~2.4% share are ~0.07 effective observations, not three."""
    table = ReliabilityTable()
    junk = Evidence(
        ref="junk",
        source_id="junk",
        kind=EvidenceKind.ASSERTED,  # 0.25 kind weight
        source_quality=SourceQuality.UNKNOWN,  # 0.10 quality weight
    )
    for i in range(3):
        claim = _claim(f"T{i}", [strong_evidence("real-ref", "real-test"), junk])
        table.observe_claim(claim, _fake_score(f"T{i}", 1.0), True)
    rec = table.records["junk"]
    assert rec.observations == 3
    assert rec.effective_credit == pytest.approx(3 * 0.025 / 1.025)
    assert table.reliability("junk") is None


def test_honest_co_sources_still_learn(tmp_path) -> None:
    table = ledger_table(tmp_path)
    for i in range(6):
        claim = _claim(
            f"H{i}",
            [strong_evidence("one", "S1"), strong_evidence("two", "S2")],
        )
        credited = table.observe_claim_resolution(claim, _fake_score(f"H{i}", 1.0), True)
        assert credited == ["S1", "S2"]
    # Each claim is half an observation about each source; six
    # claims reach the cold-start guard and the record is perfect.
    assert table.records["S1"].effective_credit == pytest.approx(3.0)
    assert table.reliability("S1") == 1.0
    assert table.reliability("S2") == 1.0


def test_framing_minor_contributor_not_destroyed() -> None:
    """RT1 p4 §G variant: the victim barely touches the doomed
    claims (asserted/model next to observed/test)."""
    table = ReliabilityTable()
    victim = Evidence(
        ref="victim-ref",
        source_id="victim",
        kind=EvidenceKind.ASSERTED,
        source_quality=SourceQuality.MODEL,
    )
    for i in range(3):
        claim = _claim(f"G{i}", [victim, strong_evidence("other-ref", "other")])
        table.observe_claim(claim, _fake_score(f"G{i}", 0.95), False)
    rec = table.records["victim"]
    assert rec.effective_credit == pytest.approx(3 * 0.05 / 1.05)
    # The per-claim error is honest (0.95 vs false); the protection
    # is that ~0.14 effective observations cannot condemn a source.
    assert table.reliability("victim") is None


def test_framing_equal_contributor_takes_proportional_blame(tmp_path) -> None:
    """RT1 p4 §G as written: victim contributes half of each
    doomed claim. Three claims are 1.5 effective observations
    (still cold-start; the old code measured 0.0975 here); six
    claims reach measurement and the full proportional loss lands."""
    table = ledger_table(tmp_path)
    for i in range(3):
        claim = _claim(
            f"G{i}",
            [strong_evidence("victim-ref", "victim"), strong_evidence("other-ref", "other")],
        )
        table.observe_claim_resolution(claim, _fake_score(f"G{i}", 0.95), False)
    assert table.records["victim"].effective_credit == pytest.approx(1.5)
    assert table.reliability("victim") is None
    for i in range(3, 6):
        claim = _claim(
            f"G{i}",
            [strong_evidence("victim-ref", "victim"), strong_evidence("other-ref", "other")],
        )
        table.observe_claim_resolution(claim, _fake_score(f"G{i}", 0.95), False)
    assert table.reliability("victim") == pytest.approx(1 - 0.95**2)


def test_observe_claim_no_positive_weight_credits_nobody() -> None:
    table = ReliabilityTable()
    claim = _claim(
        "Z",
        [
            Evidence(
                ref="junk",
                source_id="junk",
                kind=EvidenceKind.UNSUPPORTED,
                source_quality=SourceQuality.UNKNOWN,
            )
        ],
    )
    assert table.observe_claim(claim, _fake_score("Z", 1.0), True) == []
    assert table.records == {}


# ------------------------------------------------------------------
# T305 - provenance (inverts RT1 p4 §E direct-farming surface)
# ------------------------------------------------------------------


def test_record_requires_provenance_on_direct_path() -> None:
    table = ReliabilityTable()
    with pytest.raises(ValueError, match="provenance"):
        table.record("evil-source", 1.0, True)
    with pytest.raises(ValueError, match="provenance"):
        table.record("evil-source", 1.0, True, provenance="  ")


def test_record_unattributed_only_via_named_compatibility_path() -> None:
    table = ReliabilityTable()
    table.record("S", 1.0, True, allow_unattributed=True)
    assert table.records["S"].provenance == UNATTRIBUTED_PROVENANCE


def test_provenance_persists_and_threads_observe_claim() -> None:
    table = ReliabilityTable()
    table.record("S", 0.9, True, provenance="grader-7")
    assert table.records["S"].provenance == "grader-7"
    claim = _claim("P", [strong_evidence("one", "S1")])
    table.observe_claim(claim, _fake_score("P", 1.0), True)
    assert table.records["S1"].provenance == OBSERVE_CLAIM_PROVENANCE
    table.observe_claim(claim, _fake_score("P", 1.0), True, provenance="panel-review")
    assert table.records["S1"].provenance == "panel-review"
    clone = ReliabilityTable.from_dict(table.to_dict())
    assert clone.records["S"].provenance == "grader-7"
    assert clone.records["S1"].provenance == "panel-review"


def test_legacy_table_loads_with_defaulted_provenance_and_credit() -> None:
    # A pre-FR-3 file: no credit_weight, no provenance. Legacy
    # records were full-credit by construction, so effective
    # credit defaults to the observation count.
    legacy = {"min_observations": 3, "records": {"old": {"observations": 4, "brier_sum": 0.84}}}
    table = ReliabilityTable.from_dict(legacy)
    rec = table.records["old"]
    assert rec.provenance == LEGACY_PROVENANCE
    assert rec.effective_credit == 4.0
    # FR-3.7: legacy history loads with its honest marker but
    # canonises nothing on its own — the 0.79 measurement survives
    # only as a capped provisional value until anchored records
    # exist.
    assert rec.anchored_credit == 0.0
    assert rec.anchors == ()
    assert table.reliability("old") is None
    assert table.provisional_reliability("old") == pytest.approx(0.5)
    assert table.credit_status("old") == "provisional"
