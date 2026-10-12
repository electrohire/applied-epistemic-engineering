# Plan: AEE Trust Hardening (Spec 002)

**Input**: `specs/002-aee-trust-hardening/spec.md` + `claims.json` (assessed, after_specify, ITERATE)

**Prerequisites**: claims.json (required, assessed), spec.md (required)

**Organization**: Engine first where load-bearing — strict loading (FR-1) is the foundation the drafting command's TODO-rejection, the dispositions' strict validity, and verify-evidence all lean on. Extension and evaluator work follow once the engine contracts they consume are stable. WP-8b (Axiomere anchoring) is deliberately last and detachable.

## Phase 0 — Baseline before changes (guard rail)

- Capture the pre-change benchmark baseline with `spec-kit-aee-benchmark` (diagnostic rate on malformed/legacy/valid bundles) so FR-1's effect is measurable (feeds T810).
- Snapshot current CLI behavior on the three FR-1 fixtures as golden files (today's silent/bad behaviors), to be inverted by the new tests.

## Phase 1 — Engine: strict loading, validate, migrate (FR-1)

- `src/aee/model.py`: strict `from_dict` path (unknown-field detection, empty-text rejection, did-you-mean suggestions, enum errors with valid-value lists). Keep a lenient path behind an explicit flag for internal extraction use.
- `src/aee/extract.py`: `load_claims(..., strict=True)` default; migration mapping for legacy vocabularies.
- `src/aee/cli.py`: `validate` and `migrate` subcommands; `--lenient` on assess with metadata echo; clean-error path for all input errors.
- Fixtures + tests under `tests/fixtures/` and `tests/test_strict_loading.py`.

## Phase 2 — Engine: verifiable evidence + version stamps (FR-3, FR-4)

- `aee verify-evidence` (new module `src/aee/evidence_check.py`): ref resolution, content_hash recomputation, observed_at parse check, declared-vs-derived quality report; `assess --verify-evidence` folds findings into failure modes.
- Version stamping: `engine.py`/`cli.py` stamp `metadata.engine_version` from `aee.__version__`; drift test tying `aee --version` to the stamp.

## Phase 3 — Engine: dispositions + independence (FR-5, FR-6)

- Bundle format: `dispositions` on claims (model + schema), strict validity (reason required), challenge regeneration honoring stored dispositions, coverage in the summary.
- `_COMPOUND` recalibration with a fixture set of atomic prose claims that must not draw the challenge.
- Scoring: consume `independent_of`; independence basis in score notes; shared-evidence warning class (`independence_unmodeled`).

## Phase 4 — Extension: drafting, provenance, ledger parity (FR-2, FR-4.2, FR-8a)

- `spec-kit-aee`: new command `commands/speckit.aee.draft-claims.md` + runner support in `scripts/python/run_aee.py` (draft generation via engine helpers; depends_on scaffolding proposals per FR-6.3).
- Runner passes extension version into assessment metadata (`metadata.extension_version`).
- Engine CLI ledger default parity (FR-8.1) lands in the engine in this phase's first task so the runner and CLI converge together; runner reports verify-ledger verdict after append (FR-8.2); docs updated in both repos (FR-4.3 policy, FR-8.3 record semantics).

## Phase 5 — Evaluator: reference evaluator (FR-7)

- `spec-kit-evaluator`: deterministic spec-structure evaluator (script + `evaluators.yml` registration + passing/failing fixture specs + README walkthrough). Schema-validate emitted results in the walkthrough test.

## Phase 6 — Anchoring (WP-8b, optional, non-blocking) (FR-8.4–8.6)

- Anchor command against the `axiomere` Python package; receipt into `metadata.anchor`; graceful absence. Scheduled only after Phases 1–4 are merged; may ship as its own spec if it grows.

## Phase 7 — Verification close-out

- Benchmark re-run vs. the Phase 0 baseline (TH-002-21); full test suites in all three repos; re-assessment of this spec's claims (after_implement) with outcome claims re-scored on implementation evidence; GAPS/assessment records updated honestly (no status changes without evidence).

## Sequencing notes

- Phases 1→3 are engine-only and sequential (shared model/scoring surface).
- Phase 4 depends on Phase 1 (strict loader) and Phase 3 (dispositions in drafts are out of scope; drafts depend only on FR-1's TODO rejection).
- Phase 5 is independent and may run parallel to Phases 2–4 (different repo, different owner surface).
- Phase 6 depends on Phase 2's metadata shape (anchor receipt joins `metadata`).
