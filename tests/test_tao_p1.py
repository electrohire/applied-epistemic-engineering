"""Spec 004 Phase P1 acceptance tests: decomposition (R2),
attribution (R4), and priority (R7).

Against plan.md Phase P1: a scored headline claim with no attribution
claim must be impossible to produce silently; a contested attribution
caps the parent at `checked`; priority is a read over the ledger and
priority citations resolve by recomputed entry hash.
"""

import pytest
from test_scoring import strong_evidence

from aee import (
    AEEEngine,
    AssessmentPolicy,
    Claim,
    ClaimStage,
    ClaimStatus,
    Evidence,
    EvidenceKind,
    FailureMode,
    Severity,
    SourceQuality,
)
from aee.decomposition import (
    attribution_contests,
    effective_stage_overrides,
    missing_roles,
)
from aee.evidence_check import check_evidence
from aee.ledger import HashChainLedger
from aee.priority import claim_priority, priority_index

POLICY = AssessmentPolicy()
ROLES = [
    "statement-fidelity",
    "evidence-verification",
    "novelty",
    "attribution",
    "significance",
]


def subclaim(role: str, **overrides) -> Claim:
    kwargs = dict(
        id=f"SUB-{role}",
        text=f"Sub-claim discharging {role}",
        status=ClaimStatus.SUPPORTED,
        stage=ClaimStage.ACCEPTED,
        role=role,
        boundary=["scope of the sub-claim"],
        falsification_tests=[f"Show the {role} sub-claim is wrong with a record"],
        evidence=[
            strong_evidence(f"{role}-one", f"{role}-S1"),
            strong_evidence(f"{role}-two", f"{role}-S2"),
        ],
    )
    kwargs.update(overrides)
    return Claim(**kwargs)


def headline(roles=ROLES, **overrides) -> Claim:
    kwargs = dict(
        id="HEAD",
        text="The headline result holds",
        status=ClaimStatus.SUPPORTED,
        stage=ClaimStage.ACCEPTED,
        headline=True,
        depends_on=[f"SUB-{role}" for role in roles],
        boundary=["the stated deployment"],
        falsification_tests=["Show the headline result fails in the stated deployment"],
        # Spec 004 R5.1 (P2): the third item is human-paced, so the
        # machine-only gate does not cap the headline at `checked`
        # and mask the decomposition behavior under test.
        evidence=[
            strong_evidence("h-one", "HS1"),
            strong_evidence("h-two", "HS2"),
            Evidence(
                ref="h-review",
                source_id="head-reviewer",
                kind=EvidenceKind.OBSERVED,
                source_quality=SourceQuality.PRIMARY,
            ),
        ],
    )
    kwargs.update(overrides)
    return Claim(**kwargs)


def bundle(roles=ROLES, **headline_overrides):
    return [headline(roles, **headline_overrides)] + [subclaim(role) for role in roles]


# -- R2: decomposition ----------------------------------------------------


def test_complete_decomposition_is_silent():
    claims = bundle()
    by_id = {claim.id: claim for claim in claims}
    assert missing_roles(claims[0], by_id) == []
    assessment = AEEEngine(policy=POLICY).assess(claims)
    assert not [
        f for f in assessment.failures if f.category == "decomposition_incomplete"
    ]
    assert assessment.reported_statuses["HEAD"] == "supported"


def test_missing_role_fails_loudly_and_caps_stage_at_created():
    claims = bundle(roles=ROLES[:-1])  # significance never written
    assessment = AEEEngine(policy=POLICY).assess(claims)
    failures = [f for f in assessment.failures if f.category == "decomposition_incomplete"]
    assert len(failures) == 1
    assert failures[0].severity == Severity.HIGH
    assert "significance" in failures[0].challenge
    # R2.3: the parent is treated as `created` - draft report, no verdict.
    assert assessment.reported_statuses["HEAD"] == "draft"
    assert assessment.verdicts["HEAD"].verdict.value == "unjudged"


def test_unlinked_role_does_not_count():
    # All five role claims exist in the bundle, but the parent does
    # not link the attribution one: omission by unlinking is still
    # incomplete (the audit's corpus pattern).
    claims = [headline(roles=[r for r in ROLES if r != "attribution"])] + [
        subclaim(role) for role in ROLES
    ]
    assessment = AEEEngine(policy=POLICY).assess(claims)
    assert [
        f for f in assessment.failures if f.category == "decomposition_incomplete"
    ]
    assert assessment.reported_statuses["HEAD"] == "draft"


def test_non_headline_claims_need_no_decomposition():
    claims = [headline(headline=False, depends_on=[])]
    assessment = AEEEngine(policy=POLICY).assess(claims)
    assert not [
        f for f in assessment.failures if f.category == "decomposition_incomplete"
    ]


# -- R4: attribution -------------------------------------------------------


