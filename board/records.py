#!/usr/bin/env python3
"""Record resolution and wake-falsifier evaluation (spec AB-001 3.1, 5.1).

A wait's ``wake_falsifier`` names a record and a field whose change
ends the wait. This module is the one resolver of those references,
shared by the append path (wake-on-watch, FR-P3), the keeper
(matching and the sweep re-read, FR-P2/FR-P4), and the tests. The
reference grammar:

- ``board:<row_id>`` — a row of the board itself, read from the
  folded state; the citation hash is the board's head hash at
  evaluation time.
- ``gatekeeper:<job_id>`` — the job's queue record in the gatekeeper
  queue directory, in the gatekeeper's own format; the record is
  augmented with its payload exit code under the verdict rules'
  convention (``board.verdicts``), so a falsifier may name
  ``payload_exit_code``. If the queue record is absent, the
  gatekeeper ledger is searched for the job's line and that line is
  the record.
- ``ci:<run_id>`` — the run record in the CI records directory, in
  the shape the verdict resolver already reads (``<run_id>.json``).
- ``file:<path>`` — a JSON record at a path (a wait naming a message
  or mail arrival names the arrival's record file this way).
- ``clock:now`` — the clock itself, for armed moments; the record is
  ``{"now": <current time>}`` and the ending condition is the
  current time reaching the falsifier's ``equals`` timestamp.

The falsifier's ending condition: when the falsifier carries
``equals``, the named field's current value must equal it; otherwise
the field must be present and non-empty (a CI run that has reached
any conclusion, a queue record that has reached a state). Evaluation
returns one of ``holds`` / ``not_yet`` / ``unresolvable`` with a
citation: the record reference, the field, the value read, and the
record's content hash where the record carries or admits one. A
record that cannot be read is ``unresolvable``, never a silent
``not_yet``.

Time discipline: cadences are the genesis format (``30m``, ``2h``,
``1d``); timestamps are ISO 8601 UTC with a ``Z`` suffix. Every
consumer takes an injectable clock so drills run on stated times;
no event is ever backdated from these helpers.

This does not establish that a record's contents are true; it
establishes what the record said when it was read, cited by hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import canonical

_CADENCE_RE = re.compile(r"^(\d+)([mhd])$")
_CADENCE_UNITS = {"m": "minutes", "h": "hours", "d": "days"}


def parse_cadence(text: Any) -> timedelta | None:
    """Parse a genesis cadence string (``30m``), or None if malformed."""
    if not isinstance(text, str):
        return None
    match = _CADENCE_RE.match(text.strip())
    if match is None:
        return None
    return timedelta(**{_CADENCE_UNITS[match.group(2)]: int(match.group(1))})


def parse_timestamp(text: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp to an aware UTC datetime, or None."""
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_timestamp(moment: datetime) -> str:
    """Format an aware datetime as ISO 8601 UTC with a ``Z`` suffix."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RecordRead:
    """A resolved record: its fields, and how it is cited."""

    record: dict[str, Any]
    citation_hash: str | None
    detail: str


@dataclass(frozen=True)
class FalsifierOutcome:
    """The outcome of evaluating one wait's wake falsifier."""

    outcome: str  # "holds" | "not_yet" | "unresolvable"
    detail: str
    citation: dict[str, Any]


def _content_hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical.canonical_bytes(record)).hexdigest()


def _read_json_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"the record cannot be read: {exc}"
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"the record is not valid JSON: {exc}"
    if not isinstance(record, dict):
        return None, "the record is not a JSON object"
    return record, None


def _gatekeeper_record(
    job_id: str,
    queue_dir: Path | None,
    ledger_path: Path | None,
) -> RecordRead | None:
    """The queue record for a job, augmented with its payload exit code.

    Falls back to the job's ledger line when the queue record is
    absent (the queue is a working directory; the ledger is the
    gatekeeper's durable record). Returns None when neither carries
    the job.
    """
    from . import verdicts

    if queue_dir is not None:
        record, error = _read_json_file(Path(queue_dir) / f"{job_id}.json")
        if error is None and record is not None:
            if record.get("id") != job_id:
                return RecordRead(
                    {},
                    None,
                    f"the queue record's id does not match the job id {job_id!r}",
                )
            augmented = dict(record)
            augmented["payload_exit_code"] = verdicts._gatekeeper_payload_exit(record)
            return RecordRead(
                augmented,
                _content_hash(augmented),
                "read from the gatekeeper queue record",
            )
    if ledger_path is not None:
        try:
            lines = Path(ledger_path).read_bytes().splitlines()
        except OSError:
            lines = []
        for raw in lines:
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(entry, dict) and entry.get("id") == job_id:
                augmented = dict(entry)
                augmented["payload_exit_code"] = verdicts._gatekeeper_payload_exit(entry)
                return RecordRead(
                    augmented,
                    hashlib.sha256(raw).hexdigest(),
                    "read from the gatekeeper ledger line for the job",
                )
    return None


