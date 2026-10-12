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


class ClaimStage(StrEnum):
    """Lifecycle stage of a claim (Spec 004 R1.1, OD-T2 ratified).

    Tao's five stage terms verbatim: a claim is ``created``, then
    ``checked``, ``explained``, ``accepted``, and ``digested``.
    Stage is a stored record advanced only by recorded stage events
    (R1.2), never recomputed from a score.
    """

    CREATED = "created"
    CHECKED = "checked"
    EXPLAINED = "explained"
    ACCEPTED = "accepted"
    DIGESTED = "digested"


STAGE_ORDER: dict[ClaimStage, int] = {
    ClaimStage.CREATED: 0,
    ClaimStage.CHECKED: 1,
    ClaimStage.EXPLAINED: 2,
    ClaimStage.ACCEPTED: 3,
    ClaimStage.DIGESTED: 4,
}

# The five required sub-claim roles for a headline claim (Spec 004
# R2.1). A headline claim's decomposition is complete only when a
# linked (`depends_on`) sub-claim exists for every role here.
DECOMPOSITION_ROLES: tuple[str, ...] = (
    "statement-fidelity",
    "evidence-verification",
    "novelty",
    "attribution",
    "significance",
)


class EvidenceKind(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    ASSERTED = "asserted"
    CONTRADICTED = "contradicted"
    UNSUPPORTED = "unsupported"
    # Spec 004 R3.1: evidence that a named human explained the claim.
    # Strict loading enforces the named-human rule on this kind
    # (R3.2, OD-T4): see validate_exposition_evidence.
    EXPOSITION = "exposition"


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
    | type[ClaimStage]
    | type[EvidenceKind]
    | type[EvidenceDirection]
    | type[SourceQuality]
    | type[Uncertainty]
    | type[Severity]
    | type[DispositionKind]
    | type[StageEventKind]
    | type[IdentityKind],
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


def _bool_field(value: dict[str, Any], field: str, *, context: str) -> bool:
    raw = value.get(field, False)
    if not isinstance(raw, bool):
        raise BundleValidationError(
            f"{context}: field '{field}' must be a boolean, got {type(raw).__name__}"
        )
    return raw


def _role_field(value: dict[str, Any], context: str) -> str | None:
    """A sub-claim's decomposition role (Spec 004 R2.1): null, or one
    of DECOMPOSITION_ROLES - anything else is a loud strict error."""
    raw = value.get("role")
    if raw is None:
        return None
    if not isinstance(raw, str) or raw not in DECOMPOSITION_ROLES:
        valid = ", ".join(DECOMPOSITION_ROLES)
        raise BundleValidationError(
            f"{context}: field 'role' has invalid value {raw!r}; "
            f"valid values: {valid} (or null for a non-sub-claim)"
        )
    return raw


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


class IdentityKind(StrEnum):
    """What a project-local identity registry entry IS (Spec 004 OD-T4).

    Only ``person`` entries can satisfy the named-human rule for
    exposition evidence (R3.2). The other values exist so a registry
    can declare a tool, model, or team alias explicitly — and so the
    engine can reject it by shape, not by guessing from the id.
    """

    PERSON = "person"
    TOOL = "tool"
    MODEL = "model"
    TEAM = "team"


@dataclass(slots=True)
class IdentityEntry:
    """One entry in a project-local identity registry (OD-T4)."""

    id: str
    name: str = ""
    kind: IdentityKind = IdentityKind.PERSON

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("identity entry id must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "kind": self.kind.value}

    _FIELDS = frozenset({"id", "name", "kind"})

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], *, strict: bool = True, context: str = "identity entry"
    ) -> IdentityEntry:
        if not strict:
            return cls(
                id=str(value.get("id", "")),
                name=str(value.get("name", "")),
                kind=IdentityKind(value.get("kind", IdentityKind.PERSON.value)),
            )
        if not isinstance(value, dict):
            raise BundleValidationError(
                f"{context}: identity entry must be an object, got {type(value).__name__}"
            )
        _check_unknown_fields(value, set(cls._FIELDS), context)
        return cls(
            id=_str_field(value, "id", context=context, required=True, non_empty=True),
            name=_str_field(value, "name", context=context),
            kind=_enum_field(
                IdentityKind,
                value.get("kind", IdentityKind.PERSON.value),
                context=context,
                field="kind",
            ),
        )


