#!/usr/bin/env python3
"""Recovery procedures (spec AB-001 3.2, FR-S3a; task T006).

Recovery is a visible procedure with preserved evidence; a log that
needed recovery says so in its own chain. The fold is never edited
into passing.

Torn tail: a final line that fails to parse or fails the chain is
truncated to the last chain-valid event. The discarded bytes are
preserved to a recovery file beside the log, with their SHA-256
recorded in that file and returned to the caller.

Fork or mid-log break: the board halts, and recovery is only by a
planner-authorized ``recovery`` event appended through the append
command. The canonical head is the branch folded into the last
committed state snapshot (the state file's head hash). Later events
on the surviving prefix are re-appended as new events citing the
originals when still legal, or recorded as discarded; raw lines past
the first chain failure (a divergent branch) are preserved as bytes
in the recovery file. The ``recovery`` event cites the recovery
file's SHA-256 and the authorizing planner, and lists what was
re-appended and what was discarded.

This does not establish that recovery is cheap; it establishes that
it is never invisible.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from . import append as append_mod
from . import canonical, fold, state


def _write_recovery_file(board_dir: Path, record: dict[str, Any]) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = Path(board_dir) / f"recovery-{stamp}.json"
    record = dict(record)
    record["recorded_at"] = stamp
    if not state._write_verified(path, canonical.canonical_line(record)):
        raise OSError(f"recovery file write could not be verified: {path}")
    return path


def _valid_prefix(lines: list[bytes]) -> tuple[list[dict[str, Any]], int]:
    """Parse and chain-verify lines; return (events, first_bad_index).

    Indices count non-blank lines only; logs written by the append
    command have no blank lines.
    """
    events: list[dict[str, Any]] = []
    prev = canonical.GENESIS_PREV_HASH
    index = 0
    for raw in lines:
        if not raw.strip():
            continue
        try:
            event = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return events, index
        if event.get("prev_hash") != prev or canonical.event_hash(event) != event.get("event_hash"):
            return events, index
        events.append(event)
        prev = event["event_hash"]
        index += 1
    return events, index


def _truncate_log(board_dir: Path, keep_events: int) -> None:
    path = Path(board_dir) / fold.EVENTS_FILE
    lines = [raw for raw in path.read_bytes().splitlines(keepends=True) if raw.strip()]
    kept = b"".join(lines[:keep_events])
    if not state._write_verified(path, kept):
        raise OSError(f"log truncation could not be verified: {path}")


def recover_torn_tail(board_dir: Path) -> dict[str, Any]:
    """Truncate a torn final line, preserving the discarded bytes.

    Returns the recovery record. Raises ValueError if the damage is
    not confined to the final line (that is a fork / mid-log break,
    recovered by recover_fork) or if there is nothing to recover.
    """
    board_dir = Path(board_dir)
    lines = [raw for raw in (board_dir / fold.EVENTS_FILE).read_bytes().splitlines() if raw.strip()]
    events, first_bad = _valid_prefix(lines)
    if first_bad >= len(lines):
        raise ValueError("no torn tail: the log is chain-valid end to end")
    if first_bad != len(lines) - 1:
        raise ValueError(
            f"damage starts at line {first_bad} of {len(lines)}; not a torn tail - use recover_fork"
        )
    discarded = lines[first_bad]
    record = {
        "kind": "torn_tail",
        "board_id": events[-1]["board_id"] if events else "",
        "discarded_line_index": first_bad,
        "discarded_sha256": hashlib.sha256(discarded).hexdigest(),
        "discarded_bytes_b64": base64.b64encode(discarded).decode("ascii"),
        "head_after": events[-1]["event_hash"] if events else canonical.GENESIS_PREV_HASH,
    }
    recovery_file = _write_recovery_file(board_dir, record)
    _truncate_log(board_dir, first_bad)
    result = fold.fold_board(board_dir)
    if not result.ok:
        raise OSError("fold still refuses after torn-tail truncation")
    state.write_state(board_dir, result.state)
    record["recovery_file"] = recovery_file.name
    return record


def recover_fork(board_dir: Path, planner: str) -> dict[str, Any]:
    """Recover a forked or mid-log-broken log under planner authority.

    See the module docstring for the procedure. Returns a summary with
    the recovery file name, its SHA-256, and the re-appended and
    discarded event ids as recorded in the ``recovery`` event.
    """
    board_dir = Path(board_dir)
    stored = state.read_state(board_dir)
    if stored is None:
        raise ValueError("no committed state snapshot; the canonical branch is unknowable")
    canonical_head = stored["head_hash"]
    lines = [raw for raw in (board_dir / fold.EVENTS_FILE).read_bytes().splitlines() if raw.strip()]
    events, first_bad = _valid_prefix(lines)
    if first_bad >= len(lines):
        raise ValueError("no fork or break: the log is chain-valid end to end")
    canonical_index = next(
        (i for i, e in enumerate(events) if e["event_hash"] == canonical_head), None
    )
    if canonical_index is None:
        raise ValueError(
            "the state snapshot's head hash is not in the surviving "
            "chain prefix; the canonical branch is unknowable"
        )
    discarded_events = events[canonical_index + 1 :]
    record = {
        "kind": "fork_recovery",
        "board_id": stored["board_id"],
        "authorized_by": planner,
        "canonical_head": canonical_head,
        "discarded_event_ids": [e["event_id"] for e in discarded_events],
        "discarded_raw_lines_b64": [
            base64.b64encode(raw).decode("ascii") for raw in lines[first_bad:]
        ],
    }
    recovery_file = _write_recovery_file(board_dir, record)
    recovery_sha = hashlib.sha256(recovery_file.read_bytes()).hexdigest()
    _truncate_log(board_dir, canonical_index + 1)
    result = fold.fold_board(board_dir)
    if not result.ok:
        raise OSError("the canonical prefix does not fold after truncation")
    state.write_state(board_dir, result.state)
    head = canonical_head
    reappended: list[str] = []
    discarded: list[str] = []
    for original in discarded_events:
        if original["kind"] in ("genesis", "recovery"):
            discarded.append(original["event_id"])
            continue
        replay_payload = dict(original.get("payload") or {})
        # Append-service stamps are not caller input: a replayed wait
        # registration is re-evaluated and re-stamped by the append
        # path (FR-P3), so the original's wake_check is dropped here
        # rather than refused as caller-supplied.
        replay_payload.pop("wake_check", None)
        replay = {
            "event_id": f"recovered-{uuid.uuid4().hex[:16]}",
            "board_id": original["board_id"],
            "row_id": original["row_id"],
            "actor": original["actor"],
            "kind": original["kind"],
            "payload": {
                **replay_payload,
                "recovered_from": original["event_id"],
            },
        }
        try:
            stored_event = append_mod.append_event(board_dir, replay, head)
            head = stored_event["event_hash"]
            reappended.append(original["event_id"])
        except append_mod.BoardRefusal:
            discarded.append(original["event_id"])
    recovery_event = {
        "event_id": f"recovery-{uuid.uuid4().hex[:16]}",
        "board_id": stored["board_id"],
        "row_id": None,
        "actor": planner,
        "kind": "recovery",
        "payload": {
            "recovery_file": recovery_file.name,
            "recovery_file_sha256": recovery_sha,
            "authorized_by": planner,
            "reappended": reappended,
            "discarded": discarded,
        },
    }
    append_mod.append_event(board_dir, recovery_event, head)
    return {
        "recovery_file": recovery_file.name,
        "recovery_file_sha256": recovery_sha,
        "canonical_head": canonical_head,
        "reappended": reappended,
        "discarded": discarded,
    }
