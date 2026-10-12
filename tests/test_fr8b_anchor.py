"""Spec 002 FR-8b acceptance tests (T804-T806): Axiomere anchoring.

The axiomere package is an OPTIONAL dependency (FR-8.6): the
unavailable path is tested everywhere; the live path is tested
wherever the package is importable (it is exercised for real in
environments that carry it, and skipped - never faked - where it
is absent).
"""

import json

import pytest

from aee import AEEEngine, Claim, ClaimStage, ClaimStatus, Evidence, EvidenceKind, SourceQuality
from aee.anchor import AnchorUnavailable, anchor_assessment, anchor_available
from aee.cli import main as cli_main
from aee.ledger import assessment_content_digest


def _assessment_dict() -> dict:
    claim = Claim(
        id="A",
        text="Latency is below 100 ms",
        status=ClaimStatus.SUPPORTED,
        stage=ClaimStage.ACCEPTED,
        boundary=["only within profile L"],
        falsification_tests=["Measure p95 and observe it exceed 100 ms"],
        evidence=[
            Evidence(ref="run-1", source_id="S1", kind=EvidenceKind.OBSERVED,
                     source_quality=SourceQuality.TEST),
        ],
    )
    return AEEEngine().assess([claim]).to_dict()


def test_anchor_availability_matches_importability():
    import importlib.util

    assert anchor_available() == (importlib.util.find_spec("axiomere") is not None)


def test_anchor_unavailable_is_graceful(monkeypatch, tmp_path, capsys):
    # Simulate the absent-package environment deterministically.
    monkeypatch.setattr("aee.anchor.anchor_available", lambda: False)
    assessment = _assessment_dict()
    with pytest.raises(AnchorUnavailable, match="anchor unavailable"):
        anchor_assessment(assessment, ledger_path=tmp_path / "x.axmr")

    path = tmp_path / "assessment.json"
    path.write_text(json.dumps(assessment), encoding="utf-8")
    exit_code = cli_main(
        ["anchor", "--input", str(path), "--ledger", str(tmp_path / "x.axmr")]
    )
    assert exit_code == 2
    assert "anchor unavailable" in capsys.readouterr().err
    # The assessment file is untouched by the failed anchor.
    assert "anchor" not in json.loads(path.read_text())["metadata"]


@pytest.mark.skipif(not anchor_available(), reason="optional axiomere package not installed")
def test_anchor_receipt_matches_assessment_and_verifies(tmp_path):
    # T806: the receipt's hash is the assessment's content digest,
    # and the .axmr ledger verifies with the package's own
    # verify_file.
    import axiomere

    assessment = _assessment_dict()
    ledger = tmp_path / "anchors.axmr"
    receipt = anchor_assessment(
        assessment, ledger_path=ledger, project="spec-002", phase="fr8b"
    )
    assert receipt["assessment_sha256"] == assessment_content_digest(assessment)
    assert receipt["ledger"] == str(ledger)
    assert receipt["event_seq"] is not None
    assert receipt["checkpoint_root"]
    ok, event_count, reason = axiomere.verify_file(str(ledger))
    assert ok, reason
    assert event_count >= 2  # the anchor event + its checkpoint

    # Anchoring again appends (append-only): a second event lands
    # and the chain still verifies end to end.
    receipt2 = anchor_assessment(assessment, ledger_path=ledger)
    assert receipt2["event_seq"] > receipt["event_seq"]
    ok, event_count, reason = axiomere.verify_file(str(ledger))
    assert ok, reason
    assert event_count >= 4


@pytest.mark.skipif(not anchor_available(), reason="optional axiomere package not installed")
def test_cli_anchor_writes_receipt_into_metadata(tmp_path):
    assessment = _assessment_dict()
    path = tmp_path / "assessment.json"
    path.write_text(json.dumps(assessment), encoding="utf-8")
    ledger = tmp_path / "anchors.axmr"
    exit_code = cli_main(
        ["anchor", "--input", str(path), "--ledger", str(ledger), "--project", "spec-002"]
    )
    assert exit_code == 0
    written = json.loads(path.read_text())
    anchor = written["metadata"]["anchor"]
    assert anchor["assessment_sha256"] == assessment_content_digest(assessment)
    assert anchor["checkpoint_root"]
