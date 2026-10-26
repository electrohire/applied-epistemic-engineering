"""Spec 003 Phase 2 - FR-2, the score-inflation kit (T201-T209).

Every test inverts a red-team probe: RT1 p1 sections B/C/D/G/J, p6
section C, the p7 kill chain end-to-end, RT1-04/06/13/14/21/23, and the
RT2 p04 section 1 string-list fixture (score side - strict loading
already rejects the bundle; nothing char-exploded may reach a score).

Held behavior is pinned too: honest bundles keep the scores they had
before this phase (test_control_bundle_scores_unchanged, values
captured from main @ 0c8600a before the change).
"""

from __future__ import annotations

import pytest

from aee import (
    AEEEngine,
    Claim,
    ClaimStage,
    ClaimStatus,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    ScoringEngine,
    SourceQuality,
)
from aee.model import BundleValidationError
from aee.policy import AssessmentPolicy, corroboration_sources, evaluate_policy

TEXT = "Widget latency is 42 ms at p95 under load profile L"


def ev(
    ref: str,
    kind: EvidenceKind = EvidenceKind.OBSERVED,
    q: SourceQuality = SourceQuality.TEST,
    direction: EvidenceDirection = EvidenceDirection.SUPPORTS,
    source_id: str = "",
) -> Evidence:
    return Evidence(ref=ref, kind=kind, direction=direction, source_quality=q, source_id=source_id)


def claim(
    cid: str,
    evidence: list[Evidence],
    status: ClaimStatus = ClaimStatus.SUPPORTED,
    text: str = TEXT,
) -> Claim:
    return Claim(
        id=cid,
        text=text,
        status=status,
        # Spec 004 migration of this factory: these fixtures model
        # ratified claims, which in the stage vocabulary sit at
        # `accepted` (below it, verdicts/outcomes are stage-capped
        # and the FR-2/FR-3 gate behavior under test is unreachable).
        stage=ClaimStage.ACCEPTED,
        boundary=["load profile L"],
        falsification_tests=["measure p95 != 42"],
        evidence=evidence,
    )


def score(c: Claim) -> object:
    return ScoringEngine().score([c])[c.id]


# --- T201 / RT1-02: deduplication (p1 section B) -------------------------------


def test_duplicate_evidence_contributes_once() -> None:
    one = score(claim("B1", [ev("s.pdf", kind=EvidenceKind.ASSERTED, q=SourceQuality.MODEL)]))
    many = score(
        claim(
            "B2",
            [ev("s.pdf", kind=EvidenceKind.ASSERTED, q=SourceQuality.MODEL) for _ in range(20)],
        )
    )
    # Before the FR-2 fix: 1x scored 0.3775, 20x scored 0.702833 (past
    # 0.70). Methodology 2.0 (FR-8): both move to 0.2275 - undated
    # evidence counts unknown/stale for freshness (FR-8.6) and the
    # label-only boundary earns partial credit (FR-8.7); the dedup
    # invariant itself (many == one) is unchanged.
    assert many.direct_score == pytest.approx(one.direct_score)
    assert one.direct_score == pytest.approx(0.2275)
    assert many.evidence_score == one.evidence_score
    assert any("Duplicate evidence: 19 item(s) collapsed" in note for note in many.notes)


def test_cosmetic_ref_variants_of_one_item_deduplicate() -> None:
    s = score(claim("B3", [ev("s.pdf"), ev("./S.PDF ")]))
    single = score(claim("B4", [ev("s.pdf")]))
    assert s.evidence_score == single.evidence_score
    assert any("collapsed" in note for note in s.notes)


def test_same_ref_different_kind_is_not_a_duplicate() -> None:
    # Dedup must not hide a genuine second epistemic act behind a
    # cosmetic match: observed + asserted from the same ref both count.
    both = score(
        claim(
            "B5",
            [ev("s.pdf"), ev("s.pdf", kind=EvidenceKind.ASSERTED, q=SourceQuality.HUMAN)],
        )
    )
    assert both.evidence_score == 1.0  # observed/test alone already saturates


# --- T207 / RT1-23: empty ref earns nothing (p1 section D) ---------------------


def test_empty_ref_earns_no_weight() -> None:
    s = score(claim("D1", [ev("")]))
    # Before the fix: evidence=1.0, direct=0.8 from a fabricated empty ref.
    assert s.evidence_score == 0.0
    assert s.independence_score == 0.0
    assert any("empty" in note and "no evidence weight" in note for note in s.notes)


