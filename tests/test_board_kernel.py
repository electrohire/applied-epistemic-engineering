"""Phase 2 kernel: T008 (transition table), T009 (resumption notes,
FR-K3), T011 (amendments, FR-K4), T012 (assignment, FR-K5).

The table is exercised two ways: at the fold, with the kernel checker
injected over hand-chained stored events (the done path included,
with append-stamped attachment events simulated as stored events —
the append service's stamping itself is T010's test surface), and
end-to-end through the real append command for every transition the
append path can already serve.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import append as append_mod  # noqa: E402
from board import canonical, fold, kernel  # noqa: E402

if sys.platform == "win32":
    pytest.skip(
        "board substrate is POSIX-only (plan: fcntl.flock; boards live on Linux hosts)",
        allow_module_level=True,
    )

BOARD = "board-kernel"
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
    "Current position: the fold is written and its tests pass.\n"
    "Next action: wire the kernel checker into fold_board.\n"
    "Records that matter: spec AB-001 Section 4.2; board/kernel.py.\n"
    "What would change the plan: a red-team finding against the table.\n"
)
WAIT = {
    "wait_kind": "named_event",
    "match": {"event": "ci-green"},
    "wake_falsifier": {"record": "ci:123", "field": "conclusion"},
    "sweep_deadline": "2026-11-21T12:00:00Z",
    "escalation": "owner",
}
CI_REF = "ci:123456789#" + "b" * 40


class Chain:
    """Hand-chained stored events, folded with the kernel checker."""

    def __init__(self, genesis: dict | None = None):
        self.events: list[dict] = []
        self.prev = canonical.GENESIS_PREV_HASH
        self.add("genesis-" + BOARD, "genesis", None, genesis or GENESIS, actor="planner")

    def add(self, event_id, kind, row_id, payload, actor="planner"):
        event = {
            "event_id": event_id,
            "board_id": BOARD,
            "row_id": row_id,
            "actor": actor,
            "writer": f"board-append@h:{BOARD}",
            "kind": kind,
            "payload": payload,
            "prev_hash": self.prev,
        }
        event["event_hash"] = canonical.event_hash(event)
        self.events.append(event)
        self.prev = event["event_hash"]
        return event

    def create(self, row_id, actor="planner", **payload):
        payload.setdefault("row_id", row_id)
        payload.setdefault("task_ref", f"T-{row_id}")
        return self.add(f"create-{row_id}", "row_created", row_id, payload, actor=actor)

    def transition(self, row_id, to_status, actor="planner", changes_extra=None, **payload):
        changes = {"status": to_status}
        if changes_extra:
            changes.update(changes_extra)
        return self.add(
            f"tr-{row_id}-{to_status}-{len(self.events)}",
            "row_update",
            row_id,
            {"changes": changes, **payload},
            actor=actor,
        )

    def fold(self):
        return fold.fold_events(self.events, transition_checker=kernel.kernel_checker)

    def drive_to_review(self, row_id, work_product=None):
        """Create a row and drive it to in_review along the legal path."""
        self.create(row_id, assignee_kind="worker")
        self.transition(row_id, "planned")
        self.transition(row_id, "ready")
        self.transition(row_id, "in_progress")
        self.transition(row_id, "in_review", work_product=work_product or ["commit:" + "b" * 40])


def refusal_reason(chain: Chain) -> str:
    result = chain.fold()
    assert not result.ok, "expected the kernel to refuse this log"
    assert result.refusal is not None
    return result.refusal.reason


# --- T008: one acceptance test per table row -------------------------------


def test_creation_rows_proposed_and_planned():
    chain = Chain()
    chain.create("r1")
    chain.create("r2", status="planned")
    result = chain.fold()
    assert result.ok
    assert result.state["rows"]["r1"]["status"] == "proposed"
    assert result.state["rows"]["r2"]["status"] == "planned"


def test_full_legal_path_to_done():
    chain = Chain()
    chain.drive_to_review("r1")
    chain.add(
        "attach-r1",
        "verdict_attached",
        "r1",
        {
            "verdict_ref": CI_REF,
            "verdict_evaluation": {"outcome": "favorable", "detail": "ci success at head"},
        },
        actor="reviewer",
    )
    chain.transition("r1", "done", actor="reviewer", verdict_ref=CI_REF)
    result = chain.fold()
    assert result.ok
    row = result.state["rows"]["r1"]
    assert row["status"] == "done" and row["verdict_ref"] == CI_REF


def test_block_and_unblock_rows():
    chain = Chain()
    chain.create("r1", assignee_kind="worker")
    chain.transition("r1", "planned")
    chain.transition("r1", "ready")
    chain.transition("r1", "in_progress")
    chain.transition("r1", "blocked", changes_extra={"wait": WAIT}, resumption_note=NOTE)
    result = chain.fold()
    assert result.ok
    row = result.state["rows"]["r1"]
    assert row["status"] == "blocked" and row["wait"] == WAIT
    assert "Current position" in row["resumption_note"]
    chain.transition("r1", "in_progress", changes_extra={"wait": None}, wake_ref="wake-event-1")
    result = chain.fold()
    assert result.ok
    row = result.state["rows"]["r1"]
    assert row["status"] == "in_progress" and row["wait"] is None


def test_rework_row_and_withdraw_and_supersede_rows():
    chain = Chain()
    chain.drive_to_review("r1")
    chain.transition("r1", "in_progress", actor="reviewer", comment_ref="review:msg-1")
    chain.transition("r1", "in_review", work_product=["commit:" + "c" * 40])
    chain.transition("r1", "withdrawn", reason="the task was descoped")
    chain.create("r2")
    chain.create("r3")
    chain.transition("r2", "superseded", replaced_by="r3")
    result = chain.fold()
    assert result.ok
    assert result.state["rows"]["r1"]["status"] == "withdrawn"
    assert result.state["rows"]["r2"]["status"] == "superseded"


def test_halt_and_resume_rows():
    chain = Chain()
    chain.create("r1")
    halt = chain.add("halt-1", "halt", None, {"tripwire": "integrity_failure"})
    chain.add("resume-1", "resume", None, {"halt_event": halt["event_id"], "reason": "cleared"})
    chain.transition("r1", "planned")
    result = chain.fold()
    assert result.ok and not result.state["halted"]


# --- T008: a refusal test per guard ----------------------------------------


def test_refusal_transition_not_in_table():
    chain = Chain()
    chain.create("r1")
    chain.transition("r1", "ready")  # proposed -> ready is not a table row
    assert "no transition" in refusal_reason(chain)


def test_refusal_creation_status_not_a_creation_row():
    chain = Chain()
    chain.create("r1", status="in_progress")
    assert "created as proposed or planned" in refusal_reason(chain)


def test_refusal_ready_with_unfinished_dependency():
    chain = Chain()
    chain.create("dep")
    chain.create("r1", depends_on=["dep"])
    chain.transition("r1", "planned")
    chain.transition("r1", "ready")
    assert "not done" in refusal_reason(chain)


def test_refusal_ready_with_missing_dependency():
    chain = Chain()
    chain.create("r1", depends_on=["ghost"])
    chain.transition("r1", "planned")
    chain.transition("r1", "ready")
    assert "does not exist" in refusal_reason(chain)


def test_ready_accepted_once_dependency_done():
    chain = Chain()
    chain.drive_to_review("dep")
    chain.add(
        "attach-dep",
        "verdict_attached",
        "dep",
        {"verdict_ref": CI_REF, "verdict_evaluation": {"outcome": "favorable"}},
        actor="reviewer",
    )
    chain.transition("dep", "done", actor="reviewer", verdict_ref=CI_REF)
    chain.create("r1", depends_on=["dep"])
    chain.transition("r1", "planned")
    chain.transition("r1", "ready")
    assert chain.fold().ok


def test_refusal_take_without_holder():
    chain = Chain()
    chain.create("r1")
    chain.transition("r1", "planned")
    chain.transition("r1", "ready")
    chain.transition("r1", "in_progress")
    assert "recorded holder" in refusal_reason(chain)


def test_refusal_take_beyond_wip_limit():
    genesis = dict(GENESIS, wip_limit=1)
    chain = Chain(genesis)
    for row_id in ("r1", "r2"):
        chain.create(row_id, assignee_kind="worker")
        chain.transition(row_id, "planned")
        chain.transition(row_id, "ready")
    chain.transition("r1", "in_progress")
    chain.transition("r2", "in_progress")
    assert "wip_limit" in refusal_reason(chain)


def test_refusal_block_without_wait_or_note():
    chain = Chain()
    chain.create("r1", assignee_kind="worker")
    chain.transition("r1", "planned")
    chain.transition("r1", "ready")
    chain.transition("r1", "in_progress")
    chain.transition("r1", "blocked", resumption_note=NOTE)
    assert "registered structured wait" in refusal_reason(chain)
    chain2 = Chain()
    chain2.create("r1", assignee_kind="worker")
    chain2.transition("r1", "planned")
    chain2.transition("r1", "ready")
    chain2.transition("r1", "in_progress")
    chain2.transition("r1", "blocked", changes_extra={"wait": WAIT})
    assert "FR-K3" in refusal_reason(chain2)


def test_refusal_unblock_without_wake_or_override():
    chain = Chain()
    chain.create("r1", assignee_kind="worker")
    chain.transition("r1", "planned")
    chain.transition("r1", "ready")
    chain.transition("r1", "in_progress")
    chain.transition("r1", "blocked", changes_extra={"wait": WAIT}, resumption_note=NOTE)
    chain.transition("r1", "in_progress", changes_extra={"wait": None})
    assert "wake reference or a planner override" in refusal_reason(chain)


def test_unblock_by_planner_override():
    chain = Chain()
    chain.create("r1", assignee_kind="worker")
    chain.transition("r1", "planned")
    chain.transition("r1", "ready")
    chain.transition("r1", "in_progress")
    chain.transition("r1", "blocked", changes_extra={"wait": WAIT}, resumption_note=NOTE)
    chain.transition(
        "r1", "in_progress", changes_extra={"wait": None}, override_reason="the wait is moot"
    )
    assert chain.fold().ok


def test_refusal_review_without_work_product():
    chain = Chain()
    chain.create("r1", assignee_kind="worker")
    chain.transition("r1", "planned")
    chain.transition("r1", "ready")
    chain.transition("r1", "in_progress")
    chain.transition("r1", "in_review")
    assert "work product" in refusal_reason(chain)


def test_refusal_rework_without_reference():
    chain = Chain()
    chain.drive_to_review("r1")
    chain.transition("r1", "in_progress", actor="reviewer")
    assert "rework path" in refusal_reason(chain)


def test_refusal_done_without_attachment():
    chain = Chain()
    chain.drive_to_review("r1")
    chain.transition("r1", "done", actor="reviewer", verdict_ref=CI_REF)
    assert "attached verdict_ref" in refusal_reason(chain)


def test_refusal_done_with_unfavorable_verdict():
    chain = Chain()
    chain.drive_to_review("r1")
    chain.add(
        "attach-r1",
        "verdict_attached",
        "r1",
        {"verdict_ref": CI_REF, "verdict_evaluation": {"outcome": "unfavorable"}},
        actor="reviewer",
    )
    chain.transition("r1", "done", actor="reviewer", verdict_ref=CI_REF)
    assert "not favorable" in refusal_reason(chain)


def test_refusal_done_event_must_carry_full_ref():
    chain = Chain()
    chain.drive_to_review("r1")
    chain.add(
        "attach-r1",
        "verdict_attached",
        "r1",
        {"verdict_ref": CI_REF, "verdict_evaluation": {"outcome": "favorable"}},
        actor="reviewer",
    )
    chain.transition("r1", "done", actor="reviewer")  # no verdict_ref in the event
    assert "carries the full verdict_ref" in refusal_reason(chain)


def test_refusal_withdraw_without_reason_and_supersede_without_pointer():
    chain = Chain()
    chain.create("r1")
    chain.transition("r1", "withdrawn")
    assert "records a reason" in refusal_reason(chain)
    chain2 = Chain()
    chain2.create("r1")
    chain2.transition("r1", "superseded")
    assert "replacing row" in refusal_reason(chain2)


def test_refusal_terminal_row_takes_no_events():
    chain = Chain()
    chain.create("r1")
    chain.transition("r1", "withdrawn", reason="descoped")
    chain.transition("r1", "planned")
    assert "terminal" in refusal_reason(chain)


def test_refusal_halt_without_reason_and_resume_mismatch():
    chain = Chain()
    chain.create("r1")
    chain.add("halt-1", "halt", None, {})
    assert "tripwire class or the planner's reason" in refusal_reason(chain)
    chain2 = Chain()
    chain2.create("r1")
    chain2.add("halt-1", "halt", None, {"reason": "owner order"})
    chain2.add("resume-1", "resume", None, {"halt_event": "halt-other", "reason": "go"})
    assert "references the halt event" in refusal_reason(chain2)


def test_transition_while_halted_refused():
    chain = Chain()
    chain.create("r1")
    chain.add("halt-1", "halt", None, {"reason": "owner order"})
    chain.transition("r1", "planned")
    assert "halted" in refusal_reason(chain)


def test_refusal_row_update_of_amendment_only_fields():
    chain = Chain()
    chain.create("r1")
    chain.add(
        "upd-r1",
        "row_update",
        "r1",
        {"changes": {"depends_on": []}},
    )
    assert "row_update changes may carry only" in refusal_reason(chain)


# --- T009: resumption-note validation --------------------------------------


@pytest.mark.parametrize("missing", list(kernel.NOTE_PARTS))
def test_note_missing_each_labeled_part(missing):
    lines = [f"{part}: something recorded." for part in kernel.NOTE_PARTS if part != missing]
    problems = kernel.validate_resumption_note("\n".join(lines))
    assert any(missing in problem for problem in problems)


def test_note_complete_and_empty():
    assert kernel.validate_resumption_note(NOTE) == []
    assert kernel.validate_resumption_note("") != []
    assert kernel.validate_resumption_note(None) != []


def test_refusal_block_with_incomplete_note():
    chain = Chain()
    chain.create("r1", assignee_kind="worker")
    chain.transition("r1", "planned")
    chain.transition("r1", "ready")
    chain.transition("r1", "in_progress")
    chain.transition(
        "r1", "blocked", changes_extra={"wait": WAIT}, resumption_note="Current position: stuck."
    )
    assert "FR-K3" in refusal_reason(chain)


# --- T010 fold-level attachment rules (stamping itself is T010/PR-2) -------


def test_refusal_attachment_without_stamp():
    chain = Chain()
    chain.drive_to_review("r1")
    chain.add("attach-r1", "verdict_attached", "r1", {"verdict_ref": CI_REF}, actor="reviewer")
    assert "stamped verdict_evaluation" in refusal_reason(chain)


def test_refusal_attachment_bad_ref_format():
    chain = Chain()
    chain.drive_to_review("r1")
    chain.add(
        "attach-r1",
        "verdict_attached",
        "r1",
        {"verdict_ref": "ci:123#nothex", "verdict_evaluation": {"outcome": "favorable"}},
        actor="reviewer",
    )
    assert "pinned format" in refusal_reason(chain)


def test_refusal_holder_attaches_own_verdict():
    chain = Chain()
    chain.create("r1", assignee_instance="agent-x")
    chain.transition("r1", "planned")
    chain.transition("r1", "ready")
    chain.transition("r1", "in_progress")
    chain.transition("r1", "in_review", work_product=["commit:" + "b" * 40])
    chain.add(
        "attach-r1",
        "verdict_attached",
        "r1",
        {"verdict_ref": CI_REF, "verdict_evaluation": {"outcome": "favorable"}},
        actor="agent-x",
    )
    assert "current holder may not attach" in refusal_reason(chain)


def test_superseding_attachment_chain():
    chain = Chain()
    chain.drive_to_review("r1")
    other_ref = "ci:987654321#" + "c" * 40
    chain.add(
        "attach-1",
        "verdict_attached",
        "r1",
        {"verdict_ref": CI_REF, "verdict_evaluation": {"outcome": "unfavorable"}},
        actor="reviewer",
    )
    chain.add(
        "attach-2",
        "verdict_attached",
        "r1",
        {
            "verdict_ref": other_ref,
            "previous_ref": CI_REF,
            "reason": "the first run was superseded by a re-run",
            "verdict_evaluation": {"outcome": "favorable"},
        },
        actor="reviewer",
    )
    chain.transition("r1", "done", actor="reviewer", verdict_ref=other_ref)
    result = chain.fold()
    assert result.ok
    assert result.state["rows"]["r1"]["verdict_ref"] == other_ref


def test_refusal_superseding_attachment_without_previous_or_reason():
    chain = Chain()
    chain.drive_to_review("r1")
    chain.add(
        "attach-1",
        "verdict_attached",
        "r1",
        {"verdict_ref": CI_REF, "verdict_evaluation": {"outcome": "favorable"}},
        actor="reviewer",
    )
    chain.add(
        "attach-2",
        "verdict_attached",
        "r1",
        {"verdict_ref": "ci:987654321#" + "c" * 40, "verdict_evaluation": {"outcome": "favorable"}},
        actor="reviewer",
    )
    assert "records the previous reference" in refusal_reason(chain)


# --- T011: amendment mechanics ----------------------------------------------


def amend(chain: Chain, row_id, changes, actor="planner", **payload):
    return chain.add(
        f"amend-{row_id}-{len(chain.events)}",
        "amendment",
        row_id,
        {"changes": changes, "reason": "the plan changed", "authority": "planner", **payload},
        actor=actor,
    )


def test_amendment_applies_and_counts():
    chain = Chain()
    chain.create("r1")
    amend(chain, "r1", {"body": "revised scope"})
    result = chain.fold()
    assert result.ok
    row = result.state["rows"]["r1"]
    assert row["body"] == "revised scope" and row["amendment_seq"] == 1


def test_refusal_amendment_without_reason_or_authority():
    chain = Chain()
    chain.create("r1")
    chain.add("amend-1", "amendment", "r1", {"changes": {"body": "x"}, "authority": "planner"})
    assert "records its reason" in refusal_reason(chain)
    chain2 = Chain()
    chain2.create("r1")
    chain2.add("amend-1", "amendment", "r1", {"changes": {"body": "x"}, "reason": "why"})
    assert "records its authority" in refusal_reason(chain2)


def test_refusal_amendment_of_non_amendable_fields():
    chain = Chain()
    chain.create("r1")
    amend(chain, "r1", {"status": "ready"})
    assert "amendable fields are exactly" in refusal_reason(chain)
    chain2 = Chain()
    chain2.create("r1")
    amend(chain2, "r1", {"verdict_ref": CI_REF})
    assert "superseding attachment" in refusal_reason(chain2)


def test_refusal_cycle_at_creation_and_at_amendment():
    chain = Chain()
    chain.create("a", depends_on=["b"])  # forward reference is allowed
    chain.create("b", depends_on=["a"])  # closing the cycle is refused
    assert "closes a cycle" in refusal_reason(chain)
    chain2 = Chain()
    chain2.create("a")
    chain2.create("b", depends_on=["a"])
    amend(chain2, "a", {"depends_on": ["b"]})
    assert "closes a cycle" in refusal_reason(chain2)
    chain3 = Chain()
    chain3.create("a", depends_on=["a"])
    assert "closes a cycle" in refusal_reason(chain3)


def test_repointing_dependents_after_supersede():
    chain = Chain()
    chain.create("old")
    chain.create("dependent", depends_on=["old"])
    chain.create("new")
    chain.transition("old", "superseded", replaced_by="new")
    amend(chain, "dependent", {"depends_on": ["new"]})
    result = chain.fold()
    assert result.ok
    assert result.state["rows"]["dependent"]["depends_on"] == ["new"]


def test_refusal_handoff_without_note_and_acceptance_with_note():
    chain = Chain()
    chain.create("r1", assignee_instance="agent-a")
    chain.transition("r1", "planned")
    chain.transition("r1", "ready")
    chain.transition("r1", "in_progress")
    amend(chain, "r1", {"assignee_instance": "agent-b"})
    assert "FR-K3 (handoff)" in refusal_reason(chain)
    chain2 = Chain()
    chain2.create("r1", assignee_instance="agent-a")
    chain2.transition("r1", "planned")
    chain2.transition("r1", "ready")
    chain2.transition("r1", "in_progress")
    amend(chain2, "r1", {"assignee_instance": "agent-b"}, resumption_note=NOTE)
    assert chain2.fold().ok


# --- T012: assignment rules ---------------------------------------------------


def test_gate_row_creation_rules():
    chain = Chain()
    chain.create("g1", gate_row=True, assignee_kind="worker")
    assert "FR-K5" in refusal_reason(chain)
    chain2 = Chain()
    chain2.create("g1", gate_row=True, assignee_instance="tristen")
    result = chain2.fold()
    assert result.ok and result.state["gate_rows"] == ["g1"]
    chain3 = Chain()
    chain3.create("w1", assignee_kind="worker")
    assert chain3.fold().ok


def test_refusal_amendment_giving_gate_row_a_kind():
    chain = Chain()
    chain.create("g1", gate_row=True, assignee_instance="tristen")
    amend(chain, "g1", {"assignee_kind": "worker"})
    assert "FR-K5" in refusal_reason(chain)


# --- End-to-end through the real append command -------------------------------


def _append(board_dir, event):
    return append_mod.append_event(board_dir, event, fold.log_head_hash(board_dir))


def _caller(event_id, kind, row_id, payload, actor="planner"):
    return {
        "event_id": event_id,
        "board_id": "board-kernel-e2e",
        "row_id": row_id,
        "actor": actor,
        "kind": kind,
        "payload": payload,
    }


def test_append_path_enforces_the_kernel(tmp_path):
    board_dir = tmp_path / "b"
    genesis = dict(GENESIS, board_id="board-kernel-e2e")
    append_mod.create_board(board_dir, genesis, actor="planner")
    _append(
        board_dir,
        _caller(
            "e1",
            "row_created",
            "r1",
            {"row_id": "r1", "task_ref": "T1", "assignee_kind": "worker"},
        ),
    )
    # proposed -> ready is not in the table: the append is refused and
    # the log does not grow.
    with pytest.raises(append_mod.BoardRefusal) as exc:
        _append(
            board_dir,
            _caller("e2", "row_update", "r1", {"changes": {"status": "ready"}}),
        )
    assert exc.value.code == "FOLD_REFUSED" and "no transition" in exc.value.message
    for index, status in enumerate(("planned", "ready", "in_progress")):
        _append(
            board_dir,
            _caller(f"s{index}", "row_update", "r1", {"changes": {"status": status}}),
        )
    _append(
        board_dir,
        _caller(
            "s3",
            "row_update",
            "r1",
            {"changes": {"status": "blocked", "wait": WAIT}, "resumption_note": NOTE},
        ),
    )
    _append(
        board_dir,
        _caller(
            "s4",
            "row_update",
            "r1",
            {"changes": {"status": "in_progress", "wait": None}, "wake_ref": "wake-1"},
        ),
    )
    _append(
        board_dir,
        _caller(
            "s5",
            "row_update",
            "r1",
            {"changes": {"status": "in_review"}, "work_product": ["commit:" + "b" * 40]},
        ),
    )
    result = fold.fold_board(board_dir)
    assert result.ok
    row = result.state["rows"]["r1"]
    assert row["status"] == "in_review" and row["wait"] is None
    assert "Current position" in row["resumption_note"]


def test_append_path_gate_row_refusal(tmp_path):
    board_dir = tmp_path / "b"
    genesis = dict(GENESIS, board_id="board-kernel-e2e")
    append_mod.create_board(board_dir, genesis, actor="planner")
    with pytest.raises(append_mod.BoardRefusal) as exc:
        _append(
            board_dir,
            _caller(
                "e1",
                "row_created",
                "g1",
                {
                    "row_id": "g1",
                    "task_ref": "G1",
                    "gate_row": True,
                    "assignee_kind": "worker",
                },
            ),
        )
    assert "FR-K5" in exc.value.message


def test_fold_board_default_checker_is_the_kernel(tmp_path):
    # A raw-written log with a kernel-illegal transition folds under
    # the structural default but is refused by fold_board's kernel.
    chain = Chain()
    chain.create("r1")
    chain.transition("r1", "ready")
    board_dir = tmp_path / "b"
    board_dir.mkdir()
    lines = b"".join(canonical.canonical_line(event) for event in chain.events)
    (board_dir / "events.jsonl").write_bytes(lines)
    structural = fold.fold_lines(lines.splitlines())
    assert structural.ok
    enforced = fold.fold_board(board_dir)
    assert not enforced.ok
    assert enforced.refusal is not None and "no transition" in enforced.refusal.reason
