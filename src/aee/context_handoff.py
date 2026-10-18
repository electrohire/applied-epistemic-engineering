"""Deterministic bounded context; summaries never promote epistemic state.

The handoff preserves recorded statuses, not a certification that they are true.
Its ledger anchor detects local history mutation, not producer authenticity.
Evidence applicability requires a separate freshness/verification assessment.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from aee.ledger import HashChainLedger
from aee.model import Claim, IdentityRegistry, normalize_claim_id

MAX_CLAIMS = 10_000
MAX_CONTEXT_BYTES = 1024 * 1024


class ContextBudgetExceeded(ValueError):
    """The complete selected dependency/blocker closure cannot fit its budget."""

    def __init__(self, required_bytes: int, max_bytes: int) -> None:
        self.required_bytes = required_bytes
        self.max_bytes = max_bytes
        super().__init__(f"context requires {required_bytes} bytes; max_bytes is {max_bytes}")


def build_context(
    claims: Sequence[Claim],
    requirement_ids: Sequence[str],
    *,
    max_bytes: int = 32 * 1024,
    ledger: HashChainLedger | None = None,
    identity_registry: IdentityRegistry | None = None,
) -> dict[str, Any]:
    """Select scoped claims and their dependency/conflict closure without inference.

    All selected blockers remain present or the call fails explicitly. Omitted
    claims are named. Missing referenced IDs remain unresolved. No stored status,
    stage or evidence label is recomputed from a summary, frequency or score.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_CONTEXT_BYTES:
        raise ValueError("max_bytes must be a positive integer at most 1MiB")
    if (
        not isinstance(claims, Sequence)
        or isinstance(claims, (str, bytes))
        or not 1 <= len(claims) <= MAX_CLAIMS
        or any(not isinstance(claim, Claim) for claim in claims)
    ):
        raise ValueError("claims must be a bounded nonempty sequence of Claim objects")
    if (
        not isinstance(requirement_ids, Sequence)
        or isinstance(requirement_ids, (str, bytes))
        or not 1 <= len(requirement_ids) <= MAX_CLAIMS
        or any(
            not isinstance(identity, str) or not identity.strip() for identity in requirement_ids
        )
    ):
        raise ValueError("requirement_ids must be a bounded nonempty sequence of IDs")
    # Copy through strict loading, including directly constructed Python claims.
    # Preserve the complete evidence/failure/stage-event representation so a
    # compact handoff cannot silently strip counterevidence or acceptance history.
    records = [
        Claim.from_dict(claim.to_dict(), identity_registry=identity_registry).to_dict()
        for claim in claims
    ]
    by_id = {record["id"]: record for record in records}
    if len(by_id) != len(records):
        raise ValueError("duplicate normalized claim IDs")
    requested = sorted(normalize_claim_id(identity) for identity in requirement_ids)
    if len(set(requested)) != len(requested):
        raise ValueError("duplicate normalized requested IDs")
    if set(requested) - by_id.keys():
        raise ValueError("unknown requested claim IDs")
    incoming_conflicts: dict[str, list[str]] = {}
    for record in records:
        for target in record["conflicts_with"]:
            incoming_conflicts.setdefault(target, []).append(record["id"])
    selected: set[str] = set()
    unresolved: set[str] = set()
    pending = list(requested)
    while pending:
        identity = pending.pop()
        if identity in selected:
            continue
        if identity not in by_id:
            unresolved.add(identity)
            continue
        selected.add(identity)
        record = by_id[identity]
        pending.extend(record["depends_on"] + record["conflicts_with"])
        pending.extend(incoming_conflicts.get(identity, []))
    provenance: dict[str, Any] = {"ledger": "unrecorded"}
    if ledger is not None:
        verified = ledger.verify(require_anchor=True)
        if not verified.valid:
            raise ValueError("context ledger/anchor verification failed")
        provenance = {
            "ledger": "anchored",
            "entry_count": verified.entries,
            "tip_hash": verified.head_hash,
        }
    chosen = [by_id[identity] for identity in sorted(selected)]
    value = {
        "schema_version": "1.0",
        "requested_ids": requested,
        "claims": chosen,
        "unknown_ids": [
            item["id"]
            for item in chosen
            if item["status"] in {"draft", "unsupported", "unverifiable", "partially_supported"}
        ],
        "contradictions": [
            {"claim_id": item["id"], "conflicts_with": item["conflicts_with"]}
            for item in chosen
            if item["conflicts_with"] or item["status"] == "contradicted"
        ],
        "unresolved_references": sorted(unresolved),
        "omitted_ids": sorted(by_id.keys() - selected),
        "provenance": provenance,
        "applicability": "unassessed",
    }
    required = len(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    )
    if required > max_bytes:
        raise ContextBudgetExceeded(required, max_bytes)
    return value
