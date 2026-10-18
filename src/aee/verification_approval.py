"""Scoped permission to use a non-test method, separate from its execution.

Records and human names cannot authenticate themselves. The embedding host must
authenticate the human receipt through an independent channel and supply the
dedicated digest policy outside the editable agent workspace. Do not construct
that policy from imported JSON, execution pins or an agent-controlled CLI flag.
This module supplies no identity, signature or trusted timestamp service.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from aee.execution_scope import ScopeSnapshot, check_freshness, scope_path
from aee.extract import duplicate_key_hook
from aee.ledger import HashChainLedger
from aee.model import normalize_claim_id

MAX_APPROVAL_BYTES = 2 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("approval text must be bounded and nonempty")
    return value


@dataclass(frozen=True, slots=True)
class VerificationMethodApproval:
    """Immutable untrusted statement; host policy determines its authority."""

    canonical: bytes

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> VerificationMethodApproval:
        if (
            not isinstance(value, Mapping)
            or set(value)
            != {
                "schema_version",
                "decision",
                "method_id",
                "method_description",
                "requirement_ids",
                "approver_label",
                "approved_at",
                "receipt_path",
                "scope",
            }
            or value["schema_version"] != "1.0"
            or value["decision"] != "approve_method"
        ):
            raise ValueError("invalid method approval fields/version/decision")
        ids = value["requirement_ids"]
        if (
            not isinstance(ids, list)
            or not 1 <= len(ids) <= 10000
            or any(
                not isinstance(i, str) or not i or len(i) > 8192 or normalize_claim_id(i) != i
                for i in ids
            )
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("approval requires bounded unique canonical requirement IDs")
        timestamp = _text(value["approved_at"], 128)
        if datetime.fromisoformat(timestamp).utcoffset() is None:
            raise ValueError("approval timestamp requires a timezone; it is not trusted time")
        scope = ScopeSnapshot.from_dict(value["scope"])
        receipt = scope_path(value["receipt_path"])
        if receipt != value["receipt_path"] or receipt not in dict(scope.files):
            raise ValueError("approval receipt must be a canonical file in the approved scope")
        method_id = _text(value["method_id"], 256)
        if normalize_claim_id(method_id) != method_id:
            raise ValueError("method_id must be canonical")
        normalized = dict(
            schema_version="1.0",
            decision="approve_method",
            method_id=method_id,
            method_description=_text(value["method_description"], 8192),
            requirement_ids=sorted(ids),
            approver_label=_text(value["approver_label"], 256),
            approved_at=timestamp,
            receipt_path=receipt,
            scope=scope.to_dict(),
        )
        data = json.dumps(
            normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
        if len(data) > MAX_APPROVAL_BYTES:
            raise ValueError("method approval exceeds its byte limit")
        return cls(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> VerificationMethodApproval:
        if not isinstance(data, bytes) or len(data) > MAX_APPROVAL_BYTES:
            raise ValueError("method approval input must be bounded bytes")
        try:
            return cls.from_dict(
                json.loads(
                    data.decode("utf-8"), object_pairs_hook=duplicate_key_hook("method approval")
                )
            )
        except RecursionError as exc:
            raise ValueError("method approval nesting exceeds the parser limit") from exc

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.canonical))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical).hexdigest()


def check_method_approval(
    record: VerificationMethodApproval,
    root: str | Path,
    *,
    repository_id: str,
    trusted_human_approval_digests: Collection[str] = (),
) -> dict[str, Any]:
    """Check host-authenticated, still-applicable permission, never verification.

    The host must verify the original human receipt before pinning this complete
    record. Immediate observation of an agent writing the record is insufficient.
    Removing a digest from that dedicated policy revokes its authority.
    """
    record = VerificationMethodApproval.from_bytes(record.canonical)
    if (
        not isinstance(trusted_human_approval_digests, Collection)
        or isinstance(trusted_human_approval_digests, (str, bytes))
        or any(
            not isinstance(pin, str) or not _HASH.fullmatch(pin)
            for pin in trusted_human_approval_digests
        )
    ):
        raise ValueError("invalid dedicated human approval policy")
    value = record.to_dict()
    try:
        freshness = check_freshness(
            ScopeSnapshot.from_dict(value["scope"]), root, repository_id=repository_id
        ).status
    except (OSError, ValueError):
        freshness = "unknown"
    trusted = record.digest in trusted_human_approval_digests
    approved = trusted and freshness == "fresh"
    return dict(
        record_sha256=record.digest,
        method_id=value["method_id"],
        requirement_ids=value["requirement_ids"],
        receipt_path=value["receipt_path"],
        freshness=freshness,
        approval_status="method_approved" if approved else "unverified",
        approval_authority="external-host-policy" if trusted else "unverified",
        identity_proof="not_established_by_record",
        verification_status="unassessed",
        outcome="pass" if approved else "gather_evidence",
        scope=(
            "Permission to use this scoped method only; not execution, a passing result, "
            "adequacy or requirement acceptance."
        ),
    )


def append_method_approval(
    record: VerificationMethodApproval,
    ledger: HashChainLedger,
    *,
    actor: str = "aee-method-receipt",
) -> dict[str, Any]:
    """Retain an approval statement; actor labels/ledger hashes confer no trust."""
    record = VerificationMethodApproval.from_bytes(record.canonical)
    actor = _text(actor, 256)
    return ledger.append(
        "verification_method_approval",
        dict(record_sha256=record.digest, record=record.to_dict(), approval_trust="unverified"),
        actor=actor,
    )
