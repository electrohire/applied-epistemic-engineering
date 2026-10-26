"""Spec 003 FR-3 addendum - provenance authority (T307-T312).

The Phase 9 probe re-run left RT1-07 composite partially live:
the coattail and framing constructions were inverted by FR-3,
but direct ``record()`` minting still canonised a junk source in
three calls at the original numbers (reliability 1.0, MODEL blend
0.20 -> 0.60) once the caller supplied ANY self-asserted
provenance string - the FR-3.5 field was a label, not an
authority check. These tests pin the addendum's semantics:

* self-asserted history (string provenance, the unattributed
  compatibility path, legacy loads) never canonises and never
  moves a blended weight, however much of it accumulates;
* canonisation is earned only on observations anchored to
  hash-chained ledger resolution entries the engine verifies
  (resolution, payload match, one observation per anchor);
* the self-asserted track stays visible as a capped, labelled
  provisional measurement.
"""

from __future__ import annotations

import json

import pytest
from test_scoring import strong_evidence

from aee import (
    Claim,
    Evidence,
    EvidenceKind,
    HashChainLedger,
    ProvenanceAnchor,
    ReliabilityTable,
    SourceQuality,
)
from aee.model import BundleValidationError
from aee.reliability import (
    CLAIM_RESOLUTION_EVENT_TYPE,
    PROVISIONAL_RELIABILITY_CAP,
    RESOLUTION_EVENT_TYPE,
    blended_weight,
)
from aee.scoring import ClaimScore

MODEL_ITEM = Evidence(
    ref="x",
    source_id="evil-source",
    kind=EvidenceKind.ASSERTED,
    source_quality=SourceQuality.MODEL,
)


def _claim(claim_id: str, evidence: list[Evidence]) -> Claim:
    return Claim(
        id=claim_id,
        text="The widget holds",
        boundary=["lab"],
        falsification_tests=["drop it"],
        evidence=evidence,
    )


def _fake_score(claim_id: str, propagated: float) -> ClaimScore:
    return ClaimScore(
        claim_id=claim_id,
        direct_score=propagated,
        propagated_score=propagated,
        evidence_score=1.0,
        independence_score=1.0,
        falsifiability_score=1.0,
        boundary_score=1.0,
        contradiction_penalty=0.0,
    )


# ------------------------------------------------------------------
# T312 - the RT1-07 residual, verbatim (p4 section E / p4b E1-E3)
# ------------------------------------------------------------------


def test_probe_e2_self_asserted_string_never_canonises() -> None:
    """Before the addendum this reproduced the PoC exactly:
    reliability 1.0 and a 0.20 -> 0.60 MODEL blend."""
    table = ReliabilityTable()
    for _ in range(3):
        table.record("evil-source", 1.0, True, provenance="attacker-self-report")
    assert table.reliability("evil-source") is None
    assert table.credit_status("evil-source") == "provisional"
    # The history is visible, capped, and labelled provisional.
    assert table.provisional_reliability("evil-source") == PROVISIONAL_RELIABILITY_CAP
    weight, measured = blended_weight(MODEL_ITEM, 0.20, table, 0.5)
    assert weight == 0.20
    assert measured is None


def test_probe_e2_no_accumulation_loophole() -> None:
    """Volume does not substitute for authority: thirty
    self-asserted perfect records canonise no more than three."""
    table = ReliabilityTable()
    for _ in range(30):
        table.record("evil-source", 1.0, True, provenance="attacker-self-report")
    assert table.records["evil-source"].observations == 30
    assert table.records["evil-source"].anchored_credit == 0.0
    assert table.reliability("evil-source") is None
    weight, measured = blended_weight(MODEL_ITEM, 0.20, table, 0.5)
    assert (weight, measured) == (0.20, None)


def test_probe_e3_unattributed_path_never_canonises() -> None:
    table = ReliabilityTable()
    for _ in range(3):
        table.record("evil-source", 1.0, True, allow_unattributed=True)
    assert table.reliability("evil-source") is None
    assert table.provisional_reliability("evil-source") == PROVISIONAL_RELIABILITY_CAP
    weight, measured = blended_weight(MODEL_ITEM, 0.20, table, 0.5)
    assert (weight, measured) == (0.20, None)


def test_observe_claim_default_provenance_is_provisional_only(tmp_path) -> None:
    """The engine-internal observe_claim path is not exempt: its
    default label is a string like any other, so unanchored claim
    credit is provisional until the resolution is anchored."""
    table = ReliabilityTable()
    claim = _claim("C1", [strong_evidence("one", "S1")])
    for _ in range(3):
        table.observe_claim(claim, _fake_score("C1", 1.0), True)
    assert table.records["S1"].effective_credit == pytest.approx(3.0)
    assert table.reliability("S1") is None
    assert table.credit_status("S1") == "provisional"


# ------------------------------------------------------------------
# T307/T308 - anchored recording: the honest path canonises
# ------------------------------------------------------------------