def test_empty_ref_alongside_real_evidence_adds_nothing() -> None:
    with_empty = score(claim("D2", [ev("real.pdf"), ev("")]))
    without = score(claim("D3", [ev("real.pdf")]))
    assert with_empty.direct_score == without.direct_score


# --- T204 / RT1-06: zero-weight items mint nothing (p1 section C) ---------------


def test_zero_weight_items_mint_no_independence() -> None:
    junk = [
        ev(f"junk{i}", kind=EvidenceKind.UNSUPPORTED, q=SourceQuality.UNKNOWN) for i in range(2)
    ]
    s = score(claim("C1", junk))
    # Before the fix: independence=1.0 from two zero-weight items.
    assert s.evidence_score == 0.0
    assert s.independence_score == 0.0


def test_zero_weight_junk_does_not_pad_a_real_source() -> None:
    mixed = score(
        claim(
            "C3",
            [ev("real.pdf"), ev("junk", kind=EvidenceKind.CONTRADICTED, q=SourceQuality.UNKNOWN)],
        )
    )
    # Before the fix: the contradicted-kind junk item lifted the real
    # item's independence from 0.5 to 1.0 (and direct to 1.0).
    assert mixed.independence_score == 0.5


def test_zero_weight_items_mint_no_policy_corroboration() -> None:
    junk = [
        ev(f"junk{i}", kind=EvidenceKind.UNSUPPORTED, q=SourceQuality.UNKNOWN) for i in range(2)
    ]
    c = claim("C4", junk)
    assert corroboration_sources(c) == set()
    verdict = evaluate_policy(c, score(c), AssessmentPolicy(), threshold=0.70)  # type: ignore[arg-type]
    assert any("corroboration: 0 independent" in reason for reason in verdict.reasons)


def test_context_items_never_corroborate() -> None:
    items = [
        ev("a"),
        ev("ctx", direction=EvidenceDirection.CONTEXT),
        ev("ctx2", direction=EvidenceDirection.CONTEXT),
    ]
    c = claim("C5", items)
    assert corroboration_sources(c) == {"a"}


# --- T205 / RT1-14: source normalisation in both gates (p6 section C) ----------


@pytest.mark.parametrize(
    "refs",
    [
        ["study.pdf", "./study.pdf"],
        ["study.pdf", "Study.PDF"],
        ["https://x.org/s", "https://x.org/s/"],
        ["s.pdf", "s.pdf "],
    ],
)
def test_same_origin_variants_count_once_everywhere(refs: list[str]) -> None:
    c = claim("N1", [ev(r) for r in refs])
    s = score(c)
    # Before the fix: every pair scored independence=1.0, policy ACCEPT.
    assert s.independence_score == 0.5
    assert corroboration_sources(c) == {refs[0].strip().lower().rstrip("/")}
    verdict = evaluate_policy(c, s, AssessmentPolicy(), threshold=0.70)  # type: ignore[arg-type]
    assert verdict.verdict.value == "challenge"
    assert any("corroboration: 1 independent" in reason for reason in verdict.reasons)


def test_genuinely_distinct_sources_still_count_twice() -> None:
    c = claim("N2", [ev("a.pdf"), ev("b.pdf")])
    assert score(c).independence_score == 1.0
    assert len(corroboration_sources(c)) == 2


# --- T202 / RT1-03: polarity coherence (p1 section G) ---------------------------


def _laundering_claim(direction: EvidenceDirection) -> Claim:
    return claim(
        "G1",
        [
            ev("a"),
            ev("b"),
            ev(
                "refutation",
                kind=EvidenceKind.CONTRADICTED,
                q=SourceQuality.TEST,
                direction=direction,
            ),
        ],
    )


def test_contradiction_relabelled_context_surfaces() -> None:
    honest = AEEEngine().assess([_laundering_claim(EvidenceDirection.CONTRADICTS)])
    laundered = AEEEngine().assess([_laundering_claim(EvidenceDirection.CONTEXT)])
    # Before the fix: context version scored 1.0, outcome pass, ZERO
    # failures. Now the laundering produces the same routing as the
    # honest label - it cannot buy a cleaner outcome than honesty.
    assert honest.outcome == laundered.outcome == "clarify"
    assert any(
        f.challenge == "Polarity coherence challenge" and f.category == "contradiction"
        for f in laundered.failures
    )
    # The numeric score remains direction-governed (scoring does not
    # invent a penalty for an item it was told is context) - what the
    # fix removes is the SILENCE: the mismatch is on the score record
    # as well as in the routing.
    assert any("Polarity incoherence" in note for note in laundered.scores["G1"].notes)


