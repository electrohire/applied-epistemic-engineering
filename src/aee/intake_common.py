"""Shared scaffolding for this repository's ledger intakes.

Two ledger families live beside their data in this repo, each with its
own intake validator: the program ledger (claims, rules R0-R9) and the
lifecycle ledger (delivery records, rules L0-L6). The rule sets are
deliberately separate -- they judge different artifacts -- but the
plumbing under them was written twice: the canonical ledger hash, the
schema type checker and field walker, and the coverage/report output
harness. This module is the one implementation of that plumbing, and
both intakes import it, so a fix to the canonicalization or the schema
walk lands in both ledgers at once.

Nothing here knows either rule set. Callers pass their own rule prefix
("R0" / "L0"), their own schema field lists, and their own coverage
fields; the messages come back worded in the caller's vocabulary.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def ledger_sha256(path: Path) -> str:
    """SHA-256 of a ledger's canonical text (LF line endings).

    Raw file bytes differ across platforms (a Windows checkout may
    carry CRLF), so every generated layer records THIS hash: the same
    ledger content hashes identically everywhere, and regeneration
    stays byte-exact cross-platform.
    """
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_int(value: object) -> bool:
    """True for a genuine integer (a bool is not an integer here)."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value: object) -> bool:
    """True for an int or float that is not a bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def type_ok(value: object, declared: str) -> bool:
    """Whether *value* matches a schema field's declared type string.

    The declared-type vocabulary is the union of both ledger schemas:
    "string", "integer", "number", "boolean", the "or null" forms,
    "array of strings", "array of objects", and "object". An
    unrecognized declaration passes, as both intakes have always
    treated it; the pinned schemas are the vocabulary's source of
    truth, not this checker.
    """
    if declared == "string":
        return isinstance(value, str)
    if declared == "string or null":
        return value is None or isinstance(value, str)
    if declared == "integer":
        return is_int(value)
    if declared == "integer or null":
        return value is None or is_int(value)
    if declared == "number":
        return is_number(value)
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "array of strings":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if declared == "array of objects":
        return isinstance(value, list) and all(isinstance(v, dict) for v in value)
    if declared == "object":
        return isinstance(value, dict)
    if declared == "object or null":
        return value is None or isinstance(value, dict)
    return True


def schema_problems(data: dict[str, Any], fields: list[dict[str, Any]], rule: str) -> list[str]:
    """Walk *fields* against *data* and name every schema problem.

    Messages are prefixed with the caller's schema rule ("R0" for the
    program ledger, "L0" for the lifecycle ledger), so each intake's
    report keeps its own rule vocabulary. Checks, in order per field:
    a required field is present; its value matches the declared type;
    a field declaring an ``enum`` list holds one of its values; every
    ``keys_required`` key is present on an object value; every
    ``item_required`` key is present on each object item of an array
    value.
    """
    problems: list[str] = []
    for field in fields:
        name = str(field["name"])
        if name not in data:
            if field.get("required"):
                problems.append(f"{rule} schema: missing required field {name}")
            continue
        value = data[name]
        declared = str(field.get("type", ""))
        if not type_ok(value, declared):
            problems.append(f"{rule} schema: field {name} is not {declared}")
            continue
        enum = field.get("enum")
        if enum is not None and value not in enum:
            problems.append(f"{rule} schema: field {name} has unknown enum value {value!r}")
        for key in field.get("keys_required", []):
            if isinstance(value, dict) and key not in value:
                problems.append(f"{rule} schema: field {name} missing key {key}")
        for key in field.get("item_required", []):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and key not in item:
                        problems.append(f"{rule} schema: field {name} item missing key {key}")
    return problems


def print_coverage(label: str, coverage: dict[str, int], total: int) -> None:
    """Print one coverage line: ``LABEL field=n/total field=n/total``.

    Coverage is a standing number, never silence: each intake prints
    its own fields under its own label on every run.
    """
    counts = " ".join(f"{k}={v}/{total}" for k, v in coverage.items())
    print(f"{label} {counts}")


def report(
    label: str, unit: str, source_name: str, accepted: list[str], rejected: list[str]
) -> int:
    """Print an intake's verdict report and return its exit code.

    Shape: a ``LABEL ledger=<file> <unit>=<count>`` header, the
    accepted lines, the rejected lines, then a
    ``LABEL_RESULT accepted=<a> rejected=<r>`` summary. The exit code
    is 0 iff nothing was rejected.
    """
    print(f"{label} ledger={source_name} {unit}={len(accepted) + len(rejected)}")
    for line in accepted:
        print(" ", line)
    for line in rejected:
        print(" ", line)
    print(f"{label}_RESULT accepted={len(accepted)} rejected={len(rejected)}")
    return 0 if not rejected else 1
