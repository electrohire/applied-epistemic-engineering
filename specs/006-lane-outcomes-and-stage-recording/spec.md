# Feature Specification: Independent Lane Outcomes and a Recorded Path for Stage and Status

**Feature Branch**: `spec006/lane-outcomes-stage-recording`

**Created**: 2026-10-20

**Status**: Draft — claims assessed before implementation (see `assessment-before.json`); re-assessed after implementation (see `assessment-after.json`).

## The problem, in plain words

The engine reports two lanes. Lane 1 is machine checking: did the
evidence hold up, and did every claim score at or above the threshold?
Lane 2 is human progress: has a person explained the claim, accepted
it, and moved it through its lifecycle stages?

Today the lane-1 result is not computed at all. The code copies the
overall (headline) outcome into the lane-1 slot. The headline outcome,
in turn, can never be `pass` while any claim is still a draft or is
below the `explained` stage — those are lane-2 facts about human
progress. So a bundle whose machine checking is completely clean still
shows `iterate` in both places. A reader cannot tell "the machine
checks failed" from "the machine checks passed and people have not
finished their part yet". That makes the headline outcome read as
`iterate` in nearly every real run, and the lane pair that Spec 004
required (its R1.4 allows a pass "in its lane-qualified form", and its
R6.2 requires surfaces to show the pair) was never actually built.

There is a second, linked problem. Even a team that wants to finish
the human part has no recorded way to do it with the shipped tools:

- A claim's lifecycle stage moves only through a recorded stage event.
  The model has a method for that, but nothing in the shipped code
  calls it, and there is no command for it.
- A claim's declared status (for example `draft`) is set when the
  bundle is loaded and nothing can change it afterwards. The draft cap
  therefore never lifts through any supported path.
- One of the events that is supposed to lift a claim out of `created`
  is "an assessment run recorded as a stage event", and no command
  records one.

So `pass` is unreachable in practice for a bundle that starts life as
drafts, no matter how good its evidence is.

## What this spec changes

### A1 — Lane 1 gets its own outcome

Lane 1's outcome is computed from lane-1 facts only: the failure
records and the scores. It runs the same decision steps the headline
runs, in the same order, over those facts:

1. No claims: `block`.
2. Any critical failure: `block`.
3. Any high-severity contradiction: `clarify`.
4. Any high-severity missing-evidence failure: `gather_evidence`.
5. Any remaining outcome-bearing failure, or any claim score below
   the threshold: `iterate`.
6. Otherwise: `pass`.

Two headline steps do **not** run for lane 1, because they are not
machine-checking facts:

- The draft cap (a claim whose declared status is `draft` holds the
  headline at `iterate`). Draft status is an authoring state — lane-2
  state. The draft-cap failure records are likewise excluded from
  lane 1's failure set.
- The stage rule (a claim below `explained` holds the headline at
  `iterate`). Stage is the human-progress record — lane 2 by
  definition.

Policy verdicts, when a policy is attached, demote lane 1 only for
lane-1 reasons. A verdict of `abstain` (no usable support, or support
that is only a model talking about itself) is a lane-1 fact and
demotes a lane-1 `pass` to `abstain`. A verdict of `challenge` demotes
lane 1 to `iterate` only when at least one of its reasons is a lane-1
reason (contested evidence, an unresolved high or critical failure,
too few independent sources, or a score below the threshold). A
challenge whose only reasons are the draft cap or a stage ceiling
does not demote lane 1: both are lane-2 state. A verdict of
`unjudged` never demotes lane 1: it exists only because a claim is at
stage `created`, which is lane-2 state. This is the same demote-only
shape the headline already uses; it is not a new kind of rule.

The shared steps are factored into one helper that both outcomes use,
so the steps lane 1 and the headline share cannot drift apart.

### A2 — The pair is reported everywhere the headline is

- The assessment record keeps `outcome` as the headline, and
  `lanes.lane_1.outcome` now carries the real lane-1 outcome. Lane 2
  continues to be reported as state (stages, exposition, caps), never
  as a score.
