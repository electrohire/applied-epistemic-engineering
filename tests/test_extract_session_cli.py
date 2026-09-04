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
