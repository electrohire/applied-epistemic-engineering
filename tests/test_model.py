import json

import pytest

from aee import Claim, ClaimKind, ClaimStatus, ConfidenceBand, Evidence, EvidenceKind
from aee.schemas import assessment_schema_path


def test_claim_requires_id() -> None:
    with pytest.raises(ValueError, match="claim id"):
        Claim(id="", text="x")


@pytest.mark.parametrize(
    ("score", "band"),
    [(0.0, "unknown"), (0.1, "low"), (0.45, "medium"), (0.75, "high"), (1.0, "high")],
)
def test_confidence_bands(score: float, band: str) -> None:
    assert ConfidenceBand.from_score(score).value == band


def test_confidence_range() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        Claim(id="C-1", text="x", confidence=1.1)


def test_claim_round_trip() -> None:
    claim = Claim(
        id="REQ-1",
        text="The API returns 200",
        kind=ClaimKind.REQUIREMENT,
        status=ClaimStatus.SUPPORTED,
        boundary=["valid request"],
        evidence=[Evidence(ref="test.log", kind=EvidenceKind.OBSERVED)],
        confidence=0.8,
    )
    value = claim.to_dict()
    json.dumps(value)
    restored = Claim.from_dict(value)
    assert restored.id == claim.id
    assert restored.kind is ClaimKind.REQUIREMENT
    assert restored.evidence[0].kind is EvidenceKind.OBSERVED


def test_assessment_schema_is_packaged() -> None:
    assert assessment_schema_path().is_file()
