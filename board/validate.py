#!/usr/bin/env python3
"""Validator for the pinned board schema (spec AB-001 3.1, task T002).

Refusals are loud and named per field, and happen before any write:
a row or event missing a pinned field, carrying the fold-derived
``amendment_seq``, or carrying a caller-supplied ``writer`` is refused
by name. The schema of record is ``board/schema.json`` beside this
module; this validator is its executable form.

This does not establish that events admitted under the schema were
truthful when written.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"
_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

STATUS_ENUM = _SCHEMA["status_enum"]
EXECUTION_STATE_ENUM = _SCHEMA["execution_state_enum"]
WAIT_KIND_ENUM = _SCHEMA["wait_kind_enum"]
EVENT_FIELDS = _SCHEMA["event_fields"]
CALLER_EVENT_FIELDS = _SCHEMA["caller_event_fields"]["fields"]
GENESIS_FIELDS = _SCHEMA["genesis_fields"]
ROW_FIELDS = _SCHEMA["row_fields"]
ROW_CREATION_FIELDS = _SCHEMA["row_creation_payload_fields"]["fields"]
WAIT_FIELDS = _SCHEMA["wait_fields"]
VERDICT_ATTACHMENT_FIELDS = _SCHEMA["verdict_attachment_payload_fields"]["fields"]
AMENDABLE_FIELDS = frozenset(_SCHEMA["amendable_fields"]["fields"])

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _type_ok(value: Any, type_name: str) -> bool:
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "string_or_null":
        return value is None or isinstance(value, str)
    if type_name == "integer":
        return _is_int(value)
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "sha256_hex":
        return isinstance(value, str) and bool(_SHA256.match(value))
    if type_name == "list_of_string":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if type_name == "status_enum":
        return value in STATUS_ENUM
    if type_name == "execution_state_enum":
        return value in EXECUTION_STATE_ENUM
    if type_name == "wait_kind_enum":
        return value in WAIT_KIND_ENUM
    if type_name == "wait_or_null":
        return value is None or isinstance(value, dict)
    raise ValueError(f"unknown schema type: {type_name}")


def _check_fields(
    obj: dict[str, Any], fields: dict[str, Any], where: str, problems: list[str]
) -> None:
    for name in obj:
        if name not in fields:
            problems.append(f"{where}: unknown field {name!r} is not in the pinned schema")
    for name, spec in fields.items():
        if name not in obj:
            if spec.get("required"):
                problems.append(f"{where}: missing required field {name!r}")
            continue
        if not _type_ok(obj[name], spec["type"]):
            problems.append(
                f"{where}: field {name!r} must be {spec['type']}, got {type(obj[name]).__name__}"
            )


def validate_wait(wait: Any, where: str = "wait") -> list[str]:
    if wait is None:
        return []
    if not isinstance(wait, dict):
        return [f"{where}: must be an object or null"]
    problems: list[str] = []
    _check_fields(wait, WAIT_FIELDS, where, problems)
    return problems


def validate_genesis_payload(payload: Any) -> list[str]:
    """Problems with a genesis event's payload ([] means acceptable)."""
    if not isinstance(payload, dict):
        return ["genesis payload: must be an object"]
    problems: list[str] = []
    _check_fields(payload, GENESIS_FIELDS, "genesis payload", problems)
    return problems


def validate_row_creation_payload(payload: Any) -> list[str]:
    """Problems with a row_created event's payload ([] means acceptable)."""
    if not isinstance(payload, dict):
        return ["row_created payload: must be an object"]
    problems: list[str] = []
    for name in payload:
        if name == "amendment_seq":
            problems.append(
                "row_created payload: 'amendment_seq' is fold-derived and "
                "must never be an event payload field"
            )
        elif name == "writer":
            problems.append(
                "row_created payload: 'writer' is stamped by the append "
                "service and must never be caller-supplied"
            )
        elif name not in ROW_CREATION_FIELDS:
            problems.append(
                f"row_created payload: unknown field {name!r} is not in the pinned schema"
            )
    for name in ("row_id", "task_ref"):
        if name not in payload:
            problems.append(f"row_created payload: missing required field {name!r}")
    for name, value in payload.items():
        if (
            name in ROW_FIELDS
            and name in ROW_CREATION_FIELDS
            and not _type_ok(value, ROW_FIELDS[name]["type"])
        ):
            problems.append(
                f"row_created payload: field {name!r} must be "
                f"{ROW_FIELDS[name]['type']}, got {type(value).__name__}"
            )
    if "gate_row" in payload and not isinstance(payload["gate_row"], bool):
        problems.append(
            f"row_created payload: field 'gate_row' must be a boolean, "
            f"got {type(payload['gate_row']).__name__}"
        )
    if "wait" in payload:
        problems.extend(validate_wait(payload["wait"], "row_created payload wait"))
    return problems


