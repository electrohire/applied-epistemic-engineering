"""Spec 003 FR-8 acceptance tests: the RT1 probes, inverted.

Each test names the probe section it inverts (spec §FR-8
Acceptance). Methodology 2.0 - the joint Spec 003 FR-8 + Spec 004
bump - is what these tests pin.
"""

from datetime import UTC, datetime

import pytest
from test_scoring import strong_evidence

from aee import (
    AEEEngine,
    AssessmentPolicy,
    Claim,
    ClaimStage,
    ClaimStatus,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    FailureMode,
    Severity,
    SourceQuality,
)
from aee.challenge import StressTester
from aee.policy import evaluate_policy
from aee.review import build_review_queue
from aee.scoring import ClaimScore, ScoringEngine

POLICY = AssessmentPolicy()
AS_OF = datetime(2026, 10, 12, tzinfo=UTC)


def ev(ref, kind=EvidenceKind.OBSERVED, q=SourceQuality.TEST,
       direction=EvidenceDirection.SUPPORTS, source_id="", observed_at=None):
    return Evidence(ref=ref, kind=kind, direction=direction,
                    source_quality=q, source_id=source_id, observed_at=observed_at)


def claim(cid, evidence, **kw):
    defaults = dict(
        text="Widget latency is 42 ms at p95 under load profile L",
        status=ClaimStatus.SUPPORTED,
        stage=ClaimStage.ACCEPTED,
        boundary=["load profile L"],
        falsification_tests=["measure p95 != 42"],
        evidence=evidence,
    )
    defaults.update(kw)
    return Claim(id=cid, **defaults)


def challenges(c):
    return [f.challenge for f in StressTester().run([c])]


# -- FR-8.3 (p5 section B): cycle-local propagation -------------------------


def test_unrelated_cycle_does_not_disable_propagation():
    weak = claim("WEAK", [ev("w", kind=EvidenceKind.ASSERTED, q=SourceQuality.MODEL)])
    strong = claim("STRONG", [strong_evidence("s1", "S1"), strong_evidence("s2", "S2")],
                   depends_on=["WEAK"])
    x = claim("X", [ev("x1"), ev("x2")], depends_on=["Y"])
    y = claim("Y", [ev("y1"), ev("y2")], depends_on=["X"])
    a = AEEEngine(policy=POLICY).assess([weak, strong, x, y])
    # STRONG is capped by WEAK exactly as if the cycle were absent.
    assert a.scores["STRONG"].propagated_score == pytest.approx(
        a.scores["WEAK"].propagated_score
    )
    assert a.scores["STRONG"].propagated_score < a.scores["STRONG"].direct_score
    assert a.scores["STRONG"].propagation_status == "propagated"
    # The cycle members are marked on their own records, and the
    # bundle-level cycle failure still fires.
    for cid in ("X", "Y"):
        assert a.scores[cid].propagation_status == "suppressed_cycle"
        assert a.scores[cid].cycle_component == ["X", "Y"]
    assert any("Circular inference" in f.challenge for f in a.failures)
    assert a.outcome != "pass"


# -- FR-8.4 (p4 section C): failure-aware verdicts ----------------------------


def test_high_failure_caps_verdict_below_accept():
    c = claim("C1", [strong_evidence("a", "S1"), strong_evidence("b", "S2")], boundary=[])
    a = AEEEngine(policy=POLICY).assess([c])
    verdict = a.verdicts["C1"]
    assert verdict.verdict.value == "challenge"
    assert any("FR-8.4" in reason and "AEE-C1" in reason for reason in verdict.reasons)
    # And the standalone entry point honors the same rule when the
    # caller supplies the failures.
    standalone = evaluate_policy(
        c, a.scores["C1"], POLICY, threshold=0.70,
        failures=c.unresolved_failures,
    )
    assert standalone.verdict.value == "challenge"


# -- FR-8.5 (p4 section D): contested gate, shared basis -----------------------


