import json

import pytest

from aee import HashChainLedger


def test_empty_ledger_is_valid(tmp_path) -> None:
    result = HashChainLedger(tmp_path / "ledger.jsonl").verify()
    assert result.valid
    assert result.entries == 0


def test_append_and_verify(tmp_path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    first = ledger.append("claim", {"id": "A"})
    second = ledger.append("decision", {"id": "D"})
    result = ledger.verify()
    assert result.valid
    assert result.entries == 2
    assert second["previous_hash"] == first["entry_hash"]
    assert result.head_hash == second["entry_hash"]


def test_tampering_detected(tmp_path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = HashChainLedger(path)
    ledger.append("claim", {"id": "A"})
    value = json.loads(path.read_text())
    value["payload"]["id"] = "TAMPERED"
    path.write_text(json.dumps(value) + "\n")
    result = ledger.verify()
    assert not result.valid
    assert "entry_hash mismatch" in result.errors[0]


def test_append_refuses_invalid_chain(tmp_path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text("not json\n")
    with pytest.raises(ValueError, match="invalid ledger"):
        HashChainLedger(path).append("claim", {"id": "A"})
