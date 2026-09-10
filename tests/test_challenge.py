"""Tests for the deterministic challenge logic and the ``challenge`` CLI projection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aee import Claim, ClaimKind, ClaimStatus, Evidence, EvidenceDirection, EvidenceKind, cli
from aee.challenge import StressTester
from aee.model import SourceQuality


def categories(claim: Claim) -> set[str]:
    return {item.category for item in StressTester().run([claim])}


def test_empty_claim_is_critical() -> None:
    claim = Claim(id="CLM-1", text="")
    failures = StressTester().run([claim])
    assert failures[0].severity.value == "critical"


@pytest.mark.parametrize("word", ["fast", "scalable", "reasonable", "secure"])
def test_vague_terms(word: str) -> None:
    claim = Claim(id="CLM-1", text=f"The system is {word}", boundary=["production"])
    assert "ambiguous_requirement" in categories(claim)


def test_missing_boundary() -> None:
    assert "assumption_unvalidated" in categories(Claim(id="CLM-1", text="Latency is 10 ms"))


def test_supported_claim_requires_observed_evidence() -> None:
    claim = Claim(
        id="CLM-1",
        text="Latency is 10 ms",
        status=ClaimStatus.SUPPORTED,
        boundary=["test environment"],
        falsification_tests=["observe latency above 10 ms"],
        evidence=[Evidence(ref="agent", kind=EvidenceKind.ASSERTED)],
    )
    assert "unsupported_claim" in categories(claim)


def test_model_self_attestation() -> None:
    claim = Claim(
        id="CLM-1",
        text="The test passed",
        boundary=["current run"],
        evidence=[
            Evidence(
                ref="model-output",
                kind=EvidenceKind.ASSERTED,
                source_quality=SourceQuality.MODEL,
            )
        ],
    )
    assert "unverified_assertion" in categories(claim)


def test_compliance_requires_authority_or_test() -> None:
    claim = Claim(
        id="COMP-1",
        text="The system complies with Policy X",
        kind=ClaimKind.COMPLIANCE,
        boundary=["release 1"],
    )
    assert "missing_evidence" in categories(claim)


def test_counterevidence_is_preserved() -> None:
    claim = Claim(
        id="CLM-1",
        text="The API is available",
        boundary=["region A"],
        evidence=[
            Evidence(
                ref="outage.log",
                kind=EvidenceKind.OBSERVED,
                direction=EvidenceDirection.CONTRADICTS,
            )
        ],
    )
    assert "contradiction" in categories(claim)


def test_dependency_cycle() -> None:
    claims = [
        Claim(id="A", text="A", boundary=["x"], depends_on=["B"]),
        Claim(id="B", text="B", boundary=["x"], depends_on=["A"]),
    ]
    failures = StressTester().run(claims)
    assert any("Circular" in item.challenge for item in failures)


def test_missing_dependency() -> None:
    claim = Claim(id="A", text="A", boundary=["x"], depends_on=["MISSING"])
    assert "provenance_gap" in categories(claim)


def test_declared_conflict() -> None:
    claims = [
        Claim(id="A", text="Feature is enabled", boundary=["x"], conflicts_with=["B"]),
        Claim(id="B", text="Feature is disabled", boundary=["x"]),
    ]
    failures = StressTester().run(claims)
    assert any(item.category == "contradiction" for item in failures)


# --- CLI projection tests ---


def _write_claims(tmp_path: Path, claims: list[dict]) -> Path:
    path = tmp_path / "claims.json"
    path.write_text(json.dumps({"schema_version": "1.0", "claims": claims}), encoding="utf-8")
    return path


def _run_to_json(input_path: Path, output_path: Path) -> str:
    cli.main(["challenge", "--input", str(input_path), "--output", str(output_path)])
    return output_path.read_text(encoding="utf-8")


def test_challenge_emits_failure_projection(tmp_path: Path) -> None:
    # A claim with no explicit boundary deterministically triggers a Boundary challenge.
    claims = [
        {
            "id": "REQ-001",
            "text": "The service responds quickly",
            "kind": "requirement",
            "status": "supported",
            "boundary": [],
            "falsification_tests": ["A load test observes slow responses"],
            "source_ref": "spec.md#REQ-001",
            "uncertainty": "low",
            "evidence": [],
        }
    ]
    input_path = _write_claims(tmp_path, claims)
    output_path = tmp_path / "challenge.json"

    code = cli.main(["challenge", "--input", str(input_path), "--output", str(output_path)])

    value = json.loads(output_path.read_text(encoding="utf-8"))
    assert value["mode"] == "challenge"
    assert value["project"] == "project"
    assert value["phase"] == "after_plan"
    assert value["outcome"] in {"pass", "warn", "iterate", "clarify", "gather_evidence", "block"}

    failure_ids = [failure["id"] for failure in value["failures"]]
    assert len(failure_ids) == len(set(failure_ids)), "failure ids must be unique"
    categories = {failure["category"] for failure in value["failures"]}
    assert "assumption_unvalidated" in categories

    # Every unresolved failure must have a bounded, verifiable recovery proposal.
    recovery_failure_ids = {proposal["failure_id"] for proposal in value["recoveries"]}
    unresolved_failure_ids = {
        failure["id"] for failure in value["failures"] if not failure["resolved"]
    }
    assert recovery_failure_ids == unresolved_failure_ids
    for proposal in value["recoveries"]:
        assert proposal["verification"]

    # The projection is a subset of the full assessment: no scoring keys leak through.
    assert "scores" not in value
    assert "claims" not in value
    assert code in {0, 1, 2}


def test_challenge_is_deterministic(tmp_path: Path) -> None:
    claims = [
        {
            "id": "REQ-001",
            "text": "The service responds quickly",
            "kind": "requirement",
            "status": "supported",
            "boundary": [],
            "falsification_tests": ["A load test observes slow responses"],
            "source_ref": "spec.md#REQ-001",
            "uncertainty": "low",
            "evidence": [],
        }
    ]
    input_path = _write_claims(tmp_path, claims)

    first = json.loads(_run_to_json(input_path, tmp_path / "a.json"))
    second = json.loads(_run_to_json(input_path, tmp_path / "b.json"))

    # Strip the timestamp; everything else must be identical across runs.
    first.pop("created_at", None)
    second.pop("created_at", None)
    assert first == second
