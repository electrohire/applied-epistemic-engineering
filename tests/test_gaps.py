"""Tests for the gap register generation engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aee import GapEngine, GapEntry, GapRegister

MATRIX_CONTENT = """# Verification Matrix

| Test ID | Requirements | Layer | Gate |
|---------|-------------|-------|------|
| T-API-001 | API returns 200 on valid input | integration | gate-1 |
| T-API-002 | API returns 400 on invalid input | integration | gate-1 |
| T-DB-001 | Data persists across restarts | unit | gate-2 |
"""

EVIDENCE_PASSING = {
    "results": [
        {"test_id": "T-API-001", "status": "pass"},
        {"test_id": "T-DB-001", "status": "passed"},
    ]
}

EVIDENCE_PARTIAL = {
    "results": [
        {"test_id": "T-API-001", "status": "pass"},
    ]
}


@pytest.fixture
def matrix_file(tmp_path: Path) -> Path:
    path = tmp_path / "verification-matrix.md"
    path.write_text(MATRIX_CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def evidence_dir_passing(tmp_path: Path) -> Path:
    d = tmp_path / "evidence"
    d.mkdir()
    (d / "test-results.json").write_text(json.dumps(EVIDENCE_PASSING), encoding="utf-8")
    return d


@pytest.fixture
def evidence_dir_partial(tmp_path: Path) -> Path:
    d = tmp_path / "evidence"
    d.mkdir()
    (d / "test-results.json").write_text(json.dumps(EVIDENCE_PARTIAL), encoding="utf-8")
    return d


@pytest.fixture
def evidence_dir_empty(tmp_path: Path) -> Path:
    d = tmp_path / "evidence"
    d.mkdir()
    return d


def test_generate_all_open(matrix_file: Path, tmp_path: Path) -> None:
    empty_evidence = tmp_path / "empty-evidence"
    empty_evidence.mkdir()
    engine = GapEngine()
    register = engine.generate(matrix_file, empty_evidence)
    assert register.open_count == 3
    assert register.closed_count == 0
    assert all(e.status == "open" for e in register.entries)


def test_generate_with_passing_evidence(matrix_file: Path, evidence_dir_passing: Path) -> None:
    engine = GapEngine()
    register = engine.generate(matrix_file, evidence_dir_passing)
    assert register.open_count == 1
    assert register.closed_count == 2
    # T-API-001 and T-DB-001 should be closed
    closed_ids = {e.id for e in register.closed_gaps}
    assert "GAP-001" in closed_ids
    assert "GAP-003" in closed_ids
    # T-API-002 should be open
    open_ids = {e.id for e in register.open_gaps}
    assert "GAP-002" in open_ids


def test_generate_preserves_existing_closed_gaps(
    matrix_file: Path, evidence_dir_partial: Path, tmp_path: Path
) -> None:
    # First generate with partial evidence (T-API-001 passes)
    engine = GapEngine()
    register1 = engine.generate(matrix_file, evidence_dir_partial)
    assert register1.open_count == 2
    assert register1.closed_count == 1

    # Write the register
    gaps_path = tmp_path / "GAPS.md"
    gaps_path.write_text(register1.to_markdown(), encoding="utf-8")

    # Regenerate with no evidence but preserving existing
    empty_evidence = tmp_path / "empty-evidence"
    empty_evidence.mkdir()
    register2 = engine.generate(matrix_file, empty_evidence, existing_gaps_path=gaps_path)
    # GAP-001 was closed in register1, should be preserved
    gap1 = next(e for e in register2.entries if e.id == "GAP-001")
    assert gap1.status == "closed"


def test_close_gap(matrix_file: Path, evidence_dir_empty: Path, tmp_path: Path) -> None:
    engine = GapEngine()
    register = engine.generate(matrix_file, evidence_dir_empty)
    assert register.open_count == 3

    closed_register = engine.close_gap(register, "GAP-001")
    assert closed_register.open_count == 2
    assert closed_register.closed_count == 1
    gap1 = next(e for e in closed_register.entries if e.id == "GAP-001")
    assert gap1.status == "closed"
    assert gap1.closed_at is not None


def test_close_nonexistent_gap(matrix_file: Path, evidence_dir_empty: Path) -> None:
    engine = GapEngine()
    register = engine.generate(matrix_file, evidence_dir_empty)
    # Previously this silently returned the register unchanged and the
    # CLI reported success; a typo'd ID must be an error.
    with pytest.raises(KeyError):
        engine.close_gap(register, "GAP-999")


def test_to_markdown_format(matrix_file: Path, evidence_dir_empty: Path) -> None:
    engine = GapEngine()
    register = engine.generate(matrix_file, evidence_dir_empty)
    md = register.to_markdown()
    assert "# Gap Register" in md
    assert "## Open Gaps" in md
    assert "## Closed Gaps" in md
    assert "**Open:** 3" in md
    assert "**Closed:** 0" in md
    assert "| GAP-001 |" in md
    assert "| GAP-002 |" in md
    assert "| GAP-003 |" in md


def test_to_markdown_empty_register() -> None:
    register = GapRegister(entries=[], generated_at="2026-01-01T00:00:00Z")
    md = register.to_markdown()
    assert "No open gaps" in md
    assert "No closed gaps" in md


def test_load_register_roundtrip(
    matrix_file: Path, evidence_dir_passing: Path, tmp_path: Path
) -> None:
    engine = GapEngine()
    register = engine.generate(matrix_file, evidence_dir_passing)
    gaps_path = tmp_path / "GAPS.md"
    gaps_path.write_text(register.to_markdown(), encoding="utf-8")

    loaded = engine.load_register(gaps_path)
    assert loaded.open_count == register.open_count
    assert loaded.closed_count == register.closed_count
    # Verify specific entries
    for original in register.entries:
        loaded_entry = next(e for e in loaded.entries if e.id == original.id)
        assert loaded_entry.status == original.status
        assert loaded_entry.requirement == original.requirement


def test_load_register_missing_file(tmp_path: Path) -> None:
    engine = GapEngine()
    with pytest.raises(FileNotFoundError):
        engine.load_register(tmp_path / "nonexistent.md")


def test_generate_missing_matrix(tmp_path: Path) -> None:
    engine = GapEngine()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with pytest.raises(FileNotFoundError):
        engine.generate(tmp_path / "nonexistent.md", evidence)


def test_evidence_with_tests_key(tmp_path: Path) -> None:
    """Evidence files can use 'tests' instead of 'results' key."""
    matrix = tmp_path / "matrix.md"
    matrix.write_text(
        "| Test ID | Requirements | Layer | Gate |\n"
        "|---------|-------------|-------|------|\n"
        "| T-X-001 | Test X | unit | gate-1 |\n",
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "results.json").write_text(
        json.dumps({"tests": [{"test_id": "T-X-001", "status": "ok"}]}),
        encoding="utf-8",
    )
    engine = GapEngine()
    register = engine.generate(matrix, evidence)
    assert register.closed_count == 1


def test_evidence_ignores_failing_tests(matrix_file: Path, tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "results.json").write_text(
        json.dumps({"results": [{"test_id": "T-API-001", "status": "fail"}]}),
        encoding="utf-8",
    )
    engine = GapEngine()
    register = engine.generate(matrix_file, evidence)
    assert register.open_count == 3
    assert register.closed_count == 0


def test_gap_entry_to_row() -> None:
    entry = GapEntry(
        id="GAP-001",
        test_id="T-API-001",
        requirement="API returns 200",
        gate="gate-1",
        status="open",
        evidence="T-API-001 pass",
    )
    row = entry.to_row(False)
    assert row == "| GAP-001 | T-API-001 | API returns 200 | gate-1 | open | T-API-001 pass |"

    entry.closed_at = "2026-01-01T00:00:00Z"
    entry.status = "closed"
    row = entry.to_row(True)
    assert row == (
        "| GAP-001 | T-API-001 | API returns 200 | gate-1 | 2026-01-01T00:00:00Z | T-API-001 pass |"
    )


def test_preservation_survives_matrix_row_insertion(
    matrix_file: Path, evidence_dir_empty: Path, tmp_path: Path
) -> None:
    """Regression: preservation keyed on positional GAP IDs moved a
    closure onto a different test after any matrix edit. Identity is
    the test_id."""
    engine = GapEngine()
    register = engine.generate(matrix_file, evidence_dir_empty)
    register = engine.close_gap(register, "GAP-002")  # T-API-002
    gaps_path = tmp_path / "GAPS.md"
    gaps_path.write_text(register.to_markdown(), encoding="utf-8")

    edited = tmp_path / "matrix-v2.md"
    edited.write_text(
        MATRIX_CONTENT.replace(
            "| T-API-001 |",
            "| T-NEW-001 | Inserted row | unit | gate-0 |\n| T-API-001 |",
        ),
        encoding="utf-8",
    )
    register2 = engine.generate(edited, evidence_dir_empty, existing_gaps_path=gaps_path)
    by_test = {e.test_id: e for e in register2.entries}
    assert by_test["T-API-002"].status == "closed"
    assert by_test["T-API-002"].id == "GAP-003"  # renumbered, closure followed the test
    assert by_test["T-NEW-001"].status == "open"


def test_nonclosed_statuses_survive_roundtrip(
    matrix_file: Path, evidence_dir_empty: Path, tmp_path: Path
) -> None:
    """in_progress / blocked must survive load + regenerate; the old
    parser reset every open row to plain "open"."""
    engine = GapEngine()
    register = engine.generate(matrix_file, evidence_dir_empty)
    register.entries[0].status = "in_progress"
    register.entries[1].status = "blocked"
    gaps_path = tmp_path / "GAPS.md"
    gaps_path.write_text(register.to_markdown(), encoding="utf-8")

    loaded = engine.load_register(gaps_path)
    by_id = {e.id: e for e in loaded.entries}
    assert by_id["GAP-001"].status == "in_progress"
    assert by_id["GAP-002"].status == "blocked"
    assert by_id["GAP-001"].test_id == "T-API-001"

    register2 = engine.generate(matrix_file, evidence_dir_empty, existing_gaps_path=gaps_path)
    by_test = {e.test_id: e for e in register2.entries}
    assert by_test["T-API-001"].status == "in_progress"
    assert by_test["T-API-002"].status == "blocked"


def test_corrupt_evidence_file_warns(
    matrix_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Corrupt evidence must be loud, never indistinguishable from
    'no evidence'."""
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "broken.json").write_text("{not json", encoding="utf-8")
    register = GapEngine().generate(matrix_file, evidence)
    assert register.open_count == 3
    assert "broken.json" in capsys.readouterr().err


