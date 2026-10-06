"""Policy gates ported from the epistemic-ledger program.

The gates layer verdicts above scores: corroboration (a single
source cannot carry a claim), forced abstention (no support, or
model self-attestation only, means the claim was never measured),
and the contested gate (live contradiction must be resolved, not
averaged away). Policy is opt-in; without one the engine's behavior
is unchanged.
"""

import pytest
from test_scoring import strong_evidence

from aee import (
    AEEEngine,
    AssessmentPolicy,
    Claim,
    ClaimStatus,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    SourceQuality,
    Verdict,
)
from aee.policy import evaluate_policy
from aee.scoring import ScoringEngine

POLICY = AssessmentPolicy()


def clean_claim(**overrides) -> Claim:
    kwargs = dict(
        id="A",
        text="Latency is below 100 ms",
        status=ClaimStatus.SUPPORTED,
        boundary=["p95 in production"],
        falsification_tests=["Observe p95 at or above 100 ms"],
        evidence=[strong_evidence("one", "S1"), strong_evidence("two", "S2")],
    )
    kwargs.update(overrides)
    return Claim(**kwargs)


def verdict_for(claim: Claim):
    score = ScoringEngine().score([claim])[claim.id]
    return evaluate_policy(claim, score, POLICY, threshold=0.70)


def test_two_independent_sources_accept() -> None:
    verdict = verdict_for(clean_claim())
    assert verdict.verdict == Verdict.ACCEPT
    assert verdict.reasons == []


def test_single_source_is_challenged_for_corroboration() -> None:
    claim = clean_claim(evidence=[strong_evidence("one", "S1")])
    verdict = verdict_for(claim)
    assert verdict.verdict == Verdict.CHALLENGE
    assert any("corroboration" in reason for reason in verdict.reasons)


def test_no_evidence_abstains() -> None:
    verdict = verdict_for(clean_claim(evidence=[]))
    assert verdict.verdict == Verdict.ABSTAIN
    assert verdict.reasons == ["no supporting evidence"]


def test_model_self_attestation_only_abstains() -> None:
    claim = clean_claim(
        evidence=[
            Evidence(
                ref="model-note",
                source_id="S1",
                kind=EvidenceKind.ASSERTED,
                source_quality=SourceQuality.MODEL,
            ),
            Evidence(
                ref="model-note-2",
                source_id="S2",
                kind=EvidenceKind.ASSERTED,
                source_quality=SourceQuality.MODEL,
            ),
        ]
    )
    verdict = verdict_for(claim)
    assert verdict.verdict == Verdict.ABSTAIN
    assert verdict.reasons == ["support is model self-attestation only"]


def test_abstention_precedes_challenge() -> None:
    # No support but a live contradiction: the claim cannot be
    # judged at all, so it abstains rather than challenges.
    claim = clean_claim(
        evidence=[
            Evidence(
                ref="contra",
                kind=EvidenceKind.OBSERVED,
                direction=EvidenceDirection.CONTRADICTS,
                source_quality=SourceQuality.PRIMARY,
            ),
        ]
    )
    verdict = verdict_for(claim)
    assert verdict.verdict == Verdict.ABSTAIN


def test_contested_claim_is_challenged() -> None:
    claim = clean_claim()
    claim.add_evidence(
        Evidence(
            ref="contra",
            kind=EvidenceKind.OBSERVED,
            direction=EvidenceDirection.CONTRADICTS,
            source_quality=SourceQuality.PRIMARY,
        )
    )
    verdict = verdict_for(claim)
    assert verdict.verdict == Verdict.CHALLENGE
    assert any("contested" in reason for reason in verdict.reasons)


def test_engine_without_policy_has_no_verdicts() -> None:
    result = AEEEngine().assess([clean_claim()])
    assert result.outcome == "pass"
    assert result.verdicts == {}
    assert result.to_dict()["verdicts"] == {}


def test_engine_all_accept_still_passes() -> None:
    result = AEEEngine(policy=POLICY).assess([clean_claim()])
    assert result.outcome == "pass"
    assert result.verdicts["A"].verdict == Verdict.ACCEPT
    assert result.to_dict()["verdicts"]["A"]["verdict"] == "accept"


def test_engine_corroboration_challenge_demotes_pass() -> None:
    claim = clean_claim(evidence=[strong_evidence("one", "S1")])
    result = AEEEngine(policy=POLICY).assess([claim])
    assert result.verdicts["A"].verdict == Verdict.CHALLENGE
    assert result.outcome == "iterate"
    assert not result.healthy


def test_engine_abstention_blocks_pass() -> None:
    claims = [clean_claim(), clean_claim(id="B", evidence=[])]
    result = AEEEngine(policy=POLICY).assess(claims)
    assert result.verdicts["B"].verdict == Verdict.ABSTAIN
    assert result.outcome != "pass"
    assert "1 abstain" in result.summary


def test_policy_validation() -> None:
    with pytest.raises(ValueError):
        AssessmentPolicy(min_independent_sources=0)
    with pytest.raises(ValueError):
        AssessmentPolicy(contested_penalty_threshold=0.8)
    with pytest.raises(ValueError):
        AssessmentPolicy(contested_penalty_threshold=-0.1)


def test_relaxed_policy_accepts_single_source() -> None:
    policy = AssessmentPolicy(min_independent_sources=1)
    claim = clean_claim(evidence=[strong_evidence("one", "S1")])
    score = ScoringEngine().score([claim])[claim.id]
    verdict = evaluate_policy(claim, score, policy, threshold=0.70)
    assert verdict.verdict == Verdict.ACCEPT