def test_weak_kind_contradiction_trips_contested_gate_standalone():
    c = claim("D2", [ev("a"), ev("b"),
                     ev("refute", kind=EvidenceKind.ASSERTED, q=SourceQuality.MODEL,
                        direction=EvidenceDirection.CONTRADICTS)])
    score = ScoringEngine().score([c])["D2"]
    assert score.contradiction_penalty < POLICY.contested_penalty_threshold
    verdict = evaluate_policy(c, score, POLICY, threshold=0.70)
    assert verdict.verdict.value == "challenge"
    assert any("FR-8.5" in reason for reason in verdict.reasons)


def test_hidden_refutation_trips_contested_gate():
    c = claim("D3", [ev("a"), ev("b"),
                     ev("refute", kind=EvidenceKind.CONTRADICTED,
                        direction=EvidenceDirection.CONTEXT)])
    score = ScoringEngine().score([c])["D3"]
    verdict = evaluate_policy(c, score, POLICY, threshold=0.70)
    assert verdict.verdict.value == "challenge"


# -- FR-8.6 (p1 section F): freshness is set-based -----------------------------


def _freshness_scores():
    def score(cid, evidence):
        return ScoringEngine().score(
            [claim(cid, evidence)], as_of=AS_OF
        )[cid].direct_score

    old = score("F1", [ev("a", observed_at="2010-01-01"), ev("b", observed_at="2010-01-01")])
    nodate = score("F2", [ev("a"), ev("b")])
    future = score("F3", [ev("a", observed_at="2999-01-01"), ev("b", observed_at="2999-01-01")])
    masked = score("F4", [ev("old", observed_at="2010-01-01"),
                          ev("fresh-junk", kind=EvidenceKind.ASSERTED, q=SourceQuality.MODEL,
                             observed_at="2026-10-01")])
    bad = score("F5", [ev("a", observed_at="not-a-date"), ev("b", observed_at="also-bad")])
    return old, nodate, future, masked, bad


def test_freshness_variants_score_no_better_than_honestly_old():
    old, nodate, future, masked, bad = _freshness_scores()
    # None of the four evasions beats honestly dated old evidence.
    assert nodate <= old
    assert future <= old
    assert bad <= old
    # One fresh item does not erase the stale half of the set: the
    # masked claim sits between fully-fresh and fully-stale, and in
    # particular does not reach the no-penalty score.
    fresh = ScoringEngine().score(
        [claim("F0", [ev("a", observed_at="2026-10-01"), ev("b", observed_at="2026-10-01")])],
        as_of=AS_OF,
    )["F0"].direct_score
    assert old < masked < fresh


def test_freshness_basis_is_named_in_notes():
    score = ScoringEngine().score(
        [claim("F9", [ev("a"), ev("b", observed_at="2010-01-01")])], as_of=AS_OF
    )["F9"]
    note = next(n for n in score.notes if "Freshness penalty" in n)
    assert "1 stale" in note and "1 unknown" in note and "FR-8.6" in note


# -- FR-8.7 (p1 section E): substance over presence ----------------------------


def test_placeholder_entries_earn_partial_credit_with_named_criteria():
    c = Claim(id="E1", text="Widget latency is 42 ms at p95 under load profile L",
              status=ClaimStatus.SUPPORTED, boundary=["x"], falsification_tests=["y"],
              evidence=[ev("a"), ev("b")])
    score = ScoringEngine().score([c])["E1"]
    assert score.falsifiability_score == 0.5
    assert score.boundary_score == 0.5
    joined = " ".join(score.notes)
    assert "fewer than four words" in joined
    assert "placeholder" in joined
    assert "no scope or limit" in joined


def test_substantive_entries_earn_full_credit():
    c = claim("E2", [ev("a"), ev("b")],
              boundary=["only within load profile L"],
              falsification_tests=["measure p95 != 42 under load"])
    score = ScoringEngine().score([c])["E2"]
    assert score.falsifiability_score == 1.0
    assert score.boundary_score == 1.0


# -- FR-8.8 + FR-8.15 (p3 sections A/B/C, p6 section D): lexicon corpus ---------


