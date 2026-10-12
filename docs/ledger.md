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

## Head anchors (Spec 003 FR-4)

Every append also updates a sidecar anchor at `<ledger>.anchor.json`. The anchor is a small
JSON record committing exactly the head state:

```json
{"anchor_version": "1.0", "entry_count": 3, "tip_hash": "<sha256>", "ledger_name": "epistemic-ledger.jsonl"}
```

Deleting the newest ledger entries now leaves the remaining chain self-consistent but
**mismatched against the anchor**, so `verify()` reports `anchor_status: "mismatch"` and
`valid: false`. Verification states its semantics in every result: `valid` means the chain
is internally self-consistent, and completeness is established only when the anchor is
`verified` (or explicit expected tip/count assertions pass). A ledger written before
anchors existed has no sidecar: it still verifies as a chain, with
`anchor_status: "unverifiable-anchor"` — neither silently anchored nor hard-failed.
`aee verify-ledger --ledger <path> --write-anchor` mints an anchor for such a ledger after
verifying its chain, and `--expected-tip` / `--expected-count` check a ledger against
anchor values a consumer retained elsewhere:

```bash
aee verify-ledger --ledger .aee/epistemic-ledger.jsonl \
  --expected-count 3 --expected-tip <sha256>
```

OD-3 (the FR-4.1 anchor-design decision) is still formally open: this sidecar is the
local anchor the FR text requires. Pulling Spec 002 FR-8b's Axiomere anchoring forward
remains the stronger option, and a consumer who must detect truncation by someone able
to rewrite both local files should retain the anchor values outside the ledger's
directory — the sidecar's co-located copy is the current-state record, not the
independent evidence.

Verification is strict about shape as well as hashes: every physical line must be one
complete entry with the current `ledger_version`, a parseable timestamp, and correctly
typed fields; one malformed line invalidates the ledger with its line number, and
`entries()` applies the same rules. Re-appending an assessment whose hash the same
actor already recorded is refused as a duplicate unless explicitly allowed
(`allow_duplicate=True`), in which case the new entry names the original sequence.

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

