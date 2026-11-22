"""T007: the generated tasks view (spec AB-001 3.3, FR-S5; 4.3, FR-K2)."""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import append as append_mod  # noqa: E402
from board import fold, state, view  # noqa: E402

if sys.platform == "win32":
    pytest.skip(
        "board substrate is POSIX-only (plan: fcntl.flock; boards live on Linux hosts)",
        allow_module_level=True,
    )

GENESIS = {
    "board_id": "board-view",
    "program": "p",
    "spec_ref": "AB-001",
    "spec_hash": "a" * 64,
    "wip_limit": 4,
    "keeper_cadence": "30m",
    "detector_chat": "d",
    "escalation_target_2": "owner",
}


def make_board(tmp_path: Path) -> Path:
    board_dir = tmp_path / "b"
    append_mod.create_board(board_dir, GENESIS, actor="planner")
    append_mod.append_event(
        board_dir,
        {
            "event_id": "e1",
            "board_id": "board-view",
            "row_id": "r1",
            "actor": "planner",
            "kind": "row_created",
            "payload": {
                "row_id": "r1",
                "task_ref": "T001",
                "status": "in_progress",
                "execution_state": "running",
            },
        },
        fold.log_head_hash(board_dir),
    )
    return board_dir


def test_view_carries_header_and_head_hash(tmp_path):
    board_dir = make_board(tmp_path)
    out = view.generate_view(board_dir)
    text = out.read_text()
    assert view.GENERATED_HEADER in text
    assert fold.log_head_hash(board_dir) in text


def test_fr_k2_status_and_execution_state_always_together(tmp_path):
    board_dir = make_board(tmp_path)
    text = view.generate_view(board_dir).read_text()
    row_lines = [line for line in text.splitlines() if line.startswith("- [")]
    assert row_lines, "expected at least one row line"
    for line in row_lines:
        assert "in_progress" in line
        assert "execution_state: running" in line
    # execution_state never appears anywhere without a status beside it.
    for line in text.splitlines():
        if "execution_state" in line:
            assert re.search(r"\[in_progress\]", line)


def test_view_labels_stale_state(tmp_path):
    board_dir = make_board(tmp_path)
    stored = state.read_state(board_dir)
    stored["head_hash"] = "f" * 64
    state.write_state(board_dir, {k: v for k, v in stored.items() if k != "state_hash"})
    text = view.generate_view(board_dir).read_text()
    assert "STALE" in text and "f" * 64 in text
