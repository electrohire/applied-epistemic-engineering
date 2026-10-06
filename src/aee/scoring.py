"""Transparent evidence-quality scoring and dependency propagation."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aee.graph import ClaimGraph
from aee.model import (
    Claim,
    ConfidenceBand,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    SourceQuality,
)
from aee.reliability import ReliabilityTable, blended_weight

_SOURCE_WEIGHTS = {
    SourceQuality.TEST: 1.0,
    SourceQuality.PRIMARY: 0.95,
    SourceQuality.ARTIFACT: 0.90,
    SourceQuality.HUMAN: 0.70,
    SourceQuality.SECONDARY: 0.65,
    SourceQuality.TERTIARY: 0.40,
    SourceQuality.MODEL: 0.20,
    SourceQuality.UNKNOWN: 0.10,
}
_KIND_WEIGHTS = {
    EvidenceKind.OBSERVED: 1.0,
    EvidenceKind.INFERRED: 0.65,
    EvidenceKind.ASSERTED: 0.25,
    EvidenceKind.CONTRADICTED: -0.75,
    EvidenceKind.UNSUPPORTED: 0.0,
}


@dataclass(slots=True)
class ClaimScore:
    claim_id: str
    direct_score: float
    propagated_score: float
    evidence_score: float
    independence_score: float
    falsifiability_score: float
    boundary_score: float
    contradiction_penalty: float
    notes: list[str] = field(default_factory=list)

    @property
    def band(self) -> ConfidenceBand:
        return ConfidenceBand.from_score(self.propagated_score)

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "direct_score": self.direct_score,
            "propagated_score": self.propagated_score,
            "band": self.band.value,
            "components": {
                "evidence": self.evidence_score,
                "independence": self.independence_score,
                "falsifiability": self.falsifiability_score,
                "boundary": self.boundary_score,
                "contradiction_penalty": self.contradiction_penalty,
            },
            "notes": list(self.notes),
        }


class ScoringEngine:
    """Score claims using published components, never hidden model confidence.

    With a ``reliability`` table attached, a supporting source's
    static quality weight blends toward its measured reliability
    (``1 - Brier`` over resolved claims it supported; see
    aee.reliability) by ``reliability_alpha``. Every substitution
    is recorded on the claim score's notes. Without a table the
    scoring is unchanged.
    """

    def __init__(
        self,
        reliability: ReliabilityTable | None = None,
        *,
        reliability_alpha: float = 0.5,
    ) -> None:
        if not 0.0 <= reliability_alpha <= 1.0:
            raise ValueError("reliability_alpha must be between 0 and 1")
        self.reliability = reliability
        self.reliability_alpha = reliability_alpha

    def score(
        self, claims: Iterable[Claim], *, as_of: datetime | None = None
    ) -> dict[str, ClaimScore]:
        """Score claims. ``as_of`` pins the instant freshness is judged
        against; the default is the current time. Pinning it makes an
        assessment replayable — previously the freshness penalty read
        the wall clock directly, so identical input scored differently
        on different days.

        Contract — mutation: each claim's ``confidence`` attribute is
        overwritten with its propagated score, so consumers reading
        the claim objects afterwards see the assessed values. The
        returned mapping is the authoritative per-claim record;
        re-scoring replaces the attribute again.
        """
        as_of = as_of or datetime.now(UTC)
        items = list(claims)
        scores = {claim.id: self._direct(claim, as_of) for claim in items}
        graph = ClaimGraph(items)
        cycles = graph.cycles()
        if cycles:
            # Propagation is skipped on cyclic graphs. That must be
            # visible on the scores themselves, not only in the
            # challenge pass — an uncapped score otherwise looks
            # unconditional.
            for claim_score in scores.values():
                claim_score.notes.append(
                    f"Dependency propagation skipped: cycle(s) present: {cycles}"
                )
        else:
            for claim_id in graph.topological_order():
                deps = graph.dependencies(claim_id)
                if deps:
                    weakest = min(scores[dep.id].propagated_score for dep in deps)
                    scores[claim_id].propagated_score = min(
                        scores[claim_id].propagated_score, weakest
                    )
                    if weakest < scores[claim_id].direct_score:
                        scores[claim_id].notes.append(
                            f"Capped by weakest dependency at {weakest:.3f}"
                        )
        for claim in items:
            claim.confidence = scores[claim.id].propagated_score
        return scores

    def _direct(self, claim: Claim, as_of: datetime) -> ClaimScore:
        support = [item for item in claim.evidence if item.direction == EvidenceDirection.SUPPORTS]
        contradict = [
            item for item in claim.evidence if item.direction == EvidenceDirection.CONTRADICTS
        ]
        weighted = []
        reliability_notes: list[str] = []
        noted_sources: set[str] = set()
        for item in support:
            static = _SOURCE_WEIGHTS[item.source_quality]
            weight, measured = blended_weight(
                item, static, self.reliability, self.reliability_alpha
            )
            if measured is not None:
                source_id = item.source_id or item.ref
                if source_id not in noted_sources:
                    noted_sources.add(source_id)
                    reliability_notes.append(
                        f"Source {source_id} weight {static:.2f} -> "
                        f"{weight:.2f} (measured reliability "
                        f"{measured:.3f})"
                    )
            weighted.append(max(0.0, _KIND_WEIGHTS[item.kind]) * weight)
        evidence_score = 1.0
        for value in weighted:
            evidence_score *= 1.0 - value
        evidence_score = 1.0 - evidence_score if weighted else 0.0

        source_ids = {item.source_id or item.ref for item in support if item.ref}
        independence_score = min(1.0, len(source_ids) / 2.0) if support else 0.0
        falsifiability_score = 1.0 if claim.falsification_tests else 0.0
        boundary_score = 1.0 if claim.boundary else 0.0
        contradiction_penalty = min(
            0.75,
            sum(
                abs(_KIND_WEIGHTS[item.kind]) * _SOURCE_WEIGHTS[item.source_quality]
                for item in contradict
            ),
        )
        freshness_penalty, unparseable_dates = self._freshness_penalty(support, as_of)

        direct = (
            0.55 * evidence_score
            + 0.20 * independence_score
            + 0.15 * falsifiability_score
            + 0.10 * boundary_score
            - contradiction_penalty
            - freshness_penalty
        )
        direct = round(max(0.0, min(1.0, direct)), 6)
        notes: list[str] = []
        if not support:
            notes.append("No supporting evidence")
        if support and not any(item.kind == EvidenceKind.OBSERVED for item in support):
            notes.append("No observed supporting evidence")
        if len(source_ids) < 2:
            notes.append("Fewer than two independent supporting sources")
        if freshness_penalty:
            notes.append(f"Freshness penalty {freshness_penalty:.3f}")
        if unparseable_dates:
            notes.append(
                f"{unparseable_dates} supporting evidence item(s) had an "
                "unparseable observed_at and were ignored for freshness"
            )
        if contradiction_penalty:
            notes.append(f"Contradiction penalty {contradiction_penalty:.3f}")
        notes.extend(reliability_notes)
        return ClaimScore(
            claim_id=claim.id,
            direct_score=direct,
            propagated_score=direct,
            evidence_score=round(evidence_score, 6),
            independence_score=independence_score,
            falsifiability_score=falsifiability_score,
            boundary_score=boundary_score,
            contradiction_penalty=round(contradiction_penalty, 6),
            notes=notes,
        )

    @staticmethod
    def _freshness_penalty(evidence: Sequence[Evidence], as_of: datetime) -> tuple[float, int]:
        """Return (penalty, count of unparseable observed_at values)."""
        observed_dates: list[datetime] = []
        unparseable = 0
        for item in evidence:
            observed_at = item.observed_at
            if not observed_at:
                continue
            try:
                observed_dates.append(datetime.fromisoformat(observed_at.replace("Z", "+00:00")))
            except ValueError:
                unparseable += 1
        if not observed_dates:
            return 0.0, unparseable
        newest = max(observed_dates)
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=UTC)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)
        age_days = (as_of - newest).days
        if age_days <= 90:
            return 0.0, unparseable
        if age_days <= 365:
            return 0.05, unparseable
        return 0.10, unparseable
