# Spec 004 — integration addendum (2026-10-12)

Branch `integration/004-stack`: main `d48ce1e` (PRs #37/#38/#39)
merged with the Spec 004 phase stack (tip `698332b`) at merge
commit `d877f2e`, plus follow-up commits porting the orphaned
P0-completion work and repairing inherited lint/type findings.
This file is append-only integration evidence; no P6 record was
edited.

## Merge audit (d877f2e)

Merge base `655de24`. Six files were changed by both parents and
are hand-resolved in the merge (merged blob differs from both
parents); every other file took one parent's version unchanged:

- `pyproject.toml` — union: version 1.5.0 (stack) + `jsonschema`
  dev dependency (main, PR #37). `_version.py` is 1.5.0: lockstep.
- `src/aee/cli.py` — union: the stack's stage/identity/priority/
  anchor/graph-lenient surfaces + main PR #38's ledger-bound
  reliability loading in `_assess` (the only main-side cli change).
- `src/aee/__init__.py` — union: stack stage/identity exports +
  main's `ProvenanceAnchor` export.
- `tests/test_cli_policy.py`, `tests/test_reliability_validation.py`
  — unions of both sides' test changes.
- `specs/003-aee-red-team-remediation/tasks.md` — union: T307–T313
  (PR #38), T512/T513 (PR #39), T902 checked (stack P6).

Files changed by only one side carried that side whole:
`reliability.py` (PR #38 anchored canonisation, incl.
`ProvenanceAnchor`, anchored-only `reliability()`, provisional
track capped at 0.5, `record_resolution`/`verify_anchors`) and
`gaps.py` (PR #39 FR-5.11 symlink confinement) were touched by
main only — the stack had no competing changes to either, so
both semantics survive by construction and are exercised by
their main-side tests in the integrated suite. No resolution
dropped a side's semantics; nothing in the merge needed repair.

## Suite reconciliation

Collected/passed (CI-pinned pytest 9.1.1, this clone):

| Tree | Collected | Passed | Skipped |
|---|---|---|---|
| base 655de24 | 494 | 492 | 2 (evaluator sibling) |
| main d48ce1e | 522 | 520 | 2 |
| stack 698332b | 642 | 638 | 4 (2 evaluator + 2 axiomere) |
| merged d877f2e | 670 | 666 | 4 |
| integrated (final) | 689 | 685 | 4 |

Arithmetic: main added 28 tests over base and retired none; the
stack added 150 and retired 2 (base tests it deliberately
superseded: `test_cycle_skips_propagation_with_note`, replaced by
P4's `test_cycle_suppression_is_local_with_note`, and the
schema-parity `[minimal claim]` case, superseded by the stage-era
corpus incl. `[claim without stage]`). Node-id comparison
confirms the merged collection is exactly the parents' union
minus those 2 stack retirements: 522 + 150 − 2 = 670 collected,
520 + 148 − 2 = 666 passed. The reference points reconcile: the
"494" stack branch point is the base collection (492 passed + 2
skipped); "520" is main's passed count; the stack's "637 at P4"
grew to 638 passed at its P6 tip. The final +19 are the ported
orphan tests (below).

## Orphan port (impl/004-p0-vocabulary @ 3f4349b, 5fa2fdf)

That branch was never an ancestor of the stack. Verdicts:

- verified_unexplained — already present (P2, same semantics).
- not_understood — already present (P2, a superset of sources).
- digestion tracking — MISSING in part: P3's lanes reported stage
  and exposition presence, but no per-claim explainer record
  (R3.3: "who the explainers are"). Ported: `Assessment.digestion`
  (effective stage / resolved exposition present / explainers),
  `explainers` in lanes lane_2, assessment-schema property.
- lenient identity_resolution — MISSING. Ported: lenient load
  records unresolved exposition + an `identity_resolution`
  failure; the engine re-emits it at assessment; unresolved
  exposition confers no explanation credit anywhere.
- lenient stage derivation from the latest stage event —
  MISSING. Ported (`stage_derived` + not_understood notice).
- registry entries must declare `kind` (OD-T4) — MISSING (a
  missing kind silently defaulted to `person`). Ported, with
  duplicate ids still reported before shape problems.
- `verdict_ceiling` policy accessor + `aee` export — MISSING
  (table and enforcement were present). Ported.
- below_stage rename (the orphan's mypy fix) — MISSING. Ported
  in adapted form; it also clears two inherited mypy errors.
- implementation-p0.md addenda — MISSING. Appended verbatim to
  that record with a port note.
- Orphan surface forms NOT reintroduced (P2/P3 superseded them):
  the `Stages:` / `Verified but unexplained: N` summary sentences
  and the `stage_defaults` / metadata `stage_counts` keys. The
  ported tests (tests/test_stage_p0_completion.py: 14 of 19 orphan
  tests verbatim, 5 adapted) name each supersession.

## Inherited gate failures, repaired

At d877f2e, with CI-pinned ruff 0.16.9 / mypy 2.3.1: `ruff check`
reported 19 errors and strict mypy 10 — the stack's per-phase
"ruff + mypy clean" records do not survive verification.
`ruff format --check` failed on 17 files, all stack-introduced
(main and base are format-clean). All three gates are clean on
the integrated tree (follow-up commits on this branch; formatting
applied with `ruff format .`, no logic changes).

## Assessor re-runs (integrated build)

Invocation as in P6 (lenient load, `AEEEngine(policy=
AssessmentPolicy()).assess(claims, phase="after_implement")`) on
`claims-after-implement.json` for both bundles:

- Spec 004: outcome **ITERATE** (P6: ITERATE). All 21 propagated
  scores identical, incl. TA-004-12..19 @ 0.85, TA-004-20 @
  0.380625, TA-004-21 @ 0.89725. Verdicts, summary,
  reported_statuses, stage_caps, claims, failure count (77) and
  not_understood count (55) all identical to the P6 record.
- Spec 003: outcome **ITERATE** (stack's assessment-after-
  implement: ITERATE). All 35 propagated scores identical, incl.
  RT-003-30..34 @ 0.85 and RT-003-35 @ 0.875. Failure count (155)
  and not_understood count (99) identical.

Post-integration scores and outcomes do NOT differ from the P6
records, so no difference-explaining addendum is required; this
file records the re-runs themselves. The only serialised
differences from the P6 assessment files are the port's additive
surfaces: the new top-level `digestion` object and `explainers`
lists in lanes lane_2 (empty for both bundles — neither carries
exposition evidence, per the P6 audit addendum's own finding).
