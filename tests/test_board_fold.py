"""T004: fold and chain verification (spec AB-001 3.2, FR-S1/FR-S2)."""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import append as append_mod  # noqa: E402
from board import canonical, fold  # noqa: E402

GENESIS = {
    "board_id": "board-fold",
    "program": "p",
    "spec_ref": "AB-001",
    "spec_hash": "a" * 64,
    "wip_limit": 4,
    "keeper_cadence": "30m",
    "detector_chat": "d",
    "escalation_target_2": "owner",
}


def build_events(tmp_path: Path, rows: int = 3) -> list[dict]:
    board_dir = tmp_path / "b"
    append_mod.create_board(board_dir, GENESIS, actor="planner")
    for i in range(rows):
        append_mod.append_event(
            board_dir,
            {
                "event_id": f"e{i}",
                "board_id": "board-fold",
                "row_id": f"r{i}",
                "actor": "planner",
                "kind": "row_created",
                "payload": {"row_id": f"r{i}", "task_ref": f"T{i}"},
            },
            fold.log_head_hash(board_dir),
        )
    return append_mod._read_events(board_dir)


def test_genesis_fold(tmp_path):
    events = build_events(tmp_path)
    result = fold.fold_events(events)
    assert result.ok
    assert result.state["event_count"] == 4
    assert set(result.state["rows"]) == {"r0", "r1", "r2"}
    row = result.state["rows"]["r0"]
    assert row["amendment_seq"] == 0 and row["created_event"] == "e0"


def test_tampered_event_breaks_fold_at_named_event(tmp_path):
    events = build_events(tmp_path)
    events[2]["payload"] = {"row_id": "r1", "task_ref": "FORGED"}
    result = fold.fold_events(events)
    assert not result.ok
    assert result.refusal is not None
    assert result.refusal.index == 2 and result.refusal.event_id == "e1"


def test_reordering_breaks_the_chain(tmp_path):
    events = build_events(tmp_path)
    events[1], events[2] = events[2], events[1]
    result = fold.fold_events(events)
    assert not result.ok and "chain break" in (result.refusal.reason if result.refusal else "")


def test_illegal_transition_refused_via_injected_kernel_checker(tmp_path):
    events = build_events(tmp_path)

    def no_rows_checker(event, state):
        if event["kind"] == "row_created":
            return "kernel table: rows may not be created in this drill"
        return None

    result = fold.fold_events(events, transition_checker=no_rows_checker)
    assert not result.ok
    assert result.refusal is not None and result.refusal.event_id == "e0"


def test_structural_refusals(tmp_path):
    events = build_events(tmp_path)
    # An event naming an unknown row is refused structurally.
    rogue = dict(events[-1])
    rogue = {
        "event_id": "rogue",
        "board_id": "board-fold",
        "row_id": "ghost",
        "actor": "planner",
        "writer": "board-append@h:board-fold",
        "kind": "row_update",
        "payload": {"changes": {"status": "ready"}},
        "prev_hash": events[-1]["event_hash"],
    }
    rogue["event_hash"] = canonical.event_hash(rogue)
    result = fold.fold_events([*events, rogue])
    assert not result.ok and "unknown row" in (result.refusal.reason if result.refusal else "")


def test_duplicate_event_id_is_a_finding_not_a_refusal(tmp_path):
    events = build_events(tmp_path, rows=1)
    duplicate = dict(events[-1])
    # Re-chain the duplicate so only the event_id repeats.
    duplicate["prev_hash"] = events[-1]["event_hash"]
    duplicate["event_hash"] = canonical.event_hash(duplicate)
    result = fold.fold_events([*events, duplicate])
    assert result.ok
    assert any(f["kind"] == "duplicate_event_id" for f in result.findings)
    assert result.state["event_count"] == 2  # genesis + one row; duplicate not applied


def test_halt_blocks_row_changes_until_resume(tmp_path):
    events = build_events(tmp_path, rows=1)

    def board_event(event_id, kind, prev):
        event = {
            "event_id": event_id,
            "board_id": "board-fold",
            "row_id": None,
            "actor": "planner",
            "writer": "board-append@h:board-fold",
            "kind": kind,
            "payload": {},
            "prev_hash": prev,
        }
        event["event_hash"] = canonical.event_hash(event)
        return event

    halt = board_event("halt-1", "halt", events[-1]["event_hash"])
    blocked = {
        "event_id": "e-blocked",
        "board_id": "board-fold",
        "row_id": "r0",
        "actor": "planner",
        "writer": "board-append@h:board-fold",
        "kind": "row_update",
        "payload": {"changes": {"status": "ready"}},
        "prev_hash": halt["event_hash"],
    }
    blocked["event_hash"] = canonical.event_hash(blocked)
    result = fold.fold_events([*events, halt, blocked])
    assert not result.ok and "halted" in (result.refusal.reason if result.refusal else "")
    resume = board_event("resume-1", "resume", halt["event_hash"])
    after = dict(blocked)
    after["prev_hash"] = resume["event_hash"]
    after["event_hash"] = canonical.event_hash(after)
    result = fold.fold_events([*events, halt, resume, after])
    assert result.ok and result.state["rows"]["r0"]["status"] == "ready"


def test_fold_performance_bound_10000_events():
    events = []
    prev = canonical.GENESIS_PREV_HASH
    genesis = {
        "event_id": "genesis-b",
        "board_id": "b",
        "row_id": None,
        "actor": "planner",
        "writer": "board-append@h:b",
        "kind": "genesis",
        "payload": GENESIS | {"board_id": "b"},
        "prev_hash": prev,
    }
    genesis["event_hash"] = canonical.event_hash(genesis)
    events.append(genesis)
    prev = genesis["event_hash"]
    for i in range(9999):
        event = {
            "event_id": f"e{i}",
            "board_id": "b",
            "row_id": f"r{i}",
            "actor": "planner",
            "writer": "board-append@h:b",
            "kind": "row_created",
            "payload": {"row_id": f"r{i}", "task_ref": f"T{i}"},
            "prev_hash": prev,
        }
        event["event_hash"] = canonical.event_hash(event)
        events.append(event)
        prev = event["event_hash"]
    start = time.monotonic()
    result = fold.fold_events(events)
    elapsed = time.monotonic() - start
    assert result.ok and result.state["event_count"] == 10000
    assert elapsed < 60, f"fold of 10,000 events took {elapsed:.1f}s (bound: 60s)"
