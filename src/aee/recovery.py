"""Recovery proposals for failed or under-supported claims."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from aee.model import FailureMode, Severity


class RecoveryStrategy(StrEnum):
    DECOMPOSE = "decompose"
    NARROW_BOUNDARY = "narrow_boundary"
    GATHER_EVIDENCE = "gather_evidence"
    DEFINE_FALSIFIER = "define_falsifier"
    RESOLVE_CONTRADICTION = "resolve_contradiction"
    REPAIR_PROVENANCE = "repair_provenance"
    CLARIFY = "clarify"
    SUPERSEDE = "supersede"


@dataclass(slots=True)
class RecoveryProposal:
    failure_id: str
    claim_id: str
    strategy: RecoveryStrategy
    action: str
    priority: int
    verification: str

    def to_dict(self) -> dict[str, object]:
        return {
            "failure_id": self.failure_id,
            "claim_id": self.claim_id,
            "strategy": self.strategy.value,
            "action": self.action,
            "priority": self.priority,
            "verification": self.verification,
        }


class RecoveryOperator:
    """Map explicit failure modes to bounded, verifiable recovery work."""

    def propose(self, failures: Iterable[FailureMode]) -> list[RecoveryProposal]:
        proposals = [self._proposal(failure) for failure in failures if not failure.resolved]
        return sorted(proposals, key=lambda item: (item.priority, item.claim_id, item.failure_id))

    def _proposal(self, failure: FailureMode) -> RecoveryProposal:
        category = failure.category
        if category == "coverage_gap":
            strategy = RecoveryStrategy.DECOMPOSE
            verification = (
                "Every resulting claim contains one independently falsifiable proposition."
            )
        elif category == "assumption_unvalidated":
            strategy = RecoveryStrategy.NARROW_BOUNDARY
            verification = (
                "The claim identifies its applicable system, population, time, and conditions."
            )
        elif category in {"missing_evidence", "unsupported_claim", "unverified_assertion"}:
            strategy = RecoveryStrategy.GATHER_EVIDENCE
            verification = "At least one inspectable non-self-attested evidence item is attached."
        elif category == "contradiction":
            strategy = RecoveryStrategy.RESOLVE_CONTRADICTION
            verification = (
                "Both positions remain recorded; discriminating evidence resolves or scopes them."
            )
        elif category == "provenance_gap":
            strategy = RecoveryStrategy.REPAIR_PROVENANCE
            verification = "Every dependency and evidence reference resolves to a stable source."
        elif category == "ambiguous_requirement":
            strategy = RecoveryStrategy.CLARIFY
            verification = "The revised claim contains a measurable observable or decision rule."
        else:
            strategy = RecoveryStrategy.DEFINE_FALSIFIER
            verification = "A concrete observation that would refute the claim is documented."
        return RecoveryProposal(
            failure_id=failure.id,
            claim_id=failure.claim_id,
            strategy=strategy,
            action=failure.recovery_hint or failure.breakpoint,
            priority=_priority(failure.severity),
            verification=verification,
        )


def _priority(severity: Severity) -> int:
    return {
        Severity.CRITICAL: 1,
        Severity.HIGH: 2,
        Severity.MEDIUM: 3,
        Severity.LOW: 4,
        Severity.INFO: 5,
    }[severity]
