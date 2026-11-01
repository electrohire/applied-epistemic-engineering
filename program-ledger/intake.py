#!/usr/bin/env python3
"""Program-ledger intake validator (Winning Combination, Stage 1).

Every claim that enters the program ledger passes through here first.
A claim is parsed by the engine's own claim model (``aee.model.Claim``)
-- the engine dogfoods its intake -- and then checked against the
pattern rules:

  R1  parses as an engine Claim (the model's own loader and validation)
  R2  carries at least one falsification test
  R3  carries at least one boundary line (its "does not establish")
  R4  carries a source_ref
  R5  carries at least one evidence item with a ref
  R6  ids are unique; depends_on / conflicts_with references resolve
  R7  metadata.date is an ISO date; metadata.components are known
  R8  a claim marked supported carries supporting evidence

Usage: python3 intake.py [claims.jsonl] [components.json]
Exit code 0 iff every claim is accepted. The report is the output;
nothing is repaired silently.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aee.model import Claim, ClaimStatus  # noqa: E402


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

    for n, data in staged:
        cid = str(data.get("id", "")).strip() or f"line {n}"
        problems: list[str] = []
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
