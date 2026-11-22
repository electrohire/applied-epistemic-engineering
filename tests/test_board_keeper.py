"""Phase 3 keeper: T013 (cited carriage + heartbeat), T015 (sweep).

Everything runs end-to-end: real board directories, the real append
path, real record files in the gatekeeper queue format, and the real
keeper machinery (board.keeper). Clocks are stated per run; nothing
is backdated. The missed-wake drill is the FR-P4 acceptance shape: a
wait whose record satisfies while no prose judgment is available is
caught by the sweep's direct re-read, with its age recorded.
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
from board import fold, keeper  # noqa: E402

if sys.platform == "win32":
    pytest.skip(
        "board substrate is POSIX-only (plan: fcntl.flock; boards live on Linux hosts)",
        allow_module_level=True,
    )

BOARD = "board-keeper"
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
DEADLINE = "2026-11-21T14:00:00Z"  # T0 + 2h; the FR-P4 minimum is T0 + 1h


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


def drive_blocked(board_dir, row_id, wait):
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
            },
        ),
    )
    for to_status in ("planned", "ready", "in_progress"):
        append(
            board_dir,
            caller(
                f"{row_id}-{to_status}",
                "row_update",
                row_id,
                {"changes": {"status": to_status}},
            ),
        )
    append(
        board_dir,
        caller(
            f"{row_id}-block",
            "row_update",
            row_id,
            {"changes": {"status": "blocked", "wait": wait}, "resumption_note": NOTE},
        ),
    )


def named_wait(reference, field="state", equals="completed", deadline=DEADLINE):
    return {
        "wait_kind": "named_event",
        "wake_falsifier": {"record": reference, "field": field, "equals": equals},
        "sweep_deadline": deadline,
        "escalation": "owner-1",
    }


def queue_record(queue_dir, job_id, state):
    record = {
        "id": job_id,
        "state": state,
        "key": "test",
        "lane": "tower-compute-quick",
        "log_tail": ["payload starting"],
        "markers": [],
    }
    (queue_dir / f"{job_id}.json").write_text(json.dumps(record), encoding="utf-8")


def events(board_dir):
    return append_mod._read_events(board_dir)


def of_kind(board_dir, kind):
    return [event for event in events(board_dir) if event["kind"] == kind]


def test_heartbeat_on_empty_run(tmp_path):
    board_dir = make_board(tmp_path)
    report = keeper.run_keeper(board_dir, {}, now=T0)
    assert report["ok"] is True
    heartbeats = of_kind(board_dir, "heartbeat")
    assert len(heartbeats) == 1
    payload = heartbeats[0]["payload"]
    assert payload["run_at"] == "2026-11-21T12:00:00Z"
    assert payload["waits_open"] == 0 and payload["posts"] == 0
    assert heartbeats[0]["actor"] == "keeper"
    assert fold.fold_board(board_dir).ok


def test_match_posts_cited_carriage_and_wake(tmp_path):
    board_dir = make_board(tmp_path)
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    queue_record(queue_dir, "job-x", "running")
    drive_blocked(board_dir, "r1", named_wait("gatekeeper:job-x"))
    sources = {"gatekeeper_queue_dir": str(queue_dir)}

    report = keeper.run_keeper(board_dir, sources, now=T0 + timedelta(minutes=30))
    assert report["ok"] is True and report["wakes"] == 0
    assert of_kind(board_dir, "wake") == []

    queue_record(queue_dir, "job-x", "completed")
    report = keeper.run_keeper(board_dir, sources, now=T0 + timedelta(minutes=60))
    assert report["wakes"] == 1 and report["posts"] == 1
    posts = of_kind(board_dir, "keeper_post")
    assert len(posts) == 1
    citation = posts[0]["payload"]["citation"]
    assert citation["record"] == "gatekeeper:job-x"
    assert citation["value"] == "completed"
    assert citation["record_hash"]
    wakes = of_kind(board_dir, "wake")
    assert len(wakes) == 1
    assert wakes[0]["actor"] == "keeper"
    assert wakes[0]["payload"]["via"] == "match"
    assert wakes[0]["payload"]["citation"]["record"] == "gatekeeper:job-x"
    assert keeper.find_uncited_assertions(events(board_dir)) == []


def test_uncited_assertion_is_flagged(tmp_path):
    board_dir = make_board(tmp_path)
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    queue_record(queue_dir, "job-x", "completed")
    drive_blocked(board_dir, "r1", named_wait("gatekeeper:job-x"))
    keeper.run_keeper(
        board_dir, {"gatekeeper_queue_dir": str(queue_dir)}, now=T0 + timedelta(minutes=30)
    )
    # A hand-made keeper post asserting an outcome with no citation.
    append(
        board_dir,
        caller(
            "rogue-post",
            "keeper_post",
            None,
            {"row": "r1", "detail": "the job finished, trust me"},
            actor="keeper",
        ),
        now=T0 + timedelta(minutes=31),
    )
    violations = keeper.find_uncited_assertions(events(board_dir))
    assert [v["event_id"] for v in violations] == ["rogue-post"]


def test_dead_source_is_a_finding_and_heartbeat_still_lands(tmp_path):
    board_dir = make_board(tmp_path)
    missing = tmp_path / "no-such-queue"
    report = keeper.run_keeper(board_dir, {"gatekeeper_queue_dir": str(missing)}, now=T0)
    assert report["ok"] is True and report["findings"] == 1
    findings = of_kind(board_dir, "keeper_finding")
    assert len(findings) == 1
    assert findings[0]["payload"]["finding"] == "source_dead"
    assert findings[0]["payload"]["source"] == "gatekeeper_queue_dir"
    assert len(of_kind(board_dir, "heartbeat")) == 1


def test_missed_wake_drill(tmp_path):
    board_dir = make_board(tmp_path)
    arrival = tmp_path / "arrival.json"
    arrival.write_text(json.dumps({"arrived": False}), encoding="utf-8")
    wait = {
        "wait_kind": "external_prose",
        "prose_condition": "the arrival note says the reviewer replied",
        "wake_falsifier": {"record": f"file:{arrival}", "field": "arrived", "equals": True},
        "sweep_deadline": DEADLINE,
        "escalation": "owner-1",
    }
    drive_blocked(board_dir, "r1", wait)

    # No prose judgment available: matching cannot fire, and does not.
    report = keeper.run_keeper(board_dir, {}, now=T0 + timedelta(minutes=30))
    assert report["wakes"] == 0 and of_kind(board_dir, "wake") == []

    # The record satisfies; the deadline passes; the sweep re-reads
    # the record directly and finds the missed wake, with its age.
    arrival.write_text(json.dumps({"arrived": True}), encoding="utf-8")
    sweep_at = T0 + timedelta(hours=2, minutes=5)
    report = keeper.run_keeper(board_dir, {}, now=sweep_at)
    assert report["missed_wakes"] == 1 and report["wakes"] == 1
    findings = [
        event
        for event in of_kind(board_dir, "keeper_finding")
        if event["payload"]["finding"] == "missed_wake"
    ]
    assert len(findings) == 1
    payload = findings[0]["payload"]
    assert payload["row"] == "r1"
    assert payload["registered_at"] == "2026-11-21T12:00:00Z"
    assert payload["age_seconds"] == int((sweep_at - T0).total_seconds())
    assert payload["citation"]["record"] == f"file:{arrival}"
    wakes = of_kind(board_dir, "wake")
    assert len(wakes) == 1 and wakes[0]["payload"]["via"] == "sweep"


def test_sweep_unresolved_escalates_once(tmp_path):
    board_dir = make_board(tmp_path)
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    drive_blocked(board_dir, "r1", named_wait("gatekeeper:job-never"))
    sources = {"gatekeeper_queue_dir": str(queue_dir)}
    after = T0 + timedelta(hours=2, minutes=5)
    report = keeper.run_keeper(board_dir, sources, now=after)
    assert report["escalations"] == 1
    escalations = of_kind(board_dir, "escalation")
    assert len(escalations) == 1
    assert escalations[0]["payload"]["target"] == "owner-1"
    assert escalations[0]["payload"]["row"] == "r1"
    # A later sweep does not re-escalate the same registration.
    report = keeper.run_keeper(board_dir, sources, now=after + timedelta(minutes=30))
    assert report["escalations"] == 0
    assert len(of_kind(board_dir, "escalation")) == 1


def test_prose_confinement(tmp_path):
    board_dir = make_board(tmp_path)
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    queue_record(queue_dir, "job-x", "completed")
    drive_blocked(board_dir, "mech", named_wait("gatekeeper:job-x"))
    prose_wait = {
        "wait_kind": "external_prose",
        "prose_condition": "the reviewer replied warmly",
        "wake_falsifier": {"record": "file:/nonexistent", "field": "x"},
        "sweep_deadline": DEADLINE,
        "escalation": "owner-1",
    }
    drive_blocked(board_dir, "prose", prose_wait)
    consulted = []

    def evaluator(wait, row):
        consulted.append(row["row_id"])
        return None

    report = keeper.run_keeper(
        board_dir,
        {"gatekeeper_queue_dir": str(queue_dir)},
        now=T0 + timedelta(minutes=30),
        prose_evaluator=evaluator,
    )
    # Prose was consulted for the prose wait only; the mechanical
    # wait matched and woke without it.
    assert consulted == ["prose"]
    assert report["wakes"] == 1
    wakes = of_kind(board_dir, "wake")
    assert wakes[0]["payload"]["row"] == "mech"


def test_prose_match_requires_a_citation(tmp_path):
    board_dir = make_board(tmp_path)
    prose_wait = {
        "wait_kind": "external_prose",
        "prose_condition": "the reviewer replied warmly",
        "wake_falsifier": {"record": "file:/nonexistent", "field": "x"},
        "sweep_deadline": DEADLINE,
        "escalation": "owner-1",
    }
    drive_blocked(board_dir, "prose", prose_wait)

    def uncited_evaluator(wait, row):
        return {"detail": "it matches, but no record is cited"}

    report = keeper.run_keeper(
        board_dir, {}, now=T0 + timedelta(minutes=30), prose_evaluator=uncited_evaluator
    )
    assert report["wakes"] == 0
    assert any(r["code"] == "UNCITED_PROSE_MATCH" for r in report["refusals"])
    assert of_kind(board_dir, "keeper_post") == []

    def cited_evaluator(wait, row):
        return {"record": "file:/mail/arrival-7.json", "field": "verdict", "value": "warm"}

    report = keeper.run_keeper(
        board_dir, {}, now=T0 + timedelta(minutes=60), prose_evaluator=cited_evaluator
    )
    assert report["wakes"] == 1
    wakes = of_kind(board_dir, "wake")
    assert wakes[0]["payload"]["citation"]["record"] == "file:/mail/arrival-7.json"
    assert keeper.find_uncited_assertions(events(board_dir)) == []
