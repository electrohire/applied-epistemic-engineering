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
    closed_register = engine.close_gap(register, "GAP-999")
    # No gap was closed, counts unchanged
    assert closed_register.open_count == 3
    assert closed_register.closed_count == 0


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
    assert row == "| GAP-001 | API returns 200 | gate-1 | open | T-API-001 pass |"

    entry.closed_at = "2026-01-01T00:00:00Z"
    entry.status = "closed"
    row = entry.to_row(True)
    assert row == "| GAP-001 | API returns 200 | gate-1 | 2026-01-01T00:00:00Z | T-API-001 pass |"
