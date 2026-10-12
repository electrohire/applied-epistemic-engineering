"""Spec 003 FR-4 - ledger integrity and anchoring (T401-T407).

Inverts RT2 p01 (tail truncation), p02 (non-object/malformed lines),
and p03 §§A/B (Unicode line separators; same-size/same-mtime tip-cache
forgery), plus RT1 p2 §H (corrupt-ledger behaviour). The RT2 p14 held
tamper classes (middle edit/delete, reorder, insertion, genesis and
sequence tampering, mid-line truncation) are regression-tested here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from aee import HashChainLedger, LedgerAnchor
from aee.cli import main
from aee.ledger import _entry_hash


def _make_ledger(tmp_path: Path, count: int = 3) -> tuple[Path, HashChainLedger]:
    path = tmp_path / "ledger.jsonl"
    ledger = HashChainLedger(path)
    for index in range(count):
        ledger.append("evt", {"n": index})
    return path, ledger


def _anchor_path(path: Path) -> Path:
    return path.with_name(path.name + ".anchor.json")


def _physical_lines(path: Path) -> list[bytes]:
    data = path.read_bytes()
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    return lines


def _write_lines(path: Path, lines: list[bytes]) -> None:
    path.write_bytes(b"\n".join(lines) + b"\n")


def _read_anchor(path: Path) -> dict[str, Any]:
    return json.loads(_anchor_path(path).read_text(encoding="utf-8"))


# -- FR-4.1: head anchor ---------------------------------------------------


def test_anchor_is_written_on_every_append_and_verifies(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = HashChainLedger(path)
    first = ledger.append("evt", {"n": 0})
    assert _read_anchor(path) == {
        "anchor_version": "1.0",
        "entry_count": 1,
        "tip_hash": first["entry_hash"],
        "ledger_name": "ledger.jsonl",
    }
    second = ledger.append("evt", {"n": 1})
    anchor = _read_anchor(path)
    assert anchor["entry_count"] == 2
    assert anchor["tip_hash"] == second["entry_hash"]
    assert LedgerAnchor.from_dict(anchor).entry_count == 2

    result = ledger.verify()
    assert result.valid
    assert result.chain_valid
    assert result.anchored
    assert result.anchor_status == "verified"
    assert result.anchor_valid is True
    assert result.anchor_entries == 2
    assert result.anchor_head_hash == second["entry_hash"]
    assert "internally self-consistent" in result.semantics
    assert "completeness is established only" in result.to_dict()["semantics"]


def test_tail_truncation_is_detected_against_the_anchor(tmp_path: Path) -> None:
    path, ledger = _make_ledger(tmp_path, 3)
    original = ledger.verify()
    lines = _physical_lines(path)
    _write_lines(path, lines[:2])

    result = HashChainLedger(path).verify()
    assert result.chain_valid  # the remaining chain is self-consistent
    assert not result.valid  # ...but it is not the anchored history
    assert result.entries == 2
    assert result.anchor_status == "mismatch"
    assert any("tail truncation" in error for error in result.errors)

    asserted = HashChainLedger(path).verify(
        expected_entry_count=original.entries,
        expected_tip_hash=original.head_hash,
    )
    assert not asserted.valid
    assert any("expected 3 ledger entries" in error for error in asserted.errors)
    assert any("expected ledger tip" in error for error in asserted.errors)


def test_verify_ledger_cli_expected_anchor_assertions_fail_on_truncation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, ledger = _make_ledger(tmp_path, 2)
    tip = ledger.verify().head_hash
    _write_lines(path, _physical_lines(path)[:1])

    code = main(
        [
            "verify-ledger",
            "--ledger",
            str(path),
            "--expected-count",
            "2",
            "--expected-tip",
            tip,
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert code == 2
    assert output["valid"] is False
    assert output["anchor_status"] == "mismatch"
    assert output["entries"] == 1


def test_anchorless_legacy_ledger_verifies_chain_but_reports_unanchored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, _ledger = _make_ledger(tmp_path, 2)
    _anchor_path(path).unlink()  # simulate a pre-FR-4 ledger

    result = HashChainLedger(path).verify()
    assert result.valid
    assert result.chain_valid
    assert not result.anchored
    assert result.anchor_status == "unverifiable-anchor"
    assert result.anchor_valid is None

    required = HashChainLedger(path).verify(require_anchor=True)
    assert not required.valid
    assert any("anchor required" in error for error in required.errors)

    code = main(["verify-ledger", "--ledger", str(path), "--write-anchor"])
    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["anchor_status"] == "verified"
    assert output["anchor_written"]["entry_count"] == 2
    assert _anchor_path(path).is_file()
    assert HashChainLedger(path).verify().anchor_status == "verified"


def test_write_anchor_bootstraps_a_manually_built_legacy_ledger(
    tmp_path: Path,
) -> None:
    path, ledger = _make_ledger(tmp_path, 1)
    _anchor_path(path).unlink()
    anchor = ledger.write_anchor()
    assert anchor.entry_count == 1
    assert ledger.verify().anchor_status == "verified"


@pytest.mark.parametrize("field", ["entry_count", "tip_hash"])
def test_anchor_tampering_is_detected(tmp_path: Path, field: str) -> None:
    path, _ledger = _make_ledger(tmp_path, 2)
    anchor = _read_anchor(path)
    if field == "entry_count":
        anchor[field] = 99
    else:
        anchor[field] = "f" * 64
    _anchor_path(path).write_text(json.dumps(anchor), encoding="utf-8")

    result = HashChainLedger(path).verify()
    assert not result.valid
    assert result.anchor_status == "mismatch"
    assert any("anchor" in error for error in result.errors)


def test_malformed_anchor_is_invalid_not_a_crash(tmp_path: Path) -> None:
    path, _ledger = _make_ledger(tmp_path, 1)
    _anchor_path(path).write_text("not json\n", encoding="utf-8")
    result = HashChainLedger(path).verify()
    assert not result.valid
    assert result.anchor_status == "invalid"
    assert any("anchor: invalid JSON" in error for error in result.errors)


def test_ledger_extension_beyond_anchor_is_detected(tmp_path: Path) -> None:
    path, ledger = _make_ledger(tmp_path, 2)
    stale_anchor = _anchor_path(path).read_bytes()
    ledger.append("evt", {"n": 2})
    _anchor_path(path).write_bytes(stale_anchor)  # append without anchor update

    result = HashChainLedger(path).verify()
    assert not result.valid
    assert result.anchor_status == "mismatch"
    assert any("behind ledger entries" in error for error in result.errors)


def test_append_refuses_to_advance_past_a_mismatched_anchor(tmp_path: Path) -> None:
    path, ledger = _make_ledger(tmp_path, 1)
    anchor = _read_anchor(path)
    anchor["entry_count"] = 99
    _anchor_path(path).write_text(json.dumps(anchor), encoding="utf-8")

    with pytest.raises(ValueError, match="anchor"):
        ledger.append("evt", {"n": 99})
    assert len(_physical_lines(path)) == 1


# -- FR-4.3 / FR-4.5: strict verification ----------------------------------


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        (b"{broken\n", "invalid JSON"),
        (b"123\n", "expected a JSON object, got number"),
        (b'"hello"\n', "expected a JSON object, got string"),
        (b"[1,2]\n", "expected a JSON object, got array"),
        (b"null\n", "expected a JSON object, got null"),
        (b"\n", "blank line is not a ledger entry"),
    ],
)
def test_one_malformed_line_invalidates_verify_and_entries_agree(
    tmp_path: Path, content: bytes, fragment: str
) -> None:
    path, _ledger = _make_ledger(tmp_path, 1)
    with path.open("ab") as handle:
        handle.write(content)

    result = HashChainLedger(path).verify()
    assert not result.valid
    assert any(error.startswith("line 2:") and fragment in error for error in result.errors)
    with pytest.raises(ValueError, match="line 2"):
        HashChainLedger(path).entries()


def test_verify_validates_version_timestamp_and_entry_shape(tmp_path: Path) -> None:
    path, _ledger = _make_ledger(tmp_path, 2)
    rows = [json.loads(line) for line in _physical_lines(path)]
    rows[1]["ledger_version"] = "999.0"
    rows[1]["timestamp"] = "not-a-date"
    rows[1]["payload"] = ["not", "an", "object"]
    previous = rows[0]["entry_hash"]
    for row in rows[1:]:
        row["previous_hash"] = previous
        row.pop("entry_hash", None)
        row["entry_hash"] = _entry_hash(row)
        previous = row["entry_hash"]
    _write_lines(
        path,
        [json.dumps(row, sort_keys=True).encode("utf-8") for row in rows],
    )

    result = HashChainLedger(path).verify()
    assert not result.valid
    assert any("ledger_version" in error for error in result.errors)
    assert any("timestamp is not parseable" in error for error in result.errors)
    assert any("payload must be a JSON object" in error for error in result.errors)


def test_missing_and_wrong_typed_fields_are_line_numbered_errors(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        json.dumps({"ledger_version": "1.0", "sequence": "one"}) + "\n",
        encoding="utf-8",
    )
    result = HashChainLedger(path).verify()
    assert not result.valid
    assert any(error.startswith("line 1:") and "missing field" in error for error in result.errors)
    assert any("sequence must be a positive integer" in error for error in result.errors)
    with pytest.raises(ValueError, match="line 1"):
        HashChainLedger(path).entries()


# -- FR-4.4: Unicode separators written by the ledger itself ----------------


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085"])
def test_unicode_separator_payload_round_trips(tmp_path: Path, separator: str) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = HashChainLedger(path)
    ledger.append("note", {"text": f"before{separator}after"})
    assert separator.encode("utf-8") not in path.read_bytes()

    fresh = HashChainLedger(path)
    assert fresh.verify().valid
    entries = list(fresh.entries())
    assert entries[0]["payload"]["text"] == f"before{separator}after"
    # The pre-FR-4 defect was permanent: every later append was refused.
    ledger.append("note", {"text": "second"})
    assert HashChainLedger(path).verify().entries == 2


# -- FR-4.2: content-keyed verified-tip cache -------------------------------


def test_same_size_same_mtime_tip_forgery_is_refused_by_cached_instance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = HashChainLedger(path)
    ledger.append("evt", {"pad": "AAAAAAAAAAAAAAAA"})
    stat = path.stat()
    forged = path.read_text(encoding="utf-8").replace("AAAAAAAAAAAAAAAA", "BBBBBBBBBBBBBBBB")
    assert len(forged.encode("utf-8")) == stat.st_size
    path.write_bytes(forged.encode("utf-8"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert (path.stat().st_size, path.stat().st_mtime_ns) == (
        stat.st_size,
        stat.st_mtime_ns,
    )

    with pytest.raises(ValueError, match="invalid ledger"):
        ledger.append("evt", {"n": 2})
    assert not HashChainLedger(path).verify().valid


def test_cached_instance_detects_middle_tamper_with_tip_unchanged(
    tmp_path: Path,
) -> None:
    path, ledger = _make_ledger(tmp_path, 3)
    stat = path.stat()
    lines = _physical_lines(path)
    lines[0] = lines[0].replace(b'"n":0', b'"n":9')
    _write_lines(path, lines)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    with pytest.raises(ValueError, match="invalid ledger"):
        ledger.append("evt", {"n": 99})


def test_cached_append_still_uses_fast_path_for_untouched_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    calls = 0
    original_verify = HashChainLedger.verify

    def counting_verify(self: HashChainLedger) -> Any:
        nonlocal calls
        calls += 1
        return original_verify(self)

    monkeypatch.setattr(HashChainLedger, "verify", counting_verify)
    for index in range(4):
        ledger.append("evt", {"n": index})
    assert calls == 1
    assert ledger.verify().valid


# -- FR-4.6: duplicate assessment appends ------------------------------------


class _FakeAssessment:
    def __init__(self) -> None:
        self.value = {
            "project": "demo",
            "phase": "after_implement",
            "outcome": "pass",
            "claims": [{"id": "C1"}],
        }

    def to_dict(self) -> dict[str, Any]:
        return self.value


def test_duplicate_assessment_is_reported_and_explicit_flag_marks_it(
    tmp_path: Path,
) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    assessment = _FakeAssessment()
    ledger.append_assessment(assessment)

    with pytest.raises(ValueError, match="duplicate assessment"):
        ledger.append_assessment(assessment)
    assert len(list(ledger.entries())) == 1

    repeated = ledger.append_assessment(assessment, allow_duplicate=True)
    assert repeated["payload"]["duplicate_of_sequence"] == 1
    assert ledger.verify().valid

    # The same artifact recorded by a different actor is a distinct record.
    ledger.append_assessment(assessment, actor="reviewer")
    assert len(list(ledger.entries())) == 3


def test_generic_duplicate_events_remain_appendable(tmp_path: Path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    ledger.append("heartbeat", {"ok": True})
    ledger.append("heartbeat", {"ok": True})
    assert ledger.verify().entries == 2


def test_generic_assessment_append_uses_the_same_duplicate_rule(
    tmp_path: Path,
) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    payload = {"assessment_sha256": "a" * 64}
    ledger.append("assessment", payload)
    with pytest.raises(ValueError, match="duplicate assessment"):
        ledger.append("assessment", payload)
    repeated = ledger.append("assessment", payload, allow_duplicate=True)
    assert repeated["payload"]["duplicate_of_sequence"] == 1


# -- RT2 p14: held tamper classes still detected -----------------------------


def _tampered_lines(kind: str, lines: list[bytes]) -> list[bytes]:
    if kind == "middle edit":
        return [lines[0], lines[1].replace(b'"n":1', b'"n":99'), lines[2], lines[3]]
    if kind == "middle deletion":
        return [lines[0], lines[2], lines[3]]
    if kind == "reorder":
        return [lines[1], lines[0], lines[2], lines[3]]
    if kind == "insertion":
        return [lines[0], lines[1], lines[1], lines[2], lines[3]]
    if kind == "genesis tamper":
        return [lines[0].replace(b"0" * 64, b"f" * 64), *lines[1:]]
    if kind == "mid-line tail truncation":
        return [*lines[:3], lines[3][:40]]
    if kind == "sequence renumber":
        return [
            lines[0],
            lines[1].replace(b'"sequence":2', b'"sequence":7'),
            lines[2],
            lines[3],
        ]
    raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind",
    [
        "middle edit",
        "middle deletion",
        "reorder",
        "insertion",
        "genesis tamper",
        "mid-line tail truncation",
        "sequence renumber",
    ],
)
def test_held_tamper_classes_are_detected(tmp_path: Path, kind: str) -> None:
    path, _ledger = _make_ledger(tmp_path, 4)
    _write_lines(path, _tampered_lines(kind, _physical_lines(path)))
    result = HashChainLedger(path).verify()
    assert not result.valid
    assert result.errors


def test_pristine_chain_remains_valid_after_tamper_matrix(tmp_path: Path) -> None:
    path, _ledger = _make_ledger(tmp_path, 4)
    original = path.read_bytes()
    _write_lines(path, _tampered_lines("middle edit", _physical_lines(path)))
    assert not HashChainLedger(path).verify().valid
    path.write_bytes(original)
    result = HashChainLedger(path).verify()
    assert result.valid
    assert result.anchor_status == "verified"


# -- Gate interplay (FR-1 ledger leg + FR-4.1 anchor) -------------------------

_GOOD_CLAIM = {
    "id": "C1",
    "text": "The widget holds for 10 s under load profile L",
    "status": "supported",
    "kind": "requirement",
    "boundary": ["load profile L"],
    "falsification_tests": ["drop the widget and observe failure"],
    "evidence": [
        {
            "ref": "reports/t.json",
            "kind": "observed",
            "direction": "supports",
            "source_quality": "test",
            "source_id": "lab-1",
            "independent_of": ["lab-2"],
        },
        {
            "ref": "reports/u.json",
            "kind": "observed",
            "direction": "supports",
            "source_quality": "primary",
            "source_id": "lab-2",
        },
    ],
}


def _assess(tmp_path: Path) -> tuple[Path, Path]:
    bundle = tmp_path / "claims.json"
    bundle.write_text(json.dumps({"claims": [_GOOD_CLAIM]}), encoding="utf-8")
    output = tmp_path / "assessment.json"
    code = main(
        [
            "assess",
            "--input",
            str(bundle),
            "--output",
            str(output),
            "--project-root",
            str(tmp_path),
        ]
    )
    assert code == 0
    value = json.loads(output.read_text(encoding="utf-8"))
    return output, Path(value["metadata"]["ledger"]["path"])


def test_assess_writes_anchor_and_gate_passes(tmp_path: Path) -> None:
    output, ledger_path = _assess(tmp_path)
    assert _anchor_path(ledger_path).is_file()
    assert HashChainLedger(ledger_path).verify().anchor_status == "verified"
    assert main(["gate", "--input", str(output)]) == 0


def test_gate_fails_after_tail_truncation_even_with_assessment_still_ledgered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output, ledger_path = _assess(tmp_path)
    ledger = HashChainLedger(ledger_path)
    ledger.append("note", {"after": "assessment"})
    assert main(["gate", "--input", str(output)]) == 0

    _write_lines(ledger_path, _physical_lines(ledger_path)[:1])
    # The assessment entry itself remains, and its chain is consistent;
    # only the anchor can see that the newest entry is gone.
    assert HashChainLedger(ledger_path).verify().chain_valid
    code = main(["gate", "--input", str(output)])
    captured = capsys.readouterr()
    assert code == 2
    assert "anchor check failed" in captured.err


def test_gate_fails_when_recorded_ledger_has_no_anchor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output, ledger_path = _assess(tmp_path)
    _anchor_path(ledger_path).unlink()
    code = main(["gate", "--input", str(output)])
    captured = capsys.readouterr()
    assert code == 2
    assert "anchor check failed" in captured.err
    assert "unverifiable-anchor" in captured.err
