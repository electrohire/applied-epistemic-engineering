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

## Assessment records (Spec 002 FR-8a)

`aee assess` appends every assessment to a ledger **by default** (FR-8.1) — the bare CLI
and the spec-kit-aee runner now behave identically:

- Default path: `.specify/extensions/aee/ledger/epistemic-ledger.jsonl` under the project
  root (the current working directory, or `--project-root` when given).
- `--ledger <path>` selects a different ledger; `--no-ledger` is the explicit opt-out.
  Whichever happened is echoed into the assessment's `metadata.ledger` — ledgering is
  never silent in either direction.

**The ledger entry is the record of what was assessed; the assessment JSON file is a
working copy** (FR-8.3). An entry stores the assessment's SHA-256 with its project,
phase, outcome, and claim ids; the JSON file is routinely overwritten by the next run
and proves nothing on its own. The documented loop is assess → verify:

```bash
aee assess --input claims.json --output assessment.json
aee verify-ledger --ledger .specify/extensions/aee/ledger/epistemic-ledger.jsonl
```

