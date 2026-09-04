# Tamper-evident ledger

`HashChainLedger` writes canonical JSON Lines. Each entry includes the hash of the previous entry
and its own canonical SHA-256 digest.

```python
from aee import HashChainLedger

ledger = HashChainLedger(".aee/epistemic-ledger.jsonl")
ledger.append("decision", {"claim_id": "DEC-001", "choice": "Option A"})
assert ledger.verify().valid
```

The chain detects modification, reordering, insertion, and deletion from the middle of the local
history. It does **not** independently prove:

- who wrote an entry;
- when the event occurred;
- that the payload is true; or
- that the ledger head was not replaced wholesale.

For stronger guarantees, anchor head hashes externally and add actor signatures, trusted
timestamps, protected storage, and independent evidence retention.

