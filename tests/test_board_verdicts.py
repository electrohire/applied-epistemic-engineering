"""Phase 2 verdicts: T010 (verdict attachment, FR-K1/FR-K1a/FR-K1b).

The resolver is tested against fixtures built from the real record
formats: the engine's evaluation JSON, gatekeeper queue records
(payload verdicts carried as *_PAYLOAD_EXIT tokens; wrapper fields
present and never decisive), CI run records in the `gh run view`
shape, and external gate records. The end-to-end tests drive a real
board through the real append path: the append service stamps the
attachment's evaluation, the fold enforces favorability, and `done`
opens only on a favorable stamp.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import append as append_mod  # noqa: E402
from board import canonical, fold, verdicts  # noqa: E402

if sys.platform == "win32":
    pytest.skip(
        "board substrate is POSIX-only (plan: fcntl.flock; boards live on Linux hosts)",
        allow_module_level=True,
    )

FIXTURES = Path(__file__).parent / "fixtures" / "board"
QUEUE_DIR = FIXTURES / "gatekeeper-queue"
CI_DIR = FIXTURES / "ci-runs"
EVALUATION = FIXTURES / "engine-evaluation.json"
HEAD_SHA = "0123456789abcdef0123456789abcdef01234567"

BOARD = "board-verdicts"
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gatekeeper_ref(job_id: str, payload_exit: int | None) -> str:
    extracted = {"job_id": job_id, "payload_exit_code": payload_exit}
    digest = hashlib.sha256(canonical.canonical_bytes(extracted)).hexdigest()
    return f"gatekeeper:{job_id}#{digest}"


def _engine_ref(*claims: str) -> str:
    return f"engine:{EVALUATION}#{_sha256(EVALUATION)}"


# ---------------------------------------------------------------- parse


def test_parse_verdict_ref_per_class():
    assert verdicts.parse_verdict_ref("engine:/x/y.json#" + "a" * 64) is not None
    assert verdicts.parse_verdict_ref("ci:123#" + "b" * 40) is not None
    assert verdicts.parse_verdict_ref("gatekeeper:job-1#" + "c" * 64) is not None
    assert verdicts.parse_verdict_ref("gate:/g.json#" + "d" * 64) is not None


@pytest.mark.parametrize(
    "bad",
    [
        "engine:/x/y.json#" + "a" * 40,  # engine digests are 64-hex
        "ci:123#" + "b" * 64,  # ci digests are the 40-hex head SHA
        "other:/x#" + "a" * 64,  # unknown class
        "engine:/x/y.json",  # no digest
        "engine:#" + "a" * 64,  # no locator
        42,
        None,
    ],
)
def test_parse_verdict_ref_refuses_malformed(bad):
    assert verdicts.parse_verdict_ref(bad) is None


# ---------------------------------------------------------------- engine


def test_engine_favorable_for_consistent_and_verified_claims():
    check = verdicts.evaluate_verdict(_engine_ref(), claim_ids=("SKA-001", "SKA-002"))
    assert check.outcome == "favorable" and check.record_hash


def test_engine_unfavorable_for_a_violated_claim():
    check = verdicts.evaluate_verdict(_engine_ref(), claim_ids=("SKA-001", "SKA-003"))
    assert check.outcome == "unfavorable" and "SKA-003" in check.detail


def test_engine_unfavorable_for_a_claim_absent_from_the_evaluation():
    check = verdicts.evaluate_verdict(_engine_ref(), claim_ids=("SKA-999",))
    assert check.outcome == "unfavorable"


def test_engine_unresolvable_on_content_hash_mismatch(tmp_path):
    ref = f"engine:{EVALUATION}#" + "0" * 64
    check = verdicts.evaluate_verdict(ref, claim_ids=("SKA-001",))
    assert check.outcome == "unresolvable" and check.record_hash is None


def test_engine_unresolvable_on_missing_file(tmp_path):
    ref = f"engine:{tmp_path / 'nope.json'}#" + "0" * 64
    assert verdicts.evaluate_verdict(ref, claim_ids=("SKA-001",)).outcome == "unresolvable"


# ---------------------------------------------------------------- gatekeeper


def test_gatekeeper_favorable_only_on_payload_exit_zero():
    check = verdicts.evaluate_verdict(
        _gatekeeper_ref("job-payload-pass", 0), gatekeeper_queue_dir=QUEUE_DIR
    )
    assert check.outcome == "favorable"


def test_gatekeeper_wrapper_success_is_not_payload_success():
    # The trap case: the wrapper concluded success while the payload
    # exited 3. The verdict rests on the payload's own exit record.
    check = verdicts.evaluate_verdict(
        _gatekeeper_ref("job-wrapper-success-payload-fail", 3),
        gatekeeper_queue_dir=QUEUE_DIR,
    )
    assert check.outcome == "unfavorable" and "3" in check.detail


def test_gatekeeper_no_payload_record_is_not_favorable():
    check = verdicts.evaluate_verdict(
        _gatekeeper_ref("job-no-payload-record", None), gatekeeper_queue_dir=QUEUE_DIR
    )
    assert check.outcome == "unfavorable" and "no payload exit record" in check.detail


def test_gatekeeper_unresolvable_on_citation_mismatch():
    ref = _gatekeeper_ref("job-payload-pass", 1)  # cites exit 1; record says 0
    check = verdicts.evaluate_verdict(ref, gatekeeper_queue_dir=QUEUE_DIR)
    assert check.outcome == "unresolvable"


def test_gatekeeper_unresolvable_without_a_queue_directory():
    check = verdicts.evaluate_verdict(_gatekeeper_ref("job-payload-pass", 0))
    assert check.outcome == "unresolvable"


# ---------------------------------------------------------------- ci


def test_ci_favorable_on_success_at_the_work_product_commit():
    ref = f"ci:44981799043#{HEAD_SHA}"
    check = verdicts.evaluate_verdict(
        ref, work_product=(f"commit:{HEAD_SHA}",), ci_records_dir=CI_DIR
    )
    assert check.outcome == "favorable"


def test_ci_unfavorable_on_a_failed_conclusion():
    ref = f"ci:44981799044#{HEAD_SHA}"
    check = verdicts.evaluate_verdict(
        ref, work_product=(f"commit:{HEAD_SHA}",), ci_records_dir=CI_DIR
    )
    assert check.outcome == "unfavorable" and "failure" in check.detail


def test_ci_unfavorable_when_the_run_covers_a_different_commit():
    ref = f"ci:44981799043#{HEAD_SHA}"
    check = verdicts.evaluate_verdict(
        ref, work_product=("commit:" + "f" * 40,), ci_records_dir=CI_DIR
    )
    assert check.outcome == "unfavorable" and "not among" in check.detail


def test_ci_unresolvable_when_the_head_sha_is_not_the_cited_digest():
    ref = "ci:44981799043#" + "e" * 40
    check = verdicts.evaluate_verdict(
        ref, work_product=(f"commit:{HEAD_SHA}",), ci_records_dir=CI_DIR
    )
    assert check.outcome == "unresolvable"


# ---------------------------------------------------------------- gate


def test_gate_favorable_json_and_text_forms(tmp_path):
    for fixture in ("gate-approval.json", "gate-approval.txt"):
        path = FIXTURES / fixture
        ref = f"gate:{path}#{_sha256(path)}"
        check = verdicts.evaluate_verdict(
            ref, work_product=("commit:" + "b" * 40,), board_dir=tmp_path / "board"
        )
        assert check.outcome == "favorable", fixture


def test_gate_record_inside_the_board_is_unresolvable(tmp_path):
    board_dir = tmp_path / "board"
    board_dir.mkdir()
    inside = board_dir / "gate.json"
    inside.write_text(
        json.dumps({"decision": "approve", "decider": "reviewer-one"}), encoding="utf-8"
    )
    ref = f"gate:{inside}#{_sha256(inside)}"
    check = verdicts.evaluate_verdict(ref, board_dir=board_dir)
    assert check.outcome == "unresolvable" and "FR-K1b" in check.detail


def test_gate_unfavorable_without_an_approval_or_a_decider(tmp_path):
    path = tmp_path / "gate.json"
    path.write_text(json.dumps({"decision": "reject", "decider": "r"}), encoding="utf-8")
    ref = f"gate:{path}#{_sha256(path)}"
    assert verdicts.evaluate_verdict(ref, board_dir=tmp_path / "b").outcome == "unfavorable"
    path.write_text(json.dumps({"decision": "approve"}), encoding="utf-8")
    ref = f"gate:{path}#{_sha256(path)}"
    check = verdicts.evaluate_verdict(ref, board_dir=tmp_path / "b")
    assert check.outcome == "unfavorable" and "no decider" in check.detail


# ---------------------------------------------------------------- end to end


def _caller(event_id, kind, row_id, payload, actor="planner"):
    return {
        "event_id": event_id,
        "board_id": BOARD,
        "row_id": row_id,
        "actor": actor,
        "kind": kind,
        "payload": payload,
    }


def _append(board_dir, event, **kwargs):
    head = fold.log_head_hash(board_dir)
    return append_mod.append_event(board_dir, event, head, **kwargs)


def _drive_to_review(board_dir, *, claims=("SKA-001",), holder="worker-1"):
    append_mod.create_board(board_dir, dict(GENESIS), actor="planner")
    _append(
        board_dir,
        _caller(
            "e1",
            "row_created",
            "r1",
            {
                "row_id": "r1",
                "task_ref": "T1",
                "assignee_kind": "worker",
                "assignee_instance": holder,
                "claim_ids": list(claims),
            },
        ),
    )
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
            {"changes": {"status": "in_review"}, "work_product": [f"commit:{HEAD_SHA}"]},
        ),
    )


def test_end_to_end_done_on_a_favorable_ci_verdict(tmp_path):
    board_dir = tmp_path / "b"
    _drive_to_review(board_dir)
    ref = f"ci:44981799043#{HEAD_SHA}"
    stored = _append(
        board_dir,
        _caller("a1", "verdict_attached", "r1", {"verdict_ref": ref}, actor="reviewer-1"),
        verdict_context={"ci_records_dir": str(CI_DIR)},
    )
    evaluation = stored["payload"]["verdict_evaluation"]
    assert evaluation["outcome"] == "favorable" and evaluation["record_hash"]
    _append(
        board_dir,
        _caller(
            "s4",
            "row_update",
            "r1",
            {"changes": {"status": "done"}, "verdict_ref": ref},
            actor="reviewer-1",
        ),
    )
    result = fold.fold_board(board_dir)
    assert result.ok
    row = result.state["rows"]["r1"]
    assert row["status"] == "done" and row["verdict_ref"] == ref


def test_end_to_end_unfavorable_gatekeeper_verdict_blocks_done(tmp_path):
    board_dir = tmp_path / "b"
    _drive_to_review(board_dir)
    ref = _gatekeeper_ref("job-wrapper-success-payload-fail", 3)
    stored = _append(
        board_dir,
        _caller("a1", "verdict_attached", "r1", {"verdict_ref": ref}, actor="reviewer-1"),
        verdict_context={"gatekeeper_queue_dir": str(QUEUE_DIR)},
    )
    assert stored["payload"]["verdict_evaluation"]["outcome"] == "unfavorable"
    with pytest.raises(append_mod.BoardRefusal) as exc:
        _append(
            board_dir,
            _caller(
                "s4",
                "row_update",
                "r1",
                {"changes": {"status": "done"}, "verdict_ref": ref},
                actor="reviewer-1",
            ),
        )
    assert exc.value.code == "FOLD_REFUSED"
    assert fold.fold_board(board_dir).state["rows"]["r1"]["status"] == "in_review"


def test_end_to_end_engine_verdict_done(tmp_path):
    board_dir = tmp_path / "b"
    _drive_to_review(board_dir, claims=("SKA-001", "SKA-002"))
    ref = _engine_ref()
    stored = _append(
        board_dir,
        _caller("a1", "verdict_attached", "r1", {"verdict_ref": ref}, actor="reviewer-1"),
    )
    assert stored["payload"]["verdict_evaluation"]["outcome"] == "favorable"
    _append(
        board_dir,
        _caller(
            "s4",
            "row_update",
            "r1",
            {"changes": {"status": "done"}, "verdict_ref": ref},
            actor="reviewer-1",
        ),
    )
    assert fold.fold_board(board_dir).state["rows"]["r1"]["status"] == "done"


def test_end_to_end_the_holder_may_not_attach_the_rows_own_verdict(tmp_path):
    board_dir = tmp_path / "b"
    _drive_to_review(board_dir, holder="worker-1")
    ref = f"ci:44981799043#{HEAD_SHA}"
    with pytest.raises(append_mod.BoardRefusal) as exc:
        _append(
            board_dir,
            _caller("a1", "verdict_attached", "r1", {"verdict_ref": ref}, actor="worker-1"),
            verdict_context={"ci_records_dir": str(CI_DIR)},
        )
    assert exc.value.code == "FOLD_REFUSED" and "holder" in exc.value.message


def test_caller_supplied_evaluation_is_refused(tmp_path):
    board_dir = tmp_path / "b"
    _drive_to_review(board_dir)
    event = _caller(
        "a1",
        "verdict_attached",
        "r1",
        {
            "verdict_ref": f"ci:44981799043#{HEAD_SHA}",
            "verdict_evaluation": {"outcome": "favorable", "detail": "trust me"},
        },
        actor="reviewer-1",
    )
    with pytest.raises(append_mod.BoardRefusal) as exc:
        _append(board_dir, event, verdict_context={"ci_records_dir": str(CI_DIR)})
    assert exc.value.code == "SCHEMA" and "verdict_evaluation" in exc.value.message
