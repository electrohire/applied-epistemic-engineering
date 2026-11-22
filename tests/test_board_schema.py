"""T002: the pinned schema and its validator (spec AB-001 3.1)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import canonical, validate  # noqa: E402

SCHEMA = json.loads((ROOT / "board" / "schema.json").read_text(encoding="utf-8"))


def genesis_payload() -> dict:
    return {
        "board_id": "board-a",
        "program": "ninety-day",
        "spec_ref": "AB-001",
        "spec_hash": "a" * 64,
        "wip_limit": 4,
        "keeper_cadence": "30m",
        "detector_chat": "detector",
        "escalation_target_2": "owner",
    }


def caller_event(**overrides) -> dict:
    event = {
        "event_id": "evt-1",
        "board_id": "board-a",
        "row_id": None,
        "actor": "planner",
        "kind": "genesis",
        "payload": genesis_payload(),
    }
    event.update(overrides)
    return event


def test_schema_file_is_pinned_and_parseable():
    assert SCHEMA["schema"] == "aee-board/1"
    assert set(SCHEMA["event_fields"]) == {
        "event_id",
        "board_id",
        "row_id",
        "actor",
        "writer",
        "kind",
        "payload",
        "prev_hash",
        "event_hash",
    }
    assert "amendment_seq" in SCHEMA["row_fields"]
    assert SCHEMA["row_fields"]["amendment_seq"]["derived"] is True
    for field in ("wip_limit", "keeper_cadence", "detector_chat", "escalation_target_2"):
        assert field in SCHEMA["genesis_fields"]


def test_valid_genesis_event_accepted():
    assert validate.validate_caller_event(caller_event()) == []


def test_missing_field_refused_by_name():
    event = caller_event()
    del event["actor"]
    problems = validate.validate_caller_event(event)
    assert any("actor" in p and "missing" in p for p in problems)


def test_caller_supplied_writer_refused_by_name():
    problems = validate.validate_caller_event(caller_event(writer="mallory"))
    assert any("writer" in p and "append service" in p for p in problems)


def test_caller_supplied_hashes_refused():
    problems = validate.validate_caller_event(caller_event(prev_hash="0" * 64))
    assert any("prev_hash" in p for p in problems)


def test_amendment_seq_in_payload_refused_by_name():
    event = caller_event(kind="amendment", payload={"amendment_seq": 3})
    problems = validate.validate_caller_event(event)
    assert any("amendment_seq" in p and "fold-derived" in p for p in problems)


def test_genesis_missing_wip_limit_refused_by_name():
    payload = genesis_payload()
    del payload["wip_limit"]
    problems = validate.validate_caller_event(caller_event(payload=payload))
    assert any("wip_limit" in p for p in problems)


def test_genesis_wrong_type_refused():
    payload = genesis_payload()
    payload["wip_limit"] = "four"
    problems = validate.validate_caller_event(caller_event(payload=payload))
    assert any("wip_limit" in p and "integer" in p for p in problems)


def test_row_creation_valid_and_refusals():
    payload = {"row_id": "r1", "task_ref": "T001", "status": "proposed", "depends_on": []}
    event = caller_event(kind="row_created", row_id="r1", payload=payload)
    assert validate.validate_caller_event(event) == []

    bad_status = dict(payload, status="bogus")
    problems = validate.validate_caller_event(
        caller_event(kind="row_created", row_id="r1", payload=bad_status)
    )
    assert any("status" in p for p in problems)

    derived = dict(payload, amendment_seq=0)
    problems = validate.validate_caller_event(
        caller_event(kind="row_created", row_id="r1", payload=derived)
    )
    assert any("amendment_seq" in p for p in problems)


def test_wait_object_checked():
    payload = {
        "row_id": "r1",
        "task_ref": "T001",
        "wait": {"wait_kind": "smoke_signal"},
    }
    problems = validate.validate_caller_event(
        caller_event(kind="row_created", row_id="r1", payload=payload)
    )
    assert any("wait_kind" in p for p in problems)


def test_stored_event_validation():
    event = caller_event()
    event["writer"] = "board-append@host:board-a"
    event["prev_hash"] = canonical.GENESIS_PREV_HASH
    event["event_hash"] = canonical.event_hash(event)
    assert validate.validate_stored_event(event) == []
    del event["event_hash"]
    assert any("event_hash" in p for p in validate.validate_stored_event(event))


def test_folded_row_validation():
    row = {
        "row_id": "r1",
        "board_id": "board-a",
        "program": "ninety-day",
        "spec_ref": "AB-001",
        "spec_hash": "a" * 64,
        "task_ref": "T001",
        "status": "proposed",
        "depends_on": [],
        "assignee_kind": None,
        "assignee_instance": None,
        "claim_ids": [],
        "execution_state": "none",
        "verdict_ref": None,
        "wait": None,
        "created_event": "evt-2",
        "last_event": "evt-2",
        "amendment_seq": 0,
    }
    assert validate.validate_row(row) == []
    row["execution_state"] = "done"  # transport state is never completion
    assert any("execution_state" in p for p in validate.validate_row(row))