- The assessment summary keeps its existing lane lines. The lane-1
  line now states the real lane-1 outcome, next to the lane-2 line,
  as it already sits next to the headline in the summary text.
- The evaluator adapter forwards the lane-1 outcome as its own
  metadata field (`lane_1_outcome`), next to the lane pair it already
  carries, so a composed result can show lane 1 distinctly instead of
  only the blended headline.

### A3 — The gate checks lane 1, and can require a lane-1 pass

`aee gate` already recomputes the headline outcome from an assessment
file's own contents and refuses the file (exit 2) when the stated
outcome does not match. It now also recomputes `lanes.lane_1.outcome`
from the file's contents — the same failures, scores, threshold, and
verdicts, under the lane-1 rules above — and refuses the file (exit 2)
when the recorded lane-1 outcome does not match. A forged lane-1
outcome is treated exactly like a forged headline.

A new flag states the lane-1 requirement directly:

```
aee gate --input assessment.json --require-lane1-pass
```

Exit codes under `--require-lane1-pass` (after all integrity checks
pass; any integrity refusal is exit 2, as today):

| Recomputed lane-1 outcome | Exit code | Meaning |
|---|---|---|
| `pass` (or `warn`, which the lane-1 steps never produce but the exit contract treats as passing) | 0 | Lane 1 passes |
| `iterate`, `clarify`, `gather_evidence`, `abstain` | 1 | Lane 1 ran and did not pass — the "iterate family" |
| `block` | 2 | Lane 1 is blocked |

Default gate behavior (no flag) is unchanged: the exit code follows
the headline outcome, exactly as before.

One gate consistency fix rides with this work, because the positive
control (A6) cannot pass without it. The engine's own
residual-unknowns generation treats a draft-cap record as an
explanatory cap record — it never produces a `not_understood` entry
for one — but the gate's empty-statement check counted draft-cap
records as open items. A clean draft bundle's genuine assessment
therefore carried a legitimately empty statement and was refused
(exit 2) instead of gating on its headline. The gate's open-items
test now matches the engine's definition (draft-cap records are
explanatory, like the stage-cap and verified-unexplained records it
already excluded). No genuine assessment that gated before is
refused by this change, and no forged one is accepted: the check
still refuses any file whose open items the engine would have
answered with an entry.

### A4 — Recorded commands for stage and status

Two new commands make the recorded acts that the framework has always
required, and that until now no shipped tool could perform:

```
aee stage <bundle> --claim <id> --to <stage> --basis <text> [--recorded-by <name>] [--basis-type <type>] [--test-id <id>] [--test-hash <sha256>] [--test-result <pass|fail>] [--identity-registry <path>] [--ledger <path>]
aee ratify <bundle> --claim <id> --status <status> --basis <text> --recorded-by <name> [--basis-type <type>] [--test-id <id>] [--test-hash <sha256>] [--test-result <pass|fail>] [--ledger <path>]
```

- `aee stage` loads the bundle strictly, advances the named claim's
  stage through the model's recorded-event method (forward only, with
  actor, basis, and timestamp on the event), writes the bundle back
  atomically (a temporary file plus rename, so a failed write never
  leaves a partial bundle), and appends the event to the project's
  hash-chain ledger when one is present (an explicit `--ledger` path
  is used when given; otherwise the default ledger location beside
  the bundle or under the working directory is used when the file
  exists).
- `aee ratify` is the recorded act that changes a claim's declared
  status. The act is recorded on the claim and in the ledger the same
  way. It refuses the status `supported` for a claim whose stage is
  `created`, with a clear message and exit 2 — at `created` the only
  reportable status is `draft`, and ratifying straight to `supported`
  would state a settlement no check has earned yet.

Rules for `aee stage`, by target stage:

- `checked`: any identified actor with a stated basis. (When
  `--recorded-by` is omitted, the actor is recorded as `aee`, the
  tool performing the recorded check.)
- `explained`: the claim must carry exposition evidence — an
  explanation by a named human — and every exposition item on the
  claim is validated with the existing named-human rule against the
  project identity registry (the bundle-adjacent registry, or
  `--identity-registry`). No valid exposition, no advance.
