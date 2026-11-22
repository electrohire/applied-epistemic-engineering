"""Phase 4 metrics: T024 (spec 5.3).

The generator runs over real board directories built through the
real append path and the real keeper, with stated clocks. Covered:
rows by status with ages from the log's stamped time evidence, waits
by kind with their outcomes (match, sweep, escalated, closed without
a wake, still waiting), planner overrides as their own category,
missed wakes as a lower bound, a planted false wake caught by
re-verification against the prefix fold, the staleness flag (stale,
fresh, and unknown), and the pilot overhead section carried verbatim
from the rhythm's input, never estimated.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import append as append_mod  # noqa: E402
from board import fold, keeper, metrics  # noqa: E402

if sys.platform == "win32":
    pytest.skip(
        "board substrate is POSIX-only (plan: fcntl.flock; boards live on Linux hosts)",
        allow_module_level=True,
    )

BOARD = "board-metrics"
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


def create_row(board_dir, row_id, now=T0, depends_on=()):
    append(
        board_dir,
        caller(
            f"create-{row_id}",
            "row_created",
            row_id,
            {
                "row_id": row_id,
                "task_ref": f"T-{row_id}",
                "assignee_kind": "worker",
                "assignee_instance": "worker-1",
                "depends_on": list(depends_on),
            },
        ),
        now=now,
    )


def drive(board_dir, row_id, *statuses, now=T0):
    for status in statuses:
        append(
            board_dir,
            caller(f"{row_id}-{status}", "row_update", row_id, {"changes": {"status": status}}),
            now=now,
        )


def block(board_dir, row_id, wait, now):
    append(
        board_dir,
        caller(
            f"{row_id}-block",
            "row_update",
            row_id,
            {"changes": {"status": "blocked", "wait": wait}, "resumption_note": NOTE},
        ),
        now=now,
    )


def named_wait(reference, deadline):
    return {
        "wait_kind": "named_event",
        "wake_falsifier": {"record": reference, "field": "state", "equals": "completed"},
        "sweep_deadline": deadline,
        "escalation": "owner-1",
    }


def stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ rows


def test_rows_by_status_and_age(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    drive(board_dir, "r1", "planned")
    create_row(board_dir, "r2")
    report = metrics.generate_metrics(board_dir, now=T0 + timedelta(hours=2))
    assert report["ok"]
    assert report["rows_by_status"] == {"planned": 1, "proposed": 1}
    # No stamped time evidence exists before these rows in this log,
    # so ages are reported in events exactly and seconds as unknown.
    assert report["rows"]["r1"]["age_seconds"] is None
    assert report["rows"]["r1"]["age_events"] == 2
    assert report["rows"]["r2"]["age_events"] == 0
    assert report["generated_from_head"] == fold.log_head_hash(board_dir)


def test_staleness_unknown_without_time_evidence(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    report = metrics.generate_metrics(board_dir, now=T0 + timedelta(days=7))
    assert report["staleness"]["stale"] is None
    assert report["staleness"]["non_terminal_rows"] == ["r1"]


# ------------------------------------------------- waits, sweep, overrides


def build_wait_board(tmp_path):
    """r-swept: prose wait whose record satisfies silently; with no
    prose judgment available, only the sweep's re-read can notice.
    r-over: blocked, then unblocked by planner override.
    r-wait: blocked on a record that never satisfies, deadline far off.
    """
    board_dir = make_board(tmp_path)
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    (queue_dir / "job-2.json").write_text(
        json.dumps({"id": "job-2", "state": "queued", "markers": [], "log_tail": []}),
        encoding="utf-8",
    )
    arrival = tmp_path / "arrival.json"
    arrival.write_text(json.dumps({"arrived": False}), encoding="utf-8")
    sources = {"gatekeeper_queue_dir": str(queue_dir)}

    create_row(board_dir, "r-swept")
    drive(board_dir, "r-swept", "planned", "ready", "in_progress")
    prose_wait = {
        "wait_kind": "external_prose",
        "prose_condition": "the arrival note says the reviewer replied",
        "wake_falsifier": {"record": f"file:{arrival}", "field": "arrived", "equals": True},
        "sweep_deadline": stamp(T0 + timedelta(hours=2)),
        "escalation": "owner-1",
    }
    block(board_dir, "r-swept", prose_wait, now=T0)
    create_row(board_dir, "r-over")
    drive(board_dir, "r-over", "planned", "ready", "in_progress")
    block(
        board_dir,
        "r-over",
        named_wait("gatekeeper:job-2", stamp(T0 + timedelta(hours=2))),
        now=T0,
    )
    append(
        board_dir,
        caller(
            "r-over-unblock",
            "row_update",
            "r-over",
            {
                "changes": {"status": "in_progress", "wait": None},
                "override_reason": "the planner takes the wait off the board",
            },
        ),
        now=T0 + timedelta(minutes=30),
    )
    create_row(board_dir, "r-wait")
    drive(board_dir, "r-wait", "planned", "ready", "in_progress")
    block(
        board_dir,
        "r-wait",
        named_wait("gatekeeper:job-2", stamp(T0 + timedelta(hours=6))),
        now=T0,
    )
    # The arrival lands with no keeper run in between; the sweep at
    # T0+3h is the first procedure that can notice.
    arrival.write_text(json.dumps({"arrived": True}), encoding="utf-8")
    run = keeper.run_keeper(board_dir, sources, now=T0 + timedelta(hours=3))
    assert run["ok"] and run["missed_wakes"] == 1
    return board_dir


def test_waits_by_kind_with_outcomes(tmp_path):
    board_dir = build_wait_board(tmp_path)
    report = metrics.generate_metrics(board_dir, now=T0 + timedelta(hours=4))
    assert report["waits_by_kind"]["external_prose"] == {"woken_by_sweep": 1}
    assert report["waits_by_kind"]["named_event"] == {
        "closed_without_wake": 1,
        "still_waiting": 1,
    }


def test_overrides_and_missed_wakes(tmp_path):
    board_dir = build_wait_board(tmp_path)
    report = metrics.generate_metrics(board_dir, now=T0 + timedelta(hours=4))
    assert report["planner_overrides"]["count"] == 1
    assert report["planner_overrides"]["events"][0]["row"] == "r-over"
    assert report["missed_wakes"]["count"] == 1
    assert report["missed_wakes"]["is_lower_bound"] is True
    assert report["false_wakes"]["count"] == 0


def test_staleness_flag_from_heartbeat_evidence(tmp_path):
    board_dir = build_wait_board(tmp_path)
    # The keeper's heartbeat at T0+3h is the last stamped activity.
    fresh = metrics.generate_metrics(board_dir, now=T0 + timedelta(hours=26))
    assert fresh["staleness"]["stale"] is False
    assert fresh["staleness"]["last_activity_at"] == stamp(T0 + timedelta(hours=3))
    stale = metrics.generate_metrics(board_dir, now=T0 + timedelta(hours=28))
    assert stale["staleness"]["stale"] is True


def test_row_age_from_stamped_evidence(tmp_path):
    board_dir = build_wait_board(tmp_path)
    report = metrics.generate_metrics(board_dir, now=T0 + timedelta(hours=4))
    # r-swept's block registration was stamped at T0 (wake-on-watch
    # evaluation); its status age is measured from that evidence.
    row = report["rows"]["r-swept"]
    assert row["status"] == "blocked"
    assert row["status_age_seconds"] == 4 * 3600


# ------------------------------------------------------------ false wakes


def test_planted_false_dependency_wake_is_caught(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r-dep")
    # The wait's match names r-dep; the row itself carries no
    # depends_on, so the ready promotion is not dependency-gated.
    create_row(board_dir, "r-waiter")
    drive(board_dir, "r-waiter", "planned", "ready", "in_progress")
    wait = {
        "wait_kind": "dependency",
        "match": {"row_id": "r-dep"},
        "wake_falsifier": {"record": "board:r-dep", "field": "status", "equals": "done"},
        "sweep_deadline": stamp(T0 + timedelta(hours=2)),
        "escalation": "owner-1",
    }
    block(board_dir, "r-waiter", wait, now=T0)
    clean = metrics.generate_metrics(board_dir, now=T0 + timedelta(hours=1))
    assert clean["waits_by_kind"]["dependency"] == {"still_waiting": 1}
    assert clean["false_wakes"]["count"] == 0
    # Plant a wake the append path would never derive: r-dep is not
    # done, so the dependency basis does not hold at the prefix fold.
    append(
        board_dir,
        caller(
            "wake:planted",
            "wake",
            "r-waiter",
            {
                "row": "r-waiter",
                "wait_event": "r-waiter-block",
                "via": "dependency",
                "detail": "planted by the test",
            },
            actor="system",
        ),
        now=T0 + timedelta(minutes=5),
    )
    report = metrics.generate_metrics(board_dir, now=T0 + timedelta(hours=1))
    assert report["false_wakes"]["count"] == 1
    assert report["false_wakes"]["events"][0]["event_id"] == "wake:planted"


# ---------------------------------------------------------------- overhead


def test_overhead_carried_verbatim_never_estimated(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    append(
        board_dir,
        caller(
            "r1-amend",
            "amendment",
            "r1",
            {
                "changes": {"body": "revised"},
                "reason": "scope clarified",
                "authority": "planner",
            },
        ),
    )
    bare = metrics.generate_metrics(board_dir, now=T0)
    assert bare["pilot_overhead"]["keeper_session_cost"] is None
    assert bare["pilot_overhead"]["genesis_events"] == 1
    assert bare["pilot_overhead"]["amendment_events"] == 1
    supplied = metrics.generate_metrics(
        board_dir,
        now=T0,
        overhead={
            "keeper_session_cost": {"agent_tokens": 12000, "wall_seconds": 95},
            "audit_labor": {"person_minutes": 40},
            "note_authoring_cost": {"agent_tokens": 300},
        },
    )
    overhead = supplied["pilot_overhead"]
    assert overhead["keeper_session_cost"] == {"agent_tokens": 12000, "wall_seconds": 95}
    assert overhead["audit_labor"] == {"person_minutes": 40}
    assert overhead["note_authoring_cost"] == {"agent_tokens": 300}


def test_metrics_on_a_broken_board_reports_not_ok(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    lines = (board_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[-1])
    tampered["payload"] = {"row_id": "r1", "task_ref": "forged"}
    lines[-1] = json.dumps(tampered)
    (board_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = metrics.generate_metrics(board_dir, now=T0)
    assert not report["ok"] and "fold_refusal" in report


def test_render_carries_the_generated_discipline(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    report = metrics.generate_metrics(board_dir, now=T0)
    text = metrics.render_metrics(report)
    assert text.startswith(metrics.GENERATED_HEADER)
    assert f"Generated from head: {fold.log_head_hash(board_dir)}" in text
    assert "proposed: 1" in text
