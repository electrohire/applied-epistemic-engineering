"""Verified-write retrofit tests (fleet standard, 2026-10-28).

The fault checks simulate the VM's write pathologies in-process: a
local write attempt that silently lands torn bytes, and an append
that lands only half its line. The verified writers must either land
the exact bytes (via the fresh-subprocess fallback) or fail loudly
with the file rolled back — never report success over bad bytes.
"""

import hashlib

import pytest

from aee import HashChainLedger, verified_write
from aee.verified_write import (
    SafeWriteError,
    append_bytes_verified,
    write_bytes_verified,
    write_text_verified,
)


def test_write_round_trip(tmp_path) -> None:
    target = tmp_path / "record.json"
    result = write_text_verified(target, '{"a": 1}\n')
    assert result["ok"] is True
    data = target.read_bytes()
    assert data == b'{"a": 1}\n'
    assert result["sha256"] == hashlib.sha256(data).hexdigest()


def test_write_refuses_empty(tmp_path) -> None:
    with pytest.raises(SafeWriteError):
        write_bytes_verified(tmp_path / "empty.bin", b"")
    assert not (tmp_path / "empty.bin").exists()


def test_write_recovers_via_child_when_local_attempts_fail(tmp_path, monkeypatch) -> None:
    # Every in-process attempt "fails" (an EPERM wave / tainted
    # process); the fresh subprocess must still land the exact bytes.
    monkeypatch.setattr(verified_write, "try_write_once", lambda path, data: False)
    target = tmp_path / "record.json"
    result = write_bytes_verified(target, b'{"via": "child"}\n')
    assert result["via"].startswith("child-")
    assert target.read_bytes() == b'{"via": "child"}\n'


def test_write_raises_when_every_path_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(verified_write, "try_write_once", lambda path, data: False)
    monkeypatch.setattr(verified_write, "_try_child", lambda path, data: False)
    with pytest.raises(SafeWriteError):
        write_bytes_verified(tmp_path / "record.json", b"payload\n", retries=1)
    assert not (tmp_path / "record.json").exists()


def test_append_round_trip(tmp_path) -> None:
    target = tmp_path / "stream.jsonl"
    append_bytes_verified(target, b'{"n": 1}\n')
    append_bytes_verified(target, b'{"n": 2}\n')
    assert target.read_bytes() == b'{"n": 1}\n{"n": 2}\n'


def test_append_rolls_back_a_torn_write(tmp_path, monkeypatch) -> None:
    target = tmp_path / "stream.jsonl"
    original = b'{"n": 1}\n'
    target.write_bytes(original)

    def torn_append(path, data):
        with path.open("ab") as handle:
            handle.write(data[: len(data) // 2])
            handle.flush()

    monkeypatch.setattr(verified_write, "_append_once", torn_append)
    with pytest.raises(SafeWriteError):
        append_bytes_verified(target, b'{"n": 2}\n')
    assert target.read_bytes() == original


def test_ledger_append_survives_torn_write_fault(tmp_path, monkeypatch) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = HashChainLedger(path)
    ledger.append("claim", {"id": "A"})
    ledger.append("decision", {"id": "D"})
    before = path.read_bytes()

    def torn_append(path_, data):
        with path_.open("ab") as handle:
            handle.write(data[:10])
            handle.flush()

    monkeypatch.setattr(verified_write, "_append_once", torn_append)
    with pytest.raises(SafeWriteError):
        ledger.append("claim", {"id": "B"})
    # The failed append left no trace: the file is byte-identical and
    # the chain still verifies against its anchor.
    assert path.read_bytes() == before
    result = ledger.verify()
    assert result.valid
    assert result.entries == 2


def test_ledger_anchor_matches_disk_after_appends(tmp_path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = HashChainLedger(path)
    entry = ledger.append("claim", {"id": "A"})
    anchor = ledger._read_anchor(ledger.anchor_path)[0]
    assert anchor is not None
    assert anchor.entry_count == 1
    assert anchor.tip_hash == entry["entry_hash"]
