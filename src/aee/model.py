"""Typed domain model for Applied Epistemic Engineering."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


def normalize_claim_id(value: str) -> str:
    """The single claim-id identity rule (Spec 003 FR-5.7, RT2-L2).

    A claim id's canonical form is: Unicode NFC, surrounding
    whitespace stripped, uppercased. Every surface that takes a claim
    id from authored input applies this one rule — the JSON loader
    (``Claim.from_dict``, strict and lenient), the Markdown extractor,
    and the session loader/facade — and every id REFERENCE
    (``depends_on``, ``conflicts_with``, disposition ``successors``,
    a failure mode's ``claim_id``) is normalised with it too, so a
    reference written ``clm-1`` resolves to the claim ``CLM-1``
    instead of dangling. Ids that differ only by case, surrounding
    whitespace, or Unicode composition (NFC vs NFD) are therefore
    THE SAME id everywhere: they cannot silently coexist as distinct
    claims, and when a bundle carries two spellings they surface as a
    duplicate id (validate error / assess block), never a silent
    merge. ``source_ref`` derivation in the Markdown extractor uses
    this normalised id as well.
    """
    return unicodedata.normalize("NFC", value.strip()).upper()


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


class DispositionKind(StrEnum):
    SPLIT = "split"
    ACCEPTED_ATOMIC = "accepted-atomic"
    WAIVED = "waived"


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


class BundleValidationError(ValueError):
    """A claim bundle failed strict loading (Spec 002 FR-1).

    Subclasses ValueError so existing clean-error paths (the CLI catches
    ValueError -> exit 2) keep working. Every message names the claim id
    (or position), the field, and the problem.
    """


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


# Field names a legacy/near-miss author plausibly meant (Spec 002 FR-1.2/1.5).
_FIELD_ALIASES: dict[str, str] = {
    "statement": "text",
    "proposition": "text",
    "claim": "text",
    "falsifier": "falsification_tests",
    "falsifiers": "falsification_tests",
    "dependencies": "depends_on",
    "conflicts": "conflicts_with",
    "source": "source_ref",
    "url": "ref",
    "path": "ref",
    "quality": "source_quality",
    "type": "kind",
}


def suggest_field_name(name: str, known: set[str]) -> str | None:
    """Did-you-mean: explicit alias first, then edit distance over known fields."""
    alias = _FIELD_ALIASES.get(name)
    if alias is not None and alias in known:
        return alias
    best: str | None = None
    best_distance = 3  # suggest only when within edit distance 2
    for candidate in sorted(known):
        distance = _edit_distance(name, candidate)
        if distance < best_distance:
            best, best_distance = candidate, distance
    return best


def _check_unknown_fields(value: dict[str, Any], known: set[str], context: str) -> None:
    unknown = sorted(set(value) - known)
    if not unknown:
        return
    parts = []
    for name in unknown:
        suggestion = suggest_field_name(name, known)
        hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
        parts.append(f"unknown field '{name}'{hint}")
    raise BundleValidationError(
        f"{context}: " + "; ".join(parts) + f". Valid fields: {', '.join(sorted(known))}"
    )


def _enum_field(
    enum_cls: type[ClaimKind]
    | type[ClaimStatus]
    | type[EvidenceKind]
    | type[EvidenceDirection]
    | type[SourceQuality]
    | type[Uncertainty]
    | type[Severity]
    | type[DispositionKind],
    raw: Any,
    *,
    context: str,
    field: str,
) -> Any:
    if isinstance(raw, enum_cls):
        return raw
    try:
        return enum_cls(raw)
    except ValueError:
        valid = ", ".join(member.value for member in enum_cls)
        raise BundleValidationError(
            f"{context}: field '{field}' has invalid value {raw!r}; valid values: {valid}"
        ) from None


def _str_field(
    value: dict[str, Any],
    field: str,
    *,
    context: str,
    default: str = "",
    required: bool = False,
    non_empty: bool = False,
) -> str:
    if field not in value:
        if required:
            raise BundleValidationError(f"{context}: field '{field}' is required but missing")
        return default
    raw = value[field]
    if not isinstance(raw, str):
        raise BundleValidationError(
            f"{context}: field '{field}' must be a string, got {type(raw).__name__}"
        )
    if non_empty and not raw.strip():
        raise BundleValidationError(f"{context}: field '{field}' must not be empty")
    return raw


def _opt_str_field(value: dict[str, Any], field: str, *, context: str) -> str | None:
    raw = value.get(field)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise BundleValidationError(
            f"{context}: field '{field}' must be a string or null, got {type(raw).__name__}"
        )
    return raw


def _str_list_field(value: dict[str, Any], field: str, *, context: str) -> list[str]:
    raw = value.get(field, [])
    if not isinstance(raw, list):
        raise BundleValidationError(
            f"{context}: field '{field}' must be a list of strings, got {type(raw).__name__}"
        )
    for item in raw:
        if not isinstance(item, str):
            raise BundleValidationError(
                f"{context}: field '{field}' must be a list of strings; "
                f"found {type(item).__name__} item {item!r}"
            )
    return [str(item) for item in raw]


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


# content_hash verification states (Spec 003 FR-5.10, RT2-L6). An
# evidence item's declared hash is a CLAIM, not a verification
# result; assessment output marks which of these states the hash is
# in so a republished hash never reads as a verification result.
CONTENT_HASH_VERIFIED = "verified"
CONTENT_HASH_DECLARED = "declared_not_verified"
CONTENT_HASH_MISMATCHED = "mismatched"


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
    # Verification state of content_hash, set ONLY by the evidence
    # checker (aee.evidence_check) when it recomputes the hash in
    # this run. Never loaded from input: from_dict accepts the key
    # (it is in _FIELDS, like Claim's confidence_band) and ignores
    # the value, so a bundle or republished assessment claiming
    # "verified" for itself resets to declared-not-verified on the
    # next assessment (FR-5.10).
    content_hash_status: str | None = None

    @property
    def is_observed(self) -> bool:
        return self.kind == EvidenceKind.OBSERVED

    @property
    def is_model_self_attestation(self) -> bool:
        """Model-quality support of an asserted-like kind (FR-2.6).

        Widened beyond the original exact pair (RT1-13): the gate used
        to require ``kind == asserted AND source_quality == model``,
        so relabelling one item ``asserted`` -> ``inferred`` — still
        model-produced, still unobserved — switched it off. An item
        counts when its declared quality is ``model`` and its kind is
        asserted-like: ``asserted`` (the model states it) or
        ``inferred`` (the model derived it; inference by the same
        model is still self-attestation, not independent evidence).
        Observed model output is NOT self-attestation here: kind
        ``observed`` claims an inspectable measurement, judged by the
        other gates.
        """
        return self.source_quality == SourceQuality.MODEL and self.kind in {
            EvidenceKind.ASSERTED,
            EvidenceKind.INFERRED,
        }

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
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
        if self.content_hash is not None:
            # FR-5.10: a declared hash is always labelled with its
            # verification state; absent a recomputation in this run
            # the honest label is declared_not_verified.
            value["content_hash_status"] = self.content_hash_status or CONTENT_HASH_DECLARED
        return value

    _FIELDS = frozenset(
        {
            "ref",
            "kind",
            "direction",
            "source_quality",
            "description",
            "source_id",
            "independent_of",
            "observed_at",
            "content_hash",
            # Emitted by to_dict as derived output; accepted on load
            # and ignored (never trusted) — see the field's comment.
            "content_hash_status",
        }
    )

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], *, strict: bool = True, context: str = "evidence"
    ) -> Evidence:
        if not strict:
            return cls(
                ref=str(value.get("ref", "")),
                kind=EvidenceKind(value.get("kind", EvidenceKind.ASSERTED.value)),
                direction=EvidenceDirection(
                    value.get("direction", EvidenceDirection.SUPPORTS.value)
                ),
                source_quality=SourceQuality(
                    value.get("source_quality", SourceQuality.UNKNOWN.value)
                ),
                description=str(value.get("description", "")),
                source_id=str(value.get("source_id", "")),
                independent_of=[str(item) for item in value.get("independent_of", [])],
                observed_at=value.get("observed_at"),
                content_hash=value.get("content_hash"),
            )
        if not isinstance(value, dict):
            raise BundleValidationError(
                f"{context}: evidence must be an object, got {type(value).__name__}"
            )
        _check_unknown_fields(value, set(cls._FIELDS), context)
        return cls(
            ref=_str_field(value, "ref", context=context, required=True),
            kind=_enum_field(
                EvidenceKind,
                value.get("kind", EvidenceKind.ASSERTED.value),
                context=context,
                field="kind",
            ),
            direction=_enum_field(
                EvidenceDirection,
                value.get("direction", EvidenceDirection.SUPPORTS.value),
                context=context,
                field="direction",
            ),
            source_quality=_enum_field(
                SourceQuality,
                value.get("source_quality", SourceQuality.UNKNOWN.value),
                context=context,
                field="source_quality",
            ),
            description=_str_field(value, "description", context=context),
            source_id=_str_field(value, "source_id", context=context),
            independent_of=_str_list_field(value, "independent_of", context=context),
            observed_at=_opt_str_field(value, "observed_at", context=context),
            content_hash=_opt_str_field(value, "content_hash", context=context),
        )


@dataclass(slots=True)
class Disposition:
    """A recorded human judgment answering a regenerated challenge
    (Spec 002 FR-5.1).

    A disposition lives on a claim in the bundle, so it persists across
    assessment runs — unlike ``FailureMode.resolved``, which is
    regenerated output state. On assessment, a challenge regenerated
    with the same ``challenge_category`` (the FailureMode ``category``
    value) as a stored disposition is reported resolved, with this
    record attached so the reason stays inspectable (FR-5.2).

    ``kind`` semantics: ``split`` — the claim was split; ``successors``
    names the resulting claim ids (FR-5.3). ``accepted-atomic`` — a
    reviewer judged the claim atomic despite the challenge.
    ``waived`` — the challenge is knowingly set aside. Every kind
    requires a non-empty ``reason``: a judgment without a stated reason
    is not auditable and never loads.
    """

    challenge_category: str
    kind: DispositionKind
    reason: str
    author: str = ""
    date: str = ""
    successors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.challenge_category.strip():
            raise ValueError("disposition challenge_category must not be empty")
        if not self.reason.strip():
            raise ValueError("disposition reason must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "challenge_category": self.challenge_category,
            "kind": self.kind.value,
            "reason": self.reason,
            "author": self.author,
            "date": self.date,
            "successors": list(self.successors),
        }

    _FIELDS = frozenset({"challenge_category", "kind", "reason", "author", "date", "successors"})

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], *, strict: bool = True, context: str = "disposition"
    ) -> Disposition:
        if not strict:
            return cls(
                challenge_category=str(value.get("challenge_category", "")),
                kind=DispositionKind(value.get("kind", DispositionKind.WAIVED.value)),
                reason=str(value.get("reason", "")),
                author=str(value.get("author", "")),
                date=str(value.get("date", "")),
                successors=[normalize_claim_id(str(item)) for item in value.get("successors", [])],
            )
        if not isinstance(value, dict):
            raise BundleValidationError(
                f"{context}: disposition must be an object, got {type(value).__name__}"
            )
        _check_unknown_fields(value, set(cls._FIELDS), context)
        return cls(
            challenge_category=_str_field(
                value, "challenge_category", context=context, required=True, non_empty=True
            ),
            kind=_enum_field(
                DispositionKind,
                value.get("kind", DispositionKind.WAIVED.value),
                context=context,
                field="kind",
            ),
            # FR-5.1: a disposition without a non-empty reason is invalid
            # under strict loading — the reason IS the audit record.
            reason=_str_field(value, "reason", context=context, required=True, non_empty=True),
            author=_str_field(value, "author", context=context),
            date=_str_field(value, "date", context=context),
            successors=[
                normalize_claim_id(ref)
                for ref in _str_list_field(value, "successors", context=context)
            ],
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
    # Set when this failure was resolved by a stored claim disposition
    # (FR-5.2): the disposition travels with the failure so the reason
    # is inspectable in assessment output. History is not erased — the
    # challenge still shows it was raised, and this shows how it was
    # answered.
    disposition: Disposition | None = None

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
            "disposition": self.disposition.to_dict() if self.disposition else None,
        }

    _FIELDS = frozenset(
        {
            "id",
            "claim_id",
            "challenge",
            "breakpoint",
            "severity",
            "category",
            "recovery_hint",
            "resolved",
            "disposition",
        }
    )

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], *, strict: bool = True, context: str = "failure mode"
    ) -> FailureMode:
        if not strict:
            raw_disposition = value.get("disposition")
            return cls(
                id=str(value.get("id", "")),
                claim_id=normalize_claim_id(str(value.get("claim_id", ""))),
                challenge=str(value.get("challenge", "")),
                breakpoint=str(value.get("breakpoint", "")),
                severity=Severity(value.get("severity", Severity.MEDIUM.value)),
                category=str(value.get("category", "other")),
                recovery_hint=str(value.get("recovery_hint", "")),
                resolved=bool(value.get("resolved", False)),
                disposition=(
                    Disposition.from_dict(raw_disposition, strict=False)
                    if isinstance(raw_disposition, dict)
                    else None
                ),
            )
        if not isinstance(value, dict):
            raise BundleValidationError(
                f"{context}: failure mode must be an object, got {type(value).__name__}"
            )
        _check_unknown_fields(value, set(cls._FIELDS), context)
        resolved = value.get("resolved", False)
        if not isinstance(resolved, bool):
            raise BundleValidationError(
                f"{context}: field 'resolved' must be a boolean, got {type(resolved).__name__}"
            )
        raw_disposition = value.get("disposition")
        if raw_disposition is not None and not isinstance(raw_disposition, dict):
            raise BundleValidationError(
                f"{context}: field 'disposition' must be an object or null, "
                f"got {type(raw_disposition).__name__}"
            )
        return cls(
            id=_str_field(value, "id", context=context, required=True, non_empty=True),
            claim_id=normalize_claim_id(
                _str_field(value, "claim_id", context=context, required=True)
            ),
            challenge=_str_field(
                value, "challenge", context=context, required=True, non_empty=True
            ),
            breakpoint=_str_field(value, "breakpoint", context=context),
            severity=_enum_field(
                Severity,
                value.get("severity", Severity.MEDIUM.value),
                context=context,
                field="severity",
            ),
            category=_str_field(value, "category", context=context, default="other"),
            recovery_hint=_str_field(value, "recovery_hint", context=context),
            resolved=resolved,
            disposition=(
                Disposition.from_dict(raw_disposition, context=f"{context} disposition")
                if isinstance(raw_disposition, dict)
                else None
            ),
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
    # Stored challenge dispositions (FR-5.1): bundle input, persisted
    # across runs — distinct from `failures`, which are regenerated
    # output state. See Disposition.
    dispositions: list[Disposition] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("claim id must not be empty")
        if not 0.0 <= (self.confidence if self.confidence is not None else 0.0) <= 1.0:
            raise ValueError("claim confidence must be between 0 and 1")

    @property
    def unresolved_failures(self) -> list[FailureMode]:
        return [failure for failure in self.failures if not failure.resolved]

    def disposition_for(self, challenge_category: str) -> Disposition | None:
        """The stored disposition answering a challenge category, if any.

        Disposition matching keys on (claim, challenge_category): the
        disposition lives on the claim, and ``challenge_category`` is the
        regenerated failure's ``category`` value. First match wins.
        """
        for disposition in self.dispositions:
            if disposition.challenge_category == challenge_category:
                return disposition
        return None

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
            "dispositions": [disposition.to_dict() for disposition in self.dispositions],
        }

    # 'confidence_band' is emitted by to_dict as derived output; it is a
    # known field on load (accepted, recomputed, never trusted as input).
    _FIELDS = frozenset(
        {
            "id",
            "text",
            "kind",
            "status",
            "boundary",
            "depends_on",
            "conflicts_with",
            "evidence",
            "assumptions",
            "alternatives",
            "falsification_tests",
            "uncertainty",
            "severity",
            "source_ref",
            "domain",
            "confidence",
            "confidence_band",
            "failures",
            "metadata",
            "dispositions",
        }
    )

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], *, strict: bool = True, context: str | None = None
    ) -> Claim:
        """Load a claim. Strict by default (Spec 002 FR-1): unknown fields,
        missing/empty text, bad enum values, and wrong types are loud errors
        naming the claim id, the field, and the problem. ``strict=False`` is
        the explicitly-named lenient compatibility path (FR-1.3) — it keeps
        the historical default-everything behavior for internal extraction
        use and is echoed into assessment metadata wherever a command
        exposes it."""
        if not strict:
            confidence = value.get("confidence")
            return cls(
                # FR-5.7: id identity is normalised on every load path,
                # lenient included — split identities are a correctness
                # defect, not a strictness preference.
                id=normalize_claim_id(str(value.get("id", ""))),
                text=str(value.get("text", "")),
                kind=ClaimKind(value.get("kind", ClaimKind.ASSUMPTION.value)),
                status=ClaimStatus(value.get("status", ClaimStatus.DRAFT.value)),
                boundary=[str(item) for item in value.get("boundary", [])],
                depends_on=[normalize_claim_id(str(item)) for item in value.get("depends_on", [])],
                conflicts_with=[
                    normalize_claim_id(str(item)) for item in value.get("conflicts_with", [])
                ],
                evidence=[
                    Evidence.from_dict(item, strict=False) for item in value.get("evidence", [])
                ],
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
                failures=[
                    FailureMode.from_dict(item, strict=False) for item in value.get("failures", [])
                ],
                metadata=dict(value.get("metadata", {})),
                dispositions=[
                    Disposition.from_dict(item, strict=False)
                    for item in value.get("dispositions", [])
                ],
            )
        if not isinstance(value, dict):
            raise BundleValidationError(
                f"{context or 'claim'}: claim must be an object, got {type(value).__name__}"
            )
        raw_id = value.get("id")
        ctx = context or (f"claim '{raw_id}'" if isinstance(raw_id, str) and raw_id else "claim")
        _check_unknown_fields(value, set(cls._FIELDS), ctx)
        claim_id = _str_field(value, "id", context=ctx, required=True, non_empty=True)
        ctx = context or f"claim '{claim_id}'"
        text = _str_field(value, "text", context=ctx, required=True, non_empty=True)
        evidence_raw = value.get("evidence", [])
        if not isinstance(evidence_raw, list):
            raise BundleValidationError(
                f"{ctx}: field 'evidence' must be a list, got {type(evidence_raw).__name__}"
            )
        failures_raw = value.get("failures", [])
        if not isinstance(failures_raw, list):
            raise BundleValidationError(
                f"{ctx}: field 'failures' must be a list, got {type(failures_raw).__name__}"
            )
        dispositions_raw = value.get("dispositions", [])
        if not isinstance(dispositions_raw, list):
            raise BundleValidationError(
                f"{ctx}: field 'dispositions' must be a list, got {type(dispositions_raw).__name__}"
            )
        metadata = value.get("metadata", {})
        if not isinstance(metadata, dict):
            raise BundleValidationError(
                f"{ctx}: field 'metadata' must be an object, got {type(metadata).__name__}"
            )
        confidence = value.get("confidence")
        confidence_value: float | None = None
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise BundleValidationError(
                    f"{ctx}: field 'confidence' must be a number or null, "
                    f"got {type(confidence).__name__}"
                )
            try:
                confidence_value = float(confidence)
            except OverflowError:
                # A several-hundred-digit integer literal is a valid
                # JSON number but not a valid confidence (RT2-M6):
                # name it here instead of leaking OverflowError from
                # the constructor call below.
                raise BundleValidationError(
                    f"{ctx}: field 'confidence' is out of range; must be between 0 and 1"
                ) from None
            if not 0.0 <= confidence_value <= 1.0:
                raise BundleValidationError(
                    f"{ctx}: field 'confidence' must be between 0 and 1, got {confidence_value!r}"
                )
        falsification_tests = _str_list_field(value, "falsification_tests", context=ctx)
        # FR-2.3: a falsification test still carrying the drafting
        # TODO marker is an unfinished draft, not a claim. Strict
        # loading rejects it so a draft cannot sneak past FR-1 with a
        # placeholder where its falsifier belongs; a human completing
        # the test is the ratification step. The lenient path is
        # exempt (it is the historical silent behaviour, by name).
        for test in falsification_tests:
            if re.match(r"TODO\b", test.strip()):
                raise BundleValidationError(
                    f"{ctx}: field 'falsification_tests' contains a TODO "
                    f"placeholder ({test!r}); a human must write a real "
                    "falsification test before this claim can load strictly"
                )
        try:
            return cls(
                id=normalize_claim_id(claim_id),
                text=text,
                kind=_enum_field(
                    ClaimKind,
                    value.get("kind", ClaimKind.ASSUMPTION.value),
                    context=ctx,
                    field="kind",
                ),
                status=_enum_field(
                    ClaimStatus,
                    value.get("status", ClaimStatus.DRAFT.value),
                    context=ctx,
                    field="status",
                ),
                boundary=_str_list_field(value, "boundary", context=ctx),
                depends_on=[
                    normalize_claim_id(ref)
                    for ref in _str_list_field(value, "depends_on", context=ctx)
                ],
                conflicts_with=[
                    normalize_claim_id(ref)
                    for ref in _str_list_field(value, "conflicts_with", context=ctx)
                ],
                evidence=[
                    Evidence.from_dict(item, context=f"{ctx} evidence[{index}]")
                    for index, item in enumerate(evidence_raw)
                ],
                assumptions=_str_list_field(value, "assumptions", context=ctx),
                alternatives=_str_list_field(value, "alternatives", context=ctx),
                falsification_tests=falsification_tests,
                uncertainty=_enum_field(
                    Uncertainty,
                    value.get("uncertainty", Uncertainty.INSUFFICIENT_EVIDENCE.value),
                    context=ctx,
                    field="uncertainty",
                ),
                severity=_enum_field(
                    Severity,
                    value.get("severity", Severity.MEDIUM.value),
                    context=ctx,
                    field="severity",
                ),
                source_ref=_str_field(value, "source_ref", context=ctx),
                domain=_str_field(value, "domain", context=ctx),
                confidence=confidence_value,
                failures=[
                    FailureMode.from_dict(item, context=f"{ctx} failures[{index}]")
                    for index, item in enumerate(failures_raw)
                ],
                metadata=dict(metadata),
                dispositions=[
                    Disposition.from_dict(item, context=f"{ctx} dispositions[{index}]")
                    for index, item in enumerate(dispositions_raw)
                ],
            )
        except BundleValidationError:
            raise
        except ValueError as exc:  # e.g. __post_init__ confidence range
            raise BundleValidationError(f"{ctx}: {exc}") from None
