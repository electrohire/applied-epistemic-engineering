# Spec 004 — P3 implementation record (lane-separated reporting)

Branch `impl/004-p3-lanes` off P2 head e0cdcfd. Claims first: the
Spec 004 bundle was assessed before and after with the real
assessor.

## Claims before / after

| Measure | Before (P2 build) | After (P3 build) |
|---|---|---|
| TA-004-12..20 mean (after_specify, 0.70) | 0.481 | 0.481 |
| TA-004-21 | 0.997 | 0.997 |
| Outcome | ITERATE | ITERATE |
| Suite | 597 passed | **603 passed** (+6 P3 tests, no regressions) |

P3 is a reporting phase: scores and outcome hold, and the bundle
now renders its own two-lane state — lane 1: iterate, 12 of 21
claims at/above threshold; lane 2: all 21 claims at effective stage
`created` (the bundle predates stage recording), 12 stage-capped,
lane-2 lag stated in the summary. The trail half of TA-004-18 /
TA-004-20 is this serialised record: it lives inside the
assessment, so the ledger's assessment hash covers it.

## What landed

- **`src/aee/lanes.py`** — `build_lanes()` derives the pair from
  records the assessment already carries (scores, stage caps,
  failure modes, attribution contests, effective-stage overrides);
  it computes nothing new about the claims. Per claim: lane 1 =
  propagated + direct score, author status, threshold comparison;
  lane 2 = effective stage, stored stage, capped flag with the cap
  reasons verbatim, exposition presence, verified-unexplained
  flag, attribution-contested flag. Per bundle: lane 1 = outcome,
  threshold, at/above counts; lane 2 = stage counts by effective
  stage, below-explained count, exposition coverage, and the
  verified-unexplained / stage-capped / attribution-contested
  counts.
- **Lane 2 is state, never a score** — pinned by a test that walks
  the lane-2 structures and asserts no `score` key exists anywhere
  in them. There is no blended number to compute.
- **Serialisation** — `Assessment.lanes`, always emitted in
  `to_dict()`; the assessment JSON schema gains a permissive
  `lanes` object property.
- **Summary pairing (R6.3)** — the summary always ends with the two
  lane sentences. Lane 2's sentence states its lag in counts
  whenever lag exists ("Lane-2 lag: N claim(s) below explained; M
  verified but unexplained; …") and says "No lane-2 lag" plainly
  when there is none — so a green lane 1 never appears in a summary
  without its lane-2 counterpart.
- **Docs** — `docs/scoring.md` gains "The two lanes" section: what
  each lane is, that they are never blended, and that the lane-2
  sentence travels with the lane-1 outcome.

## Honest limits

- The CLI's human-readable assess output prints the assessment
  summary, so the lanes appear there; a dedicated tabular lane
  display in the extension's commands is P5 surface work (held
  until P4 lands, per the sequence).
- Lane 2 inherits the honesty of the underlying records: stage is
  author-advanced (by recorded events), exposition presence is a
  record, not a quality judgment. The lane reports the state of
  the record, which is the inspectable thing.
