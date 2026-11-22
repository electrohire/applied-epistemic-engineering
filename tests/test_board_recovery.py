"""T006: recovery procedures (spec AB-001 3.2, FR-S3a) — real drills."""

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import append as append_mod  # noqa: E402
from board import canonical, fold, recover, state  # noqa: E402

if sys.platform == "win32":
    pytest.skip(
        "board substrate is POSIX-only (plan: fcntl.flock; boards live on Linux hosts)",
        allow_module_level=True,
    )

GENESIS = {
    "board_id": "board-rec",
    "program": "p",
    "spec_ref": "AB-001",
    "spec_hash": "a" * 64,
    "wip_limit": 4,
    "keeper_cadence": "30m",
    "detector_chat": "d",
    "escalation_target_2": "owner",
}


def make_board(tmp_path: Path, rows: int = 2) -> Path:
    board_dir = tmp_path / "b"
    append_mod.create_board(board_dir, GENESIS, actor="planner")
    for i in range(rows):
        append_mod.append_event(
            board_dir,
            {
                "event_id": f"e{i}",
                "board_id": "board-rec",
                "row_id": f"r{i}",
                "actor": "planner",
                "kind": "row_created",
                "payload": {"row_id": f"r{i}", "task_ref": f"T{i}"},
            },
            fold.log_head_hash(board_dir),
        )
    return board_dir


def test_torn_tail_drill(tmp_path):
    board_dir = make_board(tmp_path)
    head_before = fold.log_head_hash(board_dir)
    torn = b'{"event_id": "e-torn", "kind": "row_cre'
    with open(board_dir / "events.jsonl", "ab") as handle:
        handle.write(torn)
    record = recover.recover_torn_tail(board_dir)
    assert record["discarded_sha256"] == hashlib.sha256(torn).hexdigest()
    assert base64.b64decode(record["discarded_bytes_b64"]) == torn
    assert (board_dir / record["recovery_file"]).exists()
    result = fold.fold_board(board_dir)
    assert result.ok and result.state["head_hash"] == head_before
    assert state.freshness(board_dir)["status"] == "current"


def test_torn_tail_refuses_when_damage_is_mid_log(tmp_path):
    board_dir = make_board(tmp_path)
    lines = (board_dir / "events.jsonl").read_bytes().splitlines()
    lines[1] = b'{"broken"'
    (board_dir / "events.jsonl").write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(ValueError, match="not a torn tail"):
        recover.recover_torn_tail(board_dir)


def test_fork_drill(tmp_path):
    board_dir = make_board(tmp_path, rows=1)
    canonical_head = fold.log_head_hash(board_dir)
    # A divergent writer appends two events on top of the canonical
    # head, then a third chained on the second: the log still chains,
    # but the committed state snapshot folds only the canonical head.
    prev = canonical_head
    for i in range(2):
        event = {
            "event_id": f"div-{i}",
            "board_id": "board-rec",
            "row_id": f"rd{i}",
            "actor": "planner",
            "writer": "board-append@h:board-rec",
            "kind": "row_created",
            "payload": {"row_id": f"rd{i}", "task_ref": f"TD{i}"},
            "prev_hash": prev,
        }
        event["event_hash"] = canonical.event_hash(event)
        with open(board_dir / "events.jsonl", "ab") as handle:
            handle.write(canonical.canonical_line(event))
        prev = event["event_hash"]
    # Break the chain after the divergent events so recovery engages.
    with open(board_dir / "events.jsonl", "ab") as handle:
        handle.write(b'{"event_id": "broken-tail"\n')
    summary = recover.recover_fork(board_dir, planner="planner")
    assert summary["canonical_head"] == canonical_head
    assert set(summary["reappended"]) == {"div-0", "div-1"}
    recovery_file = board_dir / summary["recovery_file"]
    assert recovery_file.exists()
    assert summary["recovery_file_sha256"] == hashlib.sha256(recovery_file.read_bytes()).hexdigest()
    result = fold.fold_board(board_dir)
    assert result.ok
    assert {"rd0", "rd1", "r0"} <= set(result.state["rows"])
    events = append_mod._read_events(board_dir)
    recovery_events = [e for e in events if e["kind"] == "recovery"]
    assert len(recovery_events) == 1
    payload = recovery_events[0]["payload"]
    assert payload["authorized_by"] == "planner"
    assert payload["recovery_file_sha256"] == summary["recovery_file_sha256"]
    assert state.freshness(board_dir)["status"] == "current"


def test_fork_recovery_requires_a_snapshot(tmp_path):
    board_dir = make_board(tmp_path, rows=0)
    (board_dir / "state.json").unlink()
    with open(board_dir / "events.jsonl", "ab") as handle:
        handle.write(b'{"broken"\n')
    with pytest.raises(ValueError, match="canonical branch is unknowable"):
        recover.recover_fork(board_dir, planner="planner")


def test_recovery_record_is_in_the_chain(tmp_path):
    board_dir = make_board(tmp_path, rows=1)
    with open(board_dir / "events.jsonl", "ab") as handle:
        handle.write(b"torn-bytes")
    recover.recover_torn_tail(board_dir)
    # The log itself is untouched history; a later fold still verifies.
    stored = append_mod.append_event(
        board_dir,
        {
            "event_id": "after",
            "board_id": "board-rec",
            "row_id": "r9",
            "actor": "planner",
            "kind": "row_created",
            "payload": {"row_id": "r9", "task_ref": "T9"},
        },
        fold.log_head_hash(board_dir),
    )
    assert stored["kind"] == "row_created"
    assert fold.fold_board(board_dir).ok
    assert json.loads((board_dir / "state.json").read_text())["event_count"] == 3
