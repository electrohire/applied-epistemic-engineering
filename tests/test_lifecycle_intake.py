"""Lifecycle intake: valid fixtures pass; defective records refuse loudly."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
INTAKE_PATH = ROOT / "lifecycle" / "intake.py"
FIXTURES = ROOT / "lifecycle" / "fixtures.jsonl"


def load_intake() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lifecycle_intake", INTAKE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


intake = load_intake()


def fixture_records() -> list[dict]:
    return [json.loads(line) for line in FIXTURES.read_text(encoding="utf-8").splitlines()]


def rejection_text(records: list[dict]) -> str:
    _accepted, rejected = intake.validate_records(records, intake.load_schema())
    return "\n".join(rejected)


def test_lifecycle_fixtures_round_trip_through_cli() -> None:
    proc = subprocess.run(
        [sys.executable, str(INTAKE_PATH), str(FIXTURES)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "LIFECYCLE_RESULT accepted=3 rejected=0" in proc.stdout


def test_missing_provenance_is_refused() -> None:
    records = fixture_records()
    records[0]["capture_source"] = ""
    text = rejection_text(records)
    assert "DEL-FIXTURE-001: REJECT" in text
    assert "provenance" in text


def test_unpriced_authored_verifier_is_refused() -> None:
    records = fixture_records()
    records[0]["verifier_provenance"] = "authored_for_task"
    records[0]["verifier_production_cost"] = None
    text = rejection_text(records)
    assert "unpriced" in text
    assert "DEL-FIXTURE-001: REJECT" in text


def test_unknown_enum_is_refused() -> None:
    records = fixture_records()
    records[1]["origin_phase"] = "WHENEVER"
    text = rejection_text(records)
    assert "RWK-FIXTURE-001: REJECT" in text
    assert "unknown enum" in text


def test_append_refusal_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / "records.jsonl"
    target.write_text(FIXTURES.read_text(encoding="utf-8"), encoding="utf-8")
    before = target.read_bytes()
    bad = copy.deepcopy(fixture_records()[1])
    bad["rework_id"] = "RWK-FIXTURE-002"
    bad["delivery_id"] = "DEL-MISSING"
    _accepted, rejected = intake.append_record(target, bad)
    assert rejected
    assert target.read_bytes() == before


def test_escape_discovery_route_is_in_schema() -> None:
    schema = intake.load_schema()
    fields = schema["record_types"]["escape"]["fields"]
    route = next(field for field in fields if field["name"] == "discovery_route")
    assert route["enum"] == ["routine_surveillance", "study_audit"]
