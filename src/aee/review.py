"""Materiality review queue: what changed enough to re-review.

Slice 3 of the epistemic-ledger port. The ledger's revisit loop
does not re-review every dependent of a changed fact — it flags
only claims whose score moves by at least a **materiality**
threshold (default 0.05). That hysteresis was validated twice:
CHURN-01 set the default after watching raw churn flood reviewers,
and TRIGGER-STRESS-01 measured the resulting operating point
(recall 0.960 against an exact oracle, with flag volume — not
compute — the binding cost).

The analog here is phase-to-phase. A spec-driven project assesses
the same claims repeatedly as evidence arrives; re-reading every
score every phase does not scale, and diffing raw JSON invites
noise-chasing. :func:`build_review_queue` diffs two assessments
and returns the bounded list a reviewer actually owes attention:

- **items**: claims present in both whose propagated score moved
  by at least ``materiality``, largest movement first;
- **verdict_changes**: claims whose policy verdict flipped (when
  both assessments carry verdicts) — a flip is material even when
  the score move is small;
- **added / removed**: claim ids present in only one assessment.

``limit`` applies a top-k budget to ``items`` after sorting — the
ledger's follow-up lesson from hub facts flooding the queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from aee.model import ConfidenceBand

if TYPE_CHECKING:
    from aee.policy import ClaimVerdict
    from aee.scoring import ClaimScore


class AssessmentView(Protocol):
    """Anything carrying score and verdict mappings: an Assessment
    qualifies structurally, as does a view rebuilt from a
    serialized assessment (see the CLI's review subcommand)."""

    scores: dict[str, ClaimScore]
    verdicts: dict[str, ClaimVerdict]


DEFAULT_MATERIALITY = 0.05


@dataclass(slots=True)
class ReviewItem:
    claim_id: str
    previous_score: float
    current_score: float
    delta: float
    previous_band: ConfidenceBand
    current_band: ConfidenceBand

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "previous_score": self.previous_score,
            "current_score": self.current_score,
            "delta": self.delta,
            "previous_band": self.previous_band.value,
            "current_band": self.current_band.value,
        }


@dataclass(slots=True)
class VerdictChange:
    claim_id: str
    previous: str
    current: str

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "previous": self.previous,
            "current": self.current,
        }


@dataclass(slots=True)
class ReviewQueue:
    materiality: float
    items: list[ReviewItem] = field(default_factory=list)
    verdict_changes: list[VerdictChange] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "materiality": self.materiality,
            "items": [item.to_dict() for item in self.items],
            "verdict_changes": [change.to_dict() for change in self.verdict_changes],
            "added": list(self.added),
            "removed": list(self.removed),
        }


def _scores(
    source: AssessmentView | dict[str, ClaimScore],
) -> dict[str, ClaimScore]:
    return source.scores if hasattr(source, "scores") else source


def _verdicts(source: AssessmentView | dict[str, ClaimScore]) -> dict[str, str]:
    verdicts = getattr(source, "verdicts", None) or {}
    return {key: verdict.verdict.value for key, verdict in verdicts.items()}


def build_review_queue(
    previous: AssessmentView | dict[str, ClaimScore],
    current: AssessmentView | dict[str, ClaimScore],
    *,
    materiality: float = DEFAULT_MATERIALITY,
    limit: int | None = None,
) -> ReviewQueue:
    """Diff two assessments into a bounded, materiality-filtered queue."""
    if not 0.0 <= materiality <= 1.0:
        raise ValueError("materiality must be between 0 and 1")
    if limit is not None and limit < 0:
        raise ValueError("limit must be >= 0")
    prev_scores = _scores(previous)
    cur_scores = _scores(current)
    queue = ReviewQueue(materiality=materiality)
    queue.added = sorted(set(cur_scores) - set(prev_scores))
    queue.removed = sorted(set(prev_scores) - set(cur_scores))
    for claim_id in sorted(set(prev_scores) & set(cur_scores)):
        before = prev_scores[claim_id].propagated_score
        after = cur_scores[claim_id].propagated_score
        delta = round(after - before, 6)
        if abs(delta) >= materiality:
            queue.items.append(
                ReviewItem(
                    claim_id=claim_id,
                    previous_score=before,
                    current_score=after,
                    delta=delta,
                    previous_band=ConfidenceBand.from_score(before),
                    current_band=ConfidenceBand.from_score(after),
                )
            )
    queue.items.sort(key=lambda item: (-abs(item.delta), item.claim_id))
    if limit is not None:
        queue.items = queue.items[:limit]
    prev_verdicts = _verdicts(previous)
    cur_verdicts = _verdicts(current)
    for claim_id in sorted(set(prev_verdicts) & set(cur_verdicts)):
        if prev_verdicts[claim_id] != cur_verdicts[claim_id]:
            queue.verdict_changes.append(
                VerdictChange(
                    claim_id=claim_id,
                    previous=prev_verdicts[claim_id],
                    current=cur_verdicts[claim_id],
                )
            )
    return queue
