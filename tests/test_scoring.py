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
