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
    EvidenceDirection,
    EvidenceKind,
    FailureMode,
    SourceQuality,
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

        def _reject_constant(name: str) -> None:
            raise ValueError(
                f"{source.as_posix()}: non-finite number {name!r} is not "
                "allowed in a claims bundle (Spec 003 FR-3.3)"
            )

        value = json.loads(source.read_text(encoding="utf-8"), parse_constant=_reject_constant)
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


# --- Claims drafting (Spec 002 FR-2, engine helper for T201) -------------------
# The helper proposes draft claims from a spec's stated requirements.
# Invariants (FR-2.2/FR-2.4), enforced by construction — there is no
# parameter, flag, or code path here that can change them:
#   * every drafted claim is born ``status: draft``;
#   * its single evidence item is the requirement text itself, modelled
#     by this helper: kind ``asserted``, source_quality ``model`` (the
#     FR-2.2 cap — never anything stronger);
#   * ratification is a recorded human edit performed elsewhere; this
#     module holds no opinion about it and never upgrades a claim.
# A draft whose requirement text carries no testable cue gets the
# TODO falsifier below instead of an invented test (FR-2.3); strict
# loading (Claim.from_dict) rejects TODO falsifiers, so such a draft
# cannot be assessed until a human writes a real one.

TODO_FALSIFIER = (
    "TODO: no falsification test could be proposed from the requirement "
    "text; a human must write one before this draft can be completed"
)

_REQ_REF = r"FR-\d+(?:\.\d+)*|US-\d+"
_FR_BULLET = re.compile(
    rf"^\s*(?:[-*]|\d+\.)\s+(?:\*\*)?({_REQ_REF})(?:\*\*)?\s*[:\-—\u2013]\s*(.+?)\s*$"
)
_FR_HEADING = re.compile(rf"^#{{1,6}}\s+({_REQ_REF})\b\s*[:\-—\u2013.]?\s*(.*?)\s*$")
_US_HEADING = re.compile(
    r"^#{1,6}\s+User Story\s+(\d+)\b\s*[:\-—\u2013]?\s*(.*?)\s*$", re.IGNORECASE
)
_HEADING_LINE = re.compile(r"^#{1,6}\s+(.*?)\s*$")
_BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.+?)\s*$")
_CROSS_REF = re.compile(rf"\b({_REQ_REF})\b")
_TESTABLE_CUE = re.compile(
    r"\b(shall|must|will|should|given|when|then|returns?|emits?|rejects?|accepts?|"
    r"supports?|provides?|records?|computes?|validates?|stores?|allows?|prevents?|"
    r"fails?|exits?|contains?|includes?|matches?|equals?|displays?|generates?|"
    r"loads?|writes?|reads?|sends?|creates?|updates?|deletes?|verifies|checks?)\b|\d",
    re.IGNORECASE,
)


def _clean_md(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text).strip()