def test_anchored_records_canonise_at_the_original_numbers(tmp_path) -> None:
    """The probe's numbers, now earned: three anchored perfect
    records give reliability 1.0 and the 0.20 -> 0.60 blend."""
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    table = ReliabilityTable(ledger=ledger)
    for _ in range(3):
        table.record_resolution("evil-source", 1.0, True, provenance="real-resolver")
    assert table.reliability("evil-source") == 1.0
    assert table.credit_status("evil-source") == "canonised"
    weight, measured = blended_weight(MODEL_ITEM, 0.20, table, 0.5)
    assert weight == pytest.approx(0.60)
    assert measured == 1.0


def test_record_with_explicit_anchor_from_manual_entry(tmp_path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    entry = ledger.append(
        RESOLUTION_EVENT_TYPE,
        {"source_id": "S", "predicted": 0.9, "outcome": True, "provenance": "panel"},
    )
    table = ReliabilityTable(ledger=ledger)
    table.record("S", 0.9, True, provenance="panel", anchor=ProvenanceAnchor(entry["entry_hash"]))
    rec = table.records["S"]
    assert rec.anchored_credit == 1.0
    assert rec.anchors == (entry["entry_hash"],)


def test_observe_claim_resolution_canonises(tmp_path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    table = ReliabilityTable(ledger=ledger)
    claim = _claim("C1", [strong_evidence("one", "S1"), strong_evidence("two", "S2")])
    for i in range(6):
        credited = table.observe_claim_resolution(
            _claim(f"C{i}", [strong_evidence("one", "S1"), strong_evidence("two", "S2")]),
            _fake_score(f"C{i}", 1.0),
            True,
        )
        assert credited == ["S1", "S2"]
    assert table.reliability("S1") == 1.0
    assert table.records["S1"].anchored_credit == pytest.approx(3.0)
    assert claim.id == "C1"  # the fixture claim itself was never resolved


# ------------------------------------------------------------------
# T307 - forgery, mismatch, replay: refused loudly, nothing recorded
# ------------------------------------------------------------------


def test_anchor_forgery_refused(tmp_path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    table = ReliabilityTable(ledger=ledger)
    with pytest.raises(ValueError, match="does not resolve"):
        table.record(
            "evil-source",
            1.0,
            True,
            provenance="attacker-self-report",
            anchor=ProvenanceAnchor(digest="a" * 64),
        )
    assert "evil-source" not in table.records


def test_anchor_payload_mismatch_refused(tmp_path) -> None:
    """A genuine entry recording a DIFFERENT resolution backs
    nothing: wrong source, wrong prediction, wrong outcome."""
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    entry = ledger.append(
        RESOLUTION_EVENT_TYPE,
        {"source_id": "honest", "predicted": 0.5, "outcome": False, "provenance": "panel"},
    )
    anchor = ProvenanceAnchor(digest=entry["entry_hash"])
    table = ReliabilityTable(ledger=ledger)
    for source_id, predicted, outcome in [
        ("evil-source", 0.5, False),  # source differs
        ("honest", 1.0, False),  # prediction differs
        ("honest", 0.5, True),  # outcome differs
    ]:
        with pytest.raises(ValueError, match="refusing to credit"):
            table.record(source_id, predicted, outcome, provenance="panel", anchor=anchor)
    assert table.records == {}


def test_anchor_wrong_event_type_refused(tmp_path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    entry = ledger.append(
        CLAIM_RESOLUTION_EVENT_TYPE,
        {"claim_id": "C1", "outcome": True, "provenance": "panel"},
    )
    table = ReliabilityTable(ledger=ledger)
    with pytest.raises(ValueError, match="refusing to credit"):
        table.record(
            "S", 1.0, True, provenance="panel", anchor=ProvenanceAnchor(entry["entry_hash"])
        )


def test_anchor_replay_refused(tmp_path) -> None:
    """One entry canonises one observation: replaying the same
    anchor cannot farm the cold-start guard from a single genuine
    resolution."""
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    entry = ledger.append(
        RESOLUTION_EVENT_TYPE,
        {"source_id": "S", "predicted": 1.0, "outcome": True, "provenance": "panel"},
    )
    anchor = ProvenanceAnchor(digest=entry["entry_hash"])
    table = ReliabilityTable(ledger=ledger)
    table.record("S", 1.0, True, provenance="panel", anchor=anchor)
    with pytest.raises(ValueError, match="already backs"):
        table.record("S", 1.0, True, provenance="panel", anchor=anchor)
    assert table.records["S"].observations == 1


def test_anchor_requires_bound_ledger() -> None:
    table = ReliabilityTable()
    with pytest.raises(ValueError, match="bound ledger"):
        table.record("S", 1.0, True, provenance="panel", anchor=ProvenanceAnchor("b" * 64))
    with pytest.raises(ValueError, match="bound ledger"):
        table.record_resolution("S", 1.0, True, provenance="panel")


def test_anchor_on_tampered_chain_refused(tmp_path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = HashChainLedger(ledger_path)
    table = ReliabilityTable(ledger=ledger)
    anchor = table.record_resolution("S", 1.0, True, provenance="panel")
    # Rewrite history: same file, forged payload, stale hashes.
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    forged = json.loads(lines[0])
    forged["payload"]["outcome"] = False
    ledger_path.write_text(json.dumps(forged) + "\n", encoding="utf-8")
    with pytest.raises(BundleValidationError, match="does not verify"):
        table.record("S", 1.0, True, provenance="panel", anchor=anchor)


# ------------------------------------------------------------------
# T309/T310 - serialised labels and the load path
# ------------------------------------------------------------------


def test_serialised_records_label_credit_status(tmp_path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    table = ReliabilityTable(ledger=ledger)
    for _ in range(3):
        table.record_resolution("canon", 1.0, True, provenance="panel")
        table.record("prov", 1.0, True, provenance="self-report")
    data = table.to_dict()
    canon = data["records"]["canon"]
    assert canon["credit_status"] == "canonised"
    assert canon["canonised"] is True
    assert canon["anchored_credit_weight"] == 3.0
    assert len(canon["anchors"]) == 3
    prov = data["records"]["prov"]
    assert prov["credit_status"] == "provisional"
    assert prov["canonised"] is False
    assert prov["provisional_reliability"] == PROVISIONAL_RELIABILITY_CAP
    assert prov["anchors"] == []
    assert prov["anchored_credit_weight"] == 0.0


def test_loaded_table_canonises_only_after_ledger_verification(tmp_path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    table = ReliabilityTable(ledger=ledger)
    for _ in range(3):
        table.record_resolution("S", 1.0, True, provenance="panel")
    data = json.loads(json.dumps(table.to_dict()))
    # No ledger bound at load: the digests are unverified claims.
    unbound = ReliabilityTable.from_dict(data)
    assert unbound.reliability("S") is None
    assert unbound.credit_status("S") == "provisional"
    # Same file, consumer binds the ledger: canonisation returns.
    bound = ReliabilityTable.from_dict(data, ledger=ledger)
    assert bound.reliability("S") == 1.0
    # Explicit post-load binding works too.
    late = ReliabilityTable.from_dict(data)
    assert late.verify_anchors(ledger) == 3
    assert late.reliability("S") == 1.0


def test_loaded_table_with_unresolvable_anchor_fails_loudly(tmp_path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    table = ReliabilityTable(ledger=ledger)
    for _ in range(3):
        table.record_resolution("S", 1.0, True, provenance="panel")
    data = json.loads(json.dumps(table.to_dict()))
    # Swap in a digest no ledger holds: a fabricated anchor claim.
    data["records"]["S"]["anchors"][0] = "f" * 64
    empty_ledger = HashChainLedger(tmp_path / "other.jsonl")
    with pytest.raises(BundleValidationError, match="'S'"):
        ReliabilityTable.from_dict(data, ledger=empty_ledger)
    with pytest.raises(BundleValidationError, match="does not resolve"):
        ReliabilityTable.from_dict(data, ledger=ledger)


@pytest.mark.parametrize(
    "record",
    [
        # anchored credit beyond the record's whole history
        {
            "observations": 3,
            "brier_sum": 0.0,
            "credit_weight": 3.0,
            "anchored_credit_weight": 4.0,
            "anchored_brier_sum": 0.0,
            "anchors": ["a" * 64],
        },
        # anchored Brier beyond its own anchored credit
        {
            "observations": 3,
            "brier_sum": 0.5,
            "credit_weight": 3.0,
            "anchored_credit_weight": 1.0,
            "anchored_brier_sum": 2.0,
            "anchors": ["a" * 64],
        },
        # anchored credit claimed with no digests at all
        {
            "observations": 3,
            "brier_sum": 0.0,
            "credit_weight": 3.0,
            "anchored_credit_weight": 3.0,
            "anchored_brier_sum": 0.0,
            "anchors": [],
        },
        # a digest that is not a digest
        {
            "observations": 3,
            "brier_sum": 0.0,
            "credit_weight": 3.0,
            "anchored_credit_weight": 3.0,
            "anchored_brier_sum": 0.0,
            "anchors": ["xyz"],
        },
        # non-finite anchored tally
        {
            "observations": 3,
            "brier_sum": 0.0,
            "credit_weight": 3.0,
            "anchored_credit_weight": float("nan"),
            "anchored_brier_sum": 0.0,
            "anchors": ["a" * 64],
        },
    ],
)
def test_from_dict_rejects_inconsistent_anchored_fields(record) -> None:
    with pytest.raises(BundleValidationError, match="lab"):
        ReliabilityTable.from_dict({"records": {"lab": record}})


def test_anchor_object_validates_its_own_shape() -> None:
    with pytest.raises(ValueError, match="64-character"):
        ProvenanceAnchor(digest="not-a-hash")
    with pytest.raises(ValueError, match="unsupported"):
        ProvenanceAnchor(digest="a" * 64, kind="signed-email")
