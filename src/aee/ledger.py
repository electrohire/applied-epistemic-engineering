"""Append-only, tamper-evident JSONL ledger for epistemic state transitions."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class LedgerVerification:
    valid: bool
    entries: int
    errors: tuple[str, ...] = ()
    head_hash: str = GENESIS_HASH


class HashChainLedger:
    """Canonical SHA-256 chain.

    The chain detects mutation, deletion in the middle, reordering, and insertion. It does not
    prove that an assertion is true or that an actor created it; use signatures and trusted
    timestamps when those properties are required.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(
        self, event_type: str, payload: dict[str, Any], *, actor: str = "aee"
    ) -> dict[str, Any]:
        verification = self.verify()
        if not verification.valid:
            raise ValueError(
                "refusing to append to an invalid ledger: " + "; ".join(verification.errors)
            )
        entry: dict[str, Any] = {
            "ledger_version": "1.0",
            "sequence": verification.entries + 1,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "event_type": event_type,
            "actor": actor,
            "previous_hash": verification.head_hash,
            "payload": payload,
        }
        entry["entry_hash"] = _entry_hash(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical(entry) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return entry

    def append_assessment(self, assessment: Any, *, actor: str = "aee") -> dict[str, Any]:
        value = assessment.to_dict()
        digest = hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()
        return self.append(
            "assessment",
            {
                "project": value["project"],
                "phase": value["phase"],
                "outcome": value["outcome"],
                "claim_ids": [claim["id"] for claim in value["claims"]],
                "assessment_sha256": digest,
            },
            actor=actor,
        )

    def verify(self) -> LedgerVerification:
        if not self.path.exists():
            return LedgerVerification(valid=True, entries=0)
        errors: list[str] = []
        previous = GENESIS_HASH
        entries = 0
        for line_number, raw in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: invalid JSON ({exc.msg})")
                continue
            entries += 1
            if entry.get("sequence") != entries:
                errors.append(f"line {line_number}: expected sequence {entries}")
            if entry.get("previous_hash") != previous:
                errors.append(f"line {line_number}: previous_hash mismatch")
            actual = entry.get("entry_hash", "")
            expected = _entry_hash(entry)
            if actual != expected:
                errors.append(f"line {line_number}: entry_hash mismatch")
            previous = actual if isinstance(actual, str) else ""
        return LedgerVerification(
            valid=not errors,
            entries=entries,
            errors=tuple(errors),
            head_hash=previous if entries else GENESIS_HASH,
        )

    def entries(self) -> Iterable[dict[str, Any]]:
        if not self.path.exists():
            return ()
        return tuple(
            json.loads(raw)
            for raw in self.path.read_text(encoding="utf-8").splitlines()
            if raw.strip()
        )


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _entry_hash(entry: dict[str, Any]) -> str:
    material = {key: value for key, value in entry.items() if key != "entry_hash"}
    return hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()
