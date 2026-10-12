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

Spec 003 FR-8.11/FR-8.12 widened the queue's channels and fixed
its top-k integrity (the queue was blind to everything but
consecutive score deltas, and decoys could flood a target out of
a limited queue):

- **failure channel**: a claim that gains a failure mode, or whose
  worst failure severity escalates, queues even at zero score
  delta — a new CRITICAL failure always surfaces;
- **band crossings**: a score crossing a confidence band (or the
  assessment threshold, when supplied) queues even below
  materiality;
- **cumulative drift**: with a review ``baseline`` supplied, a
  claim whose cumulative movement from the baseline reaches
  materiality queues even when every consecutive step was below
  it (the salami defence). The baseline advances only when the
  caller says the queue was reviewed — this function never moves
  it implicitly;
- **rename candidates**: an id removed and an id added in the same
  diff are paired as a rename candidate (closest score match),
  surfaced as a candidate — a heuristic signal, never silently
  treated as an unrelated add/remove pair, and never asserted as
  a proven rename;
- **adverse-first top-k**: selection reserves priority for
  failure-channel items and adverse (negative) deltas ahead of
  favourable deltas of any size, so flooding the queue with
  decoy improvements cannot crowd out a collapse; when the limit
  omits items, the queue reports how many and of what kind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from aee.model import ConfidenceBand, Severity

if TYPE_CHECKING:
    from aee.model import FailureMode
    from aee.policy import ClaimVerdict
    from aee.scoring import ClaimScore


class AssessmentView(Protocol):
    """Anything carrying score, verdict, and failure mappings: an
    Assessment qualifies structurally, as does a view rebuilt from
    a serialized assessment (see the CLI's review subcommand).
    Members are read-only properties so frozen views qualify."""

    @property
    def scores(self) -> dict[str, ClaimScore]: ...

    @property
    def verdicts(self) -> dict[str, ClaimVerdict]: ...

    @property
    def failures(self) -> list[FailureMode]: ...


DEFAULT_MATERIALITY = 0.05

_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


@dataclass(slots=True)
class ReviewItem:
    claim_id: str
    previous_score: float
    current_score: float
    delta: float
    previous_band: ConfidenceBand
    current_band: ConfidenceBand
    # FR-8.11: which channel produced this item - "score" (material
    # delta), "failure" (failure channel), "band_crossing", or
    # "cumulative_drift" (measured against the review baseline;
    # previous_score is then the BASELINE score).
    kind: str = "score"
    detail: str = ""
    # FR-8.13(a): the current record's declared-state block rides
    # the view, so a queue consumer sees the author's declared
    # posture alongside the movement.
    declared_state: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "previous_score": self.previous_score,
            "current_score": self.current_score,
            "delta": self.delta,
            "previous_band": self.previous_band.value,
            "current_band": self.current_band.value,
            "kind": self.kind,
            "detail": self.detail,
            "declared_state": self.declared_state,
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
class RenameCandidate:
    removed_id: str
    added_id: str
    previous_score: float
    current_score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "removed_id": self.removed_id,
            "added_id": self.added_id,
            "previous_score": self.previous_score,
            "current_score": self.current_score,
        }


@dataclass(slots=True)
class ReviewQueue:
    materiality: float
    items: list[ReviewItem] = field(default_factory=list)
    verdict_changes: list[VerdictChange] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    rename_candidates: list[RenameCandidate] = field(default_factory=list)
    # FR-8.12: when `limit` truncated the queue, how much was left
    # out - in total and by channel kind. Zero/empty when unlimited
    # or when nothing was omitted.
    omitted: int = 0
    omitted_by_kind: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "materiality": self.materiality,
            "items": [item.to_dict() for item in self.items],
            "verdict_changes": [change.to_dict() for change in self.verdict_changes],
            "added": list(self.added),
            "removed": list(self.removed),
            "rename_candidates": [c.to_dict() for c in self.rename_candidates],
            "omitted": self.omitted,
            "omitted_by_kind": dict(self.omitted_by_kind),
        }


def _scores(
    source: AssessmentView | dict[str, ClaimScore],
) -> dict[str, ClaimScore]:
    return source.scores if hasattr(source, "scores") else source


def _verdicts(source: AssessmentView | dict[str, ClaimScore]) -> dict[str, str]:
    verdicts = getattr(source, "verdicts", None) or {}
    return {key: verdict.verdict.value for key, verdict in verdicts.items()}


def _failures_by_claim(
    source: AssessmentView | dict[str, ClaimScore],
) -> dict[str, dict[str, Severity]]:
    failures = getattr(source, "failures", None) or []
    by_claim: dict[str, dict[str, Severity]] = {}
    for failure in failures:
        if getattr(failure, "resolved", False):
            continue
        by_claim.setdefault(failure.claim_id, {})[failure.id] = failure.severity
    return by_claim


def _declared_state(score: ClaimScore) -> dict[str, object] | None:
    state = getattr(score, "declared_state", None)
    return dict(state) if state else None


