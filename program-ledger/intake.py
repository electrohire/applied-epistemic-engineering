#!/usr/bin/env python3
"""Program-ledger intake validator (Winning Combination, Stage 1).

Every claim that enters the program ledger passes through here first.
A claim is parsed by the engine's own claim model (``aee.model.Claim``)
-- the engine dogfoods its intake -- and then checked against the
pattern rules:

  R0  conforms to the pinned schema (schema.json beside the ledger,
      Amendment 3): every required field present and correctly
      typed, evidence items and metadata carrying their required
      keys; each field's provenance rule is stated in the schema
  R1  parses as an engine Claim (the model's own loader and validation)
  R2  carries at least one falsification test
  R3  carries at least one boundary line (its "does not establish")
  R4  carries a source_ref
  R5  carries at least one evidence item with a ref
  R6  ids are unique; depends_on / conflicts_with references resolve
  R7  metadata.date is an ISO date; metadata.components are known
  R8  a claim marked supported carries supporting evidence
  R9  proposition fingerprints (computed here from the normalized
      statement text, never read from the artifact) do not collide
      across distinct ids

Every run also prints INTAKE_COVERAGE: per-field coverage counts
for the pattern-required provenance fields, so a legacy gap is a
standing number, never silence (Amendment 3).

Usage: python3 intake.py [claims.jsonl] [components.json]
Exit code 0 iff every claim is accepted. The report is the output;
nothing is repaired silently.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from datetime import date
from pathlib import Path


def ledger_sha256(path: Path) -> str:
    """SHA-256 of the ledger's canonical text (LF line endings).

    Raw file bytes differ across platforms (a Windows checkout may
    carry CRLF), so every generated layer records THIS hash: the same
    ledger content hashes identically everywhere, and regeneration
    stays byte-exact cross-platform.
    """
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aee.model import Claim, ClaimStatus  # noqa: E402


def proposition_fingerprint(text: str) -> str:
    """SHA-256 of the normalized statement text (schema.json, Amendment 3)."""
    normalized = " ".join(unicodedata.normalize("NFC", text).casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _type_ok(value: object, declared: str) -> bool:
    if declared == "string":
        return isinstance(value, str)
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared == "array of strings":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if declared == "array of objects":
        return isinstance(value, list) and all(isinstance(v, dict) for v in value)
    if declared == "object":
        return isinstance(value, dict)
    return True


def schema_violations(data: dict, schema: dict) -> list[str]:
    """R0: required fields present and typed as the pinned schema declares."""
    problems: list[str] = []
    for field in schema.get("fields", []):
        name = field["name"]
        if name not in data:
            if field.get("required"):
                problems.append(f"R0 schema: missing required field {name}")
            continue
        if not _type_ok(data[name], str(field.get("type", ""))):
            problems.append(f"R0 schema: field {name} is not {field.get('type')}")
            continue
        for key in field.get("keys_required", []):
            if isinstance(data[name], dict) and key not in data[name]:
                problems.append(f"R0 schema: field {name} missing key {key}")
        for key in field.get("item_required", []):
            if isinstance(data[name], list):
                for item in data[name]:
                    if isinstance(item, dict) and key not in item:
                        problems.append(f"R0 schema: field {name} item missing key {key}")
    return problems


def _nonempty(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return len(value) > 0
    return value is not None


def validate(claims_path: Path, components_path: Path) -> tuple[list[str], list[str]]:
    known_components: set[str] = set()
    if components_path.is_file():
        known_components = {
            c["id"] for c in json.loads(components_path.read_text(encoding="utf-8"))
        }

    lines = [
        (n, raw)
        for n, raw in enumerate(claims_path.read_text(encoding="utf-8").splitlines(), start=1)
        if raw.strip()
    ]
    parsed: dict[str, Claim] = {}
    accepted: list[str] = []
    rejected: list[str] = []

    staged: list[tuple[int, dict]] = []
    for n, raw in lines:
        try:
            staged.append((n, json.loads(raw)))
        except json.JSONDecodeError as exc:
            rejected.append(f"line {n}: REJECT json-parse: {exc}")

    schema: dict | None = None
    schema_path = claims_path.parent / "schema.json"
    if schema_path.is_file():
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            schema = None

    for n, data in staged:
        cid = str(data.get("id", "")).strip() or f"line {n}"
        problems: list[str] = []
        if schema is not None:
            problems.extend(schema_violations(data, schema))
        claim: Claim | None = None
        try:
            claim = Claim.from_dict(data)
        except Exception as exc:  # the model's own verdict on its format
            problems.append(f"R1 engine-parse: {exc}")
        if claim is not None:
            if claim.id in parsed:
                problems.append("R6 duplicate id")
            if not claim.falsification_tests or not any(
                t.strip() for t in claim.falsification_tests
            ):
                problems.append("R2 no falsification test")
            if not claim.boundary or not any(b.strip() for b in claim.boundary):
                problems.append("R3 no boundary (does-not-establish) line")
            if not claim.source_ref.strip():
                problems.append("R4 no source_ref")
            if not claim.evidence or not any(e.ref.strip() for e in claim.evidence):
                problems.append("R5 no evidence ref")
            meta = claim.metadata or {}
            raw_date = str(meta.get("date", ""))
            try:
                date.fromisoformat(raw_date)
            except ValueError:
                problems.append(f"R7 metadata.date not an ISO date: {raw_date!r}")
            for comp in meta.get("components", []):
                if known_components and comp not in known_components:
                    problems.append(f"R7 unknown component: {comp}")
            if claim.status == ClaimStatus.SUPPORTED and not any(
                e.direction.value == "supports" for e in claim.evidence
            ):
                problems.append("R8 supported claim without supporting evidence")
            parsed.setdefault(claim.id, claim)
        if problems:
            rejected.append(f"{cid}: REJECT " + "; ".join(problems))
        else:
            accepted.append(f"{cid}: ACCEPT")

    # R6 reference resolution, once every id is known.
    for _n, data in staged:
        claim = parsed.get(str(data.get("id", "")).strip())
        if claim is None:
            continue
        for ref in list(claim.depends_on) + list(claim.conflicts_with):
            if ref not in parsed:
                rejected.append(f"{claim.id}: REJECT R6 unresolved reference {ref}")
                if f"{claim.id}: ACCEPT" in accepted:
                    accepted.remove(f"{claim.id}: ACCEPT")

    # R9 fingerprint collisions, once every statement is known.
    by_fingerprint: dict[str, list[str]] = {}
    for _n, data in staged:
        cid = str(data.get("id", "")).strip()
        text = data.get("text")
        if cid and isinstance(text, str) and text.strip():
            by_fingerprint.setdefault(proposition_fingerprint(text), []).append(cid)
    for ids in by_fingerprint.values():
        distinct = sorted(set(ids))
        if len(distinct) > 1:
            for cid in distinct:
                others = ", ".join(i for i in distinct if i != cid)
                rejected.append(f"{cid}: REJECT R9 fingerprint collision with {others}")
                if f"{cid}: ACCEPT" in accepted:
                    accepted.remove(f"{cid}: ACCEPT")

    if schema is None:
        rejected.append("SCHEMA: REJECT no valid pinned schema.json beside the ledger")

    total = len(staged)
    coverage = {
        "falsifier": sum(1 for _n, d in staged if _nonempty(d.get("falsification_tests"))),
        "boundary": sum(1 for _n, d in staged if _nonempty(d.get("boundary"))),
        "source_ref": sum(1 for _n, d in staged if _nonempty(d.get("source_ref"))),
        "evidence": sum(1 for _n, d in staged if _nonempty(d.get("evidence"))),
    }
    counts = " ".join(f"{k}={v}/{total}" for k, v in coverage.items())
    print(f"INTAKE_COVERAGE {counts}")

    return accepted, rejected


def main(argv: list[str]) -> int:
    claims_path = Path(argv[1]) if len(argv) > 1 else HERE / "claims.jsonl"
    components_path = Path(argv[2]) if len(argv) > 2 else HERE / "components.json"
    accepted, rejected = validate(claims_path, components_path)
    print(f"INTAKE ledger={claims_path.name} claims={len(accepted) + len(rejected)}")
    for line in accepted:
        print(" ", line)
    for line in rejected:
        print(" ", line)
    print(f"INTAKE_RESULT accepted={len(accepted)} rejected={len(rejected)}")
    return 0 if not rejected else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
