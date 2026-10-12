# Tasks: AEE Trust Hardening (Spec 002)

**Input**: Design documents from `specs/002-aee-trust-hardening/`

**Prerequisites**: spec.md (required), plan.md (required), claims.json (assessed — after_specify, ITERATE)

**Status**: Draft. All tasks unchecked; implementation is future, separately-approved work. Each task names its repo: **engine** = `electrohire/applied-epistemic-engineering`, **extension** = `electrohire/spec-kit-aee`, **evaluator** = `electrohire/spec-kit-evaluator`, **benchmark** = `electrohire/spec-kit-aee-benchmark`.

**Format**: `[ID] [Repo] Description` — grouped by finding (FR-1…FR-8), per the spec.

## Phase 0 — Baseline

- [ ] T001 [benchmark] Run spec-kit-aee-benchmark on current engine; record diagnostic-rate baseline for malformed/legacy/valid bundles in the benchmark repo.
- [ ] T002 [engine] Commit golden files of current (defective) load behavior on the three FR-1 fixtures under `tests/fixtures/`.

## FR-1 — Strict, loud validation [engine]

- [ ] T101 [engine] Strict `from_dict` for Claim/Evidence/FailureMode in `src/aee/model.py`: unknown-field errors, empty-`text` rejection, claim-id + field named in every message.
- [ ] T102 [engine] Did-you-mean suggestions for near-miss field names; enum errors listing the full valid value set.
- [ ] T103 [engine] `load_claims(strict=True)` default in `src/aee/extract.py`; `--lenient` flag on assess, echoed into assessment metadata when used.
- [ ] T104 [engine] `aee validate` subcommand (strict load + structural checks, CI exit codes) in `src/aee/cli.py`.
- [ ] T105 [engine] `aee migrate` subcommand: legacy vocabulary mapping (kind/status synonyms, `statement`→`text`, `falsifier`→`falsification_tests`), applied-mapping report, loud refusal on unmappable values.
- [ ] T106 [engine] Regression fixtures + tests: renamed-field bundle, bad-enum bundle, legacy Tekmerion Spec 001 bundle (migrate → assess round-trip).

## FR-2 — Claims drafting [extension + engine]

- [ ] T201 [engine] Drafting helper in `src/aee/extract.py` (requirement → draft claim proposal, reusing `derived_claim_id`); drafts hard-coded to `status: draft`.
- [ ] T202 [extension] New command `commands/speckit.aee.draft-claims.md` + registration in `extension.yml` provides list.
- [ ] T203 [extension] Runner support in `scripts/python/run_aee.py` for draft generation from a spec directory.
- [ ] T204 [extension] Ratification guard: no tool path sets a drafted claim above draft; TODO falsifiers emitted explicitly so FR-1 strict loading rejects unfinished drafts.
- [ ] T205 [engine] Tests: fixture spec → drafts are per-requirement, all draft, source_ref set; unedited drafts assess no higher than their evidence warrants.

## FR-3 — Verifiable evidence [engine]

- [ ] T301 [engine] New `src/aee/evidence_check.py`: ref resolution inside project root (path-safety), URL refs reported unresolvable-offline.
- [ ] T302 [engine] content_hash recomputation + observed_at parse validation in evidence_check.
- [ ] T303 [engine] Deterministic derived-quality rules + declared-vs-derived mismatch challenges; undeclared quality never upgraded from `unknown`.
- [ ] T304 [engine] `aee verify-evidence` subcommand; `assess --verify-evidence` folding findings into failure modes.
- [ ] T305 [engine] Fixtures + tests: dangling ref, corrupted hash, quality mismatch, clean bundle.

## FR-4 — Version coherence [engine + extension]

