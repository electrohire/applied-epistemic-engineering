"""Claim priority records over the assessment ledger (Spec 004 R7).

The hash-chain ledger already timestamps every assessment it records.
A claim's **priority record** is the earliest ledger entry whose
assessment contains that claim id (R7.1): when the claim was first
registered, in which entry, under which entry hash. This is a read
over existing ledger data - no new ledger format.

Claims cite a registration as **priority evidence** with an evidence
ref of the form ``ledger:<ledger-path>#<sequence>`` (R7.2);
``aee verify-evidence`` resolves that shape against the ledger and
recomputes the entry hash, so a priority citation is inspectable
rather than asserted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aee.ledger import HashChainLedger

__all__ = ["claim_priority", "priority_index"]


def _records(ledger: HashChainLedger) -> dict[str, dict[str, Any]]:
    earliest: dict[str, dict[str, Any]] = {}
    for entry in ledger.entries():
        if entry.get("event_type") != "assessment":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        claim_ids = payload.get("claim_ids")
        if not isinstance(claim_ids, list):
            continue
        for claim_id in claim_ids:
            if not isinstance(claim_id, str) or claim_id in earliest:
                continue
            earliest[claim_id] = {
                "claim_id": claim_id,
                "sequence": entry.get("sequence"),
                "timestamp": entry.get("timestamp"),
                "entry_hash": entry.get("entry_hash"),
                "assessment_sha256": payload.get("assessment_sha256"),
                "ledger_path": ledger.path.as_posix(),
            }
    return earliest


def priority_index(ledger: HashChainLedger | str | Path) -> dict[str, dict[str, Any]]:
    """Earliest registration record per claim id in the ledger."""
    if not isinstance(ledger, HashChainLedger):
        ledger = HashChainLedger(ledger)
    return _records(ledger)


def claim_priority(ledger: HashChainLedger | str | Path, claim_id: str) -> dict[str, Any] | None:
    """The claim's priority record, or None if never registered."""
    return priority_index(ledger).get(claim_id)
