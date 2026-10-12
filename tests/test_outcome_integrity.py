"""Spec 003 FR-1 — outcome integrity (T105).

Inverts the red-team probes RT1 p2 §§A/C (empty bundle vacuous pass;
duplicate ids crash), RT2 p09 §6 (gate trusts a fabricated outcome),
and RT2 p05 sections 2-3 (duplicate ids; session last-wins merge):

- an empty bundle never passes — CLI exit 2, engine outcome block;
- duplicate claim ids produce a completed block assessment carrying
  the CRITICAL duplicate-identity challenge, never an exception, and
  AEESession.load() refuses them with the same rule;
- aee gate cross-checks the outcome against the assessment's own
  scores, summary counts, threshold, and (where recorded) ledger —
  fabricated or tampered files gate as input errors (exit 2), real
  assessments keep gating exactly as their outcomes say.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aee.cli import main
from aee.engine import AEEEngine
from aee.model import Claim
from aee.session import AEESession

GOOD_CLAIM = {
    "id": "C1",
    "text": "The widget holds for 10 s under load profile L",
    "status": "supported",
    "stage": "accepted",
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


def _write_bundle(tmp_path: Path, claims: list[dict]) -> Path:
    bundle = tmp_path / "claims.json"
    bundle.write_text(json.dumps({"claims": claims}), encoding="utf-8")
    return bundle


def _assess_via_cli(tmp_path: Path, claims: list[dict]) -> Path:
    """Run the real CLI assess (ledgered by default under tmp_path)
    and return the assessment file it produced."""
    bundle = _write_bundle(tmp_path, claims)
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
    assert code in {0, 1, 2}
    return output


# -- Empty bundle (RT1-01) --------------------------------------------


def test_engine_empty_bundle_is_block_not_pass() -> None:
    assessment = AEEEngine().assess([])
    assert assessment.outcome == "block"
    assert assessment.healthy is False
    assert "Empty bundle" in assessment.summary


def test_cli_empty_bundle_is_clean_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    bundle = _write_bundle(tmp_path, [])
    code = main(["assess", "--input", str(bundle), "--no-ledger"])
    captured = capsys.readouterr()
    assert code == 2
    assert "zero claims" in captured.err
    assert "Traceback" not in captured.err


def test_cli_empty_bundle_challenge_is_clean_exit_2(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, [])
    assert main(["challenge", "--input", str(bundle)]) == 2


# -- Duplicate claim ids (RT1-12, RT2-M4) ------------------------------


def _claim(claim_id: str) -> Claim:
    return Claim(
        id=claim_id,
        text="Widget latency is 42 ms at p95 under load profile L",
        boundary=["load profile L"],
        falsification_tests=["measure p95"],
    )


def test_duplicate_ids_produce_block_assessment_not_exception() -> None:
    assessment = AEEEngine().assess([_claim("DUP"), _claim("DUP")])
    assert assessment.outcome == "block"
    duplicates = [
        failure for failure in assessment.failures if "Duplicate identity" in failure.challenge
    ]
    assert duplicates
    assert all(failure.severity.value == "critical" for failure in duplicates)


def test_duplicate_ids_cli_assessment_completes_as_block(tmp_path: Path) -> None:
    claim = dict(GOOD_CLAIM)
    output = _assess_via_cli(tmp_path, [claim, claim])
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["outcome"] == "block"


def test_session_load_refuses_duplicate_ids(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    claim = _claim("CLM-1").to_dict()
    other = _claim("CLM-1").to_dict()
    other["text"] = "second version silently wins"
    state.write_text(
        json.dumps({"project": "p", "phase": "after_plan", "claims": [claim, other]}),
        encoding="utf-8",
    )
    session = AEESession("p", state_file=state)
    with pytest.raises(ValueError, match="duplicate claim id: CLM-1"):
        session.load()


# -- Gate cross-checks (RT2-H1) ----------------------------------------


def test_gate_refuses_fabricated_outcome_only_file(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    fake = tmp_path / "fake.json"
    fake.write_text('{"outcome": "pass"}', encoding="utf-8")
    code = main(["gate", "--input", str(fake)])
    captured = capsys.readouterr()
    assert code == 2
    assert "not a complete assessment" in captured.err
    assert "Traceback" not in captured.err


def test_gate_refuses_fabricated_pass_with_zero_scores(tmp_path: Path) -> None:
    fake = tmp_path / "fake2.json"
    fake.write_text(
        '{"outcome": "pass", "claims": [], "scores": {"X": {"propagated_score": 0.0}}}',
        encoding="utf-8",
    )
    assert main(["gate", "--input", str(fake)]) == 2


def test_gate_accepts_real_passing_assessment(tmp_path: Path) -> None:
    output = _assess_via_cli(tmp_path, [GOOD_CLAIM])
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["outcome"] == "pass"
    assert main(["gate", "--input", str(output)]) == 0


def test_gate_real_non_pass_assessment_keeps_its_exit_code(tmp_path: Path) -> None:
    weak = {
        "id": "W1",
        "text": "The widget is fast",
        "status": "supported",
        "stage": "accepted",
        "kind": "requirement",
    }
    output = _assess_via_cli(tmp_path, [weak])
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["outcome"] != "pass"
    assert main(["gate", "--input", str(output)]) == 1


def test_gate_refuses_outcome_edited_to_pass(tmp_path: Path) -> None:
    weak = {"id": "W1", "text": "The widget is fast", "status": "supported", "stage": "accepted"}
    output = _assess_via_cli(tmp_path, [weak])
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["outcome"] != "pass"
    value["outcome"] = "pass"
    output.write_text(json.dumps(value), encoding="utf-8")
    # The edit also invalidates the ledger hash — either cross-check
    # refusing is correct; the gate must not return 0.
    assert main(["gate", "--input", str(output)]) == 2


def test_gate_refuses_score_tampered_below_threshold(tmp_path: Path) -> None:
    output = _assess_via_cli(tmp_path, [GOOD_CLAIM])
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["outcome"] == "pass"
    value["scores"]["C1"]["propagated_score"] = 0.0
    output.write_text(json.dumps(value), encoding="utf-8")
    assert main(["gate", "--input", str(output)]) == 2


def test_gate_refuses_assessment_whose_hash_is_not_ledgered(tmp_path: Path) -> None:
    output = _assess_via_cli(tmp_path, [GOOD_CLAIM])
    value = json.loads(output.read_text(encoding="utf-8"))
    # Claim text feeds no count, score, or failure — only the digest
    # the ledger recorded. Editing it isolates the ledger leg.
    value["claims"][0]["text"] = "A different proposition entirely"
    output.write_text(json.dumps(value), encoding="utf-8")
    assert main(["gate", "--input", str(output)]) == 2


def test_gate_refuses_when_recorded_ledger_is_missing(tmp_path: Path) -> None:
    output = _assess_via_cli(tmp_path, [GOOD_CLAIM])
    value = json.loads(output.read_text(encoding="utf-8"))
    ledger_path = Path(value["metadata"]["ledger"]["path"])
    assert ledger_path.exists()
    ledger_path.unlink()
    assert main(["gate", "--input", str(output)]) == 2


def test_gate_refuses_duplicate_id_assessment_with_forged_outcome(tmp_path: Path) -> None:
    claim = dict(GOOD_CLAIM)
    output = _assess_via_cli(tmp_path, [claim, claim])
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["outcome"] == "block"
    # The genuine block assessment gates as block (exit 2 via the
    # outcome mapping, after passing cross-checks)...
    assert main(["gate", "--input", str(output)]) == 2
    # ...and relabelling it pass is refused by the cross-checks.
    value["outcome"] = "pass"
    output.write_text(json.dumps(value), encoding="utf-8")
    assert main(["gate", "--input", str(output)]) == 2
