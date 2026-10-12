"""Verifiable evidence checks (Spec 002 FR-3).

Until FR-3, nothing in the engine resolved an evidence ``ref``:
``content_hash`` was declared and serialized but never recomputed, and
scoring weighted evidence by the author-declared ``source_quality``
verbatim. This module makes evidence inspectable:

- every local ref must resolve to a real file INSIDE the project root,
  with the path-safety discipline the spec-kit-aee extension's runner
  uses (resolved path must stay in the root; any symlinked path
  component is refused rather than followed);
- URL refs are reported ``unresolvable_offline`` — never fetched;
- a present ``content_hash`` is recomputed (SHA-256 of the file bytes)
  and a mismatch is a finding;
- a present ``observed_at`` must parse, surfaced as a finding rather
  than scoring's silent freshness note;
- a corroborated quality is DERIVED from the ref by the deterministic
  rules in :func:`derive_source_quality` and compared with the declared
  quality: a disagreement is a challenge (finding). Derivation never
  upgrades an undeclared quality — ``unknown`` stays ``unknown``
  (FR-3.4); the derived value is only reported alongside it.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from aee.model import Claim, Evidence, FailureMode, Severity, SourceQuality

# Finding categories (the granular kind; folded failure modes carry the
# broader "provenance_gap" category so recovery routing treats them as
# provenance repair — see EvidenceReport.failure_modes).
MISSING_REF = "missing_ref"
PATH_SAFETY = "path_safety"
CONTENT_HASH_MISMATCH = "content_hash_mismatch"
CONTENT_HASH_UNSUPPORTED = "content_hash_unsupported"
UNPARSEABLE_OBSERVED_AT = "unparseable_observed_at"
QUALITY_MISMATCH = "quality_mismatch"
EMPTY_REF = "empty_ref"

_SEVERITY: dict[str, Severity] = {
    MISSING_REF: Severity.HIGH,
    PATH_SAFETY: Severity.HIGH,
    CONTENT_HASH_MISMATCH: Severity.HIGH,
    CONTENT_HASH_UNSUPPORTED: Severity.MEDIUM,
    UNPARSEABLE_OBSERVED_AT: Severity.MEDIUM,
    QUALITY_MISMATCH: Severity.MEDIUM,
    EMPTY_REF: Severity.HIGH,
}

_TEST_COMPONENTS = {"tests", "test"}
_ARTIFACT_COMPONENTS = {"artifacts", "reports", "results", "captures", "evidence", "screenshots"}
_ARTIFACT_SUFFIXES = {".log", ".png", ".jpg", ".jpeg", ".gif", ".csv", ".jsonl", ".ndjson"}


def derive_source_quality(ref: str) -> SourceQuality | None:
    """Derive a corroborated source quality from a ref, deterministically.

    Rules, in priority order (first match wins); ``None`` means the ref
    type corroborates nothing and no derivation is claimed:

    ===  ===========================================  ================
    #    Ref shape                                    Derived quality
    ===  ===========================================  ================
    R1   any path component is ``tests``/``test``,    ``test``
         or the basename is a test file
         (``test_*``, ``*_test.*``, ``*.spec.*``)
    R2   a design record: a ``design`` or             ``primary``
         ``decisions`` path component, an ``adr-*``
         basename, or ``design-record`` in the
         basename
    R3   a recorded artifact: an ``artifacts`` /      ``artifact``
         ``reports`` / ``results`` / ``captures`` /
         ``evidence`` / ``screenshots`` component,
         or a log/image/tabular suffix
    ===  ===========================================  ================
    """
    parts = [part.lower() for part in ref.replace("\\", "/").split("/") if part not in {"", "."}]
    if not parts:
        return None
    basename = parts[-1]
    components = set(parts[:-1])
    if (
        components & _TEST_COMPONENTS
        or basename.startswith("test_")
        or "_test." in basename
        or ".spec." in basename
    ):
        return SourceQuality.TEST
    if (
        "design" in components
        or "decisions" in components
        or basename.startswith("adr-")
        or basename.startswith("adr_")
        or "design-record" in basename
    ):
        return SourceQuality.PRIMARY
    suffix = basename[basename.rfind(".") :] if "." in basename else ""
    if components & _ARTIFACT_COMPONENTS or suffix in _ARTIFACT_SUFFIXES:
        return SourceQuality.ARTIFACT
    return None


@dataclass(slots=True)
class EvidenceFinding:
    """One problem found while verifying one evidence item."""

    claim_id: str
    evidence_index: int
    ref: str
    category: str
    message: str
    declared_quality: str
    derived_quality: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "evidence_index": self.evidence_index,
            "ref": self.ref,
            "category": self.category,
            "message": self.message,
            "declared_quality": self.declared_quality,
            "derived_quality": self.derived_quality,
        }


@dataclass(slots=True)
class EvidenceItemResult:
    """Verification outcome for one evidence item."""

    claim_id: str
    evidence_index: int
    ref: str
    declared_quality: str
    derived_quality: str | None
    status: str  # "verified" | "unresolvable_offline" | "failed"
    resolved_path: str | None
    findings: list[EvidenceFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "evidence_index": self.evidence_index,
            "ref": self.ref,
            "declared_quality": self.declared_quality,
            "derived_quality": self.derived_quality,
            "status": self.status,
            "resolved_path": self.resolved_path,
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(slots=True)
class EvidenceReport:
    """Complete, serializable result of one verify-evidence run."""

    project_root: str
    items: list[EvidenceItemResult]

    @property
    def findings(self) -> list[EvidenceFinding]:
        return [finding for item in self.items for finding in item.findings]

    @property
    def checked(self) -> int:
        return len(self.items)

    @property
    def unresolvable_offline(self) -> int:
        return sum(1 for item in self.items if item.status == "unresolvable_offline")

    @property
    def ok(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "project_root": self.project_root,
            "checked": self.checked,
            "verified": sum(1 for item in self.items if item.status == "verified"),
            "unresolvable_offline": self.unresolvable_offline,
            "failed": sum(1 for item in self.items if item.status == "failed"),
            "findings": [finding.to_dict() for finding in self.findings],
            "items": [item.to_dict() for item in self.items],
        }

    def failure_modes(self) -> list[FailureMode]:
        """Fold every finding into a failure mode (FR-3.5), so an
        ``assess --verify-evidence`` run counts them in its outcome,
        summary, and recovery proposals exactly like a challenge."""
        modes: list[FailureMode] = []
        for finding in self.findings:
            slug = re.sub(r"[^A-Z0-9]+", "-", finding.category.upper()).strip("-")[:24]
            modes.append(
                FailureMode(
                    id=f"AEE-{finding.claim_id}-EV{finding.evidence_index}-{slug}",
                    claim_id=finding.claim_id,
                    challenge=f"Evidence verification ({finding.category})",
                    breakpoint=finding.message,
                    severity=_SEVERITY[finding.category],
                    category="provenance_gap",
                    recovery_hint=(
                        "Repair the evidence reference so it resolves inside the "
                        "project root and its declared quality matches its content."
                    ),
                )
            )
        return modes


def check_evidence(claims: Iterable[Claim], project_root: str | Path) -> EvidenceReport:
    """Verify every evidence item of every claim against ``project_root``."""
    root = Path(project_root).resolve()
    items: list[EvidenceItemResult] = []
    for claim in claims:
        for index, evidence in enumerate(claim.evidence):
            items.append(_check_item(claim.id, index, evidence, root))
    return EvidenceReport(project_root=root.as_posix(), items=items)


def _check_item(claim_id: str, index: int, evidence: Evidence, root: Path) -> EvidenceItemResult:
    ref = evidence.ref
    declared = evidence.source_quality
    result = EvidenceItemResult(
        claim_id=claim_id,
        evidence_index=index,
        ref=ref,
        declared_quality=declared.value,
        derived_quality=None,
        status="verified",
        resolved_path=None,
    )

    def add(category: str, message: str) -> None:
        result.findings.append(
            EvidenceFinding(
                claim_id=claim_id,
                evidence_index=index,
                ref=ref,
                category=category,
                message=message,
                declared_quality=declared.value,
                derived_quality=result.derived_quality,
            )
        )

    if _is_url(ref):
        # FR-3.1: report, never fetch.
        result.status = "unresolvable_offline"
        _check_observed_at(evidence, add)
        return _finish(result)
    if not ref.strip():
        add(EMPTY_REF, "evidence ref is empty; there is nothing to resolve or inspect")
        _check_observed_at(evidence, add)
        return _finish(result)

    derived = derive_source_quality(ref)
    result.derived_quality = derived.value if derived is not None else None

    resolved = _resolve_local(ref, root, add)
    if resolved is not None:
        result.resolved_path = resolved.relative_to(root).as_posix()
        if evidence.content_hash is not None:
            _check_content_hash(resolved, evidence.content_hash, add)
    _check_observed_at(evidence, add)
    # FR-3.3/FR-3.4: declared-vs-derived is a challenge, and an
    # undeclared (unknown) quality is never upgraded by derivation.
    if derived is not None and declared != SourceQuality.UNKNOWN and declared != derived:
        add(
            QUALITY_MISMATCH,
            f"declared source_quality '{declared.value}' disagrees with the quality "
            f"derived from the ref type ('{derived.value}'): {ref}",
        )
    return _finish(result)


def _finish(result: EvidenceItemResult) -> EvidenceItemResult:
    if result.findings:
        result.status = "failed"
        # Findings recorded before the derived quality was known carry
        # it too, so every finding in the report is self-describing.
        for finding in result.findings:
            if finding.derived_quality is None:
                finding.derived_quality = result.derived_quality
    return result


def _is_url(ref: str) -> bool:
    parsed = urlparse(ref)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _resolve_local(ref: str, root: Path, add: Any) -> Path | None:
    """Resolve a local ref inside ``root`` with extension-grade path
    safety; record a finding and return None when it cannot be used."""
    candidate = Path(ref)
    absolute = candidate if candidate.is_absolute() else root / candidate
    try:
        relative = absolute.relative_to(root)
    except ValueError:
        add(PATH_SAFETY, f"evidence ref escapes the project root: {ref}")
        return None
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            add(PATH_SAFETY, f"symlinked path component refused: {current.as_posix()}")
            return None
    resolved = absolute.resolve(strict=False)
    if not resolved.is_relative_to(root):
        add(PATH_SAFETY, f"evidence ref escapes the project root: {ref}")
        return None
    if not resolved.is_file():
        add(MISSING_REF, f"evidence ref does not resolve to a file inside the project root: {ref}")
        return None
    return resolved


def _check_content_hash(path: Path, declared_hash: str, add: Any) -> None:
    raw = declared_hash.strip()
    expected = raw
    if ":" in raw:
        algorithm, _, expected = raw.partition(":")
        if algorithm.strip().lower() != "sha256":
            add(
                CONTENT_HASH_UNSUPPORTED,
                f"content_hash uses unsupported algorithm '{algorithm.strip()}'; "
                "only sha256 can be recomputed",
            )
            return
    expected = expected.strip().lower()
    if not expected or any(char not in "0123456789abcdef" for char in expected):
        add(
            CONTENT_HASH_MISMATCH,
            f"declared content_hash {declared_hash!r} is not a sha256 hex digest",
        )
        return
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        add(
            CONTENT_HASH_MISMATCH,
            f"content_hash mismatch for {path.name}: declared {expected}, recomputed {actual}",
        )


def _check_observed_at(evidence: Evidence, add: Any) -> None:
    observed_at = evidence.observed_at
    if observed_at is None:
        return
    try:
        datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        add(
            UNPARSEABLE_OBSERVED_AT,
            f"observed_at {observed_at!r} does not parse as an ISO 8601 date/time",
        )
