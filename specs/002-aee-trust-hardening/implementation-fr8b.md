# Spec 002 — FR-8b implementation record (Axiomere anchoring, T804–T806)

Branch `impl/002-fr8b-axiomere-anchor` off the joint line head
b2e8000 (Spec 003 FR-8 + Spec 004 P4). Claim TH-002-20's
deliverable; WP-8b is optional and blocks nothing (FR-8.6).

## What landed

- **`src/aee/anchor.py`** — `anchor_assessment()` deposits the
  assessment's content SHA-256 (the canonical
  `assessment_content_digest`, the same digest the hash-chain
  ledger records) as an `aee.assessment.anchored` event in an
  Axiomere `.axmr` ledger via the `axiomere` package, recording
  project / phase / outcome / methodology version in the event
  payload, then takes a checkpoint so the receipt names the
  checkpoint (Merkle) root. The package is probed with
  `importlib.util.find_spec`, never imported at module import
  time; absence raises `AnchorUnavailable` with the FR-8.6
  message. The ledger file is created when absent and opened
  (append-only) when present.
- **`aee anchor` CLI** — `--input` assessment, `--ledger` .axmr
  path, `--actor/--project/--phase`, `--output` to redirect the
  receipt-bearing write (default: update the input file in
  place). The receipt (ledger path, event seq + hash, checkpoint
  seq + root + hash, the deposited digest, timestamp, actor) is
  written back as `metadata.anchor` (FR-8.5/T805). On the
  unavailable path: message on stderr, exit 2, assessment file
  untouched.
- **Tests** (`tests/test_fr8b_anchor.py`) — availability probe
  agrees with importability; the unavailable path is graceful
  (API raises, CLI exits 2 with the message, file untouched);
  the live path is `importorskip`-style guarded.

## Verification (T806)

Exercised for real against axiomere 0.1.0 (the working install in
the Tekmerion environment), not merely skipped:

- Engine suite without the package: **639 passed, 2 skipped**
  (the two live-path tests skip, honestly labelled).
- The anchor test file under the axiomere-carrying environment:
  **4 passed** — receipt `assessment_sha256` equals
  `assessment_content_digest(assessment)`; `axiomere.verify_file`
  returns ok with the expected event count; a second anchor
  appends a later event and the chain still verifies; the CLI
  writes `metadata.anchor` with a checkpoint root.

## Honest limits

- `Database.open` on an existing file is the package's own
  append path; concurrent anchoring from two processes is the
  package's concurrency story, not something this thin binding
  adds locking around.
- The receipt records the checkpoint root at anchor time; later
  events in the same ledger move the head — the receipt is a
  historical commitment, verifiable against the event seq it
  names, not a claim about the ledger's current tip.