@dataclass(slots=True)
class IdentityRegistry:
    """A project-local registry of named identities (Spec 004 OD-T4).

    The engine cannot own a global person registry, so a deployment
    supplies one: either a bundle-adjacent ``identities.json`` file
    (discovered by ``aee.extract.load_claims`` beside the bundle) or
    an explicit registry passed to the loader / ``--identity-registry``
    on the CLI. File shape: ``{"identities": [{"id": ..., "name": ...,
    "kind": "person"}, ...]}`` (a bare list, or an object mapping id
    to entry, is also accepted). Resolution is by exact ``id`` match
    against an exposition item's ``source_id``.
    """

    entries: dict[str, IdentityEntry] = field(default_factory=dict)

    def resolve(self, source_id: str) -> IdentityEntry | None:
        return self.entries.get(source_id)

    @classmethod
    def from_dict(cls, value: Any, *, context: str = "identity registry") -> IdentityRegistry:
        # Normalise the accepted shapes to raw entry rows first, so
        # the registry-level rules below run in a fixed order:
        # duplicate ids are reported before per-entry shape problems
        # (a registry with two spellings of one id is ambiguous no
        # matter what else is wrong with it). Ported from the
        # orphaned P0-completion branch @ 5fa2fdf during the Spec 004
        # integration; the stack's registry accepted the same shapes
        # but silently defaulted a missing `kind` to `person`.
        raw_rows: list[tuple[Any, str]]
        if isinstance(value, dict) and "identities" in value:
            rows = value["identities"]
            if not isinstance(rows, list):
                raise BundleValidationError(f"{context}: field 'identities' must be a list")
            raw_rows = [(row, f"{context} identities[{index}]") for index, row in enumerate(rows)]
        elif isinstance(value, list):
            raw_rows = [(row, f"{context} identities[{index}]") for index, row in enumerate(value)]
        elif isinstance(value, dict):
            raw_rows = []
            for entry_id, row in value.items():
                if not isinstance(row, dict):
                    raise BundleValidationError(
                        f"{context}: entry '{entry_id}' must be an object, got {type(row).__name__}"
                    )
                raw_rows.append(({"id": entry_id, **row}, f"{context} entry '{entry_id}'"))
        else:
            raise BundleValidationError(
                f"{context}: registry must be an object or a list, got {type(value).__name__}"
            )
        seen_ids: set[str] = set()
        for row, _row_ctx in raw_rows:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                if row["id"] in seen_ids:
                    raise BundleValidationError(f"{context}: duplicate identity id '{row['id']}'")
                seen_ids.add(row["id"])
        parsed: list[IdentityEntry] = []
        for row, row_ctx in raw_rows:
            # OD-T4 shape rule: an entry must DECLARE its kind. An
            # entry with no `kind` does not silently become a person
            # — "needs kind == 'person'" means the registry says so.
            if isinstance(row, dict) and "kind" not in row:
                raise BundleValidationError(
                    f"{row_ctx}: field 'kind' is required but missing; an identity "
                    "entry must declare its kind ('person', 'tool', 'model', or "
                    "'team') — only a declared 'person' can resolve as an explainer "
                    "(Spec 004 R3.2/OD-T4)"
                )
            parsed.append(IdentityEntry.from_dict(row, context=row_ctx))
        return cls(entries={entry.id: entry for entry in parsed})

    @classmethod
    def from_path(cls, path: str) -> IdentityRegistry:
        import json
        from pathlib import Path

        source = Path(path)
        try:
            value = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise BundleValidationError(
                f"identity registry {source.as_posix()}: cannot load: {exc}"
            ) from None
        return cls.from_dict(value, context=f"identity registry {source.as_posix()}")


