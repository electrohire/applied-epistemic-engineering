#!/usr/bin/env python3
"""The keeper: cited event carriage, matching, sweep, heartbeat.

Spec AB-001 Section 5.1 as amended (FR-P1, FR-P2, FR-P4), tasks
T013/T015/T016. The keeper is a scheduled job per board, staffed by
the board's owning chat; this module is the machinery it runs. One
run, in order:

1. Detector escalations waiting in the detector's outbox are
   recorded as board events (the detector posts outside the board;
   the record lands when appends resume — here, at the keeper's
   next run).
2. The board is folded and its open waits collected: a wait is open
   while its row carries it and no wake event answers its
   registration.
3. Source availability: every configured record source (gatekeeper
   queue directory, gatekeeper ledger, CI records directory) that
   cannot be read is a ``keeper_finding`` (``source_dead``) in the
   log — reportable, never a silent gap (FR-P1).
4. Matching (FR-P2): a ``named_event`` wait is evaluated against its
   wake falsifier's record through ``board.records``; an
   ``external_prose`` wait is evaluated ONLY through the injected
   prose evaluator (the staffing agent's judgment, passed in by the
   job's caller) and the machinery enforces the confinement — prose
   is never consulted for a mechanical kind, and a prose match
   without a record citation is never posted (FR-P1). ``dependency``
   waits are the append path's and are left alone here. A match
   posts a ``keeper_post`` citing the record read and appends the
   wake (actor ``keeper``, via ``match``).
5. Sweep (FR-P4): a wait past its ``sweep_deadline`` unwoken gets a
   direct re-read of its underlying record, and the keeper posts
   what it finds. Satisfied: a ``missed_wake`` finding carrying the
   wait's age (from its registration's stamped ``wake_check``), the
   citing post, and the wake (via ``sweep``). Unresolved: an
   ``escalation`` event naming the wait's escalation target (posted
   once per registration; delivering it to the target's channel is
   the staffing job's work). Between sweeps the missed-wake count
   is a lower bound; the run report says so.
6. A ``heartbeat`` event is appended LAST, on every run including
   empty ones. A heartbeat marks a completed run; it, not the
   scheduling job's completion state, is the keeper's verdict
   (T016).

The keeper never promotes to ready, never fires done, never decides
a gate (Section 5.2); mechanically, it appends only its own event
kinds through the real append path, under the same fold guards as
every other writer. Board refusals on individual appends (a wake
for a row that terminated meanwhile) are collected into the run
report, not fatal; a heartbeat that cannot be appended fails the
run, because a run without a heartbeat must not look complete.

Usage:
    python3 -m board.keeper run <board_dir> <sources.json>

``sources.json`` names the record locations: ``gatekeeper_queue_dir``,
``gatekeeper_ledger``, ``ci_records_dir``, ``detector_outbox_dir``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from . import append as append_mod
from . import fold, records

KEEPER_ACTOR = "keeper"
#: Event kinds by which the keeper asserts an external outcome; each
#: must carry a record citation (FR-P1). ``find_uncited_assertions``
#: is the mechanical check the audit rhythm (T018) samples with.
ASSERTION_KINDS = ("keeper_post", "wake", "escalation")
ProseEvaluator = Callable[[dict[str, Any], dict[str, Any]], "dict[str, Any] | None"]


def _append_with_retry(
    board_dir: Path,
    event: dict[str, Any],
    sources: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Append through the real path, re-reading the head on HEAD_MOVED."""
    last: append_mod.BoardRefusal | None = None
    for _ in range(4):
        head = fold.log_head_hash(board_dir)
        try:
            return append_mod.append_event(board_dir, event, head, verdict_context=sources, now=now)
        except append_mod.BoardRefusal as refusal:
            if refusal.code != "HEAD_MOVED":
                raise
            last = refusal
    assert last is not None
    raise last


