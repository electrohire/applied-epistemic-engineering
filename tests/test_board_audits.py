"""Phase 4 audits: T018-T023 (spec AB-001 Section 6).

Every audit runs end-to-end against real board directories built
through the real append path, with real record files in the real
formats. The planted-violation drills are the acceptance shape: a
verdict record swapped after citation, a CI record whose conclusion
changed after citation, a view edited by hand, a served state that
diverges from the fold, a row that traces to nothing, a row whose
reference resolves into a study arm, and shipped kernel definitions
that diverge from the canonical table. Each audit must catch its
plant and pass a clean board, and each must fail closed (a failed
report, never a pass) when its inputs cannot be read.
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
from board import audits, canonical, fold, kernel, state, view  # noqa: E402

if sys.platform == "win32":
    pytest.skip(
        "board substrate is POSIX-only (plan: fcntl.flock; boards live on Linux hosts)",
        allow_module_level=True,
    )

BOARD = "board-audits"
HEAD_SHA = "0123456789abcdef0123456789abcdef01234567"
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
    head = fold.log_head_hash(board_dir)
    return append_mod.append_event(board_dir, event, head, **kwargs)


def make_board(tmp_path, genesis=None):
    board_dir = tmp_path / "b"
    append_mod.create_board(board_dir, dict(genesis or GENESIS), actor="planner")
    return board_dir


def create_row(board_dir, row_id, task_ref="T-1", claims=(), status=None):
    payload = {
        "row_id": row_id,
        "task_ref": task_ref,
        "assignee_kind": "worker",
        "assignee_instance": "worker-1",
        "claim_ids": list(claims),
    }
    if status:
        payload["status"] = status
    append(board_dir, caller(f"create-{row_id}", "row_created", row_id, payload))


def drive(board_dir, row_id, *statuses):
    for status in statuses:
        payload = {"changes": {"status": status}}
        if status == "in_review":
            payload["work_product"] = [f"commit:{HEAD_SHA}"]
        append(board_dir, caller(f"{row_id}-{status}", "row_update", row_id, payload))


def write_evaluation(tmp_path, verdict="verified"):
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps({"verdicts": [{"id": "C-1", "verdict": verdict}]}), encoding="utf-8")
    return path


def engine_ref(path):
    return f"engine:{path}#{hashlib.sha256(path.read_bytes()).hexdigest()}"


def drive_to_done_engine(board_dir, tmp_path, row_id="r1"):
    """A row driven to done on a favorable engine verdict (real path)."""
    evaluation = write_evaluation(tmp_path)
    create_row(board_dir, row_id, claims=("C-1",))
    drive(board_dir, row_id, "planned", "ready", "in_progress", "in_review")
    ref = engine_ref(evaluation)
    append(
        board_dir,
        caller(
            f"{row_id}-attach", "verdict_attached", row_id, {"verdict_ref": ref}, actor="reviewer-1"
        ),
    )
    append(
        board_dir,
        caller(
            f"{row_id}-done",
            "row_update",
            row_id,
            {"changes": {"status": "done"}, "verdict_ref": ref},
            actor="reviewer-1",
        ),
    )
    return evaluation, ref


# ------------------------------------------------------------------ KB-2


def test_kb2_passes_a_clean_board(tmp_path):
    board_dir = make_board(tmp_path)
    drive_to_done_engine(board_dir, tmp_path)
    report = audits.audit_kb2(board_dir)
    assert report["ok"] and report["findings"] == []
    assert len(report["checked"]) == 1
    assert report["checked"][0]["outcome"] == "favorable"
    lines = (board_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert report["audited_through_index"] == len([ln for ln in lines if ln.strip()])
    assert report["audited_through_head"] == fold.log_head_hash(board_dir)


def test_kb2_catches_a_verdict_record_swapped_after_citation(tmp_path):
    board_dir = make_board(tmp_path)
    evaluation, _ref = drive_to_done_engine(board_dir, tmp_path)
    # The record the done row cites is replaced after citation.
    evaluation.write_text(
        json.dumps(
            {
                "verdicts": [
                    {"id": "C-1", "verdict": "verified"},
                    {"id": "C-2", "verdict": "verified"},
                ]
            }
        ),
        encoding="utf-8",
    )
    report = audits.audit_kb2(board_dir)
    assert not report["ok"]
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert finding["kind"] == "done_without_favorable_record"
    assert finding["outcome"] == "unresolvable" and finding["row"] == "r1"


def test_kb2_catches_a_record_that_resolves_but_is_no_longer_favorable(tmp_path):
    board_dir = make_board(tmp_path)
    ci_dir = tmp_path / "ci"
    ci_dir.mkdir()
    run = {"databaseId": 777, "conclusion": "success", "headSha": HEAD_SHA}
    (ci_dir / "777.json").write_text(json.dumps(run), encoding="utf-8")
    create_row(board_dir, "r1")
    drive(board_dir, "r1", "planned", "ready", "in_progress", "in_review")
    ref = f"ci:777#{HEAD_SHA}"
    context = {"ci_records_dir": str(ci_dir)}
    append(
        board_dir,
        caller("r1-attach", "verdict_attached", "r1", {"verdict_ref": ref}, actor="reviewer-1"),
        verdict_context=context,
    )
    append(
        board_dir,
        caller(
            "r1-done",
            "row_update",
            "r1",
            {"changes": {"status": "done"}, "verdict_ref": ref},
            actor="reviewer-1",
        ),
    )
    assert audits.audit_kb2(board_dir, ci_records_dir=ci_dir)["ok"]
    # The run record is later corrected: same head SHA, failed conclusion.
    run["conclusion"] = "failure"
    (ci_dir / "777.json").write_text(json.dumps(run), encoding="utf-8")
    report = audits.audit_kb2(board_dir, ci_records_dir=ci_dir)
    assert not report["ok"]
    assert report["findings"][0]["outcome"] == "unfavorable"


def test_kb2_gatekeeper_citation_binds_the_payload_exit_record_only(tmp_path):
    board_dir = make_board(tmp_path)
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    record = {
        "id": "job-1",
        "state": "completed",
        "run_conclusion": "success",
        "markers": ["PAYLOAD_EXIT=0"],
        "log_tail": [],
    }
    (queue_dir / "job-1.json").write_text(json.dumps(record), encoding="utf-8")
    extracted = {"job_id": "job-1", "payload_exit_code": 0}
    digest = hashlib.sha256(canonical.canonical_bytes(extracted)).hexdigest()
    ref = f"gatekeeper:job-1#{digest}"
    create_row(board_dir, "r1")
    drive(board_dir, "r1", "planned", "ready", "in_progress", "in_review")
    context = {"gatekeeper_queue_dir": str(queue_dir)}
    append(
        board_dir,
        caller("r1-attach", "verdict_attached", "r1", {"verdict_ref": ref}, actor="reviewer-1"),
        verdict_context=context,
    )
    append(
        board_dir,
        caller(
            "r1-done",
            "row_update",
            "r1",
            {"changes": {"status": "done"}, "verdict_ref": ref},
            actor="reviewer-1",
        ),
    )
    assert audits.audit_kb2(board_dir, gatekeeper_queue_dir=queue_dir)["ok"]
    # An unrelated field changes: the citation binds the payload exit
    # record, not the whole file, so the audit still passes.
    record["operator_note"] = "re-filed"
    (queue_dir / "job-1.json").write_text(json.dumps(record), encoding="utf-8")
    assert audits.audit_kb2(board_dir, gatekeeper_queue_dir=queue_dir)["ok"]
    # The payload exit record itself changes: the citation no longer
    # resolves, and the audit fires.
    record["markers"] = ["PAYLOAD_EXIT=2"]
    (queue_dir / "job-1.json").write_text(json.dumps(record), encoding="utf-8")
    report = audits.audit_kb2(board_dir, gatekeeper_queue_dir=queue_dir)
    assert not report["ok"]
    assert report["findings"][0]["outcome"] == "unresolvable"


def test_kb2_since_index_scopes_the_audit(tmp_path):
    board_dir = make_board(tmp_path)
    evaluation, _ref = drive_to_done_engine(board_dir, tmp_path)
    first = audits.audit_kb2(board_dir)
    assert first["ok"]
    evaluation.write_text(json.dumps({"verdicts": []}), encoding="utf-8")
    # The swap is visible to a full audit but outside a resumed one.
    assert not audits.audit_kb2(board_dir)["ok"]
    resumed = audits.audit_kb2(board_dir, since_index=first["audited_through_index"])
    assert resumed["ok"] and resumed["checked"] == []


def test_kb2_fails_closed_without_a_board(tmp_path):
    report = audits.audit_kb2(tmp_path / "nope")
    assert not report["ok"] and report["findings"][0]["kind"] == "board_unreadable"


def test_kb2_fails_closed_on_a_broken_chain(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    lines = (board_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[-1])
    tampered["payload"] = {"row_id": "r1", "task_ref": "forged"}
    lines[-1] = json.dumps(tampered)
    (board_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = audits.audit_kb2(board_dir)
    assert not report["ok"] and report["findings"][0]["kind"] == "fold_refusal"


# ------------------------------------------------------------------ KB-5


def test_kb5_passes_a_generated_view(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    view.generate_view(board_dir)
    report = audits.audit_kb5(board_dir)
    assert report["ok"] and report["in_flight_events"] == 0


def test_kb5_in_flight_events_explain_themselves(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    view.generate_view(board_dir)
    create_row(board_dir, "r2")  # appended after the view was generated
    report = audits.audit_kb5(board_dir)
    assert report["ok"] and report["in_flight_events"] == 1


def test_kb5_catches_a_hand_edited_view(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    path = view.generate_view(board_dir)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("proposed", "done"), encoding="utf-8")
    report = audits.audit_kb5(board_dir)
    assert not report["ok"] and report["findings"][0]["kind"] == "view_divergence"


def test_kb5_catches_a_view_from_another_log(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    path = view.generate_view(board_dir)
    text = path.read_text(encoding="utf-8")
    forged = text.replace(fold.log_head_hash(board_dir), "f" * 64)
    path.write_text(forged, encoding="utf-8")
    report = audits.audit_kb5(board_dir)
    assert not report["ok"] and report["findings"][0]["kind"] == "view_head_not_in_log"


def test_kb5_fails_closed_without_a_view(tmp_path):
    board_dir = make_board(tmp_path)
    report = audits.audit_kb5(board_dir)
    assert not report["ok"] and report["findings"][0]["kind"] == "view_missing"


# ------------------------------------------------------------------ KB-6


def test_kb6_passes_a_clean_board(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    drive(board_dir, "r1", "planned")
    report = audits.audit_kb6(board_dir)
    assert report["ok"] and report["fold_head"] == report["served_head"]


def test_kb6_catches_a_served_state_that_diverges_from_the_fold(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    # Rewrite the served state (a row's status flipped) with its
    # read-back hash recomputed, so only the fold comparison catches it.
    stored = state.read_state(board_dir)
    body = {k: v for k, v in stored.items() if k != "state_hash"}
    body["rows"]["r1"]["status"] = "done"
    forged = dict(body)
    forged["state_hash"] = canonical.state_hash(body)
    (board_dir / "state.json").write_bytes(canonical.canonical_line(forged))
    report = audits.audit_kb6(board_dir)
    assert not report["ok"]
    assert report["findings"][0]["kind"] == "state_divergence"
    assert report["findings"][0]["severity"] == "highest"


def test_kb6_fails_closed_without_a_state_file(tmp_path):
    board_dir = make_board(tmp_path)
    (board_dir / "state.json").unlink()
    report = audits.audit_kb6(board_dir)
    assert not report["ok"] and report["findings"][0]["kind"] == "state_missing"


def test_kb6_fails_closed_on_a_torn_tail(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1")
    with open(board_dir / "events.jsonl", "ab") as handle:
        handle.write(b'{"event_id": "torn", "payl')
    report = audits.audit_kb6(board_dir)
    assert not report["ok"]
    assert any(f["kind"] == "torn_tail" for f in report["findings"])


# ------------------------------------------------------------ trace audit


def write_artifact(tmp_path, lines):
    path = tmp_path / "tasks-artifact.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def trace_board(tmp_path, spec_hash):
    genesis = dict(GENESIS)
    genesis["spec_hash"] = spec_hash
    genesis["spec_ref"] = "tasks-artifact.md"
    return make_board(tmp_path, genesis)


def test_trace_passes_rows_named_by_the_artifact(tmp_path):
    artifact, digest = write_artifact(tmp_path, ["- [ ] T-1 first task", "- [ ] T-2 second"])
    board_dir = trace_board(tmp_path, digest)
    create_row(board_dir, "r1", task_ref="T-1")
    create_row(board_dir, "r2", task_ref="T-2")
    report = audits.audit_trace(board_dir, artifact)
    assert report["ok"] and report["rows_checked"] == 2


def test_trace_catches_a_row_that_traces_to_nothing(tmp_path):
    artifact, digest = write_artifact(tmp_path, ["- [ ] T-1 first task"])
    board_dir = trace_board(tmp_path, digest)
    create_row(board_dir, "r1", task_ref="T-1")
    create_row(board_dir, "rx", task_ref="T-ghost")
    report = audits.audit_trace(board_dir, artifact)
    assert not report["ok"]
    assert [f["row"] for f in report["findings"]] == ["rx"]


def test_trace_follows_a_supersede_chain(tmp_path):
    artifact, digest = write_artifact(tmp_path, ["- [ ] T-1 first task"])
    board_dir = trace_board(tmp_path, digest)
    create_row(board_dir, "r1", task_ref="T-1")
    create_row(board_dir, "r2", task_ref="T-renamed")
    append(
        board_dir,
        caller(
            "r1-supersede",
            "row_update",
            "r1",
            {"changes": {"status": "superseded"}, "replaced_by": "r2"},
        ),
    )
    report = audits.audit_trace(board_dir, artifact)
    assert report["ok"]


def test_trace_fails_closed_on_the_wrong_artifact(tmp_path):
    _artifact, digest = write_artifact(tmp_path, ["- [ ] T-1 first task"])
    board_dir = trace_board(tmp_path, digest)
    create_row(board_dir, "r1", task_ref="T-1")
    other = tmp_path / "other.md"
    other.write_text("- [ ] T-1 first task, edited after the freeze\n", encoding="utf-8")
    report = audits.audit_trace(board_dir, other)
    assert not report["ok"] and report["findings"][0]["kind"] == "artifact_hash_mismatch"


def test_trace_fails_closed_on_a_missing_artifact(tmp_path):
    _artifact, digest = write_artifact(tmp_path, ["- [ ] T-1 first task"])
    board_dir = trace_board(tmp_path, digest)
    report = audits.audit_trace(board_dir, tmp_path / "gone.md")
    assert not report["ok"] and report["findings"][0]["kind"] == "artifact_unreadable"


# --------------------------------------------------------- boundary audit

REGISTRY = ["study-arm-a/tasks.json", "study-arm-b"]


def test_boundary_passes_a_clean_board(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1", task_ref="T-1")
    report = audits.audit_boundary([board_dir], REGISTRY)
    assert report["ok"] and not report["tripwire"]


def test_boundary_catches_a_row_ref_into_a_study_arm(tmp_path):
    board_dir = make_board(tmp_path)
    create_row(board_dir, "r1", task_ref="study-arm-a/tasks.json")
    report = audits.audit_boundary([board_dir], REGISTRY)
    assert not report["ok"] and report["tripwire"]
    finding = report["findings"][0]
    assert finding["kind"] == "row_ref_in_study_arm" and finding["row"] == "r1"


def test_boundary_catches_a_board_belonging_to_a_study_arm(tmp_path):
    genesis = dict(GENESIS)
    genesis["spec_ref"] = "study-arm-b/spec.md"
    board_dir = make_board(tmp_path, genesis)
    report = audits.audit_boundary([board_dir], REGISTRY)
    assert not report["ok"] and report["tripwire"]
    assert report["findings"][0]["kind"] == "board_belongs_to_study_arm"


def test_boundary_fails_closed_on_an_empty_registry(tmp_path):
    board_dir = make_board(tmp_path)
    report = audits.audit_boundary([board_dir], [])
    assert not report["ok"] and report["findings"][0]["kind"] == "registry_empty"


def test_boundary_fails_closed_on_an_unreadable_board(tmp_path):
    report = audits.audit_boundary([tmp_path / "nope"], REGISTRY)
    assert not report["ok"] and not report["ok"]


# ------------------------------------------------------------ drift check


def test_drift_schema_precheck_passes():
    report = audits.audit_kernel_drift()
    assert report["ok"] and report["scope"] == "schema_only"
    assert report["canonical_hash"] == kernel.kernel_definitions_hash()


def test_drift_full_passes_on_the_pinned_definitions(tmp_path):
    shipped = tmp_path / "kernel-definitions.json"
    shipped.write_text(json.dumps(kernel.kernel_definitions()), encoding="utf-8")
    report = audits.audit_kernel_drift(shipped)
    assert report["ok"] and report["scope"] == "full"


def test_drift_catches_perturbed_shipped_definitions(tmp_path):
    definitions = kernel.kernel_definitions()
    definitions["transitions"][0]["guard"] = "a quietly weakened guard"
    shipped = tmp_path / "kernel-definitions.json"
    shipped.write_text(json.dumps(definitions), encoding="utf-8")
    report = audits.audit_kernel_drift(shipped)
    assert not report["ok"] and report["findings"][0]["kind"] == "kernel_drift"


def test_drift_fails_closed_on_a_missing_definitions_file(tmp_path):
    report = audits.audit_kernel_drift(tmp_path / "gone.json")
    assert not report["ok"]
    assert report["findings"][0]["kind"] == "extension_definitions_unreadable"
