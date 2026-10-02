# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/).

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
