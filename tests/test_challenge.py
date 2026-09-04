import pytest

from aee import Claim, ClaimKind, ClaimStatus, Evidence, EvidenceDirection, EvidenceKind
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
