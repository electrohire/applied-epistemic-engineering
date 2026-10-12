# Spec 003 — FR-8 implementation record (joint with Spec 004 P4)

Branch `impl/004-p4-fr8-joint` off Spec 004 P3 head aeb989e, in the
engine repo. Implemented 2026-10-12 under OD-1 (owner authorization
to reopen scoring semantics) as the ONE joint methodology bump
with Spec 004's P4: **`methodology_version` "1.0" → "2.0"** — a
single bump naming both specs, per FR-8.2 and the Spec 004 plan's
P4. Lexicon data version 1.0 (`src/aee/lexicons.py`, FR-8.8).

## Claims before / after (real assessor, threshold 0.70)

| Measure | Before (methodology 1.0) | After (methodology 2.0) |
|---|---|---|
| RT-003-30..34 each | 0.481 | 0.331 |
| RT-003-35 | 0.481 | 0.356 |
| FR-8 claims mean | 0.481 | 0.335 |
| Bundle outcome | ITERATE | ITERATE |
| Engine suite | 603 passed | **637 passed** (+34 FR-8 acceptance tests) |

The score movement decomposes exactly, and the decomposition is on
each claim's own score notes: −0.10 because the claims' evidence
is undated and unknown freshness now counts as stale in the set
penalty (FR-8.6), plus boundary partial credit where a boundary
entry names no scope or limit (FR-8.7) — several FR-8 claims'
boundaries are file-path descriptions ("src/aee/scoring.py
propagation and …"), which the new notes correctly identify as
below the substance bar. No other component moved. The claims'
statuses are re-assessed at close-out (Spec 004 P6) on the
implementation evidence, not on these numbers.

## Per-item disposition

- **FR-8.1 claims first** — RT-003-30..35 pre-existed (amendment);
  the falsification fixtures are the RT1 probes inverted, now
  `tests/test_fr8_semantics.py`.
- **FR-8.2 methodology versioning** — the single bump above;
  benchmark before/after in §Benchmark below.
- **FR-8.3 cycle-local propagation (RT1-08)** — SCC condensation
  (iterative Tarjan, `graph.strongly_connected_components`);
  suppression scoped to the cyclic component, marked per claim
  (`propagation_status: suppressed_cycle`, `cycle_component`,
  named note). Claims depending on a cycle propagate against the
  members' direct scores. Bundle cycle failure still fires.
- **FR-8.4 failure-aware verdicts (RT1-09)** — `evaluate_policy`
  takes the claim's failure modes; unresolved HIGH/CRITICAL caps
  the verdict below ACCEPT with the demoting failures named in
  the reasons. The engine always passes them.
- **FR-8.5 contested-gate alignment (RT1-25)** — one documented
  basis (`policy.counterevidence_present`): any item directed
  against the claim, or a contradicted-kind item routed otherwise.
  The penalty-magnitude route is retained alongside.
- **FR-8.6 freshness (RT1-10)** — set-based as specified (a)–(e):
  per-item fresh/recent/stale/unknown classification, unknown
  (missing, unparseable, future) counting as stale, mean-of-tiers
  aggregation, tier magnitudes unchanged, basis documented in
  `docs/scoring.md` and named in every affected score's notes.
- **FR-8.7 substance over presence (RT1-11)** — criteria as
  specified; partial credit 0.5 per below-bar entry, component =
  mean over entries, failed criteria named in notes.
- **FR-8.8 lexicons as data (RT1-15)** — `src/aee/lexicons.py`
  (versioned; corpus in `tests/test_fr8_semantics.py`, both
  directions).
- **FR-8.9 negation subject binding (RT1-16)** — shared subject
  (leading content token, synonym-normalised) + ≥3 shared
  normalised tokens + negation asymmetry. Residual limit
  documented in the detector docstring and `docs/scoring.md`:
  cross-subject full paraphrase (probe p3 §E) remains undetected,
  per the acceptance's "handled per the documented residual
  limit".
- **FR-8.10 relevant boundary (RT1-17)** — suppression only by a
  boundary sharing content tokens with the claim or naming a
  scope/limit term.
- **FR-8.11 review-queue completeness (RT1-18)** — failure
  channel on `AssessmentView` (CLI view rebuilt from serialised
  failures), band + threshold crossings, cumulative drift against
  a caller-held baseline (`build_review_queue(baseline=...)`, CLI
  `--baseline`; the baseline advances only when the caller
  replaces it — reviewed state is the caller's record, not
  something the queue mutates), rename candidates paired by
  closest score with the heuristic nature stated.
- **FR-8.12 top-k integrity (RT1-19)** — adverse-first priority
  (failure channel, then negative deltas, then favourable; claim
  id only as final stabiliser); omissions reported in total and
  by kind.
- **FR-8.13 declared state + threshold (RT1-20, RT1-24)** —
  `declared_state` on every score record and carried into review
  items; threshold INCLUSIVE on the UNROUNDED score — scores are
  now stored unrounded (rounding is display-only) with a
  regression test at 0.6999996 (does not pass) and exactly 0.70
  (passes).
- **FR-8.14 (RT1-22)** — documentation only, verified present in
  `docs/scoring.md`; not claimed fixed anywhere.
- **FR-8.15 atomic precision (RT1-26)** — noun-phrase guards
  (version lists, numeric lists, unit alternatives, range idioms)
  + proper-noun guard for vague terms; corpus both directions.

## Two acceptance-text interactions, recorded honestly

1. **p5 §B's "STRONG capped at 0.378"** cannot hold literally
   alongside FR-8.7: 0.378 was computed under presence-credit for
   the probe fixture's one-word falsifier ("f") and label boundary
   ("profile L"), which FR-8.7 — in the same authorized bump —
   deliberately reduces to partial credit. The invariant the probe
   exists to prove (STRONG capped at WEAK's score despite the
   unrelated cycle; cycle reported; suppressed claims marked)
   holds and is tested; the exact figure under methodology 2.0 is
   the fixture's new direct score, shown in the test by
   construction rather than asserted as a magic constant.
2. **Probe p4 §D's first case** (a refutation relabelled
   `direction: context` on an OBSERVED-kind item) is, on
   inspection, not counterevidence under any reading the engine
   can defend: kind and direction agree that the item is context.
   The defect class it gestures at — a real refutation hidden by
   relabelling — is the kind-`contradicted` case, which FR-2.2
   already routes to `clarify` and FR-8.5 now also trips the
   standalone gate on. Both directions are tested.

