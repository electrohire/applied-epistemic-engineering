# Spec 004 Phase P0 — Implementation Record (vocabulary + model)

**Branch:** `impl/004-p0-vocabulary` (spec/004-tao-realignment @ af0871a
+ merge of origin/main 655de24, then the P0 commits).
**Decisions applied:** OD-T2 (five stage terms verbatim), OD-T3 (cap
`supported` by stage, R1.3), OD-T4 (project-local identity registry +
engine-enforced shape rules) — all ratified 2026-10-12 (spec §9, plan §0).

## What landed

- **Model (`src/aee/model.py`)**: `ClaimStage` (created, checked,
  explained, accepted, digested) + `STAGE_ORDER`; `Claim.stage` +
  `Claim.stage_events` + `stage_defaulted` load bookkeeping;
  `Claim.advance_stage()` is the only way stage moves — recorded
  (kind/author/date/basis), forward-only, never called by any score.
  `StageEvent`/`StageEventKind` serialised in `to_dict`.
  `EvidenceKind.EXPOSITION` added. `IdentityKind` (person/tool/model/
  team), `IdentityEntry`, `IdentityRegistry` (list, `identities`
  object, or id-mapping shapes; duplicate ids rejected), and
  `validate_exposition_evidence()` — the R3.2 named-human rule as
  FR-1-shaped `BundleValidationError`s: empty source_id, no registry,
  unresolvable id, and non-person entries are all strict load errors.
- **Caps (`src/aee/stage.py`, new)**: the R1.3 table as data —
  `ALLOWED_STATUSES`, `VERDICT_CEILING`, `LIFTING_EVENT` — plus
  `StageCap` records, `reported_statuses()`, `below_explained()`.
  Caps only lower reported vocabulary; scores and stored statuses are
  untouched.
- **Policy (`src/aee/policy.py`)**: `Verdict.UNJUDGED` for stage
  `created` (no verdict issued — distinct from abstention); verdict
  ceiling `challenge` at stages checked/explained even when every
  other gate clears; exposition counts as a positive kind for the
  corroboration sign test.
- **Engine (`src/aee/engine.py`)**: assessment serialises
  `reported_statuses` + `stage_caps`; binding caps emit `stage_cap`
  failure modes naming the cap and its lifting event; outcome
  inherits the caps (R1.4, conservative form: `pass` requires every
  covered claim at stage ≥ explained — the lane-qualified outcome
  form is P3/R6); `metadata.stage_defaulted_claims` names every
  lenient-defaulted claim; the summary states stage-cap counts.
- **Loading/migration (`src/aee/extract.py`, `cli.py`)**: strict load
  requires a valid `stage` (missing = named required-field error,
  unknown = enum error); lenient load defaults `created` and flags
  `stage_defaulted`. Registry resolution order: explicit
  `load_claims(identity_registry=...)` / CLI `--identity-registry`,
  else a bundle-adjacent `identities.json`. `migrate_bundle`
  backfills `stage: created` and reports every touched claim.
- **Schemas + docs**: claim/assessment JSON schemas extended (stage,
  stage_events, reported_statuses, stage_caps, `unjudged`);
  `docs/scoring.md` documents the stage model.

## Claims first — before/after (actual assessor runs)

Spec 004's own claims bundle, phase after_specify, threshold 0.70.
Before: the frozen pre-implementation run (preserved at assessment
time, engine pre-P0). After: this branch's engine, lenient load (the
bundle predates `stage`; every claim defaults to `created` and is
named in `metadata.stage_defaulted_claims`).

| Claim | Before | After | Note |
|---|---|---|---|
| TA-004-12…20 (outcome) | 0.481 | 0.481 | scores unchanged — P0 changes vocabulary/caps, not lane-1 scores |
| TA-004-21 (decision) | 0.997 | 0.997 | — |
| Bundle outcome | ITERATE | ITERATE | correct: outcome claims are draft-stage by the framework's own new rule |

Reported statuses for the bundle's claims are now stage-capped
(`created` → draft only, verdicts unjudged where policy runs) — the
discipline applying to the framework's own spec first.

## Tests

- New: `tests/test_stage_vocabulary.py` + `tests/fixtures/stage/`
  (cap table, loading, registry, migration fixtures) and
  `tests/test_tao_p0.py` (coordinator acceptance tests: cap table
  status+verdict per stage, outcome inheritance, forward-only stage
  events, strict/lenient stage loading, migrate backfill, registry
  accept/reject matrix incl. tool/model/team entries).
- Existing suites updated where P0 deliberately changed behaviour
  (stage-aware fixtures/expectations).
- **Full suite: 573 passed, 0 failed** (baseline on main: 494;
  growth is the P0 test corpus + updated expectations).

## Honest limits / deviations

- P0 does NOT emit `not_understood` or `verified_unexplained` —
  both are P2 (plan.md) and remain open.
- R1.4 ships in its conservative form (no settlement-worded `pass`
  below stage `explained`); lane-qualified outcomes are P3.
- Scores on existing bundles can shift slightly where new failure
  modes (stage_cap) enter failure-count-sensitive paths; the
  methodology_version bump that accounts for semantics changes is
  P4's single joint bump, per OD-T1 — P0 deliberately does not bump.
- Process note: two delegated attempts at this phase reported
  commits that never reached the remote; the work was completed and
  verified in this worktree by the coordinator, with the push
  read-back as the acceptance evidence.