def validate_exposition_evidence(
    evidence: Evidence, registry: IdentityRegistry | None, *, context: str
) -> None:
    """The named-human rule for exposition evidence (Spec 004 R3.2).

    Strict loading rejects, in the FR-1 error shape (claim, field,
    problem, valid alternatives where enumerable): an exposition item
    with an empty ``source_id``; an exposition item when no identity
    registry is available; a ``source_id`` that does not resolve in
    the registry; and a ``source_id`` resolving to an entry that is
    not a person (a tool, model, or team alias — even when the id
    matches). A model-generated explanation attached as exposition is
    a load error, not a judgment call.
    """
    if evidence.kind != EvidenceKind.EXPOSITION:
        return
    ctx = f"{context}: field 'source_id'"
    if not evidence.source_id.strip():
        raise BundleValidationError(
            f"{ctx} must not be empty for exposition evidence (Spec 004 R3.2): "
            "exposition requires a named human; name the explainer by the id of a "
            "'person' entry in the project identity registry"
        )
    if registry is None:
        raise BundleValidationError(
            f"{ctx} value {evidence.source_id!r} cannot be resolved: no identity "
            "registry is available for exposition evidence (Spec 004 R3.2/OD-T4); "
            "supply one via a bundle-adjacent identities.json file, "
            "load_claims(identity_registry=...), or --identity-registry"
        )
    entry = registry.resolve(evidence.source_id)
    if entry is None:
        known = ", ".join(sorted(registry.entries)) or "(registry is empty)"
        raise BundleValidationError(
            f"{ctx} value {evidence.source_id!r} does not resolve in the identity "
            f"registry (Spec 004 R3.2); registered ids: {known}"
        )
    if entry.kind != IdentityKind.PERSON:
        raise BundleValidationError(
            f"{ctx} value {evidence.source_id!r} resolves to identity "
            f"'{entry.id}' of kind '{entry.kind.value}', not 'person' "
            "(Spec 004 R3.2): exposition requires a named human — a tool, "
            "model, or team alias cannot explain a claim"
        )


class StageEventKind(StrEnum):
    """Kind of a recorded stage-advance event (Spec 004 R1.2).

    The kind names the stage the event advanced the claim TO:
    ``checked`` (an assessment run), ``explained`` (exposition
    evidence under R3), ``accepted`` (a recorded human acceptance),
    ``digested`` (a digestion record under R3.4), ``created`` (the
    claim's creation, when recorded).
    """

    CREATED = "created"
    CHECKED = "checked"
    EXPLAINED = "explained"
    ACCEPTED = "accepted"
    DIGESTED = "digested"


