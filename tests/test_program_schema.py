"""Amendment 3: the pinned schema, proposition fingerprints, and
published coverage counts in the program-ledger intake."""

import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "program-ledger"

_spec = importlib.util.spec_from_file_location("ledger_intake", LEDGER / "intake.py")
assert _spec is not None and _spec.loader is not None
intake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(intake)

BASE_CLAIM = {
    "id": "TST-001",
    "text": "A control claim that satisfies every rule.",
    "kind": "hypothesis",
    "status": "draft",
    "stage": "created",
    "domain": "test-domain",
    "source_ref": "test-fixture",
    "falsification_tests": ["a test that would refute it"],
    "boundary": ["this does not establish anything beyond the fixture"],
    "evidence": [
        {
            "ref": "fixture-record",
            "kind": "observed",
            "direction": "supports",
            "source_quality": "test",
            "description": "the fixture itself",
        }
    ],
    "metadata": {"date": "2026-11-01", "components": ["engine"]},
}


def stage_ledger(tmp_path: Path, claims: list[dict], with_schema: bool = True) -> Path:
    if with_schema:
        shutil.copy(LEDGER / "schema.json", tmp_path / "schema.json")
    claims_path = tmp_path / "claims.jsonl"
    claims_path.write_text(
        "".join(json.dumps(c) + "\n" for c in claims), encoding="utf-8", newline="\n"
    )
    shutil.copy(LEDGER / "components.json", tmp_path / "components.json")
    return claims_path


def validate(tmp_path: Path, claims: list[dict], with_schema: bool = True):
    claims_path = stage_ledger(tmp_path, claims, with_schema)
    return intake.validate(claims_path, tmp_path / "components.json")


def test_control_claim_accepted(tmp_path: Path) -> None:
    accepted, rejected = validate(tmp_path, [dict(BASE_CLAIM)])
    assert rejected == [], rejected
    assert len(accepted) == 1


def test_missing_required_field_is_refused_by_name(tmp_path: Path) -> None:
    claim = dict(BASE_CLAIM)
    del claim["domain"]
    _accepted, rejected = validate(tmp_path, [claim])
    assert any("R0 schema: missing required field domain" in r for r in rejected), rejected


def test_wrong_type_is_refused_by_name(tmp_path: Path) -> None:
    claim = dict(BASE_CLAIM)
    claim["falsification_tests"] = "not a list"
    _accepted, rejected = validate(tmp_path, [claim])
    assert any("R0 schema: field falsification_tests" in r for r in rejected), rejected


def test_evidence_item_missing_key_is_refused(tmp_path: Path) -> None:
    claim = dict(BASE_CLAIM)
    claim["evidence"] = [{"kind": "observed"}]
    _accepted, rejected = validate(tmp_path, [claim])
    assert any("R0 schema: field evidence item missing key" in r for r in rejected), rejected


def test_fingerprint_collision_is_refused(tmp_path: Path) -> None:
    first = dict(BASE_CLAIM)
    second = dict(BASE_CLAIM)
    second["id"] = "TST-002"
    second["text"] = "  a CONTROL claim that satisfies   every rule. "
    accepted, rejected = validate(tmp_path, [first, second])
    assert accepted == [], (accepted, rejected)
    assert sum("R9 fingerprint collision" in r for r in rejected) == 2, rejected


def test_distinct_propositions_do_not_collide(tmp_path: Path) -> None:
    first = dict(BASE_CLAIM)
    second = dict(BASE_CLAIM)
    second["id"] = "TST-002"
    second["text"] = "A different claim entirely, about something else."
    accepted, rejected = validate(tmp_path, [first, second])
    assert rejected == [], rejected
    assert len(accepted) == 2


def test_missing_schema_is_a_loud_refusal(tmp_path: Path) -> None:
    _accepted, rejected = validate(tmp_path, [dict(BASE_CLAIM)], with_schema=False)
    assert any(r.startswith("SCHEMA: REJECT") for r in rejected), rejected


def test_shipped_ledger_publishes_full_coverage(capsys) -> None:  # type: ignore[no-untyped-def]
    accepted, rejected = intake.validate(LEDGER / "claims.jsonl", LEDGER / "components.json")
    out = capsys.readouterr().out
    assert rejected == [], rejected
    assert len(accepted) == 22
    assert "INTAKE_COVERAGE falsifier=22/22 boundary=22/22" in out
    assert "source_ref=22/22 evidence=22/22" in out