- `accepted` and `digested`: either basis type can carry the act
  (see "Basis types" below). As a human act, `--recorded-by` must
  name a person who resolves in the identity registry — an unnamed
  actor, an unknown id, or an id that resolves to a tool, a model,
  or a team is refused with exit 2. As a test verdict, the recorded
  run must have passed, and it must reference this claim's own
  falsification/acceptance tests.

Both commands refuse cleanly (message on stderr, exit 2) on any
failed rule, unknown claim, or invalid value, and never partially
write a bundle: the write happens only after every check has passed.

#### Basis types (design note, 2026-10-20)

Every recorded act carries an explicit **basis type**, recorded on
the act in three places — the claim's own act record in the bundle,
the stage/ratification event record, and the ledger entry — so the
choice of basis is visible in the record afterwards, not just at the
moment of the command:

- `human-act` (the default): the act rests on a named person's act.
  For `accepted` and `digested`, the name must resolve to a person
  in the project identity registry, as above.
- `test-verdict`: the act rests on a recorded run of a named, frozen
  acceptance test against the artifact. The act records the test's
  identity (`--test-id`), the exact frozen test (`--test-hash`, its
  SHA-256), and the run's result (`--test-result`, `pass` or
  `fail`). A verdict record missing any of the three is refused.

`accepted` and `digested` deliberately admit **either** basis type:
the machinery does not hard-code a human-only path. A test-verdict
advance to either stage additionally requires that the run passed
and that the verdict references the claim's own
falsification/acceptance tests — the test is named in one of them,
or the basis quotes one of them. A passing run of some other claim's
test, or of a test the claim never named, settles nothing here. The
runner who records a verdict need not be a registered person: the
authority of the act is the recorded run, not the runner.

`explained` is unchanged by the basis types: it keeps requiring
exposition evidence by a named human, whichever basis type the act
is recorded under — a test run cannot explain a claim.

Why both paths exist: acceptance practice is moving toward
pre-registered requirement tests passing on the delivered artifact,
with human acts reserved for ambiguity and high-stakes gates. This
spec does not settle which basis a given project must use for
acceptance; it makes both recordable, inspectable, and refused under
the same exit-2 contract, so the machinery works under either model
without change.

### A5 — Versions and the before/after comparison

- `methodology_version` moves from `2.0` to `2.1`. The lane-1 outcome
  is a new reported quantity with its own meaning; recording it under
  the old version would hide the change. Scores do not change (see
  "What does not change"), so this is a reporting-semantics bump, not
  a scoring bump.
- The package version moves from `1.5.3` to `1.6.0` (the project file
  and the version module, kept in lockstep), with a changelog entry
  in plain language.
- Before/after comparison, in the standing before/after discipline:
  the frozen cachetools bundle from the benchmark study
  (`current-study-01`, five claims, all draft at stage `created`, one
  shared source) is run through the old engine and the new engine,
  and the headline outcome, every per-claim score, and the lane-1
  outcome are tabulated in `before-after-cachetools.md`. The honest
  expectation, stated before running it: the headline stays `iterate`
  and the lane-1 outcome also stays `iterate` on this bundle, because
  four of its five scores are genuinely below the threshold. The fix
  is proven by the positive control (A6), not by dressing this bundle
  up.
- Release-gate battery (2026-10-20): the frozen-bundle comparison was
  extended beyond this one bundle before any release — the
  detector study's frozen assessment inputs (all five validation
  runs) were re-scored under both engines alongside the cachetools
  bundle, and the A6 controls were run as part of the battery. Full
  tables and the verdict are recorded in `battery-before-after.md`:
  headline outcomes and scores identical everywhere; the only
  differences are the predicted lane-1 computations and the
  methodology version string; no defects found.

### A6 — Controls

