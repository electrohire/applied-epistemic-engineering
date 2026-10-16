"""Exercise the standalone skill's operations without any Spec Kit installation."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from aee.cli import main


def test_standalone_skill_is_a_package_resource() -> None:
    skill = files("aee").joinpath("skills/applied-epistemic-engineering/SKILL.md")
    assert skill.is_file()
    content = skill.read_text(encoding="utf-8")
    metadata = content.split("---", 2)[1]
    assert "name: applied-epistemic-engineering" in metadata
    assert "description:" in metadata


def test_standalone_agent_workflow_preserves_draft_and_evidence(tmp_path: Path) -> None:
    # Use explicit paths: no installed extension, registry, composer, or model service.
    working = tmp_path / ".aee"
    working.mkdir()
    bundle = working / "claims.json"
    bundle.write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "REQ-1",
                        "text": "The API meets its latency requirement",
                        "status": "draft",
                        "stage": "created",
                        "evidence": [],
                        "boundary": ["specified load test"],
                        "falsification_tests": ["Measured latency exceeds the specified limit"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    original = bundle.read_bytes()
    output = working / "assessment.json"
    assert main(["validate", str(bundle)]) == 0
    assert (
        main(
            [
                "assess",
                "--input",
                str(bundle),
                "--project-root",
                str(tmp_path),
                "--phase",
                "after_plan",
                "--output",
                str(output),
            ]
        )
        == 1
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["outcome"] != "pass"
    assert bundle.read_bytes() == original
    ledger = tmp_path / ".specify/extensions/aee/ledger/epistemic-ledger.jsonl"
    assert ledger.is_file()
    assert main(["verify-ledger", "--ledger", str(ledger)]) == 0
    assert not (tmp_path / ".specify/extensions/.registry").exists()
