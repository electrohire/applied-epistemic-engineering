#!/usr/bin/env python3
"""Fold and chain verification (spec AB-001 3.2, FR-S1/FR-S2; task T004).

The fold replays events into row and board state. State is a pure
function of the log: the same log always folds to the same state.

The fold refuses divergence. A chain failure (a ``prev_hash`` that does
not match the previous event's hash, or an ``event_hash`` that does not
recompute) or a kernel-illegal transition stops the fold at the
offending event and reports it; the fold never repairs silently.

Transition legality comes from the kernel's table (spec 4.2, task T008)
by injection: ``transition_checker`` is a callable taking
``(event, state)`` and returning a refusal reason or None. The default
checker enforces only the substrate's structural rules: genesis first
and unique, row events naming existing rows, no duplicate row creation,
and no row changes while the board is halted (resume, recovery, and
board-level events excepted). Phase 2's kernel supplies the full table
through the same seam; the fold's refusal mechanics do not change.

A repeated ``event_id`` is not a fold refusal: the append path prevents
it, and in a recovered log it is reported as a finding against the
recovery record while the duplicate is not applied twice. A final line
that fails to parse is a torn tail: reported as a finding, with the
fold returning the state of the chain-valid prefix; recovery (T006)
owns truncation. A parse failure anywhere else is a refusal.

This does not establish that the events themselves were truthful;
provenance is the actor field plus the verdict rules, not the chain.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import canonical, validate

EVENTS_FILE = "events.jsonl"

TransitionChecker = Callable[[dict[str, Any], dict[str, Any]], "str | None"]


@dataclass
class FoldRefusal:
    """The fold stopped: index (0-based), event id if known, reason."""

    index: int
    event_id: str | None
    reason: str


@dataclass
class FoldResult:
    state: dict[str, Any]
    findings: list[dict[str, Any]] = field(default_factory=list)
    refusal: FoldRefusal | None = None

    @property
    def ok(self) -> bool:
        return self.refusal is None


def empty_state(board_id: str = "") -> dict[str, Any]:
    return {
        "board_id": board_id,
        "genesis": None,
        "rows": {},
        "halted": False,
        "halt_event": None,
        "head_hash": canonical.GENESIS_PREV_HASH,
        "event_count": 0,
        "last_event": None,
    }


def structural_checker(event: dict[str, Any], state: dict[str, Any]) -> str | None:
    """The substrate's structural legality rules (see module docstring)."""
    kind = event["kind"]
    if state["genesis"] is None:
        if kind != "genesis":
            return "the first event of a board must be its genesis event"
        return None
    if kind == "genesis":
        return "a board has exactly one genesis event per generation"
    if (
        state["halted"]
        and kind not in ("resume", "recovery", "halt")
        and (event.get("row_id") is not None or kind in ("row_created", "amendment"))
    ):
        return "the board is halted; row changes are refused until a resume event"
    if kind == "row_created":
        row_id = (event.get("payload") or {}).get("row_id")
        if row_id in state["rows"]:
            return f"row {row_id!r} already exists"
    elif (
        event.get("row_id") is not None
        and event["row_id"] not in state["rows"]
        and kind != "recovery"
    ):
        return f"event names unknown row {event['row_id']!r}"
    return None


def _apply(event: dict[str, Any], state: dict[str, Any]) -> None:
    kind = event["kind"]
    payload = event.get("payload") or {}
    if kind == "genesis":
        state["genesis"] = dict(payload)
        state["board_id"] = payload["board_id"]
    elif kind == "row_created":
        row = {
            "row_id": payload["row_id"],
            "board_id": state["board_id"],
            "program": (state["genesis"] or {}).get("program", ""),
            "spec_ref": (state["genesis"] or {}).get("spec_ref", ""),
            "spec_hash": (state["genesis"] or {}).get("spec_hash", ""),
            "task_ref": payload.get("task_ref", ""),
            "status": payload.get("status", "proposed"),
            "depends_on": list(payload.get("depends_on", [])),
            "assignee_kind": payload.get("assignee_kind"),
            "assignee_instance": payload.get("assignee_instance"),
            "claim_ids": list(payload.get("claim_ids", [])),
            "execution_state": payload.get("execution_state", "none"),
            "verdict_ref": payload.get("verdict_ref"),
            "wait": payload.get("wait"),
            "created_event": event["event_id"],
            "last_event": event["event_id"],
            "amendment_seq": 0,
        }
        for optional in ("body", "resumption_note", "blocker_note"):
            if optional in payload:
                row[optional] = payload[optional]
        state["rows"][row["row_id"]] = row
    elif kind in ("row_update", "amendment"):
        row = state["rows"].get(event.get("row_id") or payload.get("row_id"))
        if row is not None:
            changes = payload.get("changes") or {}
            for key, value in changes.items():
                if key in row and key not in ("amendment_seq", "created_event"):
                    row[key] = value
            if kind == "amendment":
                row["amendment_seq"] += 1
            row["last_event"] = event["event_id"]
    elif kind == "halt":
        state["halted"] = True
        state["halt_event"] = event["event_id"]
    elif kind == "resume":
        state["halted"] = False
        state["halt_event"] = None
    if event.get("row_id") is not None and kind not in ("row_created", "row_update", "amendment"):
        row = state["rows"].get(event["row_id"])
        if row is not None:
            row["last_event"] = event["event_id"]
    state["head_hash"] = event["event_hash"]
    state["event_count"] += 1
    state["last_event"] = event["event_id"]


