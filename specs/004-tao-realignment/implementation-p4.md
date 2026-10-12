# Spec 004 — P4 implementation record (joint Spec 003 FR-8)

Branch `impl/004-p4-fr8-joint` off P3 head aeb989e. P4 is the joint
phase: Spec 003 FR-8.1–FR-8.15 implemented as ONE methodology bump
with Spec 004 — **`methodology_version` "1.0" → "2.0"**, the single
bump the plan requires, naming both specs (engine code comment,
this record, and `specs/003-aee-red-team-remediation/implementation-fr8.md`,
which carries the per-item disposition).

## Claims before / after (real assessor, threshold 0.70)

| Measure | Before (P3 build) | After (P4 build) |
|---|---|---|
| TA-004-12..20 mean | 0.481 | 0.336 |
| TA-004-21 | 0.997 | 0.897 |
| Outcome | ITERATE | ITERATE |
| Spec 003 FR-8 claims mean | 0.481 | 0.335 |
| Engine suite | 603 passed | **637 passed** |

Decomposition of the movement, visible in each claim's own score
notes: −0.10 unknown-freshness set penalty (FR-8.6 — the bundles'
evidence is undated), plus FR-8.7 partial credit where boundary
entries name no scope or limit. TA-004-21's −0.100 is exactly the
freshness term. Nothing else moved; the semantics halves of
TA-004-12..20 are what the FR-8 items deliver, and their statuses
are re-assessed at P6 close-out on this evidence.

## Benchmark before / after (FR-8.2)

Before: `~/workspace/aee-joint/benchmark-before-2026-10-12.md`
(benchmark main e248d49, offline suite **321 passed** on the
re-pinned 1.4.0 stack, `check_pins.py` OK).

After: same suite on the benchmark repo untouched, engine
installed from this worktree (methodology 2.0) in a scratch venv:
**310 passed, 11 failed** — all 11 from one P0 root cause (the
benchmark runner strict-loads stageless bundles; R1.1 requires
`stage`), none from FR-8 semantics. Full analysis in the FR-8
record §Benchmark. The benchmark re-pin + fixture migration ride
with the release, which is the coordinator's gate.

## Draft cap vs stage cap (written resolution)

Kept distinct and layered — see the FR-8 record §"FR-2 draft cap
vs Spec 004 stage cap". The assessment reports which cap bound
through separate records (`draft_cap` failures are outcome-bearing;
`stage_cap` records are explanatory, with R1.4 doing the outcome
work).

## Honest limits

- The p5 §B literal figure (0.378) and the p4 §D first case are
  addressed in the FR-8 record's "acceptance-text interactions"
  section: the invariant holds in both; the literal figure cannot
  coexist with FR-8.7 in the same bump, and the §D case is not
  counterevidence under a defensible reading.
- The benchmark's scored campaigns remain host-bound and unrun;
  the before/after is the offline suite, as the before-picture
  stipulated.