# ---------------------------------------------------------------------
# Spec 003 FR-5: round-trip fidelity. generate -> load -> close ->
# rewrite must change ONLY the closed gap's own state: headers,
# statuses/severities, evidence text, and timestamps are preserved
# byte-for-byte (a split(":", 1) header parse used to corrupt the
# Updated/Source lines on every cycle).
# ---------------------------------------------------------------------


def test_register_round_trip_preserves_header_fields(
    matrix_file: Path, evidence_dir_empty: Path, tmp_path: Path
) -> None:
    engine = GapEngine()
    register = engine.generate(matrix_file, evidence_dir_empty)
    loaded = engine.load_register(_write_register(register, tmp_path))
    assert loaded.generated_at == register.generated_at
    assert loaded.source_matrix == register.source_matrix
    assert loaded.source_evidence == register.source_evidence


def _write_register(register: GapRegister, tmp_path: Path) -> Path:
    path = tmp_path / "GAPS.md"
    path.write_text(register.to_markdown(), encoding="utf-8")
    return path


def test_close_round_trip_diff_is_only_the_closed_gap(
    matrix_file: Path, evidence_dir_empty: Path, tmp_path: Path
) -> None:
    engine = GapEngine()
    register = engine.generate(matrix_file, evidence_dir_empty)
    before = register.to_markdown()
    # A human hand-edit: one gap's status and evidence note must
    # survive the close of a DIFFERENT gap exactly.
    open_row = (
        "| GAP-002 | T-API-002 | API returns 400 on invalid input "
        "| gate-1 | open | T-API-002 pass |"
    )
    edited_row = (
        "| GAP-002 | T-API-002 | API returns 400 on invalid input "
        "| gate-1 | blocked | see vendor thread #42 (alice) |"
    )
    before = before.replace(open_row, edited_row)
    assert "vendor thread #42" in before  # the edit actually landed
    path = tmp_path / "GAPS.md"
    path.write_text(before, encoding="utf-8")

    closed = engine.close_gap(engine.load_register(path), "GAP-001")
    after = closed.to_markdown()

    before_lines = before.splitlines()
    after_lines = after.splitlines()
    # Headers are byte-identical.
    assert [line for line in after_lines if line.startswith("**Updated:**")] == [
        line for line in before_lines if line.startswith("**Updated:**")
    ]
    assert [line for line in after_lines if line.startswith("**Source:**")] == [
        line for line in before_lines if line.startswith("**Source:**")
    ]
    # Every untouched row survives verbatim.
    for line in before_lines:
        if line.startswith(("| GAP-002", "| GAP-003")):
            assert line in after_lines
    # The closed gap's row carries its original test/requirement/
    # gate/evidence into the Closed section, with a timestamp.
    closed_row = next(line for line in after_lines if line.startswith("| GAP-001"))
    assert "T-API-001" in closed_row
    assert "API returns 200 on valid input" in closed_row
    assert "gate-1" in closed_row
    assert "T-API-001 pass" in closed_row
    # The derived counts moved by exactly the one closure.
    assert "**Open:** 2 | **Closed:** 1" in after


def test_two_register_loads_produce_independent_objects(
    matrix_file: Path, evidence_dir_empty: Path, tmp_path: Path
) -> None:
    engine = GapEngine()
    path = _write_register(engine.generate(matrix_file, evidence_dir_empty), tmp_path)
    first = engine.load_register(path)
    second = engine.load_register(path)
    first.entries[0].evidence = "MUTATED"
    first.entries[0].status = "blocked"
    assert second.entries[0].evidence != "MUTATED"
    assert second.entries[0].status != "blocked"


def test_generate_matrix_directory_is_a_named_error(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with pytest.raises(ValueError, match="directory"):
        GapEngine().generate(tmp_path, evidence)


def test_generate_evidence_file_is_a_named_error(matrix_file: Path, tmp_path: Path) -> None:
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        GapEngine().generate(matrix_file, evidence_file)
