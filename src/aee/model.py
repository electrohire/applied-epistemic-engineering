"""Typed domain model for Applied Epistemic Engineering."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ClaimKind(StrEnum):
    OBSERVATION = "observation"
    REQUIREMENT = "requirement"
    ASSUMPTION = "assumption"
    INFERENCE = "inference"
    HYPOTHESIS = "hypothesis"
    DECISION = "decision"
    PREDICTION = "prediction"
    COMPLIANCE = "compliance"


class ClaimStatus(StrEnum):
    DRAFT = "draft"
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"
    SUPERSEDED = "superseded"


class EvidenceKind(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    ASSERTED = "asserted"
    CONTRADICTED = "contradicted"
    UNSUPPORTED = "unsupported"


class EvidenceDirection(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


class SourceQuality(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"
    ARTIFACT = "artifact"
    TEST = "test"
    HUMAN = "human"
    MODEL = "model"
    UNKNOWN = "unknown"


class Uncertainty(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ConfidenceBand(StrEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @classmethod
    def from_score(cls, score: float) -> ConfidenceBand:
        if score >= 0.75:
            return cls.HIGH
        if score >= 0.45:
            return cls.MEDIUM
        if score > 0.0:
            return cls.LOW
        return cls.UNKNOWN


@dataclass(slots=True)
class Evidence:
    """Inspectable support, contradiction, or context for a claim."""

    ref: str
    kind: EvidenceKind = EvidenceKind.ASSERTED
    direction: EvidenceDirection = EvidenceDirection.SUPPORTS
    source_quality: SourceQuality = SourceQuality.UNKNOWN
    description: str = ""
    source_id: str = ""
    independent_of: list[str] = field(default_factory=list)
    observed_at: str | None = None
    content_hash: str | None = None

    @property
    def is_observed(self) -> bool:
        return self.kind == EvidenceKind.OBSERVED

    @property
    def is_model_self_attestation(self) -> bool:
        return self.kind == EvidenceKind.ASSERTED and self.source_quality == SourceQuality.MODEL

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "kind": self.kind.value,
            "direction": self.direction.value,
            "source_quality": self.source_quality.value,
            "description": self.description,
            "source_id": self.source_id,
            "independent_of": list(self.independent_of),
            "observed_at": self.observed_at,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Evidence:
        return cls(
            ref=str(value.get("ref", "")),
            kind=EvidenceKind(value.get("kind", EvidenceKind.ASSERTED.value)),
            direction=EvidenceDirection(value.get("direction", EvidenceDirection.SUPPORTS.value)),
            source_quality=SourceQuality(value.get("source_quality", SourceQuality.UNKNOWN.value)),
            description=str(value.get("description", "")),
            source_id=str(value.get("source_id", "")),
            independent_of=[str(item) for item in value.get("independent_of", [])],
            observed_at=value.get("observed_at"),
            content_hash=value.get("content_hash"),
        )


@dataclass(slots=True)
class FailureMode:
    """A reproducible challenge and the breakpoint it exposes."""

    id: str
    claim_id: str
    challenge: str
    breakpoint: str
    severity: Severity = Severity.MEDIUM
    category: str = "other"
    recovery_hint: str = ""
    resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim_id": self.claim_id,
            "challenge": self.challenge,
            "breakpoint": self.breakpoint,
            "severity": self.severity.value,
            "category": self.category,
            "recovery_hint": self.recovery_hint,
            "resolved": self.resolved,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> FailureMode:
        return cls(
            id=str(value.get("id", "")),
            claim_id=str(value.get("claim_id", "")),
            challenge=str(value.get("challenge", "")),
            breakpoint=str(value.get("breakpoint", "")),
            severity=Severity(value.get("severity", Severity.MEDIUM.value)),
            category=str(value.get("category", "other")),
            recovery_hint=str(value.get("recovery_hint", "")),
            resolved=bool(value.get("resolved", False)),
        )


@dataclass(slots=True)
class Claim:
    """Atomic proposition with explicit boundary, evidence, and uncertainty."""

    id: str
    text: str
    kind: ClaimKind = ClaimKind.ASSUMPTION
    status: ClaimStatus = ClaimStatus.DRAFT
    boundary: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    falsification_tests: list[str] = field(default_factory=list)
    uncertainty: Uncertainty = Uncertainty.INSUFFICIENT_EVIDENCE
    severity: Severity = Severity.MEDIUM
    source_ref: str = ""
    domain: str = ""
    confidence: float | None = None
    failures: list[FailureMode] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("claim id must not be empty")
        if not 0.0 <= (self.confidence if self.confidence is not None else 0.0) <= 1.0:
            raise ValueError("claim confidence must be between 0 and 1")

    @property
    def unresolved_failures(self) -> list[FailureMode]:
        return [failure for failure in self.failures if not failure.resolved]

    @property
    def confidence_band(self) -> ConfidenceBand:
        return ConfidenceBand.from_score(self.confidence or 0.0)

    def add_evidence(self, evidence: Evidence) -> Claim:
        self.evidence.append(evidence)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind.value,
            "status": self.status.value,
            "boundary": list(self.boundary),
            "depends_on": list(self.depends_on),
            "conflicts_with": list(self.conflicts_with),
            "evidence": [item.to_dict() for item in self.evidence],
            "assumptions": list(self.assumptions),
            "alternatives": list(self.alternatives),
            "falsification_tests": list(self.falsification_tests),
            "uncertainty": self.uncertainty.value,
            "severity": self.severity.value,
            "source_ref": self.source_ref,
            "domain": self.domain,
            "confidence": self.confidence,
            "confidence_band": self.confidence_band.value,
            "failures": [failure.to_dict() for failure in self.failures],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Claim:
        confidence = value.get("confidence")
        return cls(
            id=str(value.get("id", "")),
            text=str(value.get("text", "")),
            kind=ClaimKind(value.get("kind", ClaimKind.ASSUMPTION.value)),
            status=ClaimStatus(value.get("status", ClaimStatus.DRAFT.value)),
            boundary=[str(item) for item in value.get("boundary", [])],
            depends_on=[str(item) for item in value.get("depends_on", [])],
            conflicts_with=[str(item) for item in value.get("conflicts_with", [])],
            evidence=[Evidence.from_dict(item) for item in value.get("evidence", [])],
            assumptions=[str(item) for item in value.get("assumptions", [])],
            alternatives=[str(item) for item in value.get("alternatives", [])],
            falsification_tests=[str(item) for item in value.get("falsification_tests", [])],
            uncertainty=Uncertainty(
                value.get("uncertainty", Uncertainty.INSUFFICIENT_EVIDENCE.value)
            ),
            severity=Severity(value.get("severity", Severity.MEDIUM.value)),
            source_ref=str(value.get("source_ref", "")),
            domain=str(value.get("domain", "")),
            confidence=float(confidence) if confidence is not None else None,
            failures=[FailureMode.from_dict(item) for item in value.get("failures", [])],
            metadata=dict(value.get("metadata", {})),
        )