- [ ] T401 [engine] Stamp `metadata.engine_version` from `aee.__version__` in engine/cli metadata assembly.
- [ ] T402 [engine] Drift test: `aee --version` string equals the stamped version source.
- [ ] T403 [extension] Runner passes extension version; recorded as `metadata.extension_version`; absent (not fabricated) on the bare-CLI path.
- [ ] T404 [engine] Version policy doc (README/docs): engine version = source of truth, extension floor = compatibility contract, catalog update in the same release PR as an extension bump.

## FR-5 — Challenge dispositions [engine]

- [ ] T501 [engine] `dispositions` record on Claim (model + JSON schema): kind (split|accepted-atomic|waived), reason (required), author, date; strict-load validity.
- [ ] T502 [engine] Challenge regeneration honors stored dispositions: matched challenges report resolved with reason inspectable; `split` successors validated for existence.
- [ ] T503 [engine] Disposition coverage in assessment summary (raised / dispositioned / open).
- [ ] T504 [engine] `_COMPOUND` recalibration + atomic-prose fixture set that must not draw the irreducibility challenge.
- [ ] T505 [engine] Tests: reasoned disposition persists across runs; reasonless waiver fails strict load; removing a disposition reopens the challenge.

## FR-6 — Dependency & independence on-ramps [engine + extension]

- [ ] T601 [engine] Scoring consumes `Evidence.independent_of` (`src/aee/scoring.py`).
- [ ] T602 [engine] Independence basis in score notes (`declared` / `inferred-from-references` / `none`); inferred basis carries the shared-origin caveat.
- [ ] T603 [engine] Shared-evidence warning class (`independence_unmodeled`) when claims share supporting refs/source_ids without declarations.
- [ ] T604 [extension] Draft-claims scaffolds `depends_on` proposals from explicit spec cross-references (rides on T202/T203).
- [ ] T605 [engine] Tests: same-origin-different-ref fixture no longer reports unqualified 1.0; declarations change the computation; disjoint fixture stays silent.

## FR-7 — Reference evaluator [evaluator]

- [ ] T701 [evaluator] Deterministic spec-structure evaluator script (spec/plan/tasks presence, claims bundle presence + strict-load validity, assessment presence) emitting schema-valid evaluator results.
- [ ] T702 [evaluator] `evaluators.yml` registration for the reference evaluator.
- [ ] T703 [evaluator] Fixture specs (passing + failing) and a README walkthrough: discovery → `speckit.evaluator.run` → compose, with schema validation of the emitted result.
- [ ] T704 [evaluator] Tests for the walkthrough in a clean checkout (no hand registration).

## FR-8a — Ledger parity [engine + extension]

- [ ] T801 [engine] `assess` ledgers by default (documented default path) with `--no-ledger` opt-out; `--ledger <path>` retained.
- [ ] T802 [extension] Runner reports the verify-ledger verdict alongside assessment/evaluator/ledger paths after append.
- [ ] T803 [engine] Docs: ledger entry is the record (it already stores the assessment SHA-256); the JSON file is a working copy. CLI help updated.

## FR-8b — Axiomere anchoring (separate, later, non-blocking) [engine or extension]

- [ ] T804 [engine] Optional anchor command depositing the assessment SHA-256 into an Axiomere `.axmr` ledger via the `axiomere` Python package; graceful "anchor unavailable" when the package is absent.
- [ ] T805 [engine] Anchor receipt (ledger path, event/snapshot id, checkpoint root) recorded as `metadata.anchor`.
- [ ] T806 [engine] Verification test: receipt hash matches the assessment and verifies via the axiomere package's own `verify_file`.

## Close-out

- [ ] T810 [benchmark] Re-run spec-kit-aee-benchmark against the T001 baseline; confirm no diagnostic-rate regression (claim TH-002-21) and record results in the benchmark repo.
- [ ] T811 [engine] Re-assess Spec 002 claims (after_implement) on implementation evidence; update `assessment.json` and spec §9 honestly.
- [ ] T812 [engine] Full test suites green in engine, extension, and evaluator repos before any release step is proposed (releases remain owner-gated).
