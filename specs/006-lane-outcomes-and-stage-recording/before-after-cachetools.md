# Before/after comparison — frozen cachetools study bundle (Spec 006 A5)

## What was run

- **Bundle**: the frozen input bundle from the benchmark study
  `current-study-01` (repository `spec-kit-aee-benchmark`, read-only):
  `reports/local/current-study-01/cachetools-20261017-spec_kit_aee/aee-project/inputs/specify-757d66d19b594bcb8695c9261535998d.json`.
  This is the bundle that produced the frozen assessment
  `aee-after_specify-20261017T033309047221-fd6af9Z.json` in that study.
- **Shape**: 5 claims (R00, R01, R02, R03, R02-EXT), every claim
  `draft` at stage `created`, every claim supported by the same one
  shared source.
- **Command (both runs)**:
  `aee assess --input <bundle> --project cachetools-study --phase after_specify --no-ledger`
- **Before**: engine 1.5.3 on `main` at 8211643, methodology 2.0.
- **After**: engine 1.6.0 on `spec006/lane-outcomes-stage-recording`,
  methodology 2.1.

## Results

| Quantity | Before (1.5.3 / 2.0) | After (1.6.0 / 2.1) | Changed? |
|---|---|---|---|
| Headline outcome | iterate | iterate | No |
| Lane-1 outcome | iterate (a copy of the headline) | iterate (computed from lane-1 facts) | Same value, now computed |
| R00 propagated score | 0.685 | 0.685 | No |
| R01 propagated score | 0.7225 | 0.7225 | No |
| R02 propagated score | 0.685 | 0.685 | No |
| R03 propagated score | 0.6975 | 0.6975 | No |
| R02-EXT propagated score | 0.6475 | 0.6475 | No |
| Claims at or above the 0.70 threshold | 1 of 5 | 1 of 5 | No |

The after scores also match the frozen study assessment's recorded
scores exactly (0.685, 0.7225, 0.685, 0.6975, 0.6475).

## Reading, stated plainly

Nothing moves on this bundle, and that is the correct result. Four
of its five claims score below the 0.70 threshold on their evidence
as recorded — one shared source for five claims — so lane 1 is
`iterate` on the machine-checking facts alone, and the headline is
`iterate` as well. Spec 006 does not inflate this bundle, and this
table is not the proof of the fix. The proof is the positive control
(`tests/test_spec006_lane_outcomes.py`): a bundle with two
independent sources per claim and every score at or above the
threshold, whose lane-1 outcome moves from `iterate` (the headline
copy, before) to `pass` (computed, after) while its headline stays
`iterate` until the recorded stage and status acts complete.
