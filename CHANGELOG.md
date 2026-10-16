# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/).

## Unreleased

### Changed
- Add a standalone agent skill to the engine package source and document CLI,
  direct-agent, and Spec Kit skill workflows. Remove retired scaffold migration
  and porting pages from the current documentation.
- Distinguish the PyPI distribution, Python module, engine CLI, and Spec Kit
  extension IDs; explain bounded verification, certification limits, and why
  GitHub/RTD development docs can differ from released PyPI metadata.
- Refresh this repository's own Spec Kit, AEE, and evaluator setup.

## [1.5.2] - 2026-10-15

Documentation only. Engine behavior, scoring, and `methodology_version` are
unchanged.

### Changed
- The Spec Kit install example in the README (the PyPI project page), quickstart,
  Spec Kit integration, and migration docs now pins spec-kit-aee 1.5.1, the tested
  extension release with the `draft-claims` setup fix (it pinned 1.5.0). The text
  presents it as a pinned example of an independently versioned extension. The
  engine requirement the extension declares stays `>=1.5.0,<2`.

## [1.5.1] - 2026-10-15

Documentation and package metadata only. Engine behavior, scoring, and
`methodology_version` are unchanged.

### Changed
- README (the PyPI project page) and the quickstart now state supported
  platforms (Linux, macOS, Windows; Python 3.11-3.13) and that Spec Kit users
  install the `spec-kit-aee` extension, which installs a compatible engine
  (`>=1.5.0,<2`) automatically. The extension is a Spec Kit extension, not a
  PyPI package, and is versioned independently.
- `docs/spec-kit.md` documents the one-command Spec Kit install and what the
  extension installs automatically; `docs/migration.md` no longer tells Spec Kit
  users to install the two extensions separately.
- `docs/versioning.md`: the extension's engine floor is `>=1.5.0,<2` (it said
  `>=1.4.0,<2`), and catalog updates follow Spec Kit's current procedure (a new
  Extension Submission issue after each tested release; no direct catalog PR).
- Added the `Operating System :: OS Independent` classifier.

### Fixed
- README documentation links were relative, so they broke on PyPI; they are now
  absolute.

## [1.5.0] - 2026-10-12

### Added

- Lifecycle stage on the claim model (Spec 004 realignment): every claim carries a stage — created, checked, explained, accepted, digested — advanced by dated stage events with named authors, and reported status is capped by stage. A claim at `checked` cannot report `supported`; support consisting entirely of machine-checkable evidence (observed/test) caps the stage at `checked` until human-paced support (an exposition item, or a human / primary / secondary source) is recorded. Exposition evidence must resolve its explainer against the project-local identity registry (declared `person` entries; tools and models cannot hold the explainer role), and bundles gain digestion tracking: verified-but-unexplained claims are flagged `verified_unexplained` rather than silently settled.
- Attribution and decomposition (Spec 004): attribution is recorded as claims in their own right — a contested attribution caps its parent claim — and headline claims carry decomposition projections (faithful statement, verified evidence, genuinely open/novel, attribution clean, significance), each scored separately. Priority/registration records protect provenance, and assessments state what remains `not_understood` as a mandatory field, not an optional note.
- Lane-separated reporting (Spec 004): assessments report lane 1 (machine-speed verification — scores, outcomes) and lane 2 (human-paced acceptance — the stage distribution) side by side, never blended; lane 2 is state, not a score. The engine-side evaluator contract result carries `lanes`, `not_understood`, and `reported_statuses` in its metadata.
- Trust-hardening tooling (Spec 002): `aee validate` and `aee migrate` load claim bundles strictly and loudly (unknown keys, wrong types, and ambiguous ids are refused by name, never coerced); `verify-evidence` checks evidence references and returns receipts; a drafting helper authors claims that pass the strict loader; challenge dispositions and independence on-ramps give challenged claims a recorded resolution path. Assessments are stamped with the engine version and methodology version (FR-4), and the bare engine CLI now ledgers assessments by default like the extension runner (FR-8a), with `--no-ledger` as the explicit opt-out.
- `aee anchor` (Spec 002 FR-8b): appends an assessment's SHA-256 to an Axiomere `.axmr` ledger via the `axiomere` package, recording the receipt as `metadata.anchor` — an external, append-only anchor for the local hash chain's head.

