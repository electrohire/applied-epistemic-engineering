#!/usr/bin/env python3
"""Canonical serialization and per-event hashing (spec AB-001 3.2, FR-S1).

The canonical form is pinned: a value serializes as JSON with sorted
keys, Unicode NFC, separators ``,`` and ``:``, UTF-8, and string values
have CRLF / CR line endings normalized to LF before hashing, so the
same logical event hashes identically on any host and any checkout,
including one that would otherwise introduce CRLF. ``event_hash`` is
the SHA-256 of the event's canonical form (excluding the ``event_hash``
field itself) concatenated with ``prev_hash``.

This is a per-event canonical JSON rule. The fleet's whole-file
canonicalize-before-you-hash rule (``aee.intake_common.ledger_sha256``)
governs ledger files and does not substitute for it.

The chain detects tampering and reordering. It does not establish that
events were truthful, and it does not protect against an actor who
rewrites the whole log and recomputes the chain; committed state
snapshots are the answer to that, not the chain.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

# The prev_hash of a board's first (genesis) event.
GENESIS_PREV_HASH = "0" * 64


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        text = unicodedata.normalize("NFC", value)
        return text.replace("\r\n", "\n").replace("\r", "\n")
    if isinstance(value, dict):
        return {_normalize(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def canonical_bytes(value: Any) -> bytes:
    """The pinned canonical form of a JSON value, as UTF-8 bytes."""
    text = json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return text.encode("utf-8")


def canonical_line(value: Any) -> bytes:
    """One canonical JSONL line: the canonical form plus an LF ending."""
    return canonical_bytes(value) + b"\n"


def event_hash(event: dict[str, Any]) -> str:
    """SHA-256 of the event's canonical form concatenated with prev_hash.

    The event dict must carry ``prev_hash`` and must not yet carry a
    trusted ``event_hash``; any ``event_hash`` present is excluded from
    the canonical form, so this also verifies a stored event.
    """
    body = {key: item for key, item in event.items() if key != "event_hash"}
    digest = hashlib.sha256()
    digest.update(canonical_bytes(body))
    digest.update(str(event["prev_hash"]).encode("utf-8"))
    return digest.hexdigest()


def state_hash(state: dict[str, Any]) -> str:
    """SHA-256 of a state object's canonical form (read-back checks)."""
    return hashlib.sha256(canonical_bytes(state)).hexdigest()