def test_contradiction_relabelled_supports_surfaces_and_earns_nothing() -> None:
    c = _laundering_claim(EvidenceDirection.SUPPORTS)
    a = AEEEngine().assess([c])
    assert a.outcome == "clarify"
    # The mislabelled item is zero-weight as support (contradicted kind)
    # and excluded from corroboration: the claim's support is a+b only.
    assert corroboration_sources(c) == {"a", "b"}


def test_honest_observed_counterevidence_is_not_incoherent() -> None:
    # The reverse combination is honest labelling, not a trick: an
    # observed measurement routed 'contradicts' must NOT draw the
    # polarity challenge (FR-2.2 is one-directional by design).
    a = AEEEngine().assess([_laundering_claim(EvidenceDirection.CONTRADICTS)])
    assert not any(f.challenge == "Polarity coherence challenge" for f in a.failures)
    assert any(f.challenge == "Counterevidence challenge" for f in a.failures)


# --- T203 / RT1-04: draft outcome cap ------------------------------------------


def test_draft_with_perfect_score_cannot_pass() -> None:
    c = claim("DR1", [ev("a"), ev("b")], status=ClaimStatus.DRAFT)
    a = AEEEngine().assess([c])
    # Methodology 2.0 (FR-8): the once-"perfect" fixture scores
    # 0.85 - its evidence is undated (FR-8.6) and its boundary is a
    # label (FR-8.7). The score is still NOT silenced by the draft
    # status; only the outcome is capped.
    assert a.scores["DR1"].direct_score == pytest.approx(0.85)
    assert a.outcome == "iterate"  # the outcome is capped
    assert a.healthy is False
    assert any(f.category == "draft_cap" for f in a.failures)
    assert "Draft cap:" in a.summary and "FR-2.3" in a.summary


def test_draft_verdict_capped_below_accept() -> None:
    c = claim("DR2", [ev("a"), ev("b")], status=ClaimStatus.DRAFT)
    a = AEEEngine(policy=AssessmentPolicy()).assess([c])
    assert a.verdicts["DR2"].verdict.value == "challenge"
    assert any("draft" in reason for reason in a.verdicts["DR2"].reasons)


def test_ratified_claim_is_not_capped() -> None:
    # Spec 004 R5.1 (P2): the third item is human-paced (primary
    # source), so the machine-only gate does not cap this ratified
    # fixture at `checked`.
    c = claim(
        "DR3",
        [ev("a"), ev("b"), ev("c", q=SourceQuality.PRIMARY)],
        status=ClaimStatus.SUPPORTED,
    )
    a = AEEEngine(policy=AssessmentPolicy()).assess([c])
    assert a.outcome == "pass"
    assert a.verdicts["DR3"].verdict.value == "accept"


def test_draft_cap_does_not_mask_worse_outcomes() -> None:
    # A draft carrying a HIGH contradiction routes to clarify on the
    # contradiction's own merits - the cap is a ceiling reached only
    # when nothing worse applies, never a mask over worse news.
    c = claim(
        "DR4",
        [ev("a"), ev("b", direction=EvidenceDirection.CONTRADICTS)],
        status=ClaimStatus.DRAFT,
    )
    a = AEEEngine().assess([c])
    assert a.outcome == "clarify"


# --- T206 / RT1-13: widened model self-attestation (p4 section B) ---------------


def test_model_only_gate_survives_inferred_relabel() -> None:
    pure = claim(
        "M1",
        [ev("m", kind=EvidenceKind.ASSERTED, q=SourceQuality.MODEL)],
        status=ClaimStatus.SUPPORTED,
    )
    relabelled = claim(
        "M2",
        [ev("m", kind=EvidenceKind.INFERRED, q=SourceQuality.MODEL)],
        status=ClaimStatus.SUPPORTED,
    )
    for c in (pure, relabelled):
        a = AEEEngine(policy=AssessmentPolicy()).assess([c])
        # Before the fix: the inferred relabel switched the gate off
        # (challenge on score grounds only); now both abstain.
        assert a.verdicts[c.id].verdict.value == "abstain"
        assert any(f.challenge == "Independent-evidence challenge" for f in a.failures)


