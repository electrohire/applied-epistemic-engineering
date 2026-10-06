"""Materiality review queue (slice 3 of the epistemic-ledger port).

Diffing two assessments yields only the claims whose propagated
score moved by at least the materiality threshold, largest first,
plus verdict flips and added/removed claims. The default
materiality (0.05) is the ledger's validated hysteresis point.
"""

import pytest
from test_scoring import strong_evidence

from aee import (
    AEEEngine,
    AssessmentPolicy,
    Claim,
    ClaimStatus,
    ScoringEngine,
    build_review_queue,
)


def scored(claims):
    return ScoringEngine().score(claims)


def bare_claim(claim_id: str, evidence=None) -> Claim:
    return Claim(
        id=claim_id,
        text=claim_id,
        status=ClaimStatus.SUPPORTED,
        boundary=["x"],
        falsification_tests=["not " + claim_id],
        evidence=evidence or [],
    )


def test_material_move_is_queued_small_move_is_not() -> None:
    before = scored([bare_claim("A"), bare_claim("B")])
    after_claims = [
        bare_claim("A", [strong_evidence("one", "S1"), strong_evidence("two", "S2")]),
        bare_claim("B", [strong_evidence("one", "S1")]),
    ]
    after = scored(after_claims)
    queue = build_review_queue(before, after)
    ids = [item.claim_id for item in queue.items]
    assert "A" in ids  # 0.25 -> 1.0
    # B moves 0.25 -> ~0.775 direct... verify against the rule, not
    # a guessed number: B's delta is computed from the scores.
    b_delta = abs(after["B"].propagated_score - before["B"].propagated_score)
    assert ("B" in ids) == (b_delta >= 0.05)
    a_item = next(item for item in queue.items if item.claim_id == "A")
    assert a_item.delta == pytest.approx(0.75)
    assert a_item.previous_band.value == "low"
    assert a_item.current_band.value == "high"


def test_identical_assessments_empty_queue() -> None:
    claims = [bare_claim("A", [strong_evidence("one", "S1")])]
    queue = build_review_queue(scored(claims), scored(claims))
    assert queue.items == []
    assert queue.added == [] and queue.removed == []


def test_added_and_removed_claims() -> None:
    before = scored([bare_claim("A"), bare_claim("B")])
    after = scored([bare_claim("A"), bare_claim("C")])
    queue = build_review_queue(before, after)
    assert queue.added == ["C"]
    assert queue.removed == ["B"]


def test_limit_applies_after_sorting() -> None:
    before = scored([bare_claim("A"), bare_claim("B"), bare_claim("C")])
    after = scored(
        [
            bare_claim("A", [strong_evidence("one", "S1"), strong_evidence("two", "S2")]),  # +0.75
            bare_claim("B", [strong_evidence("one", "S1")]),  # smaller
            bare_claim("C", [strong_evidence("one", "S1"), strong_evidence("two", "S2")]),  # +0.75
        ]
    )
    queue = build_review_queue(before, after, limit=1)
    assert len(queue.items) == 1
    assert queue.items[0].claim_id in {"A", "C"}
    full = build_review_queue(before, after)
    assert [i.claim_id for i in full.items[:2]] == ["A", "C"]


def test_verdict_changes_surface() -> None:
    engine = AEEEngine(policy=AssessmentPolicy())
    weak = bare_claim("A")
    first = engine.assess([weak])
    strong = bare_claim("A", [strong_evidence("one", "S1"), strong_evidence("two", "S2")])
    second = engine.assess([strong])
    queue = build_review_queue(first, second)
    assert len(queue.verdict_changes) == 1
    change = queue.verdict_changes[0]
    assert change.claim_id == "A"
    assert change.previous == "abstain"
    assert change.current == "accept"


def test_materiality_boundary_is_inclusive() -> None:
    before = scored([bare_claim("A", [strong_evidence("one", "S1")])])
    after = scored([bare_claim("A")])
    delta = abs(after["A"].propagated_score - before["A"].propagated_score)
    queue = build_review_queue(before, after, materiality=delta)
    assert [item.claim_id for item in queue.items] == ["A"]
    queue = build_review_queue(before, after, materiality=delta + 0.001)
    assert queue.items == []


def test_to_dict_shape() -> None:
    before = scored([bare_claim("A")])
    after = scored([bare_claim("A", [strong_evidence("one", "S1"), strong_evidence("two", "S2")])])
    data = build_review_queue(before, after).to_dict()
    assert data["materiality"] == 0.05
    assert data["items"][0]["claim_id"] == "A"
    assert data["verdict_changes"] == []


def test_validation() -> None:
    empty = scored([bare_claim("A")])
    with pytest.raises(ValueError):
        build_review_queue(empty, empty, materiality=1.5)
    with pytest.raises(ValueError):
        build_review_queue(empty, empty, limit=-1)