@pytest.mark.parametrize("text", [
    "The system encrypts stored passwords plus deletes backup copies nightly",
    "The widget heats the sample while-stirring it throughout the cycle",
    "The service stores user data in the EU region with retention set to 30 days plus export on request",
    "Release 2 ships the new parser together with a migration of all stored records",
    "The gateway authenticates callers as well as authorising every request",
])
def test_compound_evasion_corpus_fires(text):
    c = claim("A", [ev("a"), ev("b")], text=text)
    assert "Irreducibility challenge" in challenges(c)


@pytest.mark.parametrize("text", [
    "The parser accepts protocol version 1, 2 in compatibility mode",
    "The sensor reports temperature in degrees Celsius or Fahrenheit as configured",
    "The trial enrolled adults aged 65 and older living in Michigan",
])
def test_atomic_corpus_does_not_fire(text):
    c = claim("B", [ev("a"), ev("b")], text=text)
    assert "Irreducibility challenge" not in challenges(c)


@pytest.mark.parametrize("text", [
    "The pipeline is seamless and intuitive for operators",
    "The model delivers world-class optimal results effortlessly",
    "The cache makes lookups blazing and magical",
    "The pipeline is seamless for operators",
    "The interface is intuitive for new users",
])
def test_vague_evasion_corpus_fires(text):
    c = claim("C", [ev("a"), ev("b")], text=text)
    assert "Precision challenge" in challenges(c)


def test_vague_word_inside_proper_noun_does_not_fire():
    c = claim("C9", [ev("a"), ev("b")],
              text="The service enables Secure Boot on the gateway device")
    assert "Precision challenge" not in challenges(c)


# -- FR-8.10 (p3 section D): relevant boundary for absolutes -------------------


def test_unrelated_boundary_does_not_suppress_absolute_challenge():
    c = claim("D1", [ev("a"), ev("b")],
              text="The system always rejects every invalid token in all deployments",
              boundary=["unrelated note"])
    assert "Counterexample challenge" in challenges(c)


def test_relevant_boundary_suppresses_absolute_challenge():
    c = claim("D2", [ev("a"), ev("b")],
              text="The system always rejects every invalid token in all deployments",
              boundary=["all deployments, without exception"])
    assert "Counterexample challenge" not in challenges(c)


# -- FR-8.9 (p3 sections E/F): negation subject binding -------------------------


def test_same_subject_negation_pair_fires():
    pair = [
        claim("E3", [ev("a"), ev("b")], text="The database stores passwords in plaintext form"),
        claim("E4", [ev("a"), ev("b")], text="The database does not store passwords in plaintext form"),
    ]
    failures = StressTester().run(pair)
    assert any("Negation conflict" in f.challenge for f in failures)


def test_different_subjects_sharing_vocabulary_do_not_fire():
    pair = [
        claim("F1", [ev("a"), ev("b")], text="The audit service does not log credit card numbers at rest"),
        claim("F2", [ev("a"), ev("b")], text="The billing service logs credit card numbers at rest for reconciliation"),
    ]
    failures = StressTester().run(pair)
    assert not any("Negation conflict" in f.challenge for f in failures)


# -- FR-8.11/FR-8.12 (p4 sections H-K): review queue -----------------------------


class _View:
    def __init__(self, score_map, failures=()):
        self.verdicts = {}
        self.scores = {
            k: ClaimScore(claim_id=k, direct_score=s, propagated_score=s,
                          evidence_score=0, independence_score=0,
                          falsifiability_score=0, boundary_score=0,
                          contradiction_penalty=0)
            for k, s in score_map.items()
        }
        self.failures = list(failures)


def _failure(claim_id, severity, fid=None):
    return FailureMode(
        id=fid or f"AEE-{claim_id}-X", claim_id=claim_id, challenge="X",
        breakpoint="x", severity=severity, category="contradiction",
        recovery_hint="fix",
    )