@dataclass(slots=True)
class StageEvent:
    """A recorded stage-advance event on a claim (Spec 004 R1.2).

    Stored on the claim in the dispositions precedent (Spec 002
    FR-5): kind, author, date, and a non-empty ``basis`` — the reason
    / evidence the advance rests on. A stage is a stored record,
    never silently recomputed; the event that advanced a claim is
    inspectable in the claim's record.
    """

    kind: StageEventKind
    basis: str
    author: str = ""
    date: str = ""

    def __post_init__(self) -> None:
        if not self.basis.strip():
            raise ValueError("stage event basis must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "author": self.author,
            "date": self.date,
            "basis": self.basis,
        }

    _FIELDS = frozenset({"kind", "author", "date", "basis"})

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], *, strict: bool = True, context: str = "stage event"
    ) -> StageEvent:
        if not strict:
            return cls(
                kind=StageEventKind(value.get("kind", StageEventKind.CREATED.value)),
                basis=str(value.get("basis", "")),
                author=str(value.get("author", "")),
                date=str(value.get("date", "")),
            )
        if not isinstance(value, dict):
            raise BundleValidationError(
                f"{context}: stage event must be an object, got {type(value).__name__}"
            )
        _check_unknown_fields(value, set(cls._FIELDS), context)
        return cls(
            kind=_enum_field(
                StageEventKind,
                value.get("kind", StageEventKind.CREATED.value),
                context=context,
                field="kind",
            ),
            # R1.2: an advance without a stated basis is not auditable.
            basis=_str_field(value, "basis", context=context, required=True, non_empty=True),
            author=_str_field(value, "author", context=context),
            date=_str_field(value, "date", context=context),
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
    # Lifecycle stage (Spec 004 R1.1/R1.2): a stored record, advanced
    # only by recorded stage events, never by score. `stage_defaulted`
    # is load-time bookkeeping (never serialised): True when the
    # lenient loader supplied the `created` default for a bundle that
    # carried no stage, so the assessment can record the default
    # (R1.1 - silence is never the compatibility strategy).
    stage: ClaimStage = ClaimStage.CREATED
    stage_events: list[StageEvent] = field(default_factory=list)
    stage_defaulted: bool = False
    # More load-time bookkeeping (never serialised; ported from the
    # orphaned P0-completion branch impl/004-p0-vocabulary @ 5fa2fdf
    # during the Spec 004 integration): `stage_derived` is True when
    # the lenient loader derived the stage from the latest recorded
    # stage event because the bundle carried events but no stored
    # stage (stored stage wins; else derive from the latest event;
    # else `created`). `unresolved_exposition` lists the source_ids
    # of exposition items that FAILED identity resolution on the
    # lenient path (R3.2): the engine re-emits them as
    # `identity_resolution` failure modes at assessment time (the
    # stress tester replaces `failures` wholesale, so a load-time
    # record alone would be lost) and digestion tracking gives those
    # items no explanation credit.
    stage_derived: bool = False
    unresolved_exposition: list[str] = field(default_factory=list)
    # Decomposition (Spec 004 R2): a headline claim requires five
    # linked sub-claims, one per role in DECOMPOSITION_ROLES; a
    # sub-claim declares its role here. Structural only (R2.4) - the
    # engine checks that the roles exist and are linked via
    # `depends_on`, never that the text discharges the role.
    headline: bool = False
    role: str | None = None

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

    def advance_stage(
        self, stage: ClaimStage, *, author: str = "", date: str = "", basis: str
    ) -> StageEvent:
        """Advance the claim's stage, recording the event (R1.2).

        The ONLY way stage moves: an explicit, recorded event with a
        basis. Forward-only - a backward move is a reclassification,
        which is append-only record work, not a silent rewrite; and
        no score anywhere calls this, so stage never advances by
        score.
        """
        if STAGE_ORDER[stage] <= STAGE_ORDER[self.stage]:
            raise ValueError(
                f"stage advance must move forward: claim is at '{self.stage.value}', "
                f"cannot advance to '{stage.value}'"
            )
        event = StageEvent(kind=StageEventKind(stage.value), basis=basis, author=author, date=date)
        self.stage_events.append(event)
        self.stage = stage
        self.stage_defaulted = False
        return event

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
            "stage": self.stage.value,
            "stage_events": [event.to_dict() for event in self.stage_events],
            "headline": self.headline,
            "role": self.role,
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
            "stage",
            "stage_events",
            "headline",
            "role",
        }
    )

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        strict: bool = True,
        context: str | None = None,
        identity_registry: IdentityRegistry | None = None,
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
            claim = cls(
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
                # R1.1 lenient path: a bundle without a stage loads
                # with stage `created`, and the default is RECORDED
                # on the claim (stage_defaulted) so the assessment
                # metadata can name every claim it touched.
                stage=ClaimStage(value.get("stage", ClaimStage.CREATED.value)),
                stage_events=[
                    StageEvent.from_dict(item, strict=False)
                    for item in value.get("stage_events", [])
                ],
                stage_defaulted="stage" not in value,
                headline=bool(value.get("headline", False)),
                role=(str(value["role"]) if value.get("role") is not None else None),
            )
            # Stage resolution (R1.1/R1.2; ported from the orphaned
            # P0-completion branch @ 5fa2fdf): a stored stage wins;
            # with no stored stage, the stage is DERIVED from the
            # latest recorded stage event when events exist; only
            # with neither does the lenient `created` default apply
            # (and stay recorded via stage_defaulted).
            if "stage" not in value and claim.stage_events:
                claim.stage = ClaimStage(claim.stage_events[-1].kind.value)
                claim.stage_defaulted = False
                claim.stage_derived = True
            # R3.2 on the lenient path (same port): an exposition
            # item that fails identity resolution is not a load error
            # here — it becomes a claim-attributed failure mode
            # (category `identity_resolution`) and confers no
            # explanation credit (its source_id is recorded on
            # `unresolved_exposition`; the engine re-emits the failure
            # at assessment time). A registry that fails to PARSE is a
            # hard error in both modes — that happens in
            # IdentityRegistry.from_path, before this code runs.
            lenient_ctx = context or f"claim '{claim.id}'"
            for index, item in enumerate(claim.evidence):
                if item.kind != EvidenceKind.EXPOSITION:
                    continue
                try:
                    validate_exposition_evidence(
                        item, identity_registry, context=f"{lenient_ctx} evidence[{index}]"
                    )
                except BundleValidationError as exc:
                    claim.unresolved_exposition.append(item.source_id)
                    claim.failures.append(
                        FailureMode(
                            id=f"AEE-{claim.id}-IDENTITY-RESOLUTION-{index}",
                            claim_id=claim.id,
                            challenge="Exposition identity resolution (lenient load)",
                            breakpoint=str(exc),
                            severity=Severity.MEDIUM,
                            category="identity_resolution",
                            recovery_hint=(
                                "Name a 'person' entry of the project identity "
                                "registry as the exposition item's source_id, or "
                                "load strictly to see the FR-1 error shape."
                            ),
                        )
                    )
            return claim
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
        stage_events_raw = value.get("stage_events", [])
        if not isinstance(stage_events_raw, list):
            raise BundleValidationError(
                f"{ctx}: field 'stage_events' must be a list, got {type(stage_events_raw).__name__}"
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
            claim = cls(
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
                stage=_enum_field(
                    ClaimStage,
                    value.get("stage", ClaimStage.CREATED.value),
                    context=ctx,
                    field="stage",
                ),
                stage_events=[
                    StageEvent.from_dict(item, context=f"{ctx} stage_events[{index}]")
                    for index, item in enumerate(stage_events_raw)
                ],
                headline=_bool_field(value, "headline", context=ctx),
                role=_role_field(value, ctx),
            )
        except BundleValidationError:
            raise
        except ValueError as exc:  # e.g. __post_init__ confidence range
            raise BundleValidationError(f"{ctx}: {exc}") from None
        # R1.1: stage is a REQUIRED field under strict loading. The
        # check runs after every other field has been parsed, so a
        # bundle with several problems still reports the most specific
        # one first (the FR-1 error precedence the existing fixtures
        # pin); a bundle whose only problem is the missing stage gets
        # this loud, named error. Pre-realignment bundles take the
        # lenient path (default `created`, recorded) or `aee migrate`
        # (backfill `created`, reported per claim).
        if "stage" not in value:
            valid = ", ".join(member.value for member in ClaimStage)
            raise BundleValidationError(
                f"{ctx}: field 'stage' is required but missing (Spec 004 R1.1); "
                f"valid values: {valid}; run 'aee migrate' to backfill "
                "'created', or load leniently to default it (the default "
                "is recorded in the assessment metadata)"
            )
        # R3.2: exposition evidence must name a resolvable human.
        for index, item in enumerate(claim.evidence):
            validate_exposition_evidence(
                item, identity_registry, context=f"{ctx} evidence[{index}]"
            )
        return claim
