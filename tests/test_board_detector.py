"""Phase 3 detector: T017 (dead-keeper detector, dual escalation).

The drill runs on real files end-to-end: a real board with an open
wait, a real keeper run that lands a heartbeat, then silence. The
detector — reading only heartbeat events — escalates to both
targets through its outbox, repeat runs in the same episode write
no duplicates, and the escalation is recorded as a board event when
appends resume. Recent non-heartbeat activity does not mask a stale
heartbeat.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import append as append_mod  # noqa: E402
from board import detector, fold, keeper  # noqa: E402

if sys.platform == "win32":
    pytest.skip(
        "board substrate is POSIX-only (plan: fcntl.flock; boards live on Linux hosts)",
        allow_module_level=True,
    )

BOARD = "board-detector"
GENESIS = {
    "board_id": BOARD,
    "program": "p",
    "spec_ref": "AB-001",
    "spec_hash": "a" * 64,
    "wip_limit": 4,
    "keeper_cadence": "30m",
    "detector_chat": "detector-chat",
    "escalation_target_2": "owner-2",
}
NOTE = (
    "Current position: blocked on a record outside this board.\n"
    "Next action: resume when the wake lands.\n"
    "Records that matter: the wait's wake falsifier.\n"
    "What would change the plan: the record resolving the other way.\n"
)
T0 = datetime(2026, 11, 21, 12, 0, 0, tzinfo=UTC)
WAIT = {
    "wait_kind": "named_event",
    "wake_falsifier": {"record": "gatekeeper:job-x", "field": "state", "equals": "completed"},
    "sweep_deadline": "2026-11-21T14:00:00Z",
    "escalation": "owner-1",
}


def caller(event_id, kind, row_id, payload, actor="planner"):
    return {
        "event_id": event_id,
        "board_id": BOARD,
        "row_id": row_id,
        "actor": actor,
        "kind": kind,
        "payload": payload,
    }


def append(board_dir, event, now=T0):
    head = fold.log_head_hash(board_dir)
    return append_mod.append_event(board_dir, event, head, now=now)


def make_board(tmp_path):
    board_dir = tmp_path / "b"
    append_mod.create_board(board_dir, dict(GENESIS), actor="planner")
    return board_dir


def blocked_board(tmp_path):
    board_dir = make_board(tmp_path)
    append(
        board_dir,
        caller(
            "create-r1",
            "row_created",
            "r1",
            {
                "row_id": "r1",
                "task_ref": "T-r1",
                "assignee_kind": "worker",
                "assignee_instance": "worker-1",
            },
        ),
    )
    for to_status in ("planned", "ready", "in_progress"):
        append(
            board_dir,
            caller(f"r1-{to_status}", "row_update", "r1", {"changes": {"status": to_status}}),
        )
    append(
        board_dir,
        caller(
            "r1-block",
            "row_update",
            "r1",
            {"changes": {"status": "blocked", "wait": dict(WAIT)}, "resumption_note": NOTE},
        ),
    )
    return board_dir


def outbox_files(outbox):
    return sorted(path.name for path in outbox.glob("*.json"))


def test_dead_keeper_drill(tmp_path):
    board_dir = blocked_board(tmp_path)
    outbox = tmp_path / "outbox"
    # The keeper runs once, on cadence, and then dies.
    report = keeper.run_keeper(board_dir, {}, now=T0)
    assert report["ok"] is True

    # Within the threshold: no escalation.
    report = detector.run_detector(board_dir, outbox, now=T0 + timedelta(minutes=59))
    assert report["ok"] is True and report["escalated"] is False
    assert outbox_files(outbox) == []

    # Past two cadence intervals with a wait open: dual escalation.
    report = detector.run_detector(board_dir, outbox, now=T0 + timedelta(minutes=61))
    assert report["escalated"] is True
    assert set(report["targets"]) == {"owner-1", "owner-2"}
    assert len(report["targets_written"]) == 2
    assert len(outbox_files(outbox)) == 2

    # A repeat run in the same episode writes no duplicates.
    report = detector.run_detector(board_dir, outbox, now=T0 + timedelta(minutes=90))
    assert report["escalated"] is True
    assert report["targets_written"] == []
    assert len(report["targets_already_recorded"]) == 2
    assert len(outbox_files(outbox)) == 2

    # When appends resume, the escalations are recorded on the board
    # under the detector chat's name — once each.
    appended = detector.record_pending_escalations(
        board_dir, outbox, now=T0 + timedelta(minutes=95)
    )
    assert len(appended) == 2
    recorded = [
        event
        for event in append_mod._read_events(board_dir)
        if event["kind"] == "detector_escalation"
    ]
    assert len(recorded) == 2
    assert {event["actor"] for event in recorded} == {"detector-chat"}
    assert {event["payload"]["target"] for event in recorded} == {"owner-1", "owner-2"}
    assert detector.record_pending_escalations(board_dir, outbox) == []
    assert fold.fold_board(board_dir).ok


def test_keeper_run_records_pending_detector_escalations(tmp_path):
    board_dir = blocked_board(tmp_path)
    outbox = tmp_path / "outbox"
    keeper.run_keeper(board_dir, {}, now=T0)
    detector.run_detector(board_dir, outbox, now=T0 + timedelta(minutes=61))
    # The keeper's next run records the pending escalations first.
    report = keeper.run_keeper(
        board_dir, {"detector_outbox_dir": str(outbox)}, now=T0 + timedelta(minutes=65)
    )
    assert report["ok"] is True
    assert len(report["detector_escalations_recorded"]) == 2
    recorded = [
        event
        for event in append_mod._read_events(board_dir)
        if event["kind"] == "detector_escalation"
    ]
    assert len(recorded) == 2


def test_no_heartbeat_ever_escalates(tmp_path):
    board_dir = blocked_board(tmp_path)
    outbox = tmp_path / "outbox"
    report = detector.run_detector(board_dir, outbox, now=T0)
    assert report["escalated"] is True
    assert report["last_heartbeat_event"] is None
    assert len(outbox_files(outbox)) == 2


def test_recent_activity_does_not_mask_a_stale_heartbeat(tmp_path):
    board_dir = blocked_board(tmp_path)
    outbox = tmp_path / "outbox"
    keeper.run_keeper(board_dir, {}, now=T0)
    # Plenty of later log activity, none of it a heartbeat.
    append(
        board_dir,
        caller(
            "create-r2",
            "row_created",
            "r2",
            {"row_id": "r2", "task_ref": "T-r2"},
        ),
        now=T0 + timedelta(minutes=50),
    )
    report = detector.run_detector(board_dir, outbox, now=T0 + timedelta(minutes=61))
    assert report["escalated"] is True


def test_terminal_board_needs_no_keeper(tmp_path):
    board_dir = make_board(tmp_path)
    outbox = tmp_path / "outbox"
    append(
        board_dir,
        caller(
            "create-r1",
            "row_created",
            "r1",
            {"row_id": "r1", "task_ref": "T-r1"},
        ),
    )
    append(
        board_dir,
        caller(
            "r1-withdraw",
            "row_update",
            "r1",
            {"changes": {"status": "withdrawn"}, "reason": "no longer needed"},
        ),
    )
    keeper.run_keeper(board_dir, {}, now=T0)
    report = detector.run_detector(board_dir, outbox, now=T0 + timedelta(hours=5))
    assert report["ok"] is True and report["escalated"] is False
    assert outbox_files(outbox) == []
