"""Per-source reliability learned from resolved claims.

Ported from the epistemic ledger's learned entrenchment
(AXIOVEX/epistemic-ledger): there, a claim's entrenchment stops
being a hand-assigned tier once outcomes exist and becomes
``1 - Brier`` over the scores that were live when each outcome
landed. Its OVERRIDE-CAL-01 study showed the loop absorbs even a
reviewer who is wrong 20% of the time — bad input degrades the
source's measured reliability instead of poisoning the store.

The analog here is per-source. A :class:`ReliabilityTable` records,
for each source, the assessments in which that source supported a
claim: the claim's propagated score at assessment time (the
system's credence, which the source's evidence fed) and the claim's
eventual outcome, once known. A source's measured reliability is
``1 - Brier`` over those observations. In scoring, a measured
reliability blends with the static :class:`SourceQuality` prior:

    weight = (1 - alpha) * static + alpha * measured

so an unmeasured source keeps its prior exactly, a source with a
perfect record can lift even MODEL evidence above its 0.20 prior,
and a source with a poor record drags even TEST evidence down.
Contradicting evidence keeps its static weight in this version:
reliability at asserting a claim and reliability at refuting one
are different tracks, and only the support track is measured here.

Everything is opt-in: ``ScoringEngine()`` without a table scores
bit-identically to previous releases. Whenever a measured weight
replaces a static one, the claim score's notes say so — measured
weights are inspectable, never silent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aee.model import Claim, Evidence, EvidenceDirection

if TYPE_CHECKING:
    from aee.scoring import ClaimScore


@dataclass(slots=True)
class SourceRecord:
    """Resolved observations for one source."""

    observations: int = 0
    brier_sum: float = 0.0

    @property
    def brier(self) -> float | None:
        if not self.observations:
            return None
        return self.brier_sum / self.observations

    @property
    def reliability(self) -> float | None:
        brier = self.brier
        return None if brier is None else 1.0 - brier

    def to_dict(self) -> dict[str, object]:
        return {
            "observations": self.observations,
            "brier_sum": self.brier_sum,
        }

    @classmethod
    def from_dict(cls, value: dict) -> SourceRecord:
        return cls(
            observations=int(value.get("observations", 0)),
            brier_sum=float(value.get("brier_sum", 0.0)),
        )


@dataclass(slots=True)
class ReliabilityTable:
    """Outcome history per source, with Brier-derived reliability.

    ``min_observations`` is the cold-start guard: below it a source
    has a record but no measured reliability, so scoring keeps the
    static prior — a source is neither canonized nor condemned on
    one outcome.
    """

    min_observations: int = 3
    records: dict[str, SourceRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.min_observations < 1:
            raise ValueError("min_observations must be >= 1")

    def record(self, source_id: str, predicted: float, outcome: bool) -> None:
        if not source_id:
            return
        if not 0.0 <= predicted <= 1.0:
            raise ValueError("predicted must be between 0 and 1")
        rec = self.records.setdefault(source_id, SourceRecord())
        rec.observations += 1
        rec.brier_sum += (predicted - (1.0 if outcome else 0.0)) ** 2

    def observe_claim(self, claim: Claim, score: ClaimScore, outcome: bool) -> list[str]:
        """Credit a resolved claim to every distinct supporting source.

        Returns the source ids credited. The prediction recorded is
        the claim's propagated score from the assessment being
        resolved — the credence the system actually held.
        """
        credited: list[str] = []
        seen: set[str] = set()
        for item in claim.evidence:
            if item.direction != EvidenceDirection.SUPPORTS:
                continue
            source_id = item.source_id or item.ref
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            self.record(source_id, score.propagated_score, outcome)
            credited.append(source_id)
        return credited

    def reliability(self, source_id: str) -> float | None:
        """Measured reliability, or None while the source is unmeasured."""
        rec = self.records.get(source_id)
        if rec is None or rec.observations < self.min_observations:
            return None
        return rec.reliability

    def to_dict(self) -> dict[str, object]:
        return {
            "min_observations": self.min_observations,
            "records": {key: rec.to_dict() for key, rec in self.records.items()},
        }

    @classmethod
    def from_dict(cls, value: dict) -> ReliabilityTable:
        return cls(
            min_observations=int(value.get("min_observations", 3)),
            records={
                key: SourceRecord.from_dict(rec) for key, rec in value.get("records", {}).items()
            },
        )


def blended_weight(
    item: Evidence,
    static_weight: float,
    table: ReliabilityTable | None,
    alpha: float,
) -> tuple[float, float | None]:
    """Blend a supporting item's static weight with measured reliability.

    Returns ``(weight, measured)`` where ``measured`` is the
    reliability used, or None when the static weight stands (no
    table, or the source has not reached ``min_observations``).
    """
    if table is None:
        return static_weight, None
    measured = table.reliability(item.source_id or item.ref)
    if measured is None:
        return static_weight, None
    return (1.0 - alpha) * static_weight + alpha * measured, measured
