#!/usr/bin/env python3
"""Weekly metrics and the pilot overhead report (spec 5.3, T024).

Generated from the log by script, per board, under the generated
view discipline: the report names the head hash it was generated
from, and the rendered form carries a generated-file header. The
metrics are the pilot's cost-and-behavior numbers, reported beside
what the board prevented, in the same weekly rhythm (Section 7.4);
they do not establish that the board pays for itself — the verdict
report (T032) answers that with these numbers.

What the log itself measures:

- rows by status, with each row's age. Events carry no general
  timestamp in this substrate; the log's stamped time evidence is
  the keeper's heartbeat ``run_at``, wait registrations'
  ``wake_check.evaluated_at``, and detector escalations'
  ``detected_at``. A row's ``age_seconds`` is measured from the
  latest stamped time at or before its creation event, so it is
  an upper bound on the true age; ``age_events`` (events since
  creation) is exact. A row with no stamped evidence at or before
  its creation reports ``age_seconds`` as null, never a guess.
- waits by kind with wake outcomes: woken by match (a wake via
  ``match``, ``wake_on_watch``, or ``dependency`` — the ending
  condition found to hold), woken by sweep, escalated, closed
  without a wake (consumed by an unblock or replaced), still
  waiting.
- planner overrides of blocked rows (the ``blocked -> in_progress``
  transition carrying an ``override_reason``) as their own
  category.
- keeper missed-wake count: the ``missed_wake`` findings the
  sweep procedure recorded. Between sweeps this is a lower bound
  (FR-P4) and the report says so on its face.
- false-wake count: wakes whose basis the log itself can
  re-verify and finds absent — a wake naming no registration of
  its row, a wake-on-watch whose registration stamp does not say
  the condition held, a dependency wake the prefix fold shows
  unsatisfied, or a keeper wake whose cited record is unchanged
  since citation (its hash still matches) and no longer satisfies
  the wait's falsifier. Wakes whose basis cannot be re-verified
  from the log and the supplied record sources are counted as
  indeterminate, never silently as sound.
- board staleness: no stamped log activity for 24 hours while
  non-terminal rows exist (Section 5.4). With no stamped time
  evidence in the log at all, staleness is reported as unknown,
  never inferred from absence.
- genesis and amendment event counts.

What the log cannot measure is supplied by the weekly rhythm as
the ``overhead`` input and carried verbatim: keeper session cost
(agent tokens and wall time), audit labor, and note-authoring
cost where KB-3 instrumentation is active. Absent the input,
those fields are null and the report says they were not supplied;
the generator never estimates them.

Usage:
    python3 -m board.metrics <board_dir> [--since N]
        [--overhead overhead.json] [--sources sources.json]
        [--render report.md]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import append as append_mod
from . import fold, records
from .kernel import TERMINAL_STATUSES

STALENESS_THRESHOLD = timedelta(hours=24)
GENERATED_HEADER = (
    "<!-- GENERATED from the board log by board/metrics.py - do not edit by hand. -->"
)
MATCH_VIAS = ("match", "wake_on_watch", "dependency")


def _event_time(event: dict[str, Any]) -> datetime | None:
    """The stamped time an event carries, if it carries one."""
    payload = event.get("payload") or {}
    for key in ("run_at", "detected_at"):
        parsed = records.parse_timestamp(payload.get(key))
        if parsed is not None:
            return parsed
    stamp = payload.get("wake_check") or {}
    return records.parse_timestamp(stamp.get("evaluated_at"))


def _parse_events(board_dir: Path) -> list[dict[str, Any]]:
    path = Path(board_dir) / fold.EVENTS_FILE
    if not path.exists():
        return []
    events = []
    for raw in path.read_bytes().splitlines():
        if raw.strip():
            events.append(json.loads(raw.decode("utf-8")))
    return events


def _wait_outcomes(
    events: list[dict[str, Any]], state: dict[str, Any]
) -> tuple[dict[str, dict[str, int]], list[dict[str, Any]]]:
    """Per-kind wake outcome counts, and the registration list."""
    registrations: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        registration = append_mod._wait_registration(event)
        if registration is None:
            continue
        row_id, wait = registration
        registrations.append(
            {
                "index": index,
                "event_id": event["event_id"],
                "row": row_id,
                "wait": wait,
                "kind": wait.get("wait_kind"),
            }
        )
    escalated = {
        (event.get("payload") or {}).get("wait_event")
        for event in events
        if event.get("kind") == "escalation"
    }
    by_kind: dict[str, dict[str, int]] = {}
    for entry in registrations:
        row = state.get("rows", {}).get(entry["row"])
        wake = append_mod.find_wake(events, entry["event_id"], entry["row"])
        if wake is not None:
            via = (wake.get("payload") or {}).get("via")
            outcome = "woken_by_sweep" if via == "sweep" else "woken_by_match"
        elif entry["event_id"] in escalated:
            outcome = "escalated"
        elif (
            row is None
            or row.get("wait") != entry["wait"]
            or row.get("status") in TERMINAL_STATUSES
        ):
            outcome = "closed_without_wake"
        else:
            outcome = "still_waiting"
        entry["outcome"] = outcome
        bucket = by_kind.setdefault(entry["kind"], {})
        bucket[outcome] = bucket.get(outcome, 0) + 1
    return by_kind, registrations


def _false_wakes(
    events: list[dict[str, Any]],
    since_index: int,
    sources: dict[str, Any],
) -> tuple[int, int, list[dict[str, Any]]]:
    """(false count, indeterminate count, details) over wake events.

    Only bases the log (plus the supplied record sources) can
    re-verify exactly are judged; the rest are indeterminate.
    """
    locations = append_mod._record_locations(sources)
    false_count = 0
    indeterminate = 0
    details: list[dict[str, Any]] = []
    registrations = {event["event_id"]: event for event in events}
    for index, event in enumerate(events):
        if index < since_index or event.get("kind") != "wake":
            continue
        payload = event.get("payload") or {}
        row_id = payload.get("row")
        registration = registrations.get(payload.get("wait_event") or "")
        via = payload.get("via")
        verdict: bool | None = None  # True = the wake's basis holds
        if registration is None or registration.get("row_id") not in (None, row_id):
            verdict = False
        elif via == "wake_on_watch":
            stamp = (registration.get("payload") or {}).get("wake_check") or {}
            verdict = stamp.get("outcome") == "holds"
        elif via == "dependency":
            prefix = fold.fold_events(events[:index], fold.default_board_checker())
            if prefix.ok:
                prow = prefix.state.get("rows", {}).get(row_id)
                pwait = (prow or {}).get("wait") or {}
                satisfied = append_mod._dependency_satisfied(prefix.state, prow, pwait)
                verdict = None if satisfied is None else satisfied[0]
        elif via in ("match", "sweep"):
            citation = payload.get("citation") or {}
            registered = append_mod._wait_registration(registration)
            if citation.get("record") and registered is not None:
                read = records.resolve_record(
                    citation["record"],
                    board_state=None,
                    gatekeeper_queue_dir=locations.get("gatekeeper_queue_dir"),
                    gatekeeper_ledger=locations.get("gatekeeper_ledger"),
                    ci_records_dir=locations.get("ci_records_dir"),
                )
                if read.citation_hash is not None and read.citation_hash == citation.get(
                    "record_hash"
                ):
                    outcome = records.evaluate_falsifier(
                        registered[1],
                        board_state=None,
                        gatekeeper_queue_dir=locations.get("gatekeeper_queue_dir"),
                        gatekeeper_ledger=locations.get("gatekeeper_ledger"),
                        ci_records_dir=locations.get("ci_records_dir"),
                    )
                    verdict = outcome.outcome == "holds"
        if verdict is False:
            false_count += 1
            details.append({"event_id": event.get("event_id"), "row": row_id, "via": via})
        elif verdict is None:
            indeterminate += 1
    return false_count, indeterminate, details


def generate_metrics(
    board_dir: Path,
    *,
    now: datetime | None = None,
    since_index: int = 0,
    overhead: dict[str, Any] | None = None,
    sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate the weekly metrics report for one board.

    Event-count sections (overrides, missed/false wakes, genesis
    and amendment counts) cover events at or after ``since_index``
    (the whole log by default); rows, waits and staleness describe
    the board as it stands. A board whose log does not fold
    reports ``ok`` False with the refusal, and nothing else.
    """
    board_dir = Path(board_dir)
    moment = now or records.utcnow()
    report: dict[str, Any] = {
        "board_dir": str(board_dir),
        "board_id": None,
        "generated_at": records.format_timestamp(moment),
        "generated_from_head": None,
        "ok": False,
        "since_index": since_index,
    }
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
    events = _parse_events(board_dir)
    report["board_id"] = state.get("board_id")
    report["generated_from_head"] = state.get("head_hash")
    report["event_count"] = len(events)

    # Stamped time evidence, by event index (see module docstring).
    time_at: list[datetime | None] = []
    latest: datetime | None = None
    for event in events:
        parsed = _event_time(event)
        if parsed is not None and (latest is None or parsed > latest):
            latest = parsed
        time_at.append(latest)
    last_activity = latest

    created_index: dict[str, int] = {}
    status_index: dict[str, int] = {}
    for index, event in enumerate(events):
        payload = event.get("payload") or {}
        if event.get("kind") == "row_created":
            created_index[str(payload.get("row_id"))] = index
            status_index[str(payload.get("row_id"))] = index
        elif event.get("kind") == "row_update":
            changes = payload.get("changes") or {}
            if "status" in changes and event.get("row_id"):
                status_index[str(event["row_id"])] = index

    def age(at_index: int | None) -> tuple[int | None, int]:
        if at_index is None:
            return None, 0
        seconds = None
        if at_index < len(time_at) and time_at[at_index] is not None:
            seconds = int((moment - time_at[at_index]).total_seconds())
        return seconds, len(events) - 1 - at_index

    rows_report: dict[str, Any] = {}
    by_status: dict[str, int] = {}
    for row_id, row in sorted(state.get("rows", {}).items()):
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        age_seconds, age_events = age(created_index.get(row_id))
        status_seconds, status_events = age(status_index.get(row_id))
        rows_report[row_id] = {
            "status": row["status"],
            "age_seconds": age_seconds,
            "age_events": age_events,
            "status_age_seconds": status_seconds,
            "status_age_events": status_events,
        }
    report["rows_by_status"] = by_status
    report["rows"] = rows_report

    by_kind, _registrations = _wait_outcomes(events, state)
    report["waits_by_kind"] = by_kind

    overrides = []
    missed_wakes = 0
    genesis_count = 0
    amendment_count = 0
    recovery_count = 0
    for index, event in enumerate(events):
        kind = event.get("kind")
        if kind == "genesis":
            genesis_count += 1
        if index < since_index:
            continue
        payload = event.get("payload") or {}
        if kind == "row_update":
            changes = payload.get("changes") or {}
            if changes.get("status") == "in_progress" and payload.get("override_reason"):
                overrides.append({"row": event.get("row_id"), "event_id": event.get("event_id")})
        elif kind == "keeper_finding" and payload.get("finding") == "missed_wake":
            missed_wakes += 1
        elif kind == "amendment":
            amendment_count += 1
        elif kind == "recovery":
            recovery_count += 1
    report["planner_overrides"] = {"count": len(overrides), "events": overrides}
    report["missed_wakes"] = {
        "count": missed_wakes,
        "is_lower_bound": True,
        "note": "the sweep procedure's recorded findings; between sweeps "
        "the true count can only be higher (FR-P4)",
    }
    false_count, indeterminate, false_details = _false_wakes(events, since_index, sources or {})
    report["false_wakes"] = {
        "count": false_count,
        "indeterminate": indeterminate,
        "events": false_details,
        "note": "wakes whose basis the log and the supplied record "
        "sources re-verify as absent; wakes that cannot be re-verified "
        "exactly are counted as indeterminate, never as sound",
    }

    non_terminal = [
        row_id
        for row_id, row in state.get("rows", {}).items()
        if row.get("status") not in TERMINAL_STATUSES
    ]
    if last_activity is None:
        stale: bool | None = None
        staleness_note = (
            "the log carries no stamped time evidence; staleness is "
            "unknown and is not inferred from absence"
        )
    else:
        stale = bool(non_terminal) and (moment - last_activity) > STALENESS_THRESHOLD
        staleness_note = (
            "no stamped log activity for 24 hours while non-terminal rows exist"
            if stale
            else "stamped log activity within 24 hours, or no non-terminal rows"
        )
    report["staleness"] = {
        "stale": stale,
        "last_activity_at": (records.format_timestamp(last_activity) if last_activity else None),
        "non_terminal_rows": non_terminal,
        "note": staleness_note,
    }

    supplied = overhead or {}
    report["pilot_overhead"] = {
        "keeper_session_cost": supplied.get("keeper_session_cost"),
        "audit_labor": supplied.get("audit_labor"),
        "note_authoring_cost": supplied.get("note_authoring_cost"),
        "genesis_events": genesis_count,
        "amendment_events": amendment_count,
        "recovery_events": recovery_count,
        "note": (
            "session costs and labor are supplied by the weekly rhythm "
            "and carried verbatim; null means not supplied, never zero"
            if overhead is None
            else "supplied by the weekly rhythm and carried verbatim"
        ),
    }
    report["ok"] = True
    return report


