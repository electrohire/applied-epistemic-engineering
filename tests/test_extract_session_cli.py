import json

from aee import AEESession, ClaimKind, Evidence
from aee.cli import main
from aee.extract import extract_markdown_claims, load_claims


def test_extract_direct_heading(tmp_path) -> None:
    path = tmp_path / "requirements.md"
    path.write_text(
        "# Requirements\n\n"
        "## REQ-API-001 — The API returns HTTP 200\n"
        "- **Boundary:** Valid authenticated requests\n"
        "- **Test:** Observe a non-200 response\n",
        encoding="utf-8",
    )
    claims = extract_markdown_claims(path)
    assert len(claims) == 1
    assert claims[0].id == "REQ-API-001"
    assert claims[0].kind is ClaimKind.REQUIREMENT
    assert claims[0].boundary == ["Valid authenticated requests"]


def test_extract_numbered_heading_with_inline_id(tmp_path) -> None:
    path = tmp_path / "requirements.md"
    path.write_text(
        "## 1. Stable error envelope\n"
        "- **ID:** REQ-API-002\n"
        "- **Description:** Errors use one envelope\n",
        encoding="utf-8",
    )
    claims = extract_markdown_claims(path)
    assert claims[0].text == "Errors use one envelope"


def test_load_json(tmp_path) -> None:
    path = tmp_path / "claims.json"
    path.write_text(json.dumps({"claims": [{"id": "A", "text": "A"}]}))
    assert load_claims(path)[0].id == "A"


def test_load_json_object_without_claims_key_raises(tmp_path) -> None:
    """Regression: a JSON object without a 'claims' key silently
    loaded as an empty claim set, producing a vacuous assessment."""
    import pytest

    path = tmp_path / "claims.json"
    path.write_text(json.dumps({"claimz": [{"id": "A", "text": "A"}]}))
    with pytest.raises(ValueError, match="'claims'"):
        load_claims(path)


def test_markdown_depends_on_case_normalized(tmp_path) -> None:
    """Regression: markdown claim ids are uppercased but depends_on
    refs were not, so a lowercase ref never matched its claim."""
    path = tmp_path / "requirements.md"
    path.write_text(
        "## req-base-001 — The base claim\n"
        "\n"
        "## req-top-002 — The dependent claim\n"
        "- **Depends on:** req-base-001\n",
        encoding="utf-8",
    )
    claims = extract_markdown_claims(path)
    by_id = {claim.id: claim for claim in claims}
    assert set(by_id) == {"REQ-BASE-001", "REQ-TOP-002"}
    assert by_id["REQ-TOP-002"].depends_on == ["REQ-BASE-001"]


def test_session_save_load(tmp_path) -> None:
    path = tmp_path / "state.json"
    session = AEESession("project", state_file=path)
    session.add_claim("A", "A")
    session.add_evidence("A", Evidence(ref="source"))
    session.save()
    restored = AEESession("other", state_file=path)
    assert restored.load() == 1
    assert restored.project == "project"


def test_cli_assess_and_ledger(tmp_path) -> None:
    input_path = tmp_path / "claims.json"
    output_path = tmp_path / "assessment.json"
    evaluator_path = tmp_path / "evaluator.json"
    ledger_path = tmp_path / "ledger.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "A",
                        "text": "A measurable result",
                        "boundary": ["test"],
                    }
                ]
            }
        )
    )
    code = main(
        [
            "assess",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--evaluator-output",
            str(evaluator_path),
            "--ledger",
            str(ledger_path),
        ]
    )
    assert code == 1
    assert output_path.exists()
    assert evaluator_path.exists()
    assert main(["verify-ledger", "--ledger", str(ledger_path)]) == 0


def test_cli_malformed_input_exits_2(tmp_path) -> None:
    """Exit-code contract: input errors are exit 2 with a clean
    message, never a traceback with Python's exit 1 (which the README
    defines as a soft outcome)."""
    bad = tmp_path / "claims.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["assess", "--input", str(bad)]) == 2
    missing = tmp_path / "nope.json"
    assert main(["assess", "--input", str(missing)]) == 2


def test_cli_gaps_close_unknown_id_exits_2(tmp_path) -> None:
    from aee import GapEngine

    matrix = tmp_path / "matrix.md"
    matrix.write_text(
        "| Test ID | Requirements | Layer | Gate |\n"
        "|---------|-------------|-------|------|\n"
        "| T-X-001 | Test X | unit | gate-1 |\n",
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    gaps = tmp_path / "GAPS.md"
    gaps.write_text(GapEngine().generate(matrix, evidence).to_markdown(), encoding="utf-8")
    rc = main(
        [
            "gaps",
            "--matrix",
            str(matrix),
            "--evidence",
            str(evidence),
            "--output",
            str(gaps),
            "--close",
            "GAP-999",
        ]
    )
    assert rc == 2
