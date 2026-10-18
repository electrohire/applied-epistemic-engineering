"""Synthetic host-policy fixtures never imply an actual maintainer approval."""

import sys
from datetime import UTC, datetime

import pytest

from aee.execution_scope import snapshot_scope
from aee.ledger import HashChainLedger
from aee.verification_approval import (
    VerificationMethodApproval,
    append_method_approval,
    check_method_approval,
)


@pytest.fixture
def candidate(tmp_path):
    (tmp_path / "requirement.md").write_text("R01: inspect the documented workflow")
    (tmp_path / "receipt.txt").write_text("Synthetic approval fixture; not a real human approval.")
    scope = snapshot_scope(tmp_path, ["requirement.md", "receipt.txt"], repository_id="example")
    value = dict(
        schema_version="1.0",
        decision="approve_method",
        method_id="MANUAL-01",
        method_description="Inspect the workflow against the stated requirement.",
        requirement_ids=["R01"],
        approver_label="synthetic maintainer label",
        approved_at=datetime.now(UTC).isoformat(),
        receipt_path="receipt.txt",
        scope=scope.to_dict(),
    )
    return tmp_path, VerificationMethodApproval.from_dict(value)


def check(candidate, trusted=False, repository_id="example"):
    root, record = candidate
    return check_method_approval(
        record,
        root,
        repository_id=repository_id,
        trusted_human_approval_digests=[record.digest] if trusted else [],
    )


def test_record_and_human_name_do_not_grant_authority(candidate, monkeypatch):
    record = candidate[1]
    assert VerificationMethodApproval.from_bytes(record.canonical).digest == record.digest
    assert check(candidate)["approval_status"] == "unverified"
    assert check(candidate)["outcome"] == "gather_evidence"
    monkeypatch.setattr(
        "subprocess.Popen", lambda *a, **k: pytest.fail("approval ingest executed a command")
    )
    result = check(candidate, trusted=True)
    assert result["outcome"] == "pass"
    assert result["approval_status"] == "method_approved"
    assert result["verification_status"] == "unassessed"
    assert "not execution" in result["scope"]
    assert result["identity_proof"] == "not_established_by_record"
    mutable = record.to_dict()
    mutable["requirement_ids"].append("R02")
    assert record.to_dict()["requirement_ids"] == ["R01"]


@pytest.mark.parametrize("change", ["requirement", "receipt", "missing", "repository", "root"])
def test_approval_is_scoped_and_can_be_revoked(candidate, change):
    root, _ = candidate
    repository = "example"
    if change == "requirement":
        (root / "requirement.md").write_text("changed")
    elif change == "receipt":
        (root / "receipt.txt").write_text("agent wrote an approval")
    elif change == "missing":
        (root / "receipt.txt").unlink()
    elif change == "repository":
        repository = "other"
    else:
        candidate = (root / "missing-root", candidate[1])
    assert check(candidate, trusted=True, repository_id=repository)["outcome"] == "gather_evidence"


@pytest.mark.parametrize(
    "key,value",
    [
        ("schema_version", "future"),
        ("decision", "verification_passed"),
        ("method_id", ""),
        ("method_id", "manual-01"),
        ("method_description", " "),
        ("approver_label", True),
        ("approved_at", "yesterday"),
        ("approved_at", "2026-10-18T00:00:00"),
        ("receipt_path", "../receipt.txt"),
        ("receipt_path", "./receipt.txt"),
        ("receipt_path", "unscoped.txt"),
        ("requirement_ids", []),
        ("requirement_ids", ["R01", "R01"]),
        ("requirement_ids", ["r01"]),
        ("requirement_ids", "R01"),
        ("requirement_ids", [None]),
    ],
)
def test_strict_record_boundary(candidate, key, value):
    record = candidate[1].to_dict()
    record[key] = value
    with pytest.raises(ValueError):
        VerificationMethodApproval.from_dict(record)


def test_unknown_approval_boolean_and_bad_json_refused(candidate, monkeypatch):
    from aee import verification_approval as module

    value = candidate[1].to_dict()
    value["human_approved"] = True
    with pytest.raises(ValueError):
        VerificationMethodApproval.from_dict(value)
    for data in [b"[]", b'{"x":1,"x":2}', b"null", b"\xff", b"[" * 2000 + b"0" + b"]" * 2000]:
        with pytest.raises(ValueError):
            VerificationMethodApproval.from_bytes(data)
    monkeypatch.setattr(module, "MAX_APPROVAL_BYTES", 1)
    with pytest.raises(ValueError):
        VerificationMethodApproval.from_bytes(candidate[1].canonical)
    with pytest.raises(ValueError):
        VerificationMethodApproval.from_dict(candidate[1].to_dict())


@pytest.mark.parametrize("pins", ["0" * 64, ["bad"], [None], True])
def test_host_policy_is_a_separate_validated_input(candidate, pins):
    with pytest.raises(ValueError):
        check_method_approval(
            candidate[1], candidate[0], repository_id="example", trusted_human_approval_digests=pins
        )


def test_anchored_ledger_retains_statement_without_promoting_it(candidate):
    root, record = candidate
    ledger = HashChainLedger(root / "ledger.jsonl")
    first = append_method_approval(record, ledger, actor="synthetic fixture")
    second = append_method_approval(record, ledger)
    assert first["payload"]["approval_trust"] == "unverified"
    assert first["payload"]["record_sha256"] == second["payload"]["record_sha256"]
    assert ledger.verify(require_anchor=True).valid
    assert check(candidate)["outcome"] == "gather_evidence"
    for actor in ["", True, "x" * 257]:
        with pytest.raises(ValueError):
            append_method_approval(record, ledger, actor=actor)
    data = ledger.path.read_text()
    ledger.path.write_text(data.replace("synthetic fixture", "changed actor"))
    with pytest.raises(ValueError):
        append_method_approval(record, ledger)


def test_excessive_json_nesting_is_an_input_error_not_a_parser_crash():
    depth = max(10000, sys.getrecursionlimit() * 4)
    with pytest.raises(ValueError, match="nesting"):
        VerificationMethodApproval.from_bytes(b"[" * depth + b"0" + b"]" * depth)