def fold_events(
    events: list[dict[str, Any]],
    transition_checker: TransitionChecker | None = None,
) -> FoldResult:
    """Fold already-parsed events, verifying the chain as they apply."""
    checker = transition_checker or structural_checker
    state = empty_state()
    findings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    prev_hash = canonical.GENESIS_PREV_HASH
    for index, event in enumerate(events):
        event_id = event.get("event_id")
        problems = validate.validate_stored_event(event)
        if problems:
            return FoldResult(state, findings, FoldRefusal(index, event_id, "; ".join(problems)))
        if event["prev_hash"] != prev_hash:
            return FoldResult(
                state,
                findings,
                FoldRefusal(
                    index,
                    event_id,
                    f"chain break: prev_hash {event['prev_hash']} does not "
                    f"match the previous event hash {prev_hash}",
                ),
            )
        if canonical.event_hash(event) != event["event_hash"]:
            return FoldResult(
                state,
                findings,
                FoldRefusal(index, event_id, "event_hash does not recompute from the content"),
            )
        if event_id in seen_ids:
            findings.append(
                {
                    "kind": "duplicate_event_id",
                    "event_id": event_id,
                    "index": index,
                    "note": "repeated event_id reported against the recovery "
                    "record; the duplicate was not applied",
                }
            )
            prev_hash = event["event_hash"]
            continue
        reason = checker(event, state)
        if reason is not None:
            return FoldResult(state, findings, FoldRefusal(index, event_id, reason))
        seen_ids.add(event_id)
        _apply(event, state)
        prev_hash = event["event_hash"]
    return FoldResult(state, findings)


def fold_lines(
    lines: list[bytes],
    transition_checker: TransitionChecker | None = None,
) -> FoldResult:
    """Fold raw JSONL lines; a torn final line is a finding, not a refusal."""
    events: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for index, raw in enumerate(lines):
        if not raw.strip():
            continue
        try:
            events.append(json.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as exc:
            if index == len(lines) - 1:
                findings.append(
                    {
                        "kind": "torn_tail",
                        "index": index,
                        "note": f"final line does not parse ({exc}); recovery owns truncation",
                    }
                )
                result = fold_events(events, transition_checker)
                result.findings = findings + result.findings
                return result
            return FoldResult(
                empty_state(),
                findings,
                FoldRefusal(index, None, f"line {index} does not parse: {exc}"),
            )
    result = fold_events(events, transition_checker)
    result.findings = findings + result.findings
    return result


def fold_board(board_dir: Path) -> FoldResult:
    path = Path(board_dir) / EVENTS_FILE
    if not path.exists():
        return FoldResult(empty_state())
    return fold_lines(path.read_bytes().splitlines())


def log_head_hash(board_dir: Path) -> str:
    """The event_hash of the log's last parseable event (genesis prev if none)."""
    path = Path(board_dir) / EVENTS_FILE
    if not path.exists():
        return canonical.GENESIS_PREV_HASH
    head = canonical.GENESIS_PREV_HASH
    for raw in path.read_bytes().splitlines():
        if not raw.strip():
            continue
        try:
            head = json.loads(raw.decode("utf-8"))["event_hash"]
        except (ValueError, UnicodeDecodeError, KeyError):
            break
    return head
