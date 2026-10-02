from aee import Claim, Evidence, EvidenceDirection, EvidenceKind, ScoringEngine, SourceQuality


def strong_evidence(ref: str, source_id: str) -> Evidence:
    return Evidence(
        ref=ref,
        source_id=source_id,
        kind=EvidenceKind.OBSERVED,
        source_quality=SourceQuality.TEST,
    )


def test_no_evidence_scores_low() -> None:
    claim = Claim(id="A", text="A", boundary=["x"], falsification_tests=["not A"])
    score = ScoringEngine().score([claim])["A"]
    assert score.direct_score == 0.25
    assert "No supporting evidence" in score.notes


def test_two_independent_observed_sources_score_high() -> None:
    claim = Claim(
        id="A",
        text="A",
        boundary=["x"],
        falsification_tests=["not A"],
        evidence=[strong_evidence("one", "S1"), strong_evidence("two", "S2")],
    )
    score = ScoringEngine().score([claim])["A"]
    assert score.propagated_score == 1.0


def test_weakest_link_propagation() -> None:
    weak = Claim(id="A", text="A", boundary=["x"])
    strong = Claim(
        id="B",
        text="B",
        boundary=["x"],
        depends_on=["A"],
        falsification_tests=["not B"],
        evidence=[strong_evidence("one", "S1"), strong_evidence("two", "S2")],
    )
    scores = ScoringEngine().score([weak, strong])
    assert scores["B"].propagated_score == scores["A"].propagated_score


def test_counterevidence_penalizes_score() -> None:
    claim = Claim(
        id="A",
        text="A",
        boundary=["x"],
        falsification_tests=["not A"],
        evidence=[
            strong_evidence("support", "S1"),
            Evidence(
                ref="counter",
                kind=EvidenceKind.OBSERVED,
                direction=EvidenceDirection.CONTRADICTS,
                source_quality=SourceQuality.PRIMARY,
            ),
        ],
    )
    score = ScoringEngine().score([claim])["A"]
    assert score.contradiction_penalty > 0
    assert score.direct_score < 0.5


def test_freshness_pinned_by_as_of() -> None:
    """as_of makes scoring replayable: the same evidence is fresh
    relative to a pinned near date and stale relative to a far one,
    independent of the wall clock."""
    from datetime import UTC, datetime

    def dated_claim() -> Claim:
        return Claim(
            id="A",
            text="A",
            boundary=["x"],
            falsification_tests=["not A"],
            evidence=[
                Evidence(
                    ref="r1",
                    source_id="s1",
                    kind=EvidenceKind.OBSERVED,
                    source_quality=SourceQuality.TEST,
                    observed_at="2020-01-01T00:00:00Z",
                ),
                Evidence(
                    ref="r2",
                    source_id="s2",
                    kind=EvidenceKind.OBSERVED,
                    source_quality=SourceQuality.TEST,
                    observed_at="2020-01-01T00:00:00Z",
                ),
            ],
        )

    near = ScoringEngine().score([dated_claim()], as_of=datetime(2020, 1, 2, tzinfo=UTC))["A"]
    far = ScoringEngine().score([dated_claim()], as_of=datetime(2026, 1, 1, tzinfo=UTC))["A"]
    assert not any("Freshness penalty" in n for n in near.notes)
    assert any("Freshness penalty" in n for n in far.notes)
    assert far.direct_score < near.direct_score
    again = ScoringEngine().score([dated_claim()], as_of=datetime(2026, 1, 1, tzinfo=UTC))["A"]
    assert again.direct_score == far.direct_score


def test_cycle_skips_propagation_with_note() -> None:
    claims = [
        Claim(id="A", text="A", depends_on=["B"]),
        Claim(id="B", text="B", depends_on=["A"]),
    ]
    scores = ScoringEngine().score(claims)
    assert any("propagation skipped" in n for n in scores["A"].notes)


def test_unparseable_observed_at_is_noted() -> None:
    claim = Claim(
        id="A",
        text="A",
        boundary=["x"],
        evidence=[
            Evidence(
                ref="r1",
                source_id="s1",
                kind=EvidenceKind.OBSERVED,
                source_quality=SourceQuality.TEST,
                observed_at="not-a-date",
            )
        ],
    )
    score = ScoringEngine().score([claim])["A"]
    assert any("unparseable observed_at" in n for n in score.notes)