## FR-2 draft cap vs Spec 004 stage cap (resolution, per plan)

Kept **distinct and layered**, as implemented across FR-2/P0: the
draft cap is an OUTCOME cap keyed on author-declared `status ==
draft` (its record is outcome-bearing by design); the stage cap
is a REPORTING/verdict cap keyed on lifecycle stage (its record
is explanatory; the outcome effect runs through R1.4's
below-explained rule). An assessment states which cap bound via
separate failure categories (`draft_cap` vs `stage_cap`) and the
stage-cap records in `stage_caps`. Neither was merged into the
other in this phase.

## Benchmark

Before (captured 2026-10-12 before any joint change,
`~/workspace/aee-joint/benchmark-before-2026-10-12.md`): benchmark
main e248d49, offline suite **321 passed**, engine = PyPI 1.4.0
pin, `scripts/check_pins.py` OK.

After (2026-10-12, this branch): same repo, same suite, run in a
scratch venv with the engine installed from this worktree
(methodology 2.0; the benchmark's own package installed --no-deps
so its 1.4.0 pin did not override the joint build; the benchmark
repo itself is untouched — a re-pin is a release-time act):
**310 passed, 11 failed** in 385.78s.

All 11 failures share ONE root cause, and it is a P0 consequence,
not an FR-8 semantics regression: the benchmark runner validates
claim bundles with strict `Claim.from_dict`, and its fixture
bundles (and the terminal bundle it synthesizes itself) carry no
`stage` field — Spec 004 R1.1 makes `stage` required on strict
load, with `aee migrate` / lenient load as the recorded remedies.
Failing: test_diagnostic_termination ×8,
test_matched_repair_port ×2, test_assessment_diagnostics ×1,
test_workflow::test_real_deterministic_extensions_on_synthetic_claim
×1 (the R1.1 error verbatim). The other 310 tests — including
every test that exercises engine scoring/gate behavior through
the benchmark — pass unchanged. Remediation is benchmark-side and
belongs with the release re-pin: add `stage` to the fixture and
synthesized bundles (or validate leniently where a model-authored
bundle is expected). Recorded here rather than fixed here because
the benchmark repo is outside this phase's branch scope and its
pin still names 1.4.0.

## Fixture updates

Pre-FR-8 tests asserting exact pre-2.0 values were updated with
the delta decomposition recorded in place (test_score_inflation
control bundle + three value assertions, test_scoring ×3,
test_review ×2, test_version_coherence methodology value). No
assertion's intent was weakened; the honest-bundle control still
pins exact values, now the methodology-2.0 ones.
