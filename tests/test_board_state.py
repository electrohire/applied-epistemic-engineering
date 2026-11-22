"""T005: state snapshots and freshness labeling (spec AB-001 3.3, FR-S4)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import append as append_mod  # noqa: E402
from board import fold, state  # noqa: E402

GENESIS = {
    "board_id": "board-state",
    "program": "p",
    "spec_ref": "AB-001",
    "spec_hash": "a" * 64,
    "wip_limit": 4,
    "keeper_cadence": "30m",
    "detector_chat": "d",
    "escalation_target_2": "owner",
}


def test_state_carries_head_and_verifies(tmp_path):
    board_dir = tmp_path / "b"
    append_mod.create_board(board_dir, GENESIS, actor="planner")
    stored = state.read_state(board_dir)
    assert stored is not None
    assert stored["head_hash"] == fold.log_head_hash(board_dir)
    assert stored["state_hash"]


def test_stale_state_is_labeled_with_both_hashes(tmp_path):
    board_dir = tmp_path / "b"
    append_mod.create_board(board_dir, GENESIS, actor="planner")
    state_head_before = state.read_state(board_dir)["head_hash"]
    # A writer outside the append path extends the log directly (the
    # exact divergence freshness labeling exists to surface).
    event = {
        "event_id": "raw-1",
        "board_id": "board-state",
        "row_id": "r1",
        "actor": "planner",
        "kind": "row_created",
        "payload": {"row_id": "r1", "task_ref": "T1"},
    }
    from board import canonical

    stored = dict(event)
    stored["writer"] = "board-append@h:board-state"
    stored["prev_hash"] = fold.log_head_hash(board_dir)
    stored["event_hash"] = canonical.event_hash(stored)
    with open(board_dir / "events.jsonl", "ab") as handle:
        handle.write(canonical.canonical_line(stored))
    info = state.freshness(board_dir)
    assert info["status"] == "stale"
    assert info["state_head"] == state_head_before
    assert info["log_head"] == stored["event_hash"]


def test_missing_state_is_labeled(tmp_path):
    board_dir = tmp_path / "b"
    board_dir.mkdir()
    info = state.freshness(board_dir)
    assert info["status"] == "missing"