def _open_waits(events: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
    """Open waits: row, wait, registration event id, registration event."""
    open_waits = []
    for row_id, row in state.get("rows", {}).items():
        wait = row.get("wait")
        if not isinstance(wait, dict):
            continue
        registration_id = append_mod.find_registration(events, row_id, wait)
        if append_mod.find_wake(events, registration_id, row_id) is not None:
            continue
        registration = next(
            (event for event in events if event["event_id"] == registration_id), None
        )
        open_waits.append(
            {
                "row_id": row_id,
                "row": row,
                "wait": wait,
                "registration_id": registration_id,
                "registration": registration,
            }
        )
    return open_waits


def _already_escalated(events: list[dict[str, Any]], registration_id: str | None) -> bool:
    if registration_id is None:
        return False
    return any(
        event.get("kind") == "escalation"
        and (event.get("payload") or {}).get("wait_event") == registration_id
        for event in events
    )


def _source_problems(sources: dict[str, Any]) -> list[dict[str, Any]]:
    """Configured record sources that cannot be read (FR-P1)."""
    problems = []
    for key in ("gatekeeper_queue_dir", "ci_records_dir"):
        value = sources.get(key)
        if value and not Path(value).is_dir():
            problems.append(
                {"source": key, "detail": f"the configured directory {value} is not readable"}
            )
    ledger = sources.get("gatekeeper_ledger")
    if ledger and not Path(ledger).is_file():
        problems.append(
            {
                "source": "gatekeeper_ledger",
                "detail": f"the configured ledger {ledger} is not readable",
            }
        )
    return problems


def _dependency_citation(state: dict[str, Any], row_id: str, detail: str) -> dict[str, Any]:
    return {
        "record": f"board:{row_id}",
        "field": "status",
        "value": detail,
        "record_hash": state.get("head_hash"),
    }


def find_uncited_assertions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keeper assertions of an outcome without a record citation.

    FR-P1: a keeper post asserting an outcome without a record
    reference is a kernel violation. This is the mechanical check:
    any event under the keeper's actor name of an assertion kind
    whose payload carries no citation naming a record. Actor is
    self-attested (spec 4.2 honesty note); the citation rule is
    mechanical regardless of who wrote the event.
    """
    violations = []
    for event in events:
        if event.get("actor") != KEEPER_ACTOR or event.get("kind") not in ASSERTION_KINDS:
            continue
        citation = (event.get("payload") or {}).get("citation")
        if not isinstance(citation, dict) or not citation.get("record"):
            violations.append(
                {
                    "event_id": event.get("event_id"),
                    "kind": event.get("kind"),
                    "row": (event.get("payload") or {}).get("row"),
                    "detail": "keeper assertion without a record citation (FR-P1)",
                }
            )
    return violations


def run_keeper(
    board_dir: Path,
    sources: dict[str, Any],
    now: datetime | None = None,
    prose_evaluator: ProseEvaluator | None = None,
) -> dict[str, Any]:
    """Run one keeper pass over a board; returns the run report.

    The report is the run's own record: counts of posts, findings,
    wakes and escalations, the waits left open, any append refusals
    collected, and whether the heartbeat landed (``ok``). The
    missed-wake count in a report is the sweep procedure's output
    for this run; between sweeps it is a lower bound (FR-P4).
    """
    from . import detector

    board_dir = Path(board_dir)
    moment = now or records.utcnow()
    stamp = records.format_timestamp(moment)
    run_stamp = stamp.replace("-", "").replace(":", "")
    report: dict[str, Any] = {
        "board_dir": str(board_dir),
        "run_at": stamp,
        "ok": False,
        "posts": 0,
        "findings": 0,
        "wakes": 0,
        "escalations": 0,
        "missed_wakes": 0,
        "missed_wake_count_is_lower_bound": True,
        "waits_open": 0,
        "unresolvable_waits": [],
        "refusals": [],
        "detector_escalations_recorded": [],
    }

    outbox = sources.get("detector_outbox_dir")
    if outbox:
        report["detector_escalations_recorded"] = detector.record_pending_escalations(
            board_dir, Path(outbox), now=moment
        )

    folded = fold.fold_board(board_dir)
    if not folded.ok:
        refusal = folded.refusal
        assert refusal is not None
        report["fold_refusal"] = {
            "event_id": refusal.event_id,
            "index": refusal.index,
            "reason": refusal.reason,
        }
        return report
    state = folded.state
    board_id = state.get("board_id") or ""
    genesis = state.get("genesis") or {}
    events = append_mod._read_events(board_dir)

    def post(event: dict[str, Any]) -> dict[str, Any] | None:
        try:
            stored = _append_with_retry(board_dir, event, sources, moment)
        except append_mod.BoardRefusal as refusal:
            report["refusals"].append(
                {"event_id": event["event_id"], "code": refusal.code, "message": refusal.message}
            )
            return None
        events.append(stored)
        return stored

    def caller(event_id: str, kind: str, row_id: str | None, payload: dict[str, Any]):
        return {
            "event_id": event_id,
            "board_id": board_id,
            "row_id": row_id,
            "actor": KEEPER_ACTOR,
            "kind": kind,
            "payload": payload,
        }

    def wake(row_id: str, registration_id: str | None, via: str, citation, detail: str):
        stored = post(
            caller(
                f"wake:keeper:{registration_id}",
                "wake",
                row_id,
                {
                    "row": row_id,
                    "wait_event": registration_id,
                    "via": via,
                    "detail": detail,
                    "citation": citation,
                },
            )
        )
        if stored is not None:
            report["wakes"] += 1
        return stored

    def keeper_post(row_id: str, registration_id: str | None, citation, detail: str):
        stored = post(
            caller(
                f"keeper-post:{run_stamp}:{row_id}",
                "keeper_post",
                None,
                {
                    "row": row_id,
                    "wait_event": registration_id,
                    "citation": citation,
                    "detail": detail,
                },
            )
        )
        if stored is not None:
            report["posts"] += 1
        return stored

    def finding(payload: dict[str, Any]):
        stored = post(
            caller(
                f"keeper-finding:{run_stamp}:{report['findings']}",
                "keeper_finding",
                None,
                payload,
            )
        )
        if stored is not None:
            report["findings"] += 1
        return stored

    locations = append_mod._record_locations(sources)

    for problem in _source_problems(sources):
        finding(
            {
                "finding": "source_dead",
                "source": problem["source"],
                "detail": problem["detail"]
                + "; waits naming this source read as unresolvable until it returns",
            }
        )

    open_waits = _open_waits(events, state)
    remaining = []
    for entry in open_waits:
        row_id, wait = entry["row_id"], entry["wait"]
        registration_id = entry["registration_id"]
        kind = wait.get("wait_kind")
        matched = False
        if kind == "named_event":
            outcome = records.evaluate_falsifier(wait, board_state=state, now=moment, **locations)
            if outcome.outcome == "holds":
                keeper_post(row_id, registration_id, outcome.citation, outcome.detail)
                wake(row_id, registration_id, "match", outcome.citation, outcome.detail)
                matched = True
            elif outcome.outcome == "unresolvable":
                report["unresolvable_waits"].append({"row": row_id, "detail": outcome.detail})
        elif kind == "external_prose" and prose_evaluator is not None:
            citation = prose_evaluator(wait, entry["row"])
            if citation is not None:
                if not isinstance(citation, dict) or not citation.get("record"):
                    report["refusals"].append(
                        {
                            "event_id": f"keeper-post:{run_stamp}:{row_id}",
                            "code": "UNCITED_PROSE_MATCH",
                            "message": "the prose evaluator returned a match "
                            "without a record citation; FR-P1 forbids posting it",
                        }
                    )
                else:
                    detail = (
                        "the wait's prose condition is met by the record "
                        f"{citation['record']} (prose evaluation by the staffing agent)"
                    )
                    keeper_post(row_id, registration_id, citation, detail)
                    wake(row_id, registration_id, "match", citation, detail)
                    matched = True
        # dependency waits are the append path's (FR-P3/A5.1.3); the
        # keeper's only duty toward them is the sweep below.
        if not matched:
            remaining.append(entry)

    swept_still_open = []
    for entry in remaining:
        row_id, wait = entry["row_id"], entry["wait"]
        registration_id = entry["registration_id"]
        deadline = records.parse_timestamp(wait.get("sweep_deadline"))
        if deadline is None:
            finding(
                {
                    "finding": "sweep_deadline_unparseable",
                    "row": row_id,
                    "wait_event": registration_id,
                    "detail": f"the wait's sweep_deadline {wait.get('sweep_deadline')!r} "
                    "does not parse; the sweep cannot bound this wait",
                }
            )
            swept_still_open.append(entry)
            continue
        if moment < deadline:
            swept_still_open.append(entry)
            continue
        # FR-P4 sweep: a direct re-read of the underlying record.
        if wait.get("wait_kind") == "dependency":
            satisfied = append_mod._dependency_satisfied(state, entry["row"], wait)
            if satisfied is not None:
                holds, why = satisfied
                outcome = records.FalsifierOutcome(
                    "holds" if holds else "not_yet",
                    why,
                    _dependency_citation(state, row_id, why),
                )
            else:
                outcome = records.evaluate_falsifier(
                    wait, board_state=state, now=moment, **locations
                )
        else:
            outcome = records.evaluate_falsifier(wait, board_state=state, now=moment, **locations)
        keeper_post(row_id, registration_id, outcome.citation, outcome.detail)
        if outcome.outcome == "holds":
            registered_at = None
            age_seconds = None
            registration = entry["registration"]
            if registration is not None:
                stamp_dict = (registration.get("payload") or {}).get("wake_check") or {}
                registered_at = stamp_dict.get("evaluated_at")
                parsed = records.parse_timestamp(registered_at)
                if parsed is not None:
                    age_seconds = int((moment - parsed).total_seconds())
            finding(
                {
                    "finding": "missed_wake",
                    "row": row_id,
                    "wait_event": registration_id,
                    "registered_at": registered_at,
                    "age_seconds": age_seconds,
                    "citation": outcome.citation,
                    "detail": "the sweep's direct re-read found this wait's ending "
                    "condition already satisfied; the wake had been missed "
                    f"(wait age {age_seconds} seconds at the sweep)",
                }
            )
            report["missed_wakes"] += 1
            wake(
                row_id,
                registration_id,
                "sweep",
                outcome.citation,
                f"sweep re-read: {outcome.detail}",
            )
        else:
            if not _already_escalated(events, registration_id):
                stored = post(
                    caller(
                        f"keeper-escalation:{registration_id}",
                        "escalation",
                        None,
                        {
                            "row": row_id,
                            "wait_event": registration_id,
                            "target": wait.get("escalation"),
                            "citation": outcome.citation,
                            "detail": "the wait survived its sweep unresolved "
                            f"({outcome.outcome}): {outcome.detail}; delivery to "
                            "the target's channel is the staffing job's work",
                        },
                    )
                )
                if stored is not None:
                    report["escalations"] += 1
            swept_still_open.append(entry)

    report["waits_open"] = len(swept_still_open)
    heartbeat = caller(
        f"keeper-heartbeat:{run_stamp}",
        "heartbeat",
        None,
        {
            "run_at": stamp,
            "cadence": genesis.get("keeper_cadence"),
            "waits_open": report["waits_open"],
            "posts": report["posts"],
            "findings": report["findings"],
            "wakes": report["wakes"],
            "escalations": report["escalations"],
            "missed_wakes": report["missed_wakes"],
        },
    )
    try:
        _append_with_retry(board_dir, heartbeat, sources, moment)
    except append_mod.BoardRefusal as refusal:
        report["refusals"].append(
            {"event_id": heartbeat["event_id"], "code": refusal.code, "message": refusal.message}
        )
        return report
    report["ok"] = True
    return report


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != "run":
        print(__doc__)
        return 2
    board_dir = Path(argv[1])
    sources = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    report = run_keeper(board_dir, sources)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
