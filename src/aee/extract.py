"""Conservative claim extraction from structured JSON and Markdown."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from aee.model import Claim, ClaimKind, ClaimStatus, Uncertainty

_ID = r"(?:REQ|CLM|HYP|DEC|ASM|COMP)-[A-Z0-9][A-Z0-9-]*"
_HEADING = re.compile(rf"^#{{1,6}}\s+({_ID})(?:\s*[-—:.]\s*(.*))?$", re.IGNORECASE)
_INLINE_ID = re.compile(rf"^\s*[-*]\s+\*\*ID:?\*\*:?\s*({_ID})\s*$", re.IGNORECASE)
_FIELD = re.compile(r"^\s*[-*]\s+\*\*(.+?):?\*\*:?\s*(.+)$")


def load_claims(path: str | Path) -> list[Claim]:
    source = Path(path)
    if source.suffix.lower() == ".json":
        value = json.loads(source.read_text(encoding="utf-8"))
        rows = value.get("claims", []) if isinstance(value, dict) else value
        if not isinstance(rows, list):
            raise ValueError("JSON input must be a claim list or contain a 'claims' list")
        return [Claim.from_dict(row) for row in rows]
    return extract_markdown_claims(source)


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
                depends_on=list(active.pop("depends_on", [])),
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
