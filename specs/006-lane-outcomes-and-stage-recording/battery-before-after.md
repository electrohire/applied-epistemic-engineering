# Spec 006 — release-gate battery: frozen bundles, baseline vs candidate

Run 2026-10-20, before any release decision. Every input below is a
frozen bundle from the benchmark record; the engines only re-scored
frozen model outputs offline — no new inference, no new evidence,
nothing re-authored.

- **Baseline engine:** 1.5.3, methodology 2.0, built from
  `origin/main` at `8211643` (a separate clean clone and venv).
- **Candidate engine:** 1.6.0, methodology 2.1, this spec's branch.
- For each bundle: headline outcome, lane-1 outcome, and every
  per-claim score under (a) the frozen original assessment where one
  exists, (b) the baseline engine, and (c) the candidate engine.
- The baseline engine must reproduce the frozen original — that is
  the battery's own setup check. It did, on every bundle.
- A difference counts as explained only when this spec predicts it:
  the lane-1 outcome is newly computed (A1), and the methodology
  version string moves 2.0 → 2.1 (A5). Headline outcomes and scores
  must not move at all. Anything else would be flagged here as a
  defect. **No unexplained differences were found.**

## 1. The frozen cachetools bundle (current-study-01)

Input:
`reports/local/current-study-01/cachetools-20261017-spec_kit_aee/aee-project/inputs/specify-757d66d19b594bcb8695c9261535998d.json`
(five claims, all draft at stage `created`, one shared source),
assessed at phase `after_specify`, the phase of the frozen original
(`aee-after_specify-20261017T033309047221-fd6af9Z.json`).

| Measure | Frozen original | Baseline 1.5.3 | Candidate 1.6.0 |
| --- | --- | --- | --- |
| Headline outcome | iterate | iterate | iterate |
| Lane-1 outcome | iterate (a copy) | iterate (a copy) | iterate (computed) |
| R00 score | 0.685 | 0.685 | 0.685 |
| R01 score | 0.7225 | 0.7225 | 0.7225 |
| R02 score | 0.685 | 0.685 | 0.685 |
| R03 score | 0.6975 | 0.6975 | 0.6975 |
| R02-EXT score | 0.6475 | 0.6475 | 0.6475 |

No differences beyond the methodology version string. Lane 1 stays
`iterate` here because four of the five scores are genuinely below
the 0.70 threshold — the honest result, stated in the spec before
the battery ran.

## 2. Detector-study sample (frozen assessment inputs)

The detector study is the matched hallucination-classification
comparison (its completed record is
`reports/hallucinations/matched-03-recovered-20261020/`). Its AEE
assessment inputs are frozen in the study's validation runs under
`reports/aee-validation/`, each holding the exact `claims.json` that
was assessed and the frozen `assessment.json` it produced. The
sample is the complete set of detector-study validation runs in the
frozen record — all five, not a selection: `matched-02`,
`matched-03`, `matched-04`, `external-hallucinations-01`,
`external-hallucinations-02`. Each bundle is a single observation
claim, status `partially_supported`, stage `checked`, score 0.90,
re-scored with the original run's own settings (phase
`after_implement`, evidence verification on).

| Bundle | Frozen original (headline / lane 1 / score) | Baseline 1.5.3 (headline / lane 1 / score) | Candidate 1.6.0 (headline / lane 1 / score) |
| --- | --- | --- | --- |
| matched-02 (OBS-MATCHED-001) | iterate / iterate / 0.90 | iterate / iterate / 0.90 | iterate / **pass** / 0.90 |
| matched-03 (OBS-MATCHED-003) | iterate / iterate / 0.90 | iterate / iterate / 0.90 | iterate / **pass** / 0.90 |
| matched-04 (OBS-MATCHED-004) | iterate / iterate / 0.90 | iterate / iterate / 0.90 | iterate / **pass** / 0.90 |
| external-hallucinations-01 | iterate / iterate / 0.90 | iterate / iterate / 0.90 | iterate / **pass** / 0.90 |
| external-hallucinations-02 | iterate / iterate / 0.90 | iterate / iterate / 0.90 | iterate / **pass** / 0.90 |