def test_contested_attribution_caps_parent_at_checked():
    claims = bundle()
    by_id = {claim.id: claim for claim in claims}
    by_id["SUB-attribution"].status = ClaimStatus.CONTRADICTED
    assert attribution_contests(claims) == {"HEAD": "SUB-attribution"}
    assert effective_stage_overrides(claims) == {"HEAD": ClaimStage.CHECKED}
    assessment = AEEEngine(policy=POLICY).assess(claims)
    # Stored stage is accepted; the report is capped at checked's
    # vocabulary: no `supported`, verdict ceiling challenge, and the
    # cap record names the attribution claim.
    assert assessment.reported_statuses["HEAD"] == "partially_supported"
    assert assessment.verdicts["HEAD"].verdict.value == "challenge"
    cap = next(cap for cap in assessment.stage_caps if cap.claim_id == "HEAD")
    assert "SUB-attribution" in cap.note
    assert "contested" in cap.note


def test_contested_via_high_contradiction_failure():
    claims = bundle()
    by_id = {claim.id: claim for claim in claims}
    by_id["SUB-attribution"].failures.append(
        FailureMode(
            id="F-ATTR",
            claim_id="SUB-attribution",
            challenge="Rival lab's earlier record contradicts the attribution",
            breakpoint="priority disputed",
            severity=Severity.HIGH,
            category="contradiction",
        )
    )
    assert attribution_contests(claims) == {"HEAD": "SUB-attribution"}


def test_uncontested_attribution_does_not_cap():
    claims = bundle()
    assert attribution_contests(claims) == {}
    assert effective_stage_overrides(claims) == {}


# -- R7: priority ------------------------------------------------------------


def _assessed_ledger(tmp_path):
    claims = [headline(headline=False, depends_on=[])]
    assessment = AEEEngine().assess(claims, project="p1-test")
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    entry = ledger.append_assessment(assessment)
    return ledger, entry


def test_priority_record_is_earliest_registration(tmp_path):
    ledger, entry = _assessed_ledger(tmp_path)
    record = claim_priority(ledger, "HEAD")
    assert record is not None
    assert record["sequence"] == entry["sequence"]
    assert record["entry_hash"] == entry["entry_hash"]
    assert record["timestamp"]
    assert claim_priority(ledger, "NEVER-REGISTERED") is None
    assert set(priority_index(ledger)) == {"HEAD"}


def test_priority_evidence_resolves_by_entry_hash(tmp_path):
    ledger, entry = _assessed_ledger(tmp_path)
    citing = Claim(
        id="CITE",
        text="This work was public first",
        evidence=[
            Evidence(
                ref=f"ledger:ledger.jsonl#{entry['sequence']}",
                kind=EvidenceKind.OBSERVED,
                source_quality=SourceQuality.PRIMARY,
                content_hash=entry["entry_hash"],
            )
        ],
    )
    report = check_evidence([citing], tmp_path)
    item = report.items[0]
    assert item.status == "verified"
    assert citing.evidence[0].content_hash_status == "verified"


def test_priority_evidence_rejects_wrong_hash_and_missing_entry(tmp_path):
    ledger, entry = _assessed_ledger(tmp_path)
    wrong_hash = Claim(
        id="CITE",
        text="Cites a hash that is not the entry's",
        evidence=[
            Evidence(
                ref=f"ledger:ledger.jsonl#{entry['sequence']}",
                kind=EvidenceKind.OBSERVED,
                content_hash="0" * 64,
            )
        ],
    )
    report = check_evidence([wrong_hash], tmp_path)
    assert report.items[0].status == "failed"
    assert any(
        f.category == "content_hash_mismatch" for f in report.items[0].findings
    )
    missing = Claim(
        id="CITE2",
        text="Cites a sequence that does not exist",
        evidence=[Evidence(ref="ledger:ledger.jsonl#99", kind=EvidenceKind.OBSERVED)],
    )
    report = check_evidence([missing], tmp_path)
    assert report.items[0].status == "failed"
    assert any(
        f.category == "ledger_entry_missing" for f in report.items[0].findings
    )


def test_r7_3_freshness_ignores_registration_and_stage():
    # R7.3(a): freshness judges evidence age by observed_at only.
    # Two identical claims differing only in stage/registration
    # trappings must score identically - registering early (or
    # advancing stage) can neither stale nor freshen a claim.
    from aee.scoring import ScoringEngine

    def aged_claim(stage):
        return Claim(
            id="AGED",
            text="A result measured long ago",
            stage=stage,
            boundary=["lab conditions"],
            falsification_tests=["Re-run the measurement and get a different result"],
            evidence=[
                Evidence(
                    ref="old-measurement",
                    kind=EvidenceKind.OBSERVED,
                    source_quality=SourceQuality.TEST,
                    source_id="LAB",
                    observed_at="2020-01-01",
                )
            ],
        )

    created = ScoringEngine().score([aged_claim(ClaimStage.CREATED)])["AGED"]
    accepted = ScoringEngine().score([aged_claim(ClaimStage.ACCEPTED)])["AGED"]
    assert created.direct_score == accepted.direct_score
    assert created.notes == accepted.notes