### Changed

- `methodology_version` "1.0" → "2.0" — the single bump covering both the Spec 004 stage model and the Spec 003 FR-8 scoring/challenge/review semantics, which were implemented jointly so no release ever carried one without the other. Scores are now stored and reported unrounded: a propagated score of 0.6999995 reports `iterate`; the 0.70 threshold is inclusive exactly at 0.70.
- Reliability canonisation requires anchored provenance (Spec 003, RT1-07): an observation counts toward a source's canonised reliability only via a `ProvenanceAnchor` that resolves in the reliability table's bound hash-chained ledger (chain verifies, payload matches exactly, one anchor per observation per source). Self-asserted provenance — free-form strings, `allow_unattributed`, legacy loads — earns provisional credit only: cold-start-gated, capped at 0.5, labelled `provisional` in the output, and never blended into canonised reliability.

### Fixed

- Outcome integrity (Spec 003 FR-1): an empty claim bundle blocks instead of passing with exit 0; duplicate claim ids block; `aee gate` recomputes the outcome from the assessment's own contents and refuses a file whose stated outcome disagrees — a bare `{"outcome":"pass"}` object no longer gates anything. Failure paths return contract verdicts and exit codes instead of tracebacks.
- Score inflation (Spec 003 FR-2): duplicate evidence items are deduplicated before scoring (the same item repeated 20× no longer moves a score); polarity coherence is enforced, so a contradicting item re-labelled `direction:"context"` can no longer launder a contradiction; draft-stage claims' outcomes are capped at `iterate` regardless of score.
- Reliability inputs (Spec 003 FR-3): table loading validates strictly — NaN and out-of-range values are refused loudly instead of corrupting Brier-derived reliability (a NaN Brier previously read back as reliability 1.0) — and resolved-claim credit is contribution-weighted rather than flat per mention.
- Ledger and CLI safety (Spec 003 FR-4/FR-5): the hash-chained ledger carries a sidecar head anchor, so tail truncation is detectable, and chain verification is strict. CLI output paths are guarded against symlink and collision attacks that could overwrite the run's own inputs; duplicate JSON keys in input files are refused; artifacts carry content digests. `aee gaps` evidence discovery is confined to the evidence root (FR-5.11): a symlink resolving outside it refuses the run, naming the offending entry and its target.
- Evaluator composition (Spec 003 FR-6): composing zero evaluator results blocks instead of passing, composition validates every input against the result contract, and the engine validates evaluator results it consumes. CI now declares `jsonschema`, so the strict schema-parity corpus (38 cases) actually runs — it was previously skipped silently in CI while passing locally.

### Known limitations

- Negation detection (FR-8.9) binds contradictions by shared subject, normalised tokens, and negation asymmetry. A cross-subject full paraphrase — "stores passwords in plaintext" against "does not persist credentials unencrypted" — remains undetected; this is a declared residual in the FR-8 record, not a silent gap.
- Lane pairing in composed evaluator results ships in the spec-kit-evaluator's own release; this release carries the engine-side contract only.

## [1.4.0] - 2026-10-06

### Added

- CLI wiring for the ported mechanisms (the Spec Kit extension drives the engine through this CLI): `aee assess --policy` attaches the policy gates, with `--min-independent-sources` and `--contested-threshold` overrides; `aee assess --reliability <table.json>` (plus `--reliability-alpha`) blends measured per-source reliability into scoring; new `aee review --previous A.json --current B.json [--materiality] [--limit] [--output]` subcommand emits the materiality review queue for two serialized assessments.

