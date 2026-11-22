"""T003: the append command (spec AB-001 3.2, FR-S3) — real drills."""

import multiprocessing as mp
import os
import signal
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import append as append_mod  # noqa: E402
from board import canonical, fold, state  # noqa: E402

if sys.platform == "win32":
    pytest.skip(
        "board substrate is POSIX-only (plan: fcntl.flock; boards live on Linux hosts)",
        allow_module_level=True,
    )

GENESIS = {
    "board_id": "board-test",
    "program": "ninety-day",
    "spec_ref": "AB-001",
    "spec_hash": "a" * 64,
    "wip_limit": 4,
    "keeper_cadence": "30m",
    "detector_chat": "detector",
    "escalation_target_2": "owner",
}


def make_board(tmp_path: Path) -> Path:
    board_dir = tmp_path / "board"
    append_mod.create_board(board_dir, GENESIS, actor="planner")
    return board_dir


def row_event(event_id: str, row_id: str) -> dict:
    return {
        "event_id": event_id,
        "board_id": "board-test",
        "row_id": row_id,
        "actor": "planner",
        "kind": "row_created",
        "payload": {"row_id": row_id, "task_ref": f"T-{row_id}", "status": "proposed"},
    }


def head(board_dir: Path) -> str:
    return fold.log_head_hash(board_dir)


def test_create_board_and_append(tmp_path):
    board_dir = make_board(tmp_path)
    assert (board_dir / ".gitattributes").read_text().count("eol=lf") == 2
    stored = append_mod.append_event(board_dir, row_event("e1", "r1"), head(board_dir))
    assert stored["writer"].startswith("board-append@")
    assert stored["prev_hash"] != canonical.GENESIS_PREV_HASH
    result = fold.fold_board(board_dir)
    assert result.ok and "r1" in result.state["rows"]
    info = state.freshness(board_dir)
    assert info["status"] == "current" and info["state_head"] == info["log_head"]


def test_writer_supplied_by_caller_is_refused(tmp_path):
    board_dir = make_board(tmp_path)
    event = row_event("e1", "r1")
    event["writer"] = "mallory"
    with pytest.raises(append_mod.BoardRefusal) as exc:
        append_mod.append_event(board_dir, event, head(board_dir))
    assert exc.value.code == "SCHEMA" and "writer" in exc.value.message


def test_fold_refused_append_never_enters_the_log(tmp_path):
    # Regression (Phase 2 integration find): the append command used
    # to write the line first and fold after, so an event the fold
    # refused stood in the log and every later append re-refused at
    # the same event. A refused append now writes nothing, and the
    # board stays usable.
    board_dir = make_board(tmp_path)
    append_mod.append_event(board_dir, row_event("e1", "r1"), head(board_dir))
    with pytest.raises(append_mod.BoardRefusal) as exc:
        # A second creation of the same row is a fold refusal.
        append_mod.append_event(board_dir, row_event("e2", "r1"), head(board_dir))
    assert exc.value.code == "FOLD_REFUSED"
    lines = (board_dir / "events.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2  # genesis + e1; the refused event is absent
    stored = append_mod.append_event(board_dir, row_event("e3", "r2"), head(board_dir))
    assert stored["kind"] == "row_created"
    assert fold.fold_board(board_dir).ok


def test_head_moved_refusal(tmp_path):
    board_dir = make_board(tmp_path)
    append_mod.append_event(board_dir, row_event("e1", "r1"), head(board_dir))
    with pytest.raises(append_mod.BoardRefusal) as exc:
        append_mod.append_event(board_dir, row_event("e2", "r2"), canonical.GENESIS_PREV_HASH)
    assert exc.value.code == "HEAD_MOVED"


def test_retry_after_lost_confirmation_is_exactly_one_event(tmp_path):
    board_dir = make_board(tmp_path)
    event = row_event("e-retry", "r1")
    expected = head(board_dir)
    first = append_mod.append_event(board_dir, event, expected)
    # The caller never saw the result and retries with the same event_id
    # and the now-stale expected head: idempotency wins, nothing is written.
    second = append_mod.append_event(board_dir, event, expected)
    assert second["event_hash"] == first["event_hash"]
    lines = (board_dir / "events.jsonl").read_text().strip().splitlines()
    assert len([line for line in lines if "e-retry" in line]) == 1
    assert fold.fold_board(board_dir).state["event_count"] == 2


def _hold_lock(board_dir: str, seconds: float, ready) -> None:
    sys.path.insert(0, str(ROOT))
    from board import append as am

    with am._AppendLock(Path(board_dir), 5):
        ready.set()
        time.sleep(seconds)


def test_lock_timeout_is_named(tmp_path):
    board_dir = make_board(tmp_path)
    ready = mp.Event()
    holder = mp.Process(target=_hold_lock, args=(str(board_dir), 4, ready))
    holder.start()
    assert ready.wait(10)
    try:
        with pytest.raises(append_mod.BoardRefusal) as exc:
            append_mod.append_event(
                board_dir, row_event("e1", "r1"), head(board_dir), lock_timeout=1
            )
        assert exc.value.code == "LOCK_TIMEOUT"
    finally:
        holder.join(10)


def test_killed_lock_holder_leaves_no_stale_lock(tmp_path):
    board_dir = make_board(tmp_path)
    ready = mp.Event()
    holder = mp.Process(target=_hold_lock, args=(str(board_dir), 60, ready))
    holder.start()
    assert ready.wait(10)
    os.kill(holder.pid, signal.SIGKILL)
    holder.join(10)
    # The kernel released the dead holder's flock: this append proceeds.
    stored = append_mod.append_event(
        board_dir, row_event("e1", "r1"), head(board_dir), lock_timeout=5
    )
    assert stored["kind"] == "row_created"
    assert fold.fold_board(board_dir).ok


def _append_worker(board_dir: str, worker: int, count: int) -> None:
    sys.path.insert(0, str(ROOT))
    from board import append as am
    from board import fold as fold_mod

    for i in range(count):
        event = {
            "event_id": f"w{worker}-e{i}",
            "board_id": "board-test",
            "row_id": f"r{worker}-{i}",
            "actor": "worker",
            "kind": "row_created",
            "payload": {
                "row_id": f"r{worker}-{i}",
                "task_ref": f"T-{worker}-{i}",
                "status": "proposed",
            },
        }
        for _ in range(200):
            try:
                am.append_event(Path(board_dir), event, fold_mod.log_head_hash(Path(board_dir)))
                break
            except am.BoardRefusal as refusal:
                if refusal.code != "HEAD_MOVED":
                    raise
        else:  # pragma: no cover
            raise RuntimeError("append never landed")


def test_concurrent_append_drill(tmp_path):
    board_dir = make_board(tmp_path)
    workers, per_worker = 6, 15
    procs = [
        mp.Process(target=_append_worker, args=(str(board_dir), w, per_worker))
        for w in range(workers)
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(120)
        assert proc.exitcode == 0
    result = fold.fold_board(board_dir)
    assert result.ok
    assert result.state["event_count"] == 1 + workers * per_worker
    info = state.freshness(board_dir)
    assert info["status"] == "current" and info["state_head"] == info["log_head"]