- **Positive control.** A bundle with two independent evidence
  sources, every score at or above the threshold, and claims at
  `draft` / `created` reports lane 1 as `pass` and the headline as
  `iterate`; the default gate exits 1 and
  `aee gate --require-lane1-pass` exits 0. Then, using only the new
  commands (plus adding the exposition evidence a human explainer
  contributes, which is evidence authoring, not a stage or status
  edit): record `checked`, ratify the status upward, record
  `explained`, and record `accepted` by a registered human. A fresh
  assessment then reaches headline `pass`. This whole path is an
  automated test. A second automated end-to-end test walks the same
  path with the two claims accepted by different basis types — one
  by a recorded passing test verdict, one by a named human act —
  and also reaches headline `pass`; companion tests pin the
  test-verdict refusals (a failed run, a verdict without the frozen
  test's hash, and a verdict that references none of the claim's
  own tests each exit 2 and write nothing).
- **Negative controls.** (a) The known kill chain — a draft claim
  carrying twenty copies of one model self-report plus one human
  assertion — reaches `pass` in neither lane: duplicate evidence
  still counts once, and the score still falls short. (b) An empty
  bundle still blocks in both lanes. (c) An assessment file whose
  recorded lane-1 outcome is forged is refused by the gate with
  exit 2.

## What does not change

This section is a commitment, and the tests pin it:

- **Headline outcome logic is unchanged.** The same steps, in the
  same order, over the same facts. A regression test pins headline
  outcomes on representative bundles before and after the change.
- **Scores are unchanged.** No scoring weight, threshold, freshness
  rule, or substance rule moves. The before/after table (A5) shows
  identical per-claim scores.
- **Evidence deduplication is unchanged.** Repeated evidence still
  counts once; the kill chain (A6) still fails.
- **Settlement caps are unchanged.** The draft cap and the stage rule
  still hold the *headline* exactly where they held it before. They
  are not weakened; they are scoped to the lane they describe.
- **Stage still moves only by recorded events**, and policy verdicts
  still only demote, never promote.

## Assessment record

Assessed with the real engine before implementation
(`assessment-before.json`: engine 1.5.3, methodology 2.0, phase
`after_specify`, outcome `iterate`) and after
(`assessment-after.json`: engine 1.6.0, methodology 2.1, phase
`after_implement`, outcome `iterate`).

| Claim | Before | After |
|---|---|---|
| TA-006-01 (problem: lane 1 is a copy) | 0.80 | 0.80 |
| TA-006-02 (problem: headline cannot pass for drafts) | 0.80 | 0.80 |
| TA-006-03 (problem: no stage/status path) | 0.90 | 0.90 |
| TA-006-04 (problem: gate never reads lanes) | 0.80 | 0.80 |
| TA-006-05 (A1 lane-1 computation) | 0.3306 | 0.3306 |
| TA-006-06 (A2 reporting) | 0.3306 | 0.3306 |
| TA-006-07 (A3 gate) | 0.3306 | 0.3306 |
| TA-006-08 (A4 stage/ratify) | 0.3306 | 0.3306 |
| TA-006-09 (A6 controls) | 0.3806 | 0.3806 |
| TA-006-10 (non-regression) | 0.3806 | 0.3806 |

The scores do not move, and this record does not pretend otherwise:
the requirement claims still rest on the spec's own assertion as
their only evidence, which is exactly what the threshold exists to
say, and their status and stage were not inflated after the fact.
What changed is the machinery the claims describe — proven by the
control tests in `tests/test_spec006_lane_outcomes.py` and by the
before/after comparison in `before-after-cachetools.md`, not by
re-scoring this bundle.

## Claims

`claims.json` holds ten claims (TA-006-01 to TA-006-10): four
observations about the current code, and six requirements this work
commits to, each with a falsification test. Following this repo's
convention for spec bundles, `claims.json` carries no stage fields;
the assessed bundle is `claims-migrated.json`, produced from it by
`aee migrate` (stage `created` backfilled for every claim, each one
reported by the migration). The claims were assessed with the real
engine before implementation (`assessment-before.json`, engine
1.5.3, methodology 2.0) and are re-assessed after
(`assessment-after.json`). No status was inflated to chase a pass:
the requirement claims start as drafts at stage `created`, and
their before-scores say so.