def _parse_requirements(spec_text: str) -> list[tuple[str, str]]:
    """(requirement_ref, requirement_text) pairs in document order.

    Sources: FR/US bullets and headings anywhere, user-story headings,
    and bullets under an acceptance heading. First occurrence of a
    ref wins; acceptance bullets are numbered AC-1, AC-2, ... in
    document order."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    lines = spec_text.splitlines()
    heading = ""
    ac_count = 0

    def add(ref: str, text: str) -> None:
        text = _clean_md(text)
        if ref not in seen and text:
            seen.add(ref)
            found.append((ref, text))

    for index, line in enumerate(lines):
        us = _US_HEADING.match(line)
        if us:
            ref = f"US-{us.group(1)}"
            text = us.group(2)
            # Prefer the story sentence itself ("As a ..., I want ...")
            # over the heading title when the section states one.
            for following in lines[index + 1 :]:
                if _HEADING_LINE.match(following):
                    break
                story = re.search(r"(As an?\s+.+)$", _clean_md(following), re.IGNORECASE)
                if story:
                    text = story.group(1)
                    break
                if following.strip():
                    break
            add(ref, text)
            heading = line
            continue
        fr_heading = _FR_HEADING.match(line)
        if fr_heading:
            text = fr_heading.group(2)
            if not text:
                for following in lines[index + 1 :]:
                    if following.strip() and not _HEADING_LINE.match(following):
                        text = following.strip()
                        break
                    if _HEADING_LINE.match(following):
                        break
            add(fr_heading.group(1), text)
            heading = line
            continue
        generic = _HEADING_LINE.match(line)
        if generic:
            heading = generic.group(1)
            continue
        bullet = _FR_BULLET.match(line)
        if bullet:
            add(bullet.group(1), bullet.group(2))
            continue
        if re.search(r"acceptance", heading, re.IGNORECASE):
            item = _BULLET.match(line)
            if item:
                ac_count += 1
                add(f"AC-{ac_count}", item.group(1))
    return found


def _propose_falsifier(text: str) -> str | None:
    """A proposed falsification test for a requirement, or None when
    the text carries no testable cue to anchor one to. Proposals are
    marked as proposals in the test text itself; inventing a test for
    an aspirational sentence would be fabrication, so those drafts
    get the TODO marker instead (FR-2.3)."""
    if not _TESTABLE_CUE.search(text):
        return None
    proposition = text.rstrip().rstrip(".")
    return (
        "Proposed falsification test: demonstrate a conforming scenario "
        f"in which the following does not hold: {proposition}."
    )


def draft_claims_from_spec(spec_text: str, *, source_name: str = "spec.md") -> list[Claim]:
    """Propose one draft claim per requirement stated in a spec.

    Engine support for the extension's draft-claims command (FR-2.1 /
    FR-2.4): deterministic, no model calls, no ratification. Each
    draft carries its source requirement reference in ``source_ref``
    (FR-2.3), a proposed falsification test where one can be anchored
    (otherwise the TODO marker strict loading rejects), and — per
    FR-6.3's engine capability — ``depends_on`` proposals scaffolded
    from explicit cross-references to other requirements in the same
    spec; the proposals are proposals by virtue of the claim's draft
    status, and the source refs they came from are recorded in
    ``metadata['depends_on_proposed_from']``."""
    requirements = _parse_requirements(spec_text)
    ids_by_ref = {ref: derived_claim_id(f"{ref} {text}") for ref, text in requirements}
    drafts: list[Claim] = []
    for ref, text in requirements:
        anchor = f"{source_name}#{ref}"
        cross_refs = [r for r in _CROSS_REF.findall(text) if r != ref and r in ids_by_ref]
        falsifier = _propose_falsifier(text)
        metadata: dict[str, Any] = {
            "drafted": True,
            "draft_source": "aee.extract.draft_claims_from_spec",
            "requirement_ref": ref,
            "falsifier_proposed": falsifier is not None,
        }
        if cross_refs:
            metadata["depends_on_proposed_from"] = cross_refs
        drafts.append(
            Claim(
                id=ids_by_ref[ref],
                text=text,
                kind=ClaimKind.REQUIREMENT,
                status=ClaimStatus.DRAFT,
                depends_on=[ids_by_ref[r] for r in cross_refs],
                falsification_tests=[falsifier if falsifier is not None else TODO_FALSIFIER],
                uncertainty=Uncertainty.INSUFFICIENT_EVIDENCE,
                source_ref=anchor,
                evidence=[
                    Evidence(
                        ref=anchor,
                        kind=EvidenceKind.ASSERTED,
                        direction=EvidenceDirection.SUPPORTS,
                        source_quality=SourceQuality.MODEL,
                        source_id=ref,
                        description=(
                            f"Draft proposed from requirement {ref} by the "
                            "drafting helper; unratified — the evidence is "
                            "the requirement text itself, as modelled."
                        ),
                    )
                ],
                metadata=metadata,
            )
        )
    return drafts


def draft_claims(path: str | Path) -> list[Claim]:
    """Draft claims from a spec file; see draft_claims_from_spec."""
    source = Path(path)
    return draft_claims_from_spec(source.read_text(encoding="utf-8"), source_name=source.as_posix())


def derived_claim_id(text: str, prefix: str = "CLM") -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10].upper()
    return f"{prefix}-{digest}"


def dump_claims(claims: list[Claim]) -> str:
    return json.dumps(
        {"schema_version": "1.0", "claims": [c.to_dict() for c in claims]},
        indent=2,
        allow_nan=False,
    )


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