def build_review_queue(
    previous: AssessmentView | dict[str, ClaimScore],
    current: AssessmentView | dict[str, ClaimScore],
    *,
    materiality: float = DEFAULT_MATERIALITY,
    limit: int | None = None,
    baseline: AssessmentView | dict[str, ClaimScore] | None = None,
    threshold: float | None = None,
) -> ReviewQueue:
    """Diff two assessments into a bounded, materiality-filtered queue.

    ``baseline`` (FR-8.11(c)) is the last REVIEWED assessment: the
    drift channel compares it against ``current``. ``threshold``
    (FR-8.11(b)) is the assessments' confidence threshold, when the
    caller knows it: crossing it queues an item just as crossing a
    confidence band does.
    """
    if not 0.0 <= materiality <= 1.0:
        raise ValueError("materiality must be between 0 and 1")
    if limit is not None and limit < 0:
        raise ValueError("limit must be >= 0")
    prev_scores = _scores(previous)
    cur_scores = _scores(current)
    queue = ReviewQueue(materiality=materiality)
    queue.added = sorted(set(cur_scores) - set(prev_scores))
    queue.removed = sorted(set(prev_scores) - set(cur_scores))

    prev_failures = _failures_by_claim(previous)
    cur_failures = _failures_by_claim(current)
    items_by_claim: dict[str, ReviewItem] = {}

    def _item(claim_id: str, before: float, after: float, kind: str, detail: str = "") -> ReviewItem:
        return ReviewItem(
            claim_id=claim_id,
            previous_score=before,
            current_score=after,
            delta=round(after - before, 6),
            previous_band=ConfidenceBand.from_score(before),
            current_band=ConfidenceBand.from_score(after),
            kind=kind,
            detail=detail,
            declared_state=_declared_state(cur_scores[claim_id]),
        )

    for claim_id in sorted(set(prev_scores) & set(cur_scores)):
        before = prev_scores[claim_id].propagated_score
        after = cur_scores[claim_id].propagated_score
        delta = round(after - before, 6)
        # Failure channel first: it outranks the score channel for
        # the same claim (a new CRITICAL failure is the story, the
        # delta is context).
        prev_f = prev_failures.get(claim_id, {})
        cur_f = cur_failures.get(claim_id, {})
        new_failures = [fid for fid in cur_f if fid not in prev_f]
        worst_before = max((_SEVERITY_RANK[s] for s in prev_f.values()), default=0)
        worst_after = max((_SEVERITY_RANK[s] for s in cur_f.values()), default=0)
        if new_failures or worst_after > worst_before:
            bits = []
            if new_failures:
                bits.append(f"new failure(s): {', '.join(sorted(new_failures))}")
            if worst_after > worst_before:
                worst_name = max(cur_f.values(), key=lambda s: _SEVERITY_RANK[s]).value
                bits.append(f"worst severity escalated to {worst_name}")
            items_by_claim[claim_id] = _item(claim_id, before, after, "failure", "; ".join(bits))
            continue
        if abs(delta) >= materiality:
            items_by_claim[claim_id] = _item(claim_id, before, after, "score")
            continue
        band_crossed = ConfidenceBand.from_score(before) != ConfidenceBand.from_score(after)
        threshold_crossed = threshold is not None and (before < threshold) != (after < threshold)
        if band_crossed or threshold_crossed:
            which = "confidence band" if band_crossed else "confidence threshold"
            items_by_claim[claim_id] = _item(
                claim_id, before, after, "band_crossing", f"crossed the {which}"
            )

    if baseline is not None:
        base_scores = _scores(baseline)
        for claim_id in sorted(set(base_scores) & set(cur_scores)):
            if claim_id in items_by_claim or claim_id not in prev_scores:
                continue
            base = base_scores[claim_id].propagated_score
            after = cur_scores[claim_id].propagated_score
            if abs(round(after - base, 6)) >= materiality:
                items_by_claim[claim_id] = _item(
                    claim_id,
                    base,
                    after,
                    "cumulative_drift",
                    "cumulative movement from the review baseline",
                )

    queue.items = list(items_by_claim.values())

    def _priority(item: ReviewItem) -> tuple[int, float, float, str]:
        # FR-8.12: failure channel first, then adverse movement,
        # then favourable - each by magnitude. Claim id is only the
        # final stabiliser, never the deciding key ahead of
        # substance, so decoys cannot game ties by naming.
        if item.kind == "failure":
            tier = 0
        elif item.delta < 0:
            tier = 1
        else:
            tier = 2
        return (tier, -abs(item.delta), item.delta, item.claim_id)

    queue.items.sort(key=_priority)
    if limit is not None and len(queue.items) > limit:
        omitted_items = queue.items[limit:]
        queue.omitted = len(omitted_items)
        for item in omitted_items:
            queue.omitted_by_kind[item.kind] = queue.omitted_by_kind.get(item.kind, 0) + 1
        queue.items = queue.items[:limit]

    # Rename candidates (FR-8.11): pair each removed id with the
    # still-unpaired added id whose current score is closest to the
    # removed claim's last score. A candidate is a signal to check,
    # not a finding that a rename happened.
    if queue.added and queue.removed:
        unpaired = list(queue.added)
        for removed_id in queue.removed:
            if not unpaired:
                break
            previous_score = prev_scores[removed_id].propagated_score
            best = min(
                unpaired,
                key=lambda added_id: abs(
                    cur_scores[added_id].propagated_score - previous_score
                ),
            )
            unpaired.remove(best)
            queue.rename_candidates.append(
                RenameCandidate(
                    removed_id=removed_id,
                    added_id=best,
                    previous_score=previous_score,
                    current_score=cur_scores[best].propagated_score,
                )
            )

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
