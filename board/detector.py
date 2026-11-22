#!/usr/bin/env python3
"""The dead-keeper detector: heartbeat staleness, dual escalation.

Spec AB-001 Section 5.4 as amended, task T017. A scheduled job
running every 2 hours, owned by the board's genesis ``detector_chat``
— a different chat from the keeper's owning chat, named at genesis,
so the detector does not share the keeper's failure modes.

The detector's liveness signal is ONLY the log's heartbeat events
(their stamped ``run_at``): recent activity of any other kind does
not make a dead keeper look alive. If no heartbeat has been
appended for more than two cadence intervals (pilot: 60 minutes at
the 30-minute cadence) while any wait is open or any non-terminal
row exists, the detector escalates:

- one escalation record per target — every open wait's named
  escalation target, plus the board's genesis
  ``escalation_target_2`` — written to the detector's outbox
  directory, outside the board, so escalation never depends on the
  keeper or its chat being alive and is never single-hop;
- the records are keyed by episode (the last heartbeat's event id,
  or the board's genesis when no heartbeat exists), so repeat
  detector runs inside one episode write no duplicates;
- when appends resume, the records are appended to the board as
  ``detector_escalation`` events under the detector chat's actor
  name (``record_pending_escalations``, which the keeper calls at
  the start of each run; the staffing job may also call it
  directly).

This does not establish fleet recovery: the board can refuse to let
a dead fleet look alive; it cannot revive one.

Usage:
    python3 -m board.detector run <board_dir> <outbox_dir>
    python3 -m board.detector record <board_dir> <outbox_dir>
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import append as append_mod
from . import fold, records
from .kernel import TERMINAL_STATUSES

_SLUG = re.compile(r"[^A-Za-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG.sub("-", text).strip("-") or "unnamed"


def _last_heartbeat(events: list[dict[str, Any]]) -> tuple[str | None, Any]:
    """(event_id, run_at) of the latest heartbeat, by its stamped time."""
    best_id: str | None = None
    best_at = None
    for event in events:
        if event.get("kind") != "heartbeat":
            continue
        run_at = records.parse_timestamp((event.get("payload") or {}).get("run_at"))
        if run_at is not None and (best_at is None or run_at > best_at):
            best_id, best_at = event["event_id"], run_at
    return best_id, best_at


def run_detector(board_dir: Path, outbox_dir: Path, now: datetime | None = None) -> dict[str, Any]:
    """Run one detector pass; returns the run report.

    On an escalation condition, one record file per target is
    written into ``outbox_dir`` (created if needed) and named in the
    report. The report also states the evidence: the last
    heartbeat's event and time, the threshold, the open waits and
    the targets.
    """
    board_dir = Path(board_dir)
    outbox_dir = Path(outbox_dir)
    moment = now or records.utcnow()
    report: dict[str, Any] = {
        "board_dir": str(board_dir),
        "run_at": records.format_timestamp(moment),
        "ok": False,
        "escalated": False,
        "targets_written": [],
        "targets_already_recorded": [],
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
    genesis = state.get("genesis") or {}
    board_id = state.get("board_id") or ""
    events = append_mod._read_events(board_dir)

    cadence = records.parse_cadence(genesis.get("keeper_cadence"))
    if cadence is None:
        report["detail"] = (
            f"the board's genesis keeper_cadence {genesis.get('keeper_cadence')!r} "
            "does not parse; staleness cannot be judged"
        )
        return report
    threshold = 2 * cadence

    open_waits = []
    for row_id, row in state.get("rows", {}).items():
        wait = row.get("wait")
        if not isinstance(wait, dict):
            continue
        registration_id = append_mod.find_registration(events, row_id, wait)
        if append_mod.find_wake(events, registration_id, row_id) is None:
            open_waits.append({"row": row_id, "target": wait.get("escalation")})
    non_terminal = [
        row_id
        for row_id, row in state.get("rows", {}).items()
        if row.get("status") not in TERMINAL_STATUSES
    ]
    heartbeat_id, heartbeat_at = _last_heartbeat(events)
    report.update(
        {
            "board_id": board_id,
            "cadence": genesis.get("keeper_cadence"),
            "threshold_seconds": int(threshold.total_seconds()),
            "last_heartbeat_event": heartbeat_id,
            "last_heartbeat_at": (records.format_timestamp(heartbeat_at) if heartbeat_at else None),
            "open_waits": open_waits,
            "non_terminal_rows": non_terminal,
        }
    )
    report["ok"] = True
    if not open_waits and not non_terminal:
        report["detail"] = "no open wait and no non-terminal row; nothing needs a keeper"
        return report
    stale = heartbeat_at is None or (moment - heartbeat_at) > threshold
    if not stale:
        report["detail"] = "the last heartbeat is within two cadence intervals"
        return report

    episode = heartbeat_id or f"genesis-{board_id}"
    targets = []
    for entry in open_waits:
        if entry["target"] and entry["target"] not in targets:
            targets.append(entry["target"])
    second = genesis.get("escalation_target_2")
    if second and second not in targets:
        targets.append(second)
    outbox_dir.mkdir(parents=True, exist_ok=True)
    for target in targets:
        name = f"{_slug(board_id)}--{_slug(episode)}--{_slug(target)}.json"
        path = outbox_dir / name
        record = {
            "board_id": board_id,
            "target": target,
            "detected_at": records.format_timestamp(moment),
            "episode": episode,
            "last_heartbeat_event": heartbeat_id,
            "last_heartbeat_at": report["last_heartbeat_at"],
            "threshold_seconds": int(threshold.total_seconds()),
            "open_waits": open_waits,
            "detail": "no keeper heartbeat for more than two cadence intervals "
            "while the board still has open work (spec 5.4)",
        }
        if path.exists():
            report["targets_already_recorded"].append(name)
            continue
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report["targets_written"].append(name)
    report["escalated"] = True
    report["targets"] = targets
    return report


def record_pending_escalations(
    board_dir: Path, outbox_dir: Path, now: datetime | None = None
) -> list[str]:
    """Append unrecorded outbox escalations as board events.

    Returns the event ids appended. An outbox record is recorded
    once, keyed by its file name in the event payload; records for
    other boards sharing the outbox are left alone.
    """
    board_dir = Path(board_dir)
    outbox_dir = Path(outbox_dir)
    if not outbox_dir.is_dir():
        return []
    folded = fold.fold_board(board_dir)
    if not folded.ok:
        return []
    state = folded.state
    genesis = state.get("genesis") or {}
    board_id = state.get("board_id") or ""
    events = append_mod._read_events(board_dir)
    recorded = {
        (event.get("payload") or {}).get("outbox_file")
        for event in events
        if event.get("kind") == "detector_escalation"
    }
    appended: list[str] = []
    moment = now or records.utcnow()
    for path in sorted(outbox_dir.glob("*.json")):
        if path.name in recorded:
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or record.get("board_id") != board_id:
            continue
        open_rows = [entry.get("row") for entry in record.get("open_waits") or []]
        event = {
            "event_id": f"detector-escalation:{path.stem}",
            "board_id": board_id,
            "row_id": None,
            "actor": genesis.get("detector_chat") or "detector",
            "kind": "detector_escalation",
            "payload": {
                "row": open_rows[0] if open_rows else None,
                "rows": open_rows,
                "target": record.get("target"),
                "detected_at": record.get("detected_at"),
                "last_heartbeat_at": record.get("last_heartbeat_at"),
                "outbox_file": path.name,
                "detail": record.get("detail"),
            },
        }
        for _ in range(4):
            head = fold.log_head_hash(board_dir)
            try:
                stored = append_mod.append_event(board_dir, event, head, now=moment)
            except append_mod.BoardRefusal as refusal:
                if refusal.code == "HEAD_MOVED":
                    continue
                break
            appended.append(stored["event_id"])
            break
    return appended


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in ("run", "record"):
        print(__doc__)
        return 2
    board_dir, outbox_dir = Path(argv[1]), Path(argv[2])
    if argv[0] == "run":
        report = run_detector(board_dir, outbox_dir)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1
    appended = record_pending_escalations(board_dir, outbox_dir)
    print(json.dumps({"recorded": appended}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