The one difference — lane 1 `iterate` → `pass` on all five — is the
spec's central prediction (A1), and the mechanism is visible in the
bundles themselves: the single claim's score is 0.90, at or above
the threshold, with no failure in lane-1 territory. The headline
`iterate` is held by the lifecycle rule (the claim sits at stage
`checked`, short of `explained`, and its status is
`partially_supported`) — lane-2 state, which the old engine copied
into lane 1 and the candidate no longer does. Headline outcomes and
scores are identical across all three columns on every bundle.

## 3. Controls (run as part of this battery)

The A6 controls are automated tests in
`tests/test_spec006_lane_outcomes.py`; the file was run against the
candidate as part of this battery: **24 passed, 0 failed** —
including the eight basis-type tests added with the A4 design note
(test-verdict acceptance and digestion, the failed-run /
missing-hash / unreferenced-test refusals, and the mixed-basis
end-to-end path).

The same positive-control bundle was also run through both engines'
command lines directly:

| Control fact | Baseline 1.5.3 | Candidate 1.6.0 |
| --- | --- | --- |
| Positive control: headline | iterate | iterate |
| Positive control: lane 1 | iterate (the defect — a copy) | pass |
| Positive control: scores | 0.85 / 0.85 | 0.85 / 0.85 |
| `aee gate` (default) | — | exit 1 |
| `aee gate --require-lane1-pass` | flag does not exist | exit 0 |
| `aee stage …` | no such command (exit 2, invalid choice) | records the act |

Negative controls (automated, candidate): the kill chain (twenty
copies of one model self-report plus one human assertion) reaches
`pass` in neither lane; an empty bundle blocks in both lanes; a
forged lane-1 outcome in an assessment file is refused by the gate
at exit 2; a ratification to `supported` at stage `created`, a
human-act acceptance by an unregistered name, and refused stage or
ratify commands all exit 2 and leave the bundle byte-identical.

## Battery verdict

Every observed difference between the baseline and the candidate is
predicted by this spec: the lane-1 outcome is computed instead of
copied (changed on the detector sample and the positive control,
unchanged where scores genuinely fall short), and the methodology
version string moved. Headline outcomes and per-claim scores are
identical on every frozen bundle. No difference is unexplained, and
no defect was found.

## Addendum (2026-10-20): deviation D1 — fix and retest

The battery above stands as recorded; this addendum is appended,
not merged into it. After the battery ran, the Phase D integration
proof found a defect the battery's bundles did not exercise: a
claim carrying exposition evidence AND an open failure could not
be composed into an evaluator result — the adapter emitted the
engine kind `exposition` into `findings[].evidence_refs[].kind`,
which the shipped evaluator contract (v1.1.2) does not allow, so
the run's evaluator result came back null and the extension runner
reported failure (exit 2) even though the assessment was written
and ledgered correctly. The defect is pre-existing (verified on
the baseline engine and on this branch before the fix, with the
identical error: `schema validation failed at
findings.0.evidence_refs.1.kind: 'exposition' is not one of
['observed', 'inferred', 'asserted', 'contradicted',
'unsupported']`).

Fix (engine-side, adapter only; see spec.md, "Deviation D1"): the
adapter translates evidence kinds into the contract vocabulary —
the five shared kinds as themselves, `exposition` as `asserted` —
keeps every ref, keeps the original kind visible in the composed
result's own claim record (`state.aee.claims`), and names every
translation in `metadata.evidence_kind_translations`.

Retest, on the exact Phase D scenario (two in-progress claims
carrying exposition evidence by named humans, each with an open
failure — one stage cap, one draft cap), through the shipped
engine + evaluator v1.1.2 pair:

- Pre-fix branch: the assessment is written; the evaluator output
  is refused with the error above and no evaluator result exists.
- Fixed branch: the evaluator result is written, is non-null, and
  validates with zero errors against the shipped evaluator v1.1.2
  schema; the shipped v1.1.2 composer accepts it
  (`invalid_results` empty, evaluator count 1) and composes it to
  `iterate` — the bundle's honest in-progress outcome — carrying
  both findings with the translated refs.
- Suite: 715 passed, 4 skipped (714 baseline + the new regression
  test, `test_engine_adapter.test_evaluator_adapter_translates_exposition_evidence_refs`,
  which fails on the pre-fix code with the recorded error);
  ruff and strict mypy clean.

No frozen bundle, score, or outcome in the battery above changes:
the fix touches only the adapter's translation of evidence kinds
into the contract envelope.