def resolve_record(
    reference: str,
    *,
    board_state: dict[str, Any] | None = None,
    gatekeeper_queue_dir: Path | None = None,
    gatekeeper_ledger: Path | None = None,
    ci_records_dir: Path | None = None,
    now: datetime | None = None,
) -> RecordRead:
    """Resolve a falsifier's record reference to the record it names.

    An unresolvable reference returns a RecordRead with an empty
    record and the reason in its detail; callers distinguish by
    checking ``record`` and ``detail`` through evaluate_falsifier,
    which is the normal entry point.
    """
    cls, sep, locator = reference.partition(":")
    if not sep or not locator:
        return RecordRead({}, None, f"malformed record reference: {reference!r}")
    if cls == "board":
        rows = (board_state or {}).get("rows") or {}
        row = rows.get(locator)
        if row is None:
            return RecordRead({}, None, f"the board has no row {locator!r}")
        return RecordRead(
            dict(row),
            (board_state or {}).get("head_hash"),
            "read from the board's folded state",
        )
    if cls == "gatekeeper":
        if gatekeeper_queue_dir is None and gatekeeper_ledger is None:
            return RecordRead({}, None, "no gatekeeper queue directory or ledger was supplied")
        found = _gatekeeper_record(
            locator,
            Path(gatekeeper_queue_dir) if gatekeeper_queue_dir else None,
            Path(gatekeeper_ledger) if gatekeeper_ledger else None,
        )
        if found is None:
            return RecordRead({}, None, f"no gatekeeper record names job {locator!r}")
        return found
    if cls == "ci":
        if ci_records_dir is None:
            return RecordRead({}, None, "no CI records directory was supplied")
        record, error = _read_json_file(Path(ci_records_dir) / f"{locator}.json")
        if error is not None or record is None:
            return RecordRead({}, None, error or "the CI record cannot be read")
        if str(record.get("databaseId")) != locator:
            return RecordRead({}, None, "the CI record's id does not match the citation's run id")
        return RecordRead(record, _content_hash(record), "read from the CI run record")
    if cls == "file":
        record, error = _read_json_file(Path(locator))
        if error is not None or record is None:
            return RecordRead({}, None, error or "the record cannot be read")
        return RecordRead(record, _content_hash(record), "read from the named record file")
    if cls == "clock":
        moment = now or utcnow()
        return RecordRead({"now": format_timestamp(moment)}, None, "read from the clock")
    return RecordRead({}, None, f"unknown record class: {cls!r}")


def read_field(record: dict[str, Any], field: str) -> Any:
    """Read a field from a record; dotted names traverse nested objects."""
    current: Any = record
    for part in field.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def evaluate_falsifier(
    wait: dict[str, Any],
    *,
    board_state: dict[str, Any] | None = None,
    gatekeeper_queue_dir: Path | None = None,
    gatekeeper_ledger: Path | None = None,
    ci_records_dir: Path | None = None,
    now: datetime | None = None,
) -> FalsifierOutcome:
    """Evaluate one wait's wake falsifier against the record's state now.

    The ending condition (see the module docstring): the named
    field equals the falsifier's ``equals`` when one is carried;
    otherwise the field is present and non-empty. For ``clock:now``
    the condition is the current time reaching ``equals``.
    """
    falsifier = wait.get("wake_falsifier") or {}
    reference = falsifier.get("record")
    field = falsifier.get("field")
    if not isinstance(reference, str) or not isinstance(field, str):
        return FalsifierOutcome(
            "unresolvable",
            "the wait's wake_falsifier does not name a record and a field",
            {"record": reference, "field": field, "value": None, "record_hash": None},
        )
    read = resolve_record(
        reference,
        board_state=board_state,
        gatekeeper_queue_dir=gatekeeper_queue_dir,
        gatekeeper_ledger=gatekeeper_ledger,
        ci_records_dir=ci_records_dir,
        now=now,
    )
    citation: dict[str, Any] = {
        "record": reference,
        "field": field,
        "value": None,
        "record_hash": read.citation_hash,
    }
    if not read.record and read.citation_hash is None:
        return FalsifierOutcome("unresolvable", read.detail, citation)
    value = read_field(read.record, field)
    citation["value"] = value
    equals = falsifier.get("equals")
    if reference.partition(":")[0] == "clock":
        target = parse_timestamp(equals)
        current = parse_timestamp(value)
        if target is None or current is None:
            return FalsifierOutcome(
                "unresolvable",
                "a clock falsifier requires an ISO timestamp as its equals value",
                citation,
            )
        if current >= target:
            return FalsifierOutcome(
                "holds", f"the armed moment {equals} has been reached", citation
            )
        return FalsifierOutcome(
            "not_yet", f"the armed moment {equals} has not been reached", citation
        )
    if equals is not None:
        if value == equals:
            return FalsifierOutcome(
                "holds",
                f"{reference} field {field!r} is {value!r}, the ending value ({read.detail})",
                citation,
            )
        return FalsifierOutcome(
            "not_yet",
            f"{reference} field {field!r} is {value!r}, not the ending value "
            f"{equals!r} ({read.detail})",
            citation,
        )
    if value is not None and value != "":
        return FalsifierOutcome(
            "holds",
            f"{reference} field {field!r} now carries {value!r}; the wait's ending "
            f"condition holds ({read.detail})",
            citation,
        )
    return FalsifierOutcome(
        "not_yet",
        f"{reference} field {field!r} carries no value yet ({read.detail})",
        citation,
    )
