"""Compact context preserves status, blockers and anchored provenance."""

import copy
import json

import pytest

from aee.context_handoff import ContextBudgetExceeded, build_context
from aee.ledger import HashChainLedger
from aee.model import Claim, IdentityRegistry


def claim(identity="R01", **values):
    return Claim.from_dict(
        dict(id=identity, text="Bounded " + identity, **{"stage": "created", **values})
    )


def test_preserves_claim_status_and_dependency_conflict_closure_without_promotion():
    claims = [
        claim("R01", depends_on=["r02"], conflicts_with=["R03"]),
        claim("R02", kind="assumption", status="unsupported"),
        claim("R03", status="contradicted"),
        claim("R04"),
    ]
    original = copy.deepcopy([c.to_dict() for c in claims])
    value = build_context(claims, ["r01"])
    assert value["requested_ids"] == ["R01"] and value["omitted_ids"] == ["R04"]
    assert [c["id"] for c in value["claims"]] == ["R01", "R02", "R03"]
    assert value["unknown_ids"] == ["R01", "R02"]
    assert value["contradictions"] == [
        dict(claim_id="R01", conflicts_with=["R03"]),
        dict(claim_id="R03", conflicts_with=[]),
    ]
    assert all(c["stage"] == "created" for c in value["claims"])
    assert value["claims"][0]["status"] == "draft"
    assert value["provenance"]["ledger"] == "unrecorded"
    assert [c.to_dict() for c in claims] == original


def test_explicit_stored_stage_preserved_not_created_by_summary():
    value = build_context([claim(stage="accepted", status="partially_supported")], ["R01"])
    assert value["claims"][0]["stage"] == "accepted"
    assert value["claims"][0]["status"] == "partially_supported"
    assert value["unknown_ids"] == ["R01"]


def test_cycles_and_unresolved_ids_remain_visible():
    value = build_context(
        [claim("R01", depends_on=["R02", "MISSING"]), claim("R02", depends_on=["R01"])], ["R01"]
    )
    assert value["unresolved_references"] == ["MISSING"]
    assert len(value["claims"]) == 2
    with pytest.raises(ValueError, match="unknown requested"):
        build_context([claim()], ["MISSING"])


def test_evidence_and_freshness_pointers_preserved_without_claiming_verified():
    item = claim(
        evidence=[
            dict(
                ref="logs/test.json",
                kind="observed",
                source_quality="test",
                direction="contradicts",
                source_id="run01",
                content_hash="a" * 64,
            )
        ]
    )
    value = build_context([item], ["R01"])
    evidence = value["claims"][0]["evidence"][0]
    assert evidence["ref"] == "logs/test.json" and evidence["direction"] == "contradicts"
    assert value["claims"][0]["status"] == "draft"
    assert value["applicability"] == "unassessed"


def test_anchor_is_actually_verified_and_handoff_is_deterministic(tmp_path):
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    ledger.append("fixture", {"fact": "bounded observation"}, actor="test")
    first = build_context([claim()], ["R01"], ledger=ledger)
    second = build_context([claim()], ["R01"], ledger=ledger)
    assert first == second
    assert first["provenance"]["entry_count"] == 1
    assert first["provenance"]["ledger"] == "anchored"
    ledger.path.write_text("tampered\n")
    with pytest.raises(ValueError, match="ledger"):
        build_context([claim()], ["R01"], ledger=ledger)


@pytest.mark.parametrize("budget", [True, 0, -1, 1.5, "2000", 2_000_000])
def test_invalid_budget_refused(budget):
    with pytest.raises(ValueError, match="max_bytes"):
        build_context([claim()], ["R01"], max_bytes=budget)


def test_budget_failure_never_silently_discards_blockers():
    with pytest.raises(ContextBudgetExceeded) as error:
        build_context(
            [claim(conflicts_with=["R02"]), claim("R02", status="contradicted")],
            ["R01"],
            max_bytes=100,
        )
    assert error.value.required_bytes > 100 and error.value.max_bytes == 100
    value = build_context([claim()], ["R01"])
    size = len(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())
    assert build_context([claim()], ["R01"], max_bytes=size) == value
    with pytest.raises(ContextBudgetExceeded):
        build_context([claim()], ["R01"], max_bytes=size - 1)


@pytest.mark.parametrize(
    "claims,ids",
    [
        ([], ["R01"]),
        ([claim()], []),
        ([claim(), claim("r01")], ["R01"]),
        ([claim()], ["r01", "R01"]),
        ([claim()], "R01"),
        ("invalid", ["R01"]),
        ([{}], ["R01"]),
        ([claim()], [3]),
    ],
)
def test_bad_inputs_refused(claims, ids):
    with pytest.raises(ValueError):
        build_context(claims, ids)


def test_bound_input_cardinality(monkeypatch):
    import aee.context_handoff as context

    monkeypatch.setattr(context, "MAX_CLAIMS", 1)
    with pytest.raises(ValueError):
        build_context([claim(), claim("R02")], ["R01"])


def test_supported_status_is_not_labeled_unknown_but_still_not_certified():
    value = build_context([claim(status="supported")], ["R01"])
    assert value["unknown_ids"] == []
    assert value["applicability"] == "unassessed"


def test_incoming_conflicts_cannot_be_silently_omitted():
    value = build_context([claim(), claim("R02", conflicts_with=["R01"])], ["R01"])
    assert value["omitted_ids"] == []
    assert value["contradictions"] == [dict(claim_id="R02", conflicts_with=["R01"])]


def test_existing_exposition_requires_same_explicit_identity_registry():
    registry = IdentityRegistry.from_dict(
        {"reviewer": {"kind": "person", "name": "Example reviewer"}}
    )
    item = Claim.from_dict(
        dict(
            id="R01",
            text="Bounded",
            stage="explained",
            evidence=[
                dict(
                    ref="records/explanation.md",
                    kind="exposition",
                    source_id="reviewer",
                    source_quality="human",
                )
            ],
        ),
        identity_registry=registry,
    )
    with pytest.raises(ValueError):
        build_context([item], ["R01"])
    value = build_context([item], ["R01"], identity_registry=registry)
    assert value["claims"][0]["stage"] == "explained"
    assert value["claims"][0]["evidence"][0]["source_id"] == "reviewer"
