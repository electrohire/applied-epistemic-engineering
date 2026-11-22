"""T001: canonical serialization and hashing (spec AB-001 3.2, FR-S1)."""

import hashlib
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board import canonical  # noqa: E402


def sample_event() -> dict:
    return {
        "event_id": "evt-0001",
        "board_id": "board-a",
        "row_id": None,
        "actor": "planner",
        "writer": "board-append@host-a:board-a",
        "kind": "genesis",
        "payload": {"program": "p", "wip_limit": 4},
        "prev_hash": canonical.GENESIS_PREV_HASH,
    }


def test_known_answer_vector():
    event = sample_event()
    # Independent recomputation of the pinned rule, not via board.canonical.
    body = {k: v for k, v in event.items() if k != "event_hash"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = hashlib.sha256(text.encode("utf-8") + event["prev_hash"].encode()).hexdigest()
    assert canonical.event_hash(event) == expected


def test_key_order_and_whitespace_do_not_matter():
    a = sample_event()
    b = dict(reversed(list(a.items())))
    assert canonical.event_hash(a) == canonical.event_hash(b)
    assert canonical.canonical_bytes({"x": 1, "y": [1, 2]}) == b'{"x":1,"y":[1,2]}'


def test_nfc_normalization():
    decomposed = "cafe\u0301"  # e + combining acute
    precomposed = "caf\u00e9"
    assert decomposed != precomposed
    a = sample_event()
    a["payload"] = {"note": decomposed}
    b = sample_event()
    b["payload"] = {"note": precomposed}
    assert unicodedata.normalize("NFC", decomposed) == precomposed
    assert canonical.event_hash(a) == canonical.event_hash(b)


def test_crlf_poisoned_input_normalizes_before_hashing():
    a = sample_event()
    a["payload"] = {"note": "line one\r\nline two\rline three"}
    b = sample_event()
    b["payload"] = {"note": "line one\nline two\nline three"}
    assert canonical.event_hash(a) == canonical.event_hash(b)
    assert b"\r" not in canonical.canonical_line(a)


def test_event_hash_excludes_stored_event_hash_field():
    event = sample_event()
    digest = canonical.event_hash(event)
    event["event_hash"] = digest
    assert canonical.event_hash(event) == digest
    event["event_hash"] = "f" * 64
    assert canonical.event_hash(event) == digest


def test_tampering_changes_the_hash():
    event = sample_event()
    digest = canonical.event_hash(event)
    event["payload"] = {"program": "p", "wip_limit": 3}
    assert canonical.event_hash(event) != digest


def test_state_hash_uses_the_same_rule():
    state = {"head_hash": "a" * 64, "rows": {}}
    text = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert canonical.state_hash(state) == hashlib.sha256(text.encode("utf-8")).hexdigest()