def test_salami_slide_caught_by_baseline_not_by_consecutive_diffs():
    baseline = _View({"S": 0.90})
    prev = _View({"S": 0.90})
    current_score = 0.90
    flagged_score_channel = 0
    drift_item = None
    for _ in range(10):
        nxt = _View({"S": round(current_score - 0.04, 6)})
        consecutive = build_review_queue(prev, nxt)
        flagged_score_channel += sum(
            1 for item in consecutive.items if item.kind == "score"
        )
        q = build_review_queue(prev, nxt, baseline=baseline)
        if drift_item is None:
            drift_item = next(
                (item for item in q.items if item.kind == "cumulative_drift"), None
            )
        prev = nxt
        current_score -= 0.04
    # Every consecutive step is below materiality, so the score
    # channel never fires (a band crossing at 0.75 may legitimately
    # fire on its own channel - that is FR-8.11(b), not the salami
    # hole). The baseline drift channel catches the slide.
    assert flagged_score_channel == 0
    assert drift_item is not None
    assert drift_item.previous_score == 0.90  # measured from the baseline


def test_band_crossing_below_materiality_queues():
    q = build_review_queue(_View({"B": 0.76}), _View({"B": 0.74}))
    assert [item.kind for item in q.items] == ["band_crossing"]


def test_same_score_critical_failure_queues():
    q = build_review_queue(
        _View({"S": 0.90}),
        _View({"S": 0.90}, failures=[_failure("S", Severity.CRITICAL)]),
    )
    assert len(q.items) == 1
    assert q.items[0].kind == "failure"
    assert "CRITICAL" in q.items[0].detail.upper() or "critical" in q.items[0].detail


def test_rename_is_surfaced_as_candidate():
    q = build_review_queue(_View({"OLD-ID": 0.95}), _View({"NEW-ID": 0.10}))
    assert q.added == ["NEW-ID"] and q.removed == ["OLD-ID"]
    assert len(q.rename_candidates) == 1
    assert q.rename_candidates[0].removed_id == "OLD-ID"
    assert q.rename_candidates[0].added_id == "NEW-ID"


def test_topk_reserves_priority_for_adverse_and_reports_omissions():
    prev_map = {f"D{i}": 0.0 for i in range(20)}
    prev_map["TARGET"] = 0.90
    cur_map = {f"D{i}": 0.99 for i in range(20)}
    cur_map["TARGET"] = 0.10
    q = build_review_queue(_View(prev_map), _View(cur_map), limit=5)
    ids = [item.claim_id for item in q.items]
    assert "TARGET" in ids
    assert q.items[0].claim_id == "TARGET"  # adverse first, ahead of +0.99 decoys
    assert q.omitted == 16
    assert q.omitted_by_kind == {"score": 16}


# -- FR-8.13 (p1 section I, p6 section A): declared state + threshold -----------


def test_declared_state_distinguishes_score_records():
    from aee.model import Uncertainty

    c1 = claim("I1", [ev("a"), ev("b")])
    c2 = claim("I2", [ev("a"), ev("b")])
    c2.uncertainty = Uncertainty.INSUFFICIENT_EVIDENCE
    c2.severity = Severity.CRITICAL
    c2.status = ClaimStatus.CONTRADICTED
    scores = ScoringEngine().score([c1, c2])
    d1 = scores["I1"].to_dict()["declared_state"]
    d2 = scores["I2"].to_dict()["declared_state"]
    assert d1 != d2
    assert d2["status"] == "contradicted"
    assert d2["severity"] == "critical"
    assert d2["uncertainty"] == "insufficient_evidence"


def test_threshold_is_inclusive_on_the_unrounded_score():
    engine = AEEEngine(threshold=0.70)

    def fake(value):
        return ClaimScore(claim_id="X", direct_score=value, propagated_score=value,
                          evidence_score=0, independence_score=0,
                          falsifiability_score=0, boundary_score=0,
                          contradiction_penalty=0)

    c = claim("X", [])
    c.failures = []
    assert engine._outcome([c], {"X": fake(0.70)}) == "pass"
    # RT1-24's exact case: 0.6999996 must NOT pass - it used to
    # round to 0.70 at serialisation and cross.
    assert engine._outcome([c], {"X": fake(0.6999996)}) != "pass"


def test_methodology_version_is_bumped():
    a = AEEEngine().assess([claim("M", [ev("a"), ev("b")])])
    assert a.methodology_version == "2.0"
    assert a.to_dict()["methodology_version"] == "2.0"
