# Spec 004 — P6 close-out record

Branch `impl/004-p6-closeout` off the final joint line head
70a4e98 (engine P5). All re-assessments run on that build:
engine 1.5.0, methodology 2.0.

## Re-assessments (after_implement)

**Spec 004** (`claims-after-implement.json` /
`assessment-after-implement.json` in this directory; the frozen
after_specify files are not rewritten):

| Claims | Before (P4 build, pre-implementation evidence) | After (final build, implementation records) |
|---|---|---|
| TA-004-12..19 (semantics) | mean 0.336 | **0.85 each** |
| TA-004-20 (sequencing decision) | 0.336-band | 0.381 — its evidence is the historical OD-T1 record under 2.0 freshness/substance semantics; recorded as-is, not re-evidenced or tuned |
| TA-004-21 (OD-T1 decision) | 0.897 | 0.897 |

Outcome ITERATE (every claim in the bundle still sits at its
recorded stage; lane 2 is stated, per the addendum).

**Spec 003 FR-8** (`claims-after-implement.json` /
`assessment-after-implement.json` in that spec's directory):

| Claims | Before | After |
|---|---|---|
| RT-003-30..34 | 0.331 | **0.85** |
| RT-003-35 | 0.356 | **0.875** |

**Spec 003 T902**: checked off with its completion evidence
(the FR-8 probes inverted on the joint build or explicitly
recorded as remainders — RT1-07's residual and RT1-22's
documented limitation), in that spec's tasks.md.

## Retro-audit sample

`audit-addendum-2026-10-12.md` (beside the original audit,
append-only): four post-realignment bundles sampled. Falsifier
coverage complete (64/64); `not_understood` populated in every
assessment (55/99/13/13 entries); explicit stage fields 0/64 and
attribution-marked claims 0/64 — recorded as findings: the
machinery ships and reports the lag; the program's own lane-2
record (stage events, exposition, attribution claims) is future
human-paced work, and nothing in the close-out claims otherwise.

## Frozen-artifact verification

See the addendum's verification section: Specs 001–003 frozen
files byte-identical to audit §8; the Spec 004 delta is
explained by commit `0082ba1` predating ratification-era freeze
(the files are identical across the audit clone tip and the
joint line tip, untouched by every implementation commit); the
audit's own files untouched since `7600277`.

## Program state at close-out (for the coordinator's merges)

Joint line: main 655de24 → impl/004-p0-vocabulary (b98811d) →
impl/004-p1-attribution (b0f6958) → impl/004-p2-policy-gates
(e0cdcfd) → impl/004-p3-lanes (aeb989e) → impl/004-p4-fr8-joint
(b2e8000) → impl/002-fr8b-axiomere-anchor (b043459) →
impl/004-p5-evaluator-contract (a6d1713 → b60d499 → 70a4e98) →
impl/004-p6-closeout (this branch). Extension:
impl/004-p5-vocabulary-alignment (3053a99) off e0064f0.
Evaluator: impl/004-p5-lane-paired-composition (63c1b7e) off
eee9fef. Engine suite along the line: 494 → 573 → 584 → 597 →
603 → 637 → 639 (+2 skipped) → 640 (+2 skipped).
