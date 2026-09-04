"""End-to-end AEE assessment orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aee.challenge import StressTester
from aee.model import Claim, Severity
from aee.recovery import RecoveryOperator, RecoveryProposal
from aee.scoring import ClaimScore, ScoringEngine

_SEVERITY_ORDER = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


@dataclass(slots=True)
class Assessment:
    """Complete, serializable result of one AEE run."""

    project: str
    phase: str
    claims: list[Claim]
    scores: dict[str, ClaimScore]
    recoveries: list[RecoveryProposal]
    outcome: str
    summary: str
    created_at: str
    methodology_version: str = "1.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def failures(self) -> list[object]:
        return [failure for claim in self.claims for failure in claim.failures]

    @property
    def healthy(self) -> bool:
        return self.outcome in {"pass", "warn"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "methodology_version": self.methodology_version,
            "project": self.project,
            "phase": self.phase,
            "outcome": self.outcome,
            "summary": self.summary,
            "created_at": self.created_at,
            "claims": [claim.to_dict() for claim in self.claims],
            "scores": {key: score.to_dict() for key, score in self.scores.items()},
            "recoveries": [item.to_dict() for item in self.recoveries],
            "metadata": dict(self.metadata),
        }


class AEEEngine:
    """Run stress testing, scoring, and recovery in a deterministic order."""

    def __init__(self, threshold: float = 0.70) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        self.threshold = threshold
        self.stress_tester = StressTester()
        self.scoring_engine = ScoringEngine()
        self.recovery_operator = RecoveryOperator()

    def assess(
        self,
        claims: Iterable[Claim],
        *,
        project: str = "project",
        phase: str = "after_plan",
        metadata: dict[str, Any] | None = None,
    ) -> Assessment:
        items = list(claims)
        failures = self.stress_tester.run(items)
        scores = self.scoring_engine.score(items)
        recoveries = self.recovery_operator.propose(failures)
        outcome = self._outcome(items, scores)
        below = sum(score.propagated_score < self.threshold for score in scores.values())
        summary = (
            f"Assessed {len(items)} claim(s); found {len(failures)} failure mode(s); "
            f"{below} claim(s) below the {self.threshold:.2f} confidence threshold."
        )
        return Assessment(
            project=project,
            phase=phase,
            claims=items,
            scores=scores,
            recoveries=recoveries,
            outcome=outcome,
            summary=summary,
            created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            metadata={"threshold": self.threshold, **(metadata or {})},
        )

    def _outcome(self, claims: list[Claim], scores: dict[str, ClaimScore]) -> str:
        failures = [failure for claim in claims for failure in claim.unresolved_failures]
        if any(failure.severity == Severity.CRITICAL for failure in failures):
            return "block"
        if any(
            failure.severity == Severity.HIGH and failure.category == "contradiction"
            for failure in failures
        ):
            return "clarify"
        if any(
            failure.severity == Severity.HIGH
            and failure.category
            in {"missing_evidence", "unsupported_claim", "unverified_assertion"}
            for failure in failures
        ):
            return "gather_evidence"
        if failures or any(score.propagated_score < self.threshold for score in scores.values()):
            return "iterate"
        return "pass"


def highest_severity(claims: Iterable[Claim]) -> Severity:
    failures = [failure for claim in claims for failure in claim.unresolved_failures]
    if not failures:
        return Severity.INFO
    return max((failure.severity for failure in failures), key=_SEVERITY_ORDER.__getitem__)
