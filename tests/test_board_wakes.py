"""Phase 3 append path: T014 (matching and wake mechanics) and the
FR-P4 half of T015 (the sweep-deadline registration refusal).

Everything runs end-to-end through the real append command on real
board directories: wake-on-watch is drilled as the lost-wakeup race
(the ending condition lands between the decision to wait and the
registration, so the registration itself must fire the wake),
dependency wakes are derived by the append operation in the same
locked operation as the `done` transition, and the deadline refusal
is checked against the board's genesis cadence. Clocks are stated,
never backdated into stored events.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import append as append_mod  # noqa: E402
from board import fold  # noqa: E402

if sys.platform == "win32":
    pytest.skip(
        "board substrate is POSIX-only (plan: fcntl.flock; boards live on Linux hosts)",
        allow_module_level=True,
    )

FIXTURES = Path(__file__).parent / "fixtures" / "board"
CI_DIR = FIXTURES / "ci-runs"
HEAD_SHA = "0123456789abcdef0123456789abcdef01234567"
CI_REF = f"ci:44981799043#{HEAD_SHA}"
CTX = {"ci_records_dir": str(CI_DIR)}

BOARD = "board-wakes"
GENESIS = {
    "board_id": BOARD,
    "program": "p",
    "spec_ref": "AB-001",
    "spec_hash": "a" * 64,
    "wip_limit": 4,
    "keeper_cadence": "30m",
    "detector_chat": "d",
    "escalation_target_2": "owner",
}
NOTE = (
    "Current position: blocked on a record outside this board.\n"
    "Next action: resume when the wake lands.\n"
    "Records that matter: the wait's wake falsifier.\n"
    "What would change the plan: the record resolving the other way.\n"
)
NOW = datetime(2026, 11, 21, 12, 0, 0, tzinfo=UTC)
DEADLINE = "2026-11-21T14:00:00Z"  # two hours after NOW; minimum is one


def caller(event_id, kind, row_id, payload, actor="planner"):
    return {
        "event_id": event_id,
        "board_id": BOARD,
        "row_id": row_id,
        "actor": actor,
        "kind": kind,
        "payload": payload,
    }


def append(board_dir, event, **kwargs):
    kwargs.setdefault("now", NOW)
    head = fold.log_head_hash(board_dir)
    return append_mod.append_event(board_dir, event, head, **kwargs)


def make_board(tmp_path):
    board_dir = tmp_path / "b"
    append_mod.create_board(board_dir, dict(GENESIS), actor="planner")
    return board_dir


def create(board_dir, row_id, **payload):
    payload.setdefault("row_id", row_id)
    payload.setdefault("task_ref", f"T-{row_id}")
    return append(board_dir, caller(f"create-{row_id}", "row_created", row_id, payload))


def transition(board_dir, event_id, row_id, to_status, actor="planner", **payload):
    return append(
        board_dir,
        caller(
            event_id,
            "row_update",
            row_id,
            {"changes": {"status": to_status}, **payload},
            actor=actor,
        ),
    )


def drive_to_in_progress(board_dir, row_id, holder="worker-1"):
    create(board_dir, row_id, assignee_kind="worker", assignee_instance=holder)
    transition(board_dir, f"{row_id}-planned", row_id, "planned")
    transition(board_dir, f"{row_id}-ready", row_id, "ready")
    transition(board_dir, f"{row_id}-take", row_id, "in_progress")


def drive_to_done(board_dir, row_id, holder="worker-1"):
    drive_to_in_progress(board_dir, row_id, holder=holder)
    transition(
        board_dir,
        f"{row_id}-review",
        row_id,
        "in_review",
        work_product=[f"commit:{HEAD_SHA}"],
    )
    append(
        board_dir,
        caller(
            f"{row_id}-attach",
            "verdict_attached",
            row_id,
            {"verdict_ref": CI_REF},
            actor="reviewer-1",
        ),
        verdict_context=CTX,
    )
    transition(board_dir, f"{row_id}-done", row_id, "done", actor="reviewer-1", verdict_ref=CI_REF)


def events(board_dir):
    return append_mod._read_events(board_dir)


def wakes(board_dir):
    return [e for e in events(board_dir) if e["kind"] == "wake"]


def named_wait(**overrides):
    wait = {
        "wait_kind": "named_event",
        "match": {"event": "ci-green"},
        "wake_falsifier": {
            "record": "ci:44981799043",
            "field": "conclusion",
            "equals": "success",
        },
        "sweep_deadline": DEADLINE,
        "escalation": "owner",
    }
    wait.update(overrides)
    return wait


def dependency_wait(**overrides):
    wait = {
        "wait_kind": "dependency",
        "wake_falsifier": {"record": "board:dep", "field": "status", "equals": "done"},
        "sweep_deadline": DEADLINE,
        "escalation": "owner",
    }
    wait.update(overrides)
    return wait


def block(board_dir, event_id, row_id, wait):
    return append(
        board_dir,
        caller(
            event_id,
            "row_update",
            row_id,
            {"changes": {"status": "blocked", "wait": wait}, "resumption_note": NOTE},
        ),
        verdict_context=CTX,
    )


# ------------------------------------------------------------ FR-P4 refusal


def test_deadline_under_two_cadence_intervals_is_refused(tmp_path):
    board_dir = make_board(tmp_path)
    drive_to_in_progress(board_dir, "r1")
    head_before = fold.log_head_hash(board_dir)
    wait = named_wait(sweep_deadline="2026-11-21T12:30:00Z")  # 30m < 2 x 30m
    with pytest.raises(append_mod.BoardRefusal) as exc:
        block(board_dir, "r1-block", "r1", wait)
    assert exc.value.code == "SWEEP_DEADLINE"
    assert fold.log_head_hash(board_dir) == head_before  # nothing entered the log


def test_deadline_at_exactly_the_minimum_is_accepted(tmp_path):
    board_dir = make_board(tmp_path)
    drive_to_in_progress(board_dir, "r1")
    wait = named_wait(
        sweep_deadline="2026-11-21T13:00:00Z",
        wake_falsifier={"record": "ci:44981799044", "field": "conclusion", "equals": "success"},
    )
    stored = block(board_dir, "r1-block", "r1", wait)
    assert stored["payload"]["wake_check"]["outcome"] == "not_yet"


def test_recovery_reregistration_is_exempt_from_the_deadline_refusal(tmp_path):
    board_dir = make_board(tmp_path)
    drive_to_in_progress(board_dir, "r1")
    wait = named_wait(sweep_deadline="2026-11-21T12:30:00Z")
    stored = append(
        board_dir,
        caller(
            "r1-block",
            "row_update",
            "r1",
            {
                "changes": {"status": "blocked", "wait": wait},
                "resumption_note": NOTE,
                "recovered_from": "original-block-event",
            },
        ),
        verdict_context=CTX,
    )
    assert "recovery" in stored["payload"]["wake_check"]["detail"]


def test_caller_supplied_wake_check_is_refused(tmp_path):
    board_dir = make_board(tmp_path)
    drive_to_in_progress(board_dir, "r1")
    event = caller(
        "r1-block",
        "row_update",
        "r1",
        {
            "changes": {"status": "blocked", "wait": named_wait()},
            "resumption_note": NOTE,
            "wake_check": {"outcome": "holds"},
        },
    )
    with pytest.raises(append_mod.BoardRefusal) as exc:
        append(board_dir, event, verdict_context=CTX)
    assert exc.value.code == "SCHEMA" and "wake_check" in exc.value.message


# ------------------------------------------------------------ FR-P3 wake-on-watch


def test_lost_wakeup_race_the_registration_itself_fires_the_wake(tmp_path):
    # The CI run concluded BEFORE the row blocks: the event landed
    # between the decision to wait and the registration. The append
    # operation evaluates the falsifier inside the same lock and
    # fires the wake in the same operation.
    board_dir = make_board(tmp_path)
    drive_to_in_progress(board_dir, "r1")
    stored = block(board_dir, "r1-block", "r1", named_wait())
    assert stored["payload"]["wake_check"]["outcome"] == "holds"
    found = wakes(board_dir)
    assert len(found) == 1
    wake = found[0]
    assert wake["actor"] == "system" and wake["payload"]["via"] == "wake_on_watch"
    assert wake["payload"]["wait_event"] == "r1-block"
    assert wake["prev_hash"] == stored["event_hash"]  # same locked operation, chained
    # The wake is citable: the unblock names it as its wake_ref.
    append(
        board_dir,
        caller(
            "r1-unblock",
            "row_update",
            "r1",
            {"changes": {"status": "in_progress", "wait": None}, "wake_ref": wake["event_id"]},
        ),
    )
    result = fold.fold_board(board_dir)
    assert result.ok and result.state["rows"]["r1"]["status"] == "in_progress"


def test_registration_stamps_not_yet_and_fires_nothing(tmp_path):
    board_dir = make_board(tmp_path)
    drive_to_in_progress(board_dir, "r1")
    wait = named_wait(
        wake_falsifier={"record": "ci:44981799044", "field": "conclusion", "equals": "success"}
    )
    stored = block(board_dir, "r1-block", "r1", wait)
    assert stored["payload"]["wake_check"]["outcome"] == "not_yet"
    assert wakes(board_dir) == []


def test_dependency_wake_on_watch_when_the_dependency_already_stands_done(tmp_path):
    board_dir = make_board(tmp_path)
    drive_to_done(board_dir, "dep")
    create(
        board_dir, "r1", assignee_kind="worker", assignee_instance="worker-1", depends_on=["dep"]
    )
    transition(board_dir, "r1-planned", "r1", "planned")
    transition(board_dir, "r1-ready", "r1", "ready")
    transition(board_dir, "r1-take", "r1", "in_progress")
    stored = block(board_dir, "r1-block", "r1", dependency_wait())
    assert stored["payload"]["wake_check"]["outcome"] == "holds"
    found = wakes(board_dir)
    assert len(found) == 1 and found[0]["payload"]["via"] == "wake_on_watch"


# ------------------------------------------------------------ dependency wakes


def test_done_transition_wakes_the_named_dependent_in_the_same_operation(tmp_path):
    board_dir = make_board(tmp_path)
    create(board_dir, "dep", assignee_kind="worker", assignee_instance="worker-1")
    drive_to_in_progress(board_dir, "r1")
    wait = dependency_wait(match={"row_id": "dep"})
    block(board_dir, "r1-block", "r1", wait)
    assert wakes(board_dir) == []  # dep is not done; no wake yet
    drive_to_done(board_dir, "dep", holder="worker-2")
    found = wakes(board_dir)
    assert len(found) == 1
    wake = found[0]
    assert wake["actor"] == "system" and wake["payload"]["via"] == "dependency"
    assert wake["payload"]["wait_event"] == "r1-block" and wake["row_id"] == "r1"
    # And the dependent can now unblock citing the wake.
    append(
        board_dir,
        caller(
            "r1-unblock",
            "row_update",
            "r1",
            {"changes": {"status": "in_progress", "wait": None}, "wake_ref": wake["event_id"]},
        ),
    )
    result = fold.fold_board(board_dir)
    assert result.ok and result.state["rows"]["r1"]["status"] == "in_progress"


def test_unnamed_dependency_wait_wakes_only_when_every_dependency_is_done(tmp_path):
    board_dir = make_board(tmp_path)
    create(board_dir, "d1", assignee_kind="worker", assignee_instance="worker-1")
    create(board_dir, "d2", assignee_kind="worker", assignee_instance="worker-1")
    create(
        board_dir,
        "r1",
        assignee_kind="worker",
        depends_on=["d1", "d2"],
        wait=dependency_wait(
            wake_falsifier={"record": "board:d1", "field": "status", "equals": "done"}
        ),
    )
    drive_to_done(board_dir, "d1", holder="worker-2")
    assert wakes(board_dir) == []  # d2 still outstanding
    drive_to_done(board_dir, "d2", holder="worker-2")
    found = wakes(board_dir)
    assert len(found) == 1 and found[0]["payload"]["via"] == "dependency"


def test_idempotent_retry_of_a_done_transition_does_not_duplicate_the_wake(tmp_path):
    board_dir = make_board(tmp_path)
    create(board_dir, "dep", assignee_kind="worker", assignee_instance="worker-1")
    drive_to_in_progress(board_dir, "r1")
    block(board_dir, "r1-block", "r1", dependency_wait(match={"row_id": "dep"}))
    drive_to_in_progress(board_dir, "dep", holder="worker-2")
    transition(board_dir, "dep-review", "dep", "in_review", work_product=[f"commit:{HEAD_SHA}"])
    append(
        board_dir,
        caller(
            "dep-attach", "verdict_attached", "dep", {"verdict_ref": CI_REF}, actor="reviewer-1"
        ),
        verdict_context=CTX,
    )
    done_event = caller(
        "dep-done",
        "row_update",
        "dep",
        {"changes": {"status": "done"}, "verdict_ref": CI_REF},
        actor="reviewer-1",
    )
    head = fold.log_head_hash(board_dir)
    append_mod.append_event(board_dir, done_event, head, verdict_context=CTX, now=NOW)
    assert len(wakes(board_dir)) == 1
    # The retry: same event_id, the head it originally expected.
    append_mod.append_event(board_dir, done_event, head, verdict_context=CTX, now=NOW)
    assert len(wakes(board_dir)) == 1


# ------------------------------------------------------------ cadence amendment


def test_board_amendment_changes_the_cadence_the_refusal_uses(tmp_path):
    board_dir = make_board(tmp_path)
    append(
        board_dir,
        caller(
            "cadence-1",
            "amendment",
            None,
            {
                "changes": {"keeper_cadence": "15m"},
                "reason": "the pilot board sweeps twice as often",
                "authority": "planner",
            },
        ),
    )
    result = fold.fold_board(board_dir)
    assert result.ok and result.state["genesis"]["keeper_cadence"] == "15m"
    drive_to_in_progress(board_dir, "r1")
    # 45 minutes is under the old minimum (60) and over the new (30).
    wait = named_wait(
        sweep_deadline="2026-11-21T12:45:00Z",
        wake_falsifier={"record": "ci:44981799044", "field": "conclusion", "equals": "success"},
    )
    stored = block(board_dir, "r1-block", "r1", wait)
    assert stored["payload"]["wake_check"]["outcome"] == "not_yet"


def test_board_amendment_refuses_other_genesis_fields_and_missing_reason(tmp_path):
    board_dir = make_board(tmp_path)
    with pytest.raises(append_mod.BoardRefusal) as exc:
        append(
            board_dir,
            caller(
                "bad-1",
                "amendment",
                None,
                {"changes": {"wip_limit": 9}, "reason": "more", "authority": "planner"},
            ),
        )
    assert exc.value.code == "FOLD_REFUSED" and "keeper_cadence" in exc.value.message
    with pytest.raises(append_mod.BoardRefusal) as exc:
        append(
            board_dir,
            caller(
                "bad-2",
                "amendment",
                None,
                {"changes": {"keeper_cadence": "15m"}, "authority": "planner"},
            ),
        )
    assert exc.value.code == "FOLD_REFUSED" and "reason" in exc.value.message


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