def validate_verdict_attachment_payload(payload: Any) -> list[str]:
    """Problems with a verdict_attached event's payload ([] = acceptable).

    The attachment carries the caller's ``verdict_ref`` (and, for a
    superseding attachment, ``previous_ref`` and ``reason``). The
    ``verdict_evaluation`` is stamped by the append service, never
    caller-supplied; its presence is a kernel concern (the fold
    refuses unstamped attachments), not a caller-schema one.
    """
    if not isinstance(payload, dict):
        return ["verdict_attached payload: must be an object"]
    problems: list[str] = []
    for name in payload:
        if name not in VERDICT_ATTACHMENT_FIELDS:
            problems.append(
                f"verdict_attached payload: unknown field {name!r} is not in the pinned schema"
            )
    if "verdict_ref" not in payload:
        problems.append("verdict_attached payload: missing required field 'verdict_ref'")
    elif not isinstance(payload["verdict_ref"], str):
        problems.append("verdict_attached payload: field 'verdict_ref' must be a string")
    if "previous_ref" in payload and not _type_ok(payload["previous_ref"], "string_or_null"):
        problems.append("verdict_attached payload: field 'previous_ref' must be string_or_null")
    if "reason" in payload and not isinstance(payload["reason"], str):
        problems.append("verdict_attached payload: field 'reason' must be a string")
    return problems


def validate_row(row: Any) -> list[str]:
    """Problems with a folded row state ([] means acceptable)."""
    if not isinstance(row, dict):
        return ["row: must be an object"]
    problems: list[str] = []
    _check_fields(row, ROW_FIELDS, "row", problems)
    if isinstance(row, dict):
        problems.extend(validate_wait(row.get("wait"), "row wait"))
    return problems


def validate_caller_event(event: Any) -> list[str]:
    """Problems with a caller-supplied event for the append command.

    The caller supplies exactly the caller event fields; ``writer``,
    ``prev_hash`` and ``event_hash`` are the append service's, and a
    payload carrying ``amendment_seq`` or ``writer`` is refused by name.
    """
    if not isinstance(event, dict):
        return ["event: must be an object"]
    problems: list[str] = []
    for name in event:
        if name == "writer":
            problems.append(
                "event: 'writer' is stamped by the append service and must never be caller-supplied"
            )
        elif name in ("prev_hash", "event_hash"):
            problems.append(f"event: {name!r} is computed by the append service, not the caller")
        elif name not in CALLER_EVENT_FIELDS:
            problems.append(f"event: unknown field {name!r} is not a caller event field")
    for name in CALLER_EVENT_FIELDS:
        if name not in event:
            problems.append(f"event: missing required field {name!r}")
    if isinstance(event.get("payload"), dict):
        payload = event["payload"]
        if "amendment_seq" in payload:
            problems.append(
                "event payload: 'amendment_seq' is fold-derived and "
                "must never be an event payload field"
            )
        if "writer" in payload:
            problems.append(
                "event payload: 'writer' is stamped by the append service "
                "and must never be caller-supplied"
            )
        if "verdict_evaluation" in payload:
            problems.append(
                "event payload: 'verdict_evaluation' is stamped by the "
                "append service and must never be caller-supplied"
            )
        if "wake_check" in payload:
            problems.append(
                "event payload: 'wake_check' is stamped by the append "
                "service (FR-P3) and must never be caller-supplied"
            )
        kind = event.get("kind")
        if kind == "genesis":
            problems.extend(validate_genesis_payload(payload))
        elif kind == "row_created":
            problems.extend(validate_row_creation_payload(payload))
        elif kind == "verdict_attached":
            problems.extend(validate_verdict_attachment_payload(payload))
    elif "payload" in event:
        problems.append("event: field 'payload' must be an object")
    if "row_id" in event and not _type_ok(event["row_id"], "string_or_null"):
        problems.append("event: field 'row_id' must be string_or_null")
    return problems


def validate_stored_event(event: Any) -> list[str]:
    """Problems with a full stored event, hashes included ([] = acceptable)."""
    if not isinstance(event, dict):
        return ["event: must be an object"]
    problems: list[str] = []
    _check_fields(event, EVENT_FIELDS, "event", problems)
    return problems
