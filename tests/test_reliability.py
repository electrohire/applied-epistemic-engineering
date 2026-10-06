"""Per-source reliability learned from resolved claims (slice 2 of
the epistemic-ledger port).

A source's measured reliability is 1 - Brier over the claims it
supported, using the score that was live when each claim resolved.
Below min_observations the static SourceQuality prior stands; above
it, scoring blends the prior toward the measurement by alpha, and
the substitution is noted on the score.
"""

import pytest
from test_scoring import strong_evidence

from aee import (
    AEEEngine,
    Claim,
    Evidence,
    EvidenceKind,
    ReliabilityTable,
    ScoringEngine,
    SourceQuality,
)


def table_with(source: str, outcomes: list[bool], predicted: float = 0.9):
    table = ReliabilityTable()
    for outcome in outcomes:
        table.record(source, predicted, outcome)
    return table


def model_claim(source: str) -> Claim:
    return Claim(
        id="A",
        text="A",
        boundary=["x"],
        falsification_tests=["not A"],
        evidence=[
            Evidence(
                ref="m1",
                source_id=source,
                kind=EvidenceKind.ASSERTED,
                source_quality=SourceQuality.MODEL,
            )
        ],
    )


def test_brier_and_reliability_math() -> None:
    table = table_with("S1", [True, True, False], predicted=0.9)
    rec = table.records["S1"]
    assert rec.observations == 3
    # (0.1)^2 + (0.1)^2 + (0.9)^2 = 0.83; mean 0.27666...
    assert rec.brier == pytest.approx(0.83 / 3)
    assert table.reliability("S1") == pytest.approx(1 - 0.83 / 3)


def test_cold_start_keeps_prior() -> None:
    table = table_with("S1", [True, True])  # 2 < min_observations=3
    assert table.reliability("S1") is None
    assert table.reliability("never-seen") is None


def test_good_record_lifts_model_evidence() -> None:
    table = table_with("M", [True] * 5, predicted=1.0)
    assert table.reliability("M") == 1.0
    baseline = ScoringEngine().score([model_claim("M")])["A"]
    lifted = ScoringEngine(reliability=table).score([model_claim("M")])["A"]
    assert lifted.direct_score > baseline.direct_score
    assert any("measured reliability 1.000" in note for note in lifted.notes)
    assert any("weight 0.20 -> 0.60" in note for note in lifted.notes)


def test_bad_record_drags_test_evidence() -> None:
    table = table_with("T", [False] * 4, predicted=1.0)
    assert table.reliability("T") == 0.0
    claim = Claim(
        id="A",
        text="A",
        boundary=["x"],
        falsification_tests=["not A"],
        evidence=[strong_evidence("one", "T")],
    )
    baseline = ScoringEngine().score([claim])["A"]
    dragged_claim = Claim(
        id="A",
        text="A",
        boundary=["x"],
        falsification_tests=["not A"],
        evidence=[strong_evidence("one", "T")],
    )
    dragged = ScoringEngine(reliability=table).score([dragged_claim])["A"]
    assert dragged.direct_score < baseline.direct_score


def test_no_table_scores_unchanged() -> None:
    claim = model_claim("M")
    plain = ScoringEngine().score([claim])["A"]
    empty = ScoringEngine(reliability=ReliabilityTable()).score([model_claim("M")])["A"]
    assert plain.direct_score == empty.direct_score
    assert not any("measured reliability" in note for note in empty.notes)


def test_alpha_one_uses_measurement_fully() -> None:
    table = table_with("M", [True] * 3, predicted=1.0)
    score = ScoringEngine(reliability=table, reliability_alpha=1.0).score([model_claim("M")])["A"]
    assert any("weight 0.20 -> 1.00" in note for note in score.notes)


def test_observe_claim_credits_distinct_sources_once() -> None:
    claim = Claim(
        id="A",
        text="A",
        evidence=[
            strong_evidence("one", "S1"),
            strong_evidence("two", "S1"),
            strong_evidence("three", "S2"),
        ],
    )
    score = ScoringEngine().score([claim])["A"]
    table = ReliabilityTable()
    credited = table.observe_claim(claim, score, True)
    assert credited == ["S1", "S2"]
    assert table.records["S1"].observations == 1
    assert table.records["S2"].observations == 1


def test_serialization_round_trip() -> None:
    table = table_with("S1", [True, False], predicted=0.7)
    table.min_observations = 5
    clone = ReliabilityTable.from_dict(table.to_dict())
    assert clone.min_observations == 5
    assert clone.records["S1"].observations == 2
    assert clone.records["S1"].brier_sum == table.records["S1"].brier_sum


def test_engine_forwards_reliability() -> None:
    table = table_with("M", [True] * 5, predicted=1.0)
    result = AEEEngine(reliability=table).assess([model_claim("M")])
    assert any("measured reliability" in note for note in result.scores["A"].notes)


def test_validation() -> None:
    with pytest.raises(ValueError):
        ReliabilityTable(min_observations=0)
    with pytest.raises(ValueError):
        ReliabilityTable().record("S", 1.5, True)
    with pytest.raises(ValueError):
        ScoringEngine(reliability_alpha=1.5)