### Fixed

- The `abstain` assessment outcome (introduced with the policy gates in 1.1.0) now maps to the soft exit code 1 like the other non-pass verdicts, instead of falling through to 2, which the exit-code contract reserves for hard blocks and errors.

## [1.3.0] - 2026-10-06

### Added

- Materiality review queue (`aee.review`), slice 3 of the epistemic-ledger port: `build_review_queue(previous, current, materiality=0.05, limit=None)` diffs two assessments (or two score mappings) and returns a `ReviewQueue` — claims whose propagated score moved by at least the materiality threshold (largest first, optional top-k budget), policy verdict flips, and added/removed claim ids, each item carrying its before/after scores and confidence bands. The 0.05 default is the ledger's validated hysteresis point (CHURN-01 / TRIGGER-STRESS-01). This completes the three ported mechanisms in `docs/porting-from-epistemic-ledger.md`.

## [1.2.0] - 2026-10-06

### Added

- Per-source reliability (`aee.reliability`), slice 2 of the epistemic-ledger port: a `ReliabilityTable` records resolved outcomes per `source_id` (the propagated score live at assessment time plus the claim's eventual truth) and derives measured reliability as 1 − Brier. `ScoringEngine(reliability=table, reliability_alpha=0.5)` — also forwarded by `AEEEngine` — blends a supporting source's static `SourceQuality` weight toward its measured reliability once the source reaches `min_observations` (default 3); below that the prior stands, contradicting evidence always keeps its static weight, and every substitution is written onto the claim score's notes. `ReliabilityTable.observe_claim` credits a resolved claim to each distinct supporting source. Without a table, scoring is bit-identical to 1.1.0. The table serializes with `to_dict`/`from_dict`.

## [1.1.0] - 2026-10-06

### Added

- Assessment policy gates (`aee.policy`), ported from the epistemic-ledger program's measured production rules: `AEEEngine(policy=AssessmentPolicy())` attaches a per-claim verdict (ACCEPT / CHALLENGE / ABSTAIN, with reasons) to every assessment. Corroboration gate: fewer than `min_independent_sources` (default 2) independent supporting sources → CHALLENGE. Forced abstention: no supporting evidence, or support consisting solely of model self-attestation → ABSTAIN. Contested gate: contradiction penalty ≥ `contested_penalty_threshold` (default 0.25) → CHALLENGE at best. An assessment containing an ABSTAIN verdict reports outcome `abstain` instead of `pass`; one containing a CHALLENGE verdict reports `iterate` instead of `pass`. Verdicts layer above scores and never mutate them, so scoring stays replayable. Without a policy, behavior is unchanged; `Assessment.to_dict()` now always includes a `verdicts` object (empty when no policy is attached).
- `docs/porting-from-epistemic-ledger.md`: the transfer map — which measured mechanisms from AXIOVEX/epistemic-ledger are ported (policy gates now; per-source reliability and the materiality review queue planned), and which are deliberately not (LLM extraction, bitemporal event sourcing, the measurement harness).

## [1.0.4] - 2026-10-02

### Fixed

- Mermaid rendering no longer merges distinct claims: node IDs are encoded injectively (`A-B` and `A_B` previously both became `C_A_B`), and labels escape double quotes as `&quot;` entities and flatten newlines instead of only rewriting quotes in the claim text while interpolating the ID raw.
- `load_claims` refuses a JSON object without a `claims` key (previously it silently loaded an empty claim set and produced a vacuous assessment), and markdown `depends_on` refs are uppercased to match the uppercased claim IDs (a lowercase ref previously never resolved).
- Ledger appends are O(1) after the first verification instead of O(n) each (O(n²) over a session): appends trust a verified-tip cache keyed on the file's size and mtime, and any external change forces a full `verify()` before the next append. Chain semantics and the append lock are unchanged.

### Documentation

- The mutation contracts are now stated where they happen: `StressTester.run` replaces each claim's `failures` list wholesale (carried-in failures are not preserved), and `ScoringEngine.score` overwrites `claim.confidence` with the propagated score. Both behaviors are pinned by tests.

## [1.0.3] - 2026-10-02

### Fixed

- Gap preservation is keyed on the stable `test_id`, not the positional `GAP-XXX` ID: inserting, deleting, or reordering a matrix row no longer moves a preserved closure onto a different test. The register format gains a `Test` column; legacy registers without it still parse and preserve by ID.
- Documented gap statuses `in_progress` and `blocked` survive a load/regenerate cycle; the register parser previously reset every open row to `open`.
- `aee gaps --close` on a nonexistent gap ID is now an error (exit 2). `close_gap` raises `KeyError`; previously it silently succeeded.
- CLI error contract: malformed input, invalid enum values, out-of-range thresholds, and unsupported phases now exit `2` with a clean message instead of a traceback with exit `1` — a code the README defines as a soft outcome, so crashes were indistinguishable from legitimate soft verdicts in CI.
- Corrupt evidence JSON files produce a stderr warning instead of being silently treated as "no evidence".
- Failure IDs are unique per failure instance: the same challenge firing against several peers previously produced identical IDs, colliding recovery proposals and evaluator findings.
- `ClaimGraph.cycles()` is iterative; dependency chains beyond ~1,000 claims no longer raise `RecursionError` inside `assess()`.
- Cyclic dependency graphs now record "propagation skipped" on the affected scores instead of silently leaving them uncapped.
- `HashChainLedger.append()` takes an advisory file lock around verify+append so concurrent appends cannot fork the chain; `entries()` reports corruption as a `ValueError` naming the line, agreeing with `verify()`.

### Added

- `ScoringEngine.score(..., as_of=...)` and `AEEEngine.assess(..., as_of=...)`: pin the instant freshness is judged against, making assessments replayable. Previously the freshness penalty read the wall clock, so identical input scored differently on different days. Unparseable `observed_at` values are now noted on the score instead of silently skipped.
- `--version` reads the package `__version__` (single source) instead of a third hardcoded copy.

### Changed

- Bump version `1.0.2` -> `1.0.3`.
- Tests: 59 -> 72 passed (gap identity/status/close/evidence regressions, CLI exit contract, freshness pinning, deep-graph, failure-ID uniqueness, ledger lock/corruption).

## [1.0.2] - 2026-09-10

### Added

- `GapEngine` and the `gaps` CLI subcommand: generate and maintain a gap register from a verification matrix and test evidence.
- Deterministic `challenge` CLI subcommand: a failures + recoveries projection over `assess` (no scoring keys leak).

### Changed

- Bump version `1.0.1` -> `1.0.2`.
- Tests: gaps (13) + challenge CLI projection (2); core suite 59 passed.

## [1.0.1] - 2026-09-04

### Changed

- Generalize migration and project documentation.
- Add structured bug-report and feature-request templates.
- Add dependency review, Dependabot, OpenSSF Scorecard, and hash-locked CI installs.
- Document the private disclosure process and response timeline.

## [1.0.0] - 2026-09-04

### Added

- Independent Applied Epistemic Engineering domain model.
- Claim decomposition, evidence/provenance representation, and explicit uncertainty.
- Deterministic stress testing, contradiction discovery, dependency analysis, and recovery.
- Evidence-quality scoring with weakest-link propagation.
- Tamper-evident SHA-256 JSONL ledger with complete-chain verification.
- Adapter for ElectroHire's Spec Kit Evaluator Contract v1.0.
- Dependency-free CLI and Python API.
- Strict Read the Docs/MkDocs documentation and multi-platform CI.

[1.0.2]: https://github.com/electrohire/applied-epistemic-engineering/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/electrohire/applied-epistemic-engineering/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/electrohire/applied-epistemic-engineering/releases/tag/v1.0.0
