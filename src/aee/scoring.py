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
    """Score claims using published components, never hidden model confidence."""

    def score(self, claims: Iterable[Claim]) -> dict[str, ClaimScore]:
        items = list(claims)
        scores = {claim.id: self._direct(claim) for claim in items}
        graph = ClaimGraph(items)
        if not graph.cycles():
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

    def _direct(self, claim: Claim) -> ClaimScore:
        support = [item for item in claim.evidence if item.direction == EvidenceDirection.SUPPORTS]
        contradict = [
            item for item in claim.evidence if item.direction == EvidenceDirection.CONTRADICTS
        ]
        weighted = [
            max(0.0, _KIND_WEIGHTS[item.kind]) * _SOURCE_WEIGHTS[item.source_quality]
            for item in support
        ]
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
        freshness_penalty = self._freshness_penalty(support)

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
        if contradiction_penalty:
            notes.append(f"Contradiction penalty {contradiction_penalty:.3f}")
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
    def _freshness_penalty(evidence: Sequence[Evidence]) -> float:
        observed_dates: list[datetime] = []
        for item in evidence:
            observed_at = item.observed_at
            if not observed_at:
                continue
            try:
                observed_dates.append(datetime.fromisoformat(observed_at.replace("Z", "+00:00")))
            except ValueError:
                continue
        if not observed_dates:
            return 0.0
        newest = max(observed_dates)
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=UTC)
        age_days = (datetime.now(UTC) - newest).days
        if age_days <= 90:
            return 0.0
        if age_days <= 365:
            return 0.05
        return 0.10