def test_human_self_report_does_not_launder_model_support() -> None:
    # p6 section B / p7 substance: 20 model items + 1 human assertion.
    # The human item makes "model-ONLY" literally false, so abstention
    # does not apply - the claim is instead held by evidence-grounding
    # (no observed support), corroboration (ONE source after dedup and
    # normalisation), and its own score.
    evs = [ev("self-report", kind=EvidenceKind.ASSERTED, q=SourceQuality.HUMAN)]
    evs += [ev("model-out", kind=EvidenceKind.ASSERTED, q=SourceQuality.MODEL) for _ in range(20)]
    c = claim("M3", evs)
    a = AEEEngine(policy=AssessmentPolicy()).assess([c])
    assert a.outcome == "gather_evidence"
    assert a.verdicts["M3"].verdict.value == "challenge"
    # Two genuinely distinct sources are declared (self-report and
    # model-out), so corroboration honestly counts 2; the claim is
    # held by its score (0.569 < 0.70 after dedup) instead.
    assert corroboration_sources(c) == {"self-report", "model-out"}
    assert any("below the 0.70" in r for r in a.verdicts["M3"].reasons)


# --- T209 / p7: the kill chain, end to end -------------------------------------


def test_p7_kill_chain_both_statuses() -> None:
    evs = [ev("self-report", kind=EvidenceKind.ASSERTED, q=SourceQuality.HUMAN)]
    evs += [ev("model-out", kind=EvidenceKind.ASSERTED, q=SourceQuality.MODEL) for _ in range(20)]
    # Before the fix: supported -> gather_evidence/0.837/accept by one
    # challenge's luck; draft -> pass/healthy/accept, zero failures.
    # After: supported routes gather_evidence on the grounding
    # challenge; the draft routes iterate - the grounding challenge is
    # draft-exempt by design (a draft has not claimed support), and
    # the FR-2.3 cap plus the below-threshold score hold it there.
    for status, expected_outcome in (
        (ClaimStatus.SUPPORTED, "gather_evidence"),
        (ClaimStatus.DRAFT, "iterate"),
    ):
        c = claim("K1", list(evs), status=status)
        a = AEEEngine(policy=AssessmentPolicy()).assess([c])
        s = a.scores["K1"]
        assert a.outcome == expected_outcome
        assert a.healthy is False
        assert a.verdicts["K1"].verdict.value != "accept"
        # Dedup collapses the 20 copies; what remains is one model
        # assertion plus one human assertion from two distinct
        # sources. Under methodology 2.0 (FR-8) the same composition
        # scores 0.4189375: undated evidence counts unknown/stale
        # (FR-8.6) and the label-only boundary earns partial credit
        # (FR-8.7). Before the FR-2 fix both statuses scored 0.837
        # and the draft passed outright.
        assert s.direct_score == pytest.approx(0.4189375)
        assert any("collapsed" in note for note in s.notes)


# --- T208 / RT1-21: cross-claim shared evidence (p1 section J) ------------------


def _split_claims(independent: bool = False) -> list[Claim]:
    claims = []
    for i in range(5):
        items = [ev("a"), ev("b")]
        if independent:
            items[0].independent_of = ["b"]
            items[1].independent_of = ["a"]
        claims.append(claim(f"J{i}", items, text=f"Widget metric {i} equals {i}2 units under L"))
    return claims


def test_shared_evidence_reported_in_summary() -> None:
    a = AEEEngine().assess(_split_claims())
    # Scores are NOT capped by FR-2.8 in this phase (reporting only):
    # every split claim still scores identically on the shared set
    # (0.85 under methodology 2.0: the shared items are undated,
    # FR-8.6, and the boundary is a label, FR-8.7). The
    # outcome is iterate, driven by the pre-existing per-claim FR-6.2
    # warnings (not by any FR-2.8 outcome effect), and the sharing is
    # on the record at bundle level as well.
    assert all(a.scores[c.id].direct_score == pytest.approx(0.85) for c in a.claims)
    assert a.outcome == "iterate"
    assert "Shared evidence:" in a.summary
    assert "2 supporting source(s) shared across 5 of 5 claim(s)" in a.summary
    assert "no outcome effect in this phase" in a.summary
    assert any(f.category == "independence_unmodeled" for f in a.failures)


