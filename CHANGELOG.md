# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/).

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
