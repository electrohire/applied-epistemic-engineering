#!/usr/bin/env python3
"""Lifecycle-ledger intake validator.

The record discipline follows program-ledger/intake.py: a pinned schema
beside the ledger, records checked on every run, a loud named rejection,
and no repair or write on refusal. Lifecycle corrections are append-only:
a correction is a new record whose correction_of field names its target.

The plumbing under the rules -- the canonical ledger hash, the schema
type checker and field walker behind L0, and the coverage/report
harness -- is shared with the program ledger's intake and lives in
``aee.intake_common``; the L-rules themselves are this ledger's own.

Usage:
    python3 intake.py [records.jsonl] [--append record.json]

Exit code 0 iff every record is accepted. In --append mode the candidate
record is validated with the existing ledger and appended only if the
complete prospective ledger accepts; a refusal leaves the file untouched.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aee.intake_common import (  # noqa: E402
    is_int,
    is_number,
    ledger_sha256,
    print_coverage,
    report,
    schema_problems,
)

__all__ = [
    "append_record",
    "ledger_sha256",
    "load_records",
    "load_schema",
    "main",
    "validate",
    "validate_records",
]

_is_int = is_int
_is_number = is_number

SURVIVAL_HORIZONS = {30, 60, 90, 180}
PROBE_OUTCOMES = {"applies_cleanly", "applies_with_conflicts", "fails_tests"}


def _iso_ok(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        pass
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _nonnegative_map(value: object) -> bool:
    return isinstance(value, dict) and all(_is_number(v) and v >= 0 for v in value.values())


def _delivery_problems(data: dict) -> list[str]:
    problems: list[str] = []
    for name in ("repo", "task_ref", "capture_source"):
        if isinstance(data.get(name), str) and not str(data[name]).strip():
            problems.append(f"L1 provenance: field {name} is empty")
    if not _nonnegative_map(data.get("tokens_by_phase")):
        problems.append("L1 accounting: tokens_by_phase must map phases to nonnegative numbers")
    if not _nonnegative_map(data.get("human_minutes_by_activity")):
        problems.append(
            "L1 accounting: human_minutes_by_activity must map activities to nonnegative numbers"
        )
    for name in ("tokens_total", "attempts", "review_rounds"):
        if _is_int(data.get(name)) and int(data[name]) < 0:
            problems.append(f"L1 accounting: field {name} is negative")
    if data.get("accepted") is True:
        if data.get("acceptance_mode") == "none":
            problems.append("L2 acceptance: accepted delivery has acceptance_mode none")
        if not _iso_ok(data.get("accepted_at")):
            problems.append("L2 acceptance: accepted delivery needs an ISO accepted_at")
    elif data.get("accepted") is False and data.get("accepted_at") is not None:
        problems.append("L2 acceptance: unaccepted delivery carries accepted_at")

    provenance = data.get("verifier_provenance")
    cost = data.get("verifier_production_cost")
    if provenance == "authored_for_task":
        if not isinstance(cost, dict):
            problems.append(
                "L3 oracle-pricing: authored_for_task verifier is unpriced "
                "(verifier_production_cost is required)"
            )
        elif not _is_number(cost.get("tokens")) or not _is_number(cost.get("human_minutes")):
            problems.append(
                "L3 oracle-pricing: verifier_production_cost needs numeric tokens and human_minutes"
            )
        elif float(cost["tokens"]) < 0 or float(cost["human_minutes"]) < 0:
            problems.append("L3 oracle-pricing: verifier_production_cost cannot be negative")
    elif provenance in {"preexisting", "none"} and cost is not None:
        problems.append(
            "L3 oracle-pricing: verifier_production_cost must be null unless authored_for_task"
        )

    censored = data.get("censored")
    ceiling = data.get("ceiling_tokens")
    if censored is True and not (_is_int(ceiling) and int(ceiling) > 0):
        problems.append("L4 censoring: censored delivery needs a positive ceiling_tokens")
    if censored is False and ceiling is not None and not (_is_int(ceiling) and int(ceiling) > 0):
        problems.append("L4 censoring: ceiling_tokens must be positive when present")

    for item in data.get("survival", []):
        if isinstance(item, dict):
            if item.get("horizon_days") not in SURVIVAL_HORIZONS:
                problems.append("L5 survival: horizon_days must be one of 30, 60, 90, 180")
            if not _iso_ok(item.get("snapshot_at")):
                problems.append("L5 survival: snapshot_at must be an ISO date or timestamp")
            for key in ("lines_handwritten", "lines_modified_or_deleted"):
                if not _is_int(item.get(key)) or int(item[key]) < 0:
                    problems.append(f"L5 survival: {key} must be a nonnegative integer")
            if not isinstance(item.get("standing"), bool):
                problems.append("L5 survival: standing must be boolean")
    for item in data.get("integration_probes", []):
        if isinstance(item, dict):
            if item.get("horizon_days") not in SURVIVAL_HORIZONS:
                problems.append("L5 integration probe: horizon_days must be one of 30, 60, 90, 180")
            if item.get("outcome") not in PROBE_OUTCOMES:
                problems.append("L5 integration probe: unknown outcome enum")
            for key in ("cost_tokens", "cost_human_minutes"):
                if not _is_number(item.get(key)) or float(item[key]) < 0:
                    problems.append(f"L5 integration probe: {key} must be nonnegative")
    return problems


def _linked_problems(records: list[dict]) -> dict[str, list[str]]:
    problems: dict[str, list[str]] = {}
    delivery_ids = {str(r["delivery_id"]) for r in records if r.get("record_type") == "delivery"}
    rework_ids = {str(r["rework_id"]) for r in records if r.get("record_type") == "rework"}
    escape_ids = {str(r["escape_id"]) for r in records if r.get("record_type") == "escape"}
    all_ids = delivery_ids | rework_ids | escape_ids

    def add(record_id: str, problem: str) -> None:
        problems.setdefault(record_id, []).append(problem)

    for record in records:
        correction = record.get("correction_of")
        if correction is not None and correction not in all_ids:
            rid = str(
                record.get("delivery_id") or record.get("rework_id") or record.get("escape_id")
            )
            add(rid, f"L6 reference: correction_of does not resolve: {correction}")
    for record in records:
        if record.get("record_type") in {"rework", "escape"}:
            rid = str(record.get("rework_id") or record.get("escape_id"))
            if record.get("delivery_id") not in delivery_ids:
                add(rid, f"L6 reference: delivery_id does not resolve: {record.get('delivery_id')}")
        if record.get("record_type") == "delivery":
            did = str(record.get("delivery_id"))
            for ref in record.get("linked_rework_ids", []):
                if ref not in rework_ids:
                    add(did, f"L6 reference: linked rework does not resolve: {ref}")
            for ref in record.get("linked_escape_ids", []):
                if ref not in escape_ids:
                    add(did, f"L6 reference: linked escape does not resolve: {ref}")
            for record2 in records:
                if (
                    record2.get("record_type") == "rework"
                    and record2.get("delivery_id") == did
                    and record2.get("rework_id") not in record.get("linked_rework_ids", [])
                ):
                    add(did, "L6 linkage: delivery omits a linked rework record")
                if (
                    record2.get("record_type") == "escape"
                    and record2.get("delivery_id") == did
                    and record2.get("escape_id") not in record.get("linked_escape_ids", [])
                ):
                    add(did, "L6 linkage: delivery omits a linked escape record")
    return problems


def validate_records(records: list[dict], schema: dict) -> tuple[list[str], list[str]]:
    accepted: list[str] = []
    rejected: list[str] = []
    per_record: dict[str, list[str]] = {}
    seen: dict[str, str] = {}
    record_types = schema.get("record_types", {})

    for index, data in enumerate(records, start=1):
        record_type = data.get("record_type")
        if record_type not in record_types:
            rid = f"line {index}"
            per_record.setdefault(rid, []).append(f"L0 schema: unknown record_type {record_type!r}")
            continue
        type_schema = record_types[record_type]
        id_field = str(type_schema["id_field"])
        rid = str(data.get(id_field, "")).strip() or f"line {index}"
        problems = schema_problems(data, list(type_schema.get("fields", [])), "L0")
        if rid in seen:
            problems.append(f"L1 identity: duplicate id {rid}")
        seen.setdefault(rid, record_type)
        if record_type == "delivery":
            problems.extend(_delivery_problems(data))
        elif record_type == "rework":
            if not _iso_ok(data.get("detected_at")):
                problems.append("L1 timestamp: detected_at must be an ISO date or timestamp")
            if _is_int(data.get("repair_tokens")) and int(data["repair_tokens"]) < 0:
                problems.append("L1 accounting: repair_tokens is negative")
            if (
                _is_number(data.get("repair_human_minutes"))
                and float(data["repair_human_minutes"]) < 0
            ):
                problems.append("L1 accounting: repair_human_minutes is negative")
            if isinstance(data.get("description"), str) and not str(data["description"]).strip():
                problems.append("L1 provenance: description is empty")
            if (
                isinstance(data.get("capture_source"), str)
                and not str(data["capture_source"]).strip()
            ):
                problems.append("L1 provenance: capture_source is empty")
        elif record_type == "escape":
            if not _iso_ok(data.get("detected_at")):
                problems.append("L1 timestamp: detected_at must be an ISO date or timestamp")
            cost = data.get("repair_cost")
            if isinstance(cost, dict) and (
                not _is_number(cost.get("tokens"))
                or not _is_number(cost.get("human_minutes"))
                or float(cost.get("tokens", -1)) < 0
                or float(cost.get("human_minutes", -1)) < 0
            ):
                problems.append(
                    "L1 accounting: repair_cost needs nonnegative tokens and human_minutes"
                )
            if (
                _is_number(data.get("time_to_detect_hours"))
                and float(data["time_to_detect_hours"]) < 0
            ):
                problems.append("L1 accounting: time_to_detect_hours is negative")
            if isinstance(data.get("description"), str) and not str(data["description"]).strip():
                problems.append("L1 provenance: description is empty")
            if (
                isinstance(data.get("capture_source"), str)
                and not str(data["capture_source"]).strip()
            ):
                problems.append("L1 provenance: capture_source is empty")
        per_record.setdefault(rid, []).extend(problems)

    for rid, problems in _linked_problems(records).items():
        per_record.setdefault(rid, []).extend(problems)

    for data in records:
        record_type = data.get("record_type")
        if record_type not in record_types:
            rid = next((k for k in per_record if k.startswith("line ")), "unknown")
        else:
            id_field = str(record_types[record_type]["id_field"])
            rid = str(data.get(id_field, "")).strip() or "unknown"
        problems = per_record.get(rid, [])
        if problems:
            rejected.append(f"{rid}: REJECT " + "; ".join(dict.fromkeys(problems)))
        else:
            accepted.append(f"{rid}: ACCEPT")

    total = len(records)
    coverage = {
        "capture_source": sum(1 for r in records if str(r.get("capture_source", "")).strip()),
        "delivery": sum(1 for r in records if r.get("record_type") == "delivery"),
        "rework": sum(1 for r in records if r.get("record_type") == "rework"),
        "escape": sum(1 for r in records if r.get("record_type") == "escape"),
    }
    print_coverage("LIFECYCLE_COVERAGE", coverage, total)
    return accepted, rejected


def load_schema(path: Path = HERE / "schema.json") -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_records(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records: list[dict] = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if raw.strip():
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {n}: invalid JSON: {exc}") from exc
    return records


def validate(path: Path) -> tuple[list[str], list[str]]:
    return validate_records(load_records(path), load_schema())


def append_record(path: Path, candidate: dict) -> tuple[list[str], list[str]]:
    """Validate the prospective ledger, then append only on full acceptance."""
    prospective = [*load_records(path), candidate]
    accepted, rejected = validate_records(prospective, load_schema())
    if rejected:
        return accepted, rejected
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(candidate, sort_keys=True) + "\n")
    return accepted, rejected


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a != "--append"]
    append_mode = "--append" in argv
    records_path = Path(args[0]) if args else HERE / "fixtures.jsonl"
    if append_mode:
        if len(args) != 2:
            print("usage: intake.py LEDGER --append RECORD_JSON")
            return 2
        candidate = json.loads(Path(args[1]).read_text(encoding="utf-8"))
        accepted, rejected = append_record(records_path, candidate)
    else:
        try:
            accepted, rejected = validate(records_path)
        except ValueError as exc:
            print(f"REJECT json-parse: {exc}")
            print("LIFECYCLE_RESULT accepted=0 rejected=1")
            return 1
    return report("LIFECYCLE", "records", records_path.name, accepted, rejected)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