def test_shared_evidence_summary_survives_independence_declaration() -> None:
    # Declaring independence silences the per-claim FR-6.2 warning
    # (correct - the independence is modeled), but identical support
    # SETS across claims are still a fact about the bundle and the
    # summary-level picture (FR-2.8) still reports it.
    a = AEEEngine().assess(_split_claims(independent=True))
    assert not any(f.category == "independence_unmodeled" for f in a.failures)
    assert "Shared evidence:" in a.summary


def test_disjoint_evidence_is_not_reported_as_shared() -> None:
    claims = [
        claim("JX", [ev("a"), ev("b")]),
        claim("JY", [ev("c"), ev("d")], text="Gadget latency is 9 ms at p95 under load profile L"),
    ]
    a = AEEEngine().assess(claims)
    assert "Shared evidence:" not in a.summary


# --- T209 / RT2 p04 section 1: string-list explosion, score side -----------------


def test_string_list_fields_never_reach_a_score() -> None:
    # The loader half landed in Spec 002 FR-1 (strict _str_list_field);
    # this pins the consequence that motivated RT2-H5: no bundle whose
    # boundary/falsifier is a bare string can be loaded and scored, so
    # the char-exploded full credit (boundary=1.0, falsifiability=1.0
    # from "production"/"run it") is unreachable.
    with pytest.raises(BundleValidationError, match="must be a list of strings"):
        Claim.from_dict(
            {"id": "S1", "text": "x", "boundary": "production", "falsification_tests": "run it"}
        )


# --- Held behavior: honest bundles score exactly as before ----------------------


def test_control_bundle_scores_unchanged() -> None:
    """Values captured from main @ 0c8600a before the FR-2 phase;
    recaptured under methodology 2.0 (Spec 003 FR-8) below - the
    deltas are exactly the documented FR-8.6/FR-8.7 effects."""
    ctl1 = claim("CTL-1", [ev("tests/latency.json"), ev("tests/load.json")])
    ctl2 = claim(
        "CTL-2",
        [ev("docs/valve-spec.pdf", q=SourceQuality.PRIMARY)],
        status=ClaimStatus.PARTIALLY_SUPPORTED,
    )
    ctl4 = claim(
        "CTL-4",
        [
            ev("metrics/cache.json"),
            ev(
                "metrics/cache-audit.json",
                q=SourceQuality.SECONDARY,
                direction=EvidenceDirection.CONTRADICTS,
            ),
        ],
    )
    ctl5 = Claim(
        id="CTL-5",
        text="Two labs measured the same tensile strength",
        status=ClaimStatus.SUPPORTED,
        stage=ClaimStage.ACCEPTED,
        boundary=["lab conditions"],
        falsification_tests=["repeat the tensile test"],
        evidence=[
            Evidence(
                ref="lab-a/report.pdf",
                kind=EvidenceKind.OBSERVED,
                source_quality=SourceQuality.PRIMARY,
                source_id="lab-a",
                independent_of=["lab-b/report.pdf"],
            ),
            Evidence(
                ref="lab-b/report.pdf",
                kind=EvidenceKind.OBSERVED,
                source_quality=SourceQuality.PRIMARY,
                source_id="lab-b",
            ),
        ],
    )
    a = AEEEngine(policy=AssessmentPolicy()).assess([ctl1, ctl2, ctl4, ctl5])
    # Methodology 2.0 (Spec 003 FR-8, joint with Spec 004): the
    # honest bundle's scores move ONLY by the documented FR-8
    # deltas, each visible in the score notes - unknown freshness
    # counts as stale in the set penalty (FR-8.6, -0.10 for these
    # undated fixtures) and the label-only boundary "load profile L"
    # / "lab conditions" earns partial credit (FR-8.7, -0.05).
    # Evidence and independence components are unchanged.
    expected = {
        "CTL-1": (0.85, 1.0, 1.0),
        "CTL-2": (0.7225, 0.95, 0.5),
        "CTL-4": (0.10, 1.0, 0.5),
        "CTL-5": (0.848625, 0.9975, 1.0),
    }
    for cid, (direct, evidence_score, independence) in expected.items():
        s = a.scores[cid]
        assert (s.direct_score, s.evidence_score, s.independence_score) == (
            pytest.approx(direct),
            pytest.approx(evidence_score),
            pytest.approx(independence),
        ), cid
    assert a.scores["CTL-4"].contradiction_penalty == 0.65
