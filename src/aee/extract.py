"""Conservative claim extraction from structured JSON and Markdown."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from aee.model import (
    BundleValidationError,
    Claim,
    ClaimKind,
    ClaimStatus,
    DispositionKind,
    Evidence,
    EvidenceKind,
    FailureMode,
    Uncertainty,
)

_ID = r"(?:REQ|CLM|HYP|DEC|ASM|COMP)-[A-Z0-9][A-Z0-9-]*"
_HEADING = re.compile(rf"^#{{1,6}}\s+({_ID})(?:\s*[-—:.]\s*(.*))?$", re.IGNORECASE)
_INLINE_ID = re.compile(rf"^\s*[-*]\s+\*\*ID:?\*\*:?\s*({_ID})\s*$", re.IGNORECASE)
_FIELD = re.compile(r"^\s*[-*]\s+\*\*(.+?):?\*\*:?\s*(.+)$")


def load_claims(path: str | Path, *, strict: bool = True) -> list[Claim]:
    """Load a claims bundle. Strict by default (Spec 002 FR-1.1);
    ``strict=False`` is the explicitly-named lenient compatibility mode
    (FR-1.3) and exists for internal extraction use."""
    source = Path(path)
    if source.suffix.lower() == ".json":
        value = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            if "claims" not in value:
                raise ValueError(
                    "JSON object input must contain a 'claims' list; "
                    "refusing to treat a missing key as an empty claim set"
                )
            rows = value["claims"]
        else:
            rows = value
        if not isinstance(rows, list):
            raise ValueError("JSON input must be a claim list or contain a 'claims' list")
        claims: list[Claim] = []
        for index, row in enumerate(rows):
            if strict and not isinstance(row, dict):
                raise BundleValidationError(
                    f"claims[{index}]: claim must be an object, got {type(row).__name__}"
                )
            row_id = row.get("id") if isinstance(row, dict) else None
            context = (
                f"claim '{row_id}'" if isinstance(row_id, str) and row_id else f"claims[{index}]"
            )
            claims.append(Claim.from_dict(row, strict=strict, context=context))
        return claims
    return extract_markdown_claims(source)


def validate_bundle_structure(claims: list[Claim]) -> tuple[list[str], list[str]]:
    """Structural checks beyond per-claim loading (for ``aee validate``):
    duplicate ids and self-references are errors; references to claims
    outside the bundle are warnings (bundles may be partial by design)."""
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        if claim.id in seen:
            errors.append(f"claim '{claim.id}': duplicate claim id in bundle")
        seen.add(claim.id)
    for claim in claims:
        for ref in claim.depends_on:
            if ref == claim.id:
                errors.append(f"claim '{claim.id}': depends_on references itself")
            elif ref not in seen:
                warnings.append(
                    f"claim '{claim.id}': depends_on references '{ref}', "
                    "which is not in this bundle"
                )
        for ref in claim.conflicts_with:
            if ref == claim.id:
                errors.append(f"claim '{claim.id}': conflicts_with references itself")
            elif ref not in seen:
                warnings.append(
                    f"claim '{claim.id}': conflicts_with references '{ref}', "
                    "which is not in this bundle"
                )
        # FR-5.3: split dispositions name their successors; a successor
        # outside the bundle is a warning here (assessment reports it
        # as a failure mode as well).
        for disposition in claim.dispositions:
            if disposition.kind is not DispositionKind.SPLIT:
                continue
            if not disposition.successors:
                warnings.append(
                    f"claim '{claim.id}': split disposition for "
                    f"'{disposition.challenge_category}' names no successor claims"
                )
            for ref in disposition.successors:
                if ref not in seen:
                    warnings.append(
                        f"claim '{claim.id}': split disposition successor '{ref}' "
                        "is not in this bundle"
                    )
    return errors, warnings


# --- Legacy bundle migration (Spec 002 FR-1.5) ---------------------------------
# Vocabulary verified against the founding Tekmerion Spec 001 bundle
# (tekmerion c1b660e, specs/001-research-engine/aee-claims.json): fields
# statement/falsifier, evidence as bare ref strings, kinds design/scope,
# statuses asserted-design/proposed-pending-owner. The kind/status targets
# match the human normalization that bundle later received in-repo
# (design -> requirement, scope -> decision, asserted-design -> draft);
# proposed-pending-owner maps to draft because a pending claim has not
# been ratified — mapping it to supported would inflate its status.
LEGACY_CLAIM_FIELD_MAP: dict[str, str] = {
    "statement": "text",
    "proposition": "text",
    "falsifier": "falsification_tests",
    "falsifiers": "falsification_tests",
    "dependencies": "depends_on",
    "conflicts": "conflicts_with",
    "source": "source_ref",
    "bounds": "boundary",
}
LEGACY_EVIDENCE_FIELD_MAP: dict[str, str] = {
    "url": "ref",
    "path": "ref",
    "quality": "source_quality",
    "type": "kind",
}
LEGACY_KIND_MAP: dict[str, str] = {
    "design": "requirement",
    "scope": "decision",
    "goal": "requirement",
    "principle": "assumption",
    "question": "hypothesis",
}
LEGACY_STATUS_MAP: dict[str, str] = {
    "asserted-design": "draft",
    "asserted": "draft",
    "proposed": "draft",
    "proposed-pending-owner": "draft",
    "pending": "draft",
    "accepted": "supported",
    "verified": "supported",
    "partial": "partially_supported",
    "refuted": "contradicted",
}
LEGACY_EVIDENCE_KIND_MAP: dict[str, str] = {
    "document": "asserted",
    "observation": "observed",
}


def _migrate_enum(
    row: dict[str, Any],
    field: str,
    valid: set[str],
    mapping: dict[str, str],
    ctx: str,
    report: list[str],
) -> None:
    raw = row.get(field)
    if raw is None or raw in valid:
        return
    if raw in mapping:
        report.append(f"{ctx}: {field} '{raw}' -> '{mapping[raw]}'")
        row[field] = mapping[raw]
        return
    raise BundleValidationError(
        f"{ctx}: field '{field}' has legacy value {raw!r} with no known mapping; "
        f"valid values: {', '.join(sorted(valid))}; "
        f"known legacy values: {', '.join(sorted(mapping))}"
    )


def _migrate_evidence(item: Any, ctx: str, report: list[str]) -> dict[str, Any]:
    if isinstance(item, str):
        report.append(f"{ctx}: evidence ref string '{item}' -> evidence object")
        return {"ref": item}
    if not isinstance(item, dict):
        raise BundleValidationError(
            f"{ctx}: evidence must be a ref string or an object, got {type(item).__name__}"
        )
    out: dict[str, Any] = {}
    for key, val in item.items():
        target = LEGACY_EVIDENCE_FIELD_MAP.get(key, key)
        if target not in Evidence._FIELDS:
            raise BundleValidationError(
                f"{ctx}: evidence field '{key}' has no known mapping and is not a "
                "current evidence field; refusing to guess"
            )
        if target in out:
            raise BundleValidationError(
                f"{ctx}: evidence has both '{key}' and its mapping target '{target}'"
            )
        if target != key:
            report.append(f"{ctx}: evidence field '{key}' -> '{target}'")
        out[target] = val
    _migrate_enum(
        out, "kind", {m.value for m in EvidenceKind}, LEGACY_EVIDENCE_KIND_MAP, ctx, report
    )
    return out


def migrate_bundle(value: Any) -> tuple[dict[str, Any], list[str]]:
    """Convert a pre-engine legacy bundle to the current format.

    Returns ``(migrated, report)`` where report names every mapping
    applied. Any field or value with no known mapping raises
    BundleValidationError — migration never guesses silently (FR-1.5).
    The migrated bundle is strict-loaded before returning, so a
    successful migration is guaranteed assessable."""
    if isinstance(value, dict):
        if "claims" not in value:
            raise BundleValidationError("migrate: JSON object input must contain a 'claims' list")
        rows = value["claims"]
        bundle: dict[str, Any] = {k: v for k, v in value.items() if k != "claims"}
    elif isinstance(value, list):
        rows = value
        bundle = {}
    else:
        raise BundleValidationError(
            f"migrate: bundle must be an object or a list, got {type(value).__name__}"
        )
    if not isinstance(rows, list):
        raise BundleValidationError("migrate: 'claims' must be a list")
    report: list[str] = []
    migrated_rows: list[dict[str, Any]] = []
    valid_kinds = {m.value for m in ClaimKind}
    valid_statuses = {m.value for m in ClaimStatus}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise BundleValidationError(
                f"claims[{index}]: claim must be an object, got {type(row).__name__}"
            )
        raw_id = row.get("id")
        ctx = f"claim '{raw_id}'" if isinstance(raw_id, str) and raw_id else f"claims[{index}]"
        out: dict[str, Any] = {}
        for key, val in row.items():
            target = LEGACY_CLAIM_FIELD_MAP.get(key, key)
            if target not in Claim._FIELDS:
                raise BundleValidationError(
                    f"{ctx}: field '{key}' has no known mapping and is not a "
                    "current claim field; refusing to guess"
                )
            if target in out:
                raise BundleValidationError(
                    f"{ctx}: claim has both '{key}' and its mapping target '{target}'"
                )
            if target != key:
                report.append(f"{ctx}: field '{key}' -> '{target}'")
            out[target] = val
        falsifiers = out.get("falsification_tests")
        if isinstance(falsifiers, str):
            out["falsification_tests"] = [falsifiers]
            report.append(f"{ctx}: single 'falsification_tests' string wrapped in a list")
        evidence = out.get("evidence")
        if isinstance(evidence, list):
            out["evidence"] = [
                _migrate_evidence(item, f"{ctx} evidence[{i}]", report)
                for i, item in enumerate(evidence)
            ]
        failures = out.get("failures")
        if isinstance(failures, list):
            for failure in failures:
                if isinstance(failure, dict):
                    for key in failure:
                        if key not in FailureMode._FIELDS:
                            raise BundleValidationError(
                                f"{ctx}: failure field '{key}' has no known mapping; "
                                "refusing to guess"
                            )
        _migrate_enum(out, "kind", valid_kinds, LEGACY_KIND_MAP, ctx, report)
        _migrate_enum(out, "status", valid_statuses, LEGACY_STATUS_MAP, ctx, report)
        migrated_rows.append(out)
    bundle["claims"] = migrated_rows
    # Guarantee: a migrated bundle strict-loads (migrate -> assess round-trip).
    for row in migrated_rows:
        Claim.from_dict(row)
    return bundle, report


def extract_markdown_claims(path: str | Path) -> list[Claim]:
    """Extract only explicitly identified claims; never invent support or certainty."""
    source = Path(path)
    lines = source.read_text(encoding="utf-8").splitlines()
    claims: list[Claim] = []
    active: dict[str, Any] | None = None
    pending_heading = ""

    def finish() -> None:
        nonlocal active
        if active is None:
            return
        text = str(active.pop("text", "")).strip()
        claim_id = str(active.pop("id"))
        if not text:
            text = pending_heading.strip()
        kind = _kind_from_id(claim_id)
        claims.append(
            Claim(
                id=claim_id.upper(),
                text=text,
                kind=kind,
                status=ClaimStatus.DRAFT,
                boundary=list(active.pop("boundary", [])),
                depends_on=[str(ref).upper() for ref in active.pop("depends_on", [])],
                falsification_tests=list(active.pop("falsification_tests", [])),
                source_ref=f"{source.as_posix()}#{claim_id}",
                uncertainty=Uncertainty.INSUFFICIENT_EVIDENCE,
                metadata=active,
            )
        )
        active = None

    for line in lines:
        heading = _HEADING.match(line)
        if heading:
            finish()
            active = {"id": heading.group(1), "text": heading.group(2) or ""}
            pending_heading = heading.group(2) or ""
            continue
        generic_heading = re.match(r"^#{1,6}\s+(?:\d+[.)]\s*)?(.+)$", line)
        if generic_heading:
            if active is not None:
                finish()
            pending_heading = generic_heading.group(1).strip()
            continue
        inline = _INLINE_ID.match(line)
        if inline and active is None:
            active = {"id": inline.group(1), "text": pending_heading}
            continue
        if active is None:
            continue
        field = _FIELD.match(line)
        if not field:
            continue
        key = field.group(1).strip().lower()
        value = field.group(2).strip()
        if key in {"description", "claim", "proposition", "text", "title"}:
            active["text"] = value
        elif key in {"boundary", "scope", "platform", "context"}:
            active.setdefault("boundary", []).append(value)
        elif key in {"depends on", "depends_on", "dependencies"}:
            active["depends_on"] = _split_refs(value)
        elif key in {"falsifier", "falsification test", "verification", "test"}:
            active.setdefault("falsification_tests", []).append(value)
        else:
            active[key.replace(" ", "_")] = value
    finish()
    return claims


def derived_claim_id(text: str, prefix: str = "CLM") -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10].upper()
    return f"{prefix}-{digest}"


def dump_claims(claims: list[Claim]) -> str:
    return json.dumps({"schema_version": "1.0", "claims": [c.to_dict() for c in claims]}, indent=2)


def _kind_from_id(claim_id: str) -> ClaimKind:
    prefix = claim_id.split("-", 1)[0].upper()
    return {
        "REQ": ClaimKind.REQUIREMENT,
        "HYP": ClaimKind.HYPOTHESIS,
        "DEC": ClaimKind.DECISION,
        "ASM": ClaimKind.ASSUMPTION,
        "COMP": ClaimKind.COMPLIANCE,
    }.get(prefix, ClaimKind.ASSUMPTION)


def _split_refs(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,;]", value) if item.strip()]
