# Audit Addendum — 2026-10-12 (P6 close-out, append-only)

Filed beside `audit-2026-10-12.md` per Spec 004 plan P6. This
addendum does not modify the original audit or any frozen
artifact; it re-runs the 2026-10-12 audit method over a sample of
POST-realignment bundles and records what it finds, including
where the sample fails the discipline the framework now ships.

## Sample

The four after-implement bundles the joint phase itself produced
(all assessed on the final joint build, engine 1.5.0 /
methodology 2.0):

| Bundle | Claims | Falsifier coverage | Explicit `stage` in file | Attribution-marked claims | not_understood entries |
|---|---|---|---|---|---|
| engine specs/004 claims-after-implement | 21 | 21/21 | 0 | 0 | 55 |
| engine specs/003 claims-after-implement | 35 | 35/35 | 0 | 0 | 99 |
| extension P5 claims-after-implement | 4 | 4/4 | 0 | 0 | 13 |
| evaluator P5 claims-after-implement | 4 | 4/4 | 0 | 0 | 13 |

## Findings

1. **The machinery is present everywhere; the lane-2 record is
   not.** Every sampled assessment carries a populated
   `not_understood` (the R5.2 machinery working as designed) and
   complete falsifier coverage — a genuine improvement over the
   2026-10-12 baseline audit, where no corpus entry stated what
   remained not understood. But no sampled bundle carries an
   explicit `stage` field on any claim: all 64 sampled claims
   load with the stage defaulted to `created` (recorded in each
   assessment's `stage_defaulted_claims`), so the Spec 004
   bundle's lane 2 reads `created: 21, checked: 0, explained: 0,
   accepted: 0, digested: 0` — even though the implementation the
   claims describe is built, tested, and recorded. This is
   truthful, not broken: stage advancement requires recorded
   stage events and, past `checked`, human evidence (exposition
   by a named human in the identity registry). None has been
   recorded yet. **The framework's first digestion-era records
   are, as the plan predicted, lane-1 complete and lane-2 at the
   starting line — and the records now SAY so, which is the
   point of the realignment.**
2. **Attribution is still not claimed.** 0 of 64 sampled claims
   carry an attribution role or exposition evidence. The R4/R7
   machinery (attribution sub-claims, contests, priority records)
   exists and is tested; the program's own bundles do not yet use
   it. Recorded as a finding for the next cycle, not waived.
3. **Scores moved on evidence, statuses stayed capped.** The
   re-assessed semantics claims (Spec 004 TA-004-12..19) score
   0.85 each on implementation-record evidence (from a 0.336
   mean under the same methodology with pre-implementation
   evidence), and Spec 003's FR-8 claims score 0.85–0.875 — yet
   every one of them reports through the stage machinery at its
   recorded stage. Lane 1 improved; lane 2 did not move; the
   display keeps those facts separate.

## Frozen-artifact verification (plan P6)

sha256 spot-check against §8 of `audit-2026-10-12.md`:

- Specs 001–003 claims.json + assessment.json (6 files):
  **byte-identical** to the §8 values.
- Spec 004 claims.json / assessment.json: the §8 values predate
  commit `0082ba1` (OD-T1 decided + plan drafted), which updated
  the then-still-draft Spec 004 bundle after the audit's hashes
  were recorded. The files are byte-identical between the audit
  clone's branch tip (`af0871a`) and the joint line's tip, and no
  commit after `0082ba1` — in particular no implementation-phase
  commit (P0–P6) and not the ratification commit `af0871a` (which
  touched only spec.md/plan.md) — has modified them.
- The audit's own files (`audit-2026-10-12.md`,
  `stage-reclassifications-2026-10-12.json`): untouched since
  their creating commit `7600277` on every line checked.