def render_metrics(report: dict[str, Any]) -> str:
    """Render the report as a generated markdown view (T007 discipline)."""
    lines = [GENERATED_HEADER]
    lines.append(f"# Weekly metrics: {report.get('board_id')}")
    lines.append(f"Generated from head: {report.get('generated_from_head')}")
    lines.append(f"Generated at: {report.get('generated_at')}")
    if not report.get("ok"):
        refusal = report.get("fold_refusal") or {}
        lines.append(f"FOLD REFUSED at event {refusal.get('event_id')}: {refusal.get('reason')}")
        lines.append("")
        return "\n".join(lines)
    lines.append("")
    lines.append("## Rows by status")
    for status, count in sorted(report["rows_by_status"].items()):
        lines.append(f"- {status}: {count}")
    lines.append("")
    lines.append("## Waits by kind and outcome")
    for kind, outcomes in sorted(report["waits_by_kind"].items()):
        summary = ", ".join(f"{name} {n}" for name, n in sorted(outcomes.items()))
        lines.append(f"- {kind}: {summary}")
    lines.append("")
    lines.append(f"Planner overrides of blocked rows: {report['planner_overrides']['count']}")
    lines.append(f"Keeper missed wakes: {report['missed_wakes']['count']} (lower bound)")
    lines.append(
        f"False wakes: {report['false_wakes']['count']} "
        f"({report['false_wakes']['indeterminate']} indeterminate)"
    )
    staleness = report["staleness"]
    label = {True: "STALE", False: "not stale", None: "unknown"}[staleness["stale"]]
    lines.append(
        f"Board staleness: {label} (last stamped activity: {staleness['last_activity_at']})"
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    board_dir = Path(argv[0])
    since = 0
    overhead = None
    sources: dict[str, Any] = {}
    render_path = None
    args = argv[1:]
    while args:
        if args[0] == "--since":
            since = int(args[1])
            args = args[2:]
        elif args[0] == "--overhead":
            overhead = json.loads(Path(args[1]).read_text(encoding="utf-8"))
            args = args[2:]
        elif args[0] == "--sources":
            sources = json.loads(Path(args[1]).read_text(encoding="utf-8"))
            args = args[2:]
        elif args[0] == "--render":
            render_path = Path(args[1])
            args = args[2:]
        else:
            print(__doc__)
            return 2
    report = generate_metrics(board_dir, since_index=since, overhead=overhead, sources=sources)
    if render_path is not None:
        from . import state

        if not state._write_verified(render_path, render_metrics(report).encode("utf-8")):
            print(f"the rendered report could not be verified: {render_path}")
            return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
