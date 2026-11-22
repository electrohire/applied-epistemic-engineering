"""Phase 3 records: the record resolver and falsifier evaluation.

Tested against fixtures in the real record formats (the gatekeeper
queue records and CI run records of the verdict fixtures) and
against records written in those formats here: a gatekeeper ledger
line, a mail-arrival record file, the board's own folded state, and
the clock.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import records  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "board"
QUEUE_DIR = FIXTURES / "gatekeeper-queue"
CI_DIR = FIXTURES / "ci-runs"

T0 = datetime(2026, 11, 21, 12, 0, 0, tzinfo=UTC)


def _wait(reference, field, **extra):
    wait = {
        "wait_kind": "named_event",
        "wake_falsifier": {"record": reference, "field": field, **extra},
        "sweep_deadline": "2026-11-21T14:00:00Z",
        "escalation": "owner",
    }
    return wait


def test_parse_cadence():
    assert records.parse_cadence("30m").total_seconds() == 1800
    assert records.parse_cadence("2h").total_seconds() == 7200
    assert records.parse_cadence("1d").total_seconds() == 86400
    assert records.parse_cadence("every half hour") is None
    assert records.parse_cadence(30) is None
    assert records.parse_cadence("") is None


def test_timestamp_roundtrip():
    parsed = records.parse_timestamp("2026-11-21T12:00:00Z")
    assert parsed == T0
    assert records.format_timestamp(parsed) == "2026-11-21T12:00:00Z"
    assert records.parse_timestamp("not a time") is None
    assert records.parse_timestamp(None) is None


def test_gatekeeper_falsifier_on_payload_exit(tmp_path):
    outcome = records.evaluate_falsifier(
        _wait("gatekeeper:job-payload-pass", "payload_exit_code", equals=0),
        gatekeeper_queue_dir=QUEUE_DIR,
    )
    assert outcome.outcome == "holds"
    assert outcome.citation["value"] == 0 and outcome.citation["record_hash"]


def test_gatekeeper_falsifier_on_state_field():
    outcome = records.evaluate_falsifier(
        _wait("gatekeeper:job-payload-pass", "state", equals="completed"),
        gatekeeper_queue_dir=QUEUE_DIR,
    )
    assert outcome.outcome == "holds"


def test_gatekeeper_ledger_fallback(tmp_path):
    # The queue record is gone; the ledger line for the job is the record.
    ledger = tmp_path / "ledger.jsonl"
    queue_record = json.loads((QUEUE_DIR / "job-payload-pass.json").read_text())
    ledger.write_text(json.dumps(queue_record) + "\n", encoding="utf-8")
    outcome = records.evaluate_falsifier(
        _wait("gatekeeper:job-payload-pass", "payload_exit_code", equals=0),
        gatekeeper_queue_dir=tmp_path / "empty-queue",
        gatekeeper_ledger=ledger,
    )
    assert outcome.outcome == "holds" and "ledger" in outcome.detail


def test_ci_falsifier_equals_and_presence():
    holds = records.evaluate_falsifier(
        _wait("ci:44981799043", "conclusion", equals="success"), ci_records_dir=CI_DIR
    )
    assert holds.outcome == "holds"
    failed = records.evaluate_falsifier(
        _wait("ci:44981799044", "conclusion", equals="success"), ci_records_dir=CI_DIR
    )
    assert failed.outcome == "not_yet" and failed.citation["value"] == "failure"
    # Presence semantics: any conclusion ends the wait.
    present = records.evaluate_falsifier(
        _wait("ci:44981799044", "conclusion"), ci_records_dir=CI_DIR
    )
    assert present.outcome == "holds"


def test_board_falsifier_reads_the_folded_row():
    state = {
        "head_hash": "h" * 64,
        "rows": {"dep": {"row_id": "dep", "status": "done"}},
    }
    outcome = records.evaluate_falsifier(
        _wait("board:dep", "status", equals="done"), board_state=state
    )
    assert outcome.outcome == "holds" and outcome.citation["record_hash"] == "h" * 64
    state["rows"]["dep"]["status"] = "in_progress"
    outcome = records.evaluate_falsifier(
        _wait("board:dep", "status", equals="done"), board_state=state
    )
    assert outcome.outcome == "not_yet"


def test_file_falsifier_for_a_named_arrival(tmp_path):
    arrival = tmp_path / "mail-arrival.json"
    arrival.write_text(json.dumps({"arrived": True, "subject": "packet"}), encoding="utf-8")
    outcome = records.evaluate_falsifier(_wait(f"file:{arrival}", "arrived", equals=True))
    assert outcome.outcome == "holds" and outcome.citation["record_hash"]


def test_clock_falsifier_for_an_armed_moment():
    wait = _wait("clock:now", "now", equals="2026-11-21T13:00:00Z")
    before = records.evaluate_falsifier(wait, now=T0)
    assert before.outcome == "not_yet"
    after = records.evaluate_falsifier(wait, now=datetime(2026, 11, 21, 13, 0, 1, tzinfo=UTC))
    assert after.outcome == "holds"


def test_unresolvable_is_not_a_silent_not_yet():
    missing = records.evaluate_falsifier(
        _wait("ci:99999999999", "conclusion"), ci_records_dir=CI_DIR
    )
    assert missing.outcome == "unresolvable"
    no_source = records.evaluate_falsifier(_wait("gatekeeper:job-payload-pass", "state"))
    assert no_source.outcome == "unresolvable"
    malformed = records.evaluate_falsifier(_wait("bogus", "state"))
    assert malformed.outcome == "unresolvable"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
