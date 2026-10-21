# Plan: The Autonomous Execution Doctrine (Spec 007)

**Input**: `specs/007-autonomous-execution-doctrine/spec.md` + `claims.json` (16 claims, assessed after_specify, ITERATE — the honest BEFORE record) + the owner's doctrine adoption of 2026-10-20 (TA-007-16).

**Prerequisites**: Spec 006 merged to main (engine 1.6.0, methodology 2.1, lane-1 outcome + `aee stage` / `aee ratify` recorded-act commands). Nothing in this plan starts before that merge: every phase is written against 006's as-built interfaces, and re-basing the plan on a moving 006 would repeat the error Spec 004's plan warned against — chasing a moving baseline.

**Organization**: Data before meaning, meaning before surfaces, surfaces before adoption — the same shape as Spec 004's plan. The model gains the doctrine's records (P0); the planning gate learns to check a prove-ready package (P1); acceptance semantics re-anchor the stages (P2) — the one phase where outcome *meaning* changes, carrying the methodology discipline; reporting makes the doctrine's quantities visible (P3); the extension presents them (P4); the benchmark adopts the shared halt taxonomy (P5); releases of the framework come under the doctrine's own rule (P6); close-out re-runs the discipline on this spec itself (P7).

**Owner decisions**: OD-007-1…OD-007-4 (spec §9) are OPEN with recommended defaults. P0 may proceed on the defaults being *proposed*; no phase that *depends* on a decision's value (P1's light-tier window, P3's held-out reporting) merges before the owner rules or the default is ratified.

## Phase P0 — Engine data model (R5, R1 model parts)

- `acceptance_mode` on `Claim` (spec R1.1, R5.1) with the three-value vocabulary, strict loading, and the FR-1 migration path: pre-doctrine bundles load lenient with mode absent and the absence recorded in assessment metadata; `aee migrate` gains the mode backfill report, following the stage precedent.
- The frozen-test record (R5.2): test identity, content hash, two derivation records, the able-to-fail run record — carried with the claim it accepts.
- Test verdicts as a first-class record kind (R5.3): frozen-test identity + hash, run record, artifact identity, verdict — checkable by the engine, not asserted at it.
- Basis types on recorded acts (R5.4): Spec 006's act machinery gains the explicit basis-type field (`human_act`, `test_verdict`, `restatement_approval`, `amendment_approval`) with per-type payload rules; existing 006 acts load as `human_act` under the migration discipline, recorded as such.
- Plan-record fields (R5.6): tier, exploration marker, restatement reference + hash, discretion envelope, per-requirement "does not establish" lines, held-out check identities + hashes. Tripwire events and assumption records (R5.5) join the assessment/claim records here so later phases only *write* them.
- Claims answered: TA-007-06 (model half), TA-007-07 (record half). Acceptance: a bundle round-trips every new record through strict loading; a bundle with an unknown mode or a malformed frozen-test record fails loudly in the FR-1 error shape; migration output names every claim it touched.

## Phase P1 — The prove-ready gate (R2)

- Package validation as a command-level check over a plan bundle: every claim has a mode (R1.4's rule enforced — a test-mode claim with no determinable test is refused, not defaulted); every `test`-mode claim has a frozen-test record with two derivations and a red record (R2.3, R2.4); tripwires and the discretion envelope are present (R2.6, R2.7); every requirement carries its "does not establish" line (R2.8).
- Divergence handling: an unresolved derivation divergence is a planning-gate refusal with the divergent requirement named — the framework's mechanical form of "this is ambiguous; a human decides before work starts".
- Restatement approval: the approval act (basis type `restatement_approval`) recorded against the restatement's hash (R2.1); tier handling incl. the light tier's no-objection window once OD-007-1 is ruled.
- Claims answered: TA-007-08, TA-007-15 (package half). Acceptance: the fixture package missing any single element is refused with that element named; the complete fixture package passes; a light-tier package with a `gate`-mode claim still demands that claim's human gate.

## Phase P2 — Acceptance semantics (R4) — the methodology phase

- Stage-basis rules enforced at recording time, extending Spec 006's `aee stage`: `checked` requires the frozen-test reference (identity, hash, red record); `explained` requires the restatement-approval act; `accepted` requires the mode's act — a `test_verdict` basis (hash-checked against the frozen record, artifact identity required) for `test` mode, the named-human act for `human_oracle` and `gate` modes (R4.1–R4.4). Mode-confused acts are refused (exit 2, 006's contract).
- Gate admissibility recompute: `aee gate` recomputes stage admissibility from the record the way it already recomputes outcomes and lane 1 (006 A3's pattern) — a forged verdict, a mismatched test hash, or an oracle claim advanced on a test verdict is refused (exit 2) from the file's own contents.
- Assessment cross-checks: a claim sitting at a stage its recorded basis does not support is reported as a defect (R4.1), never silently re-labelled.
- **Methodology discipline (Spec 003 FR-8.2)**: this phase changes what `accepted` *means*, so it carries its own `methodology_version` bump — explicitly **not** folded into Spec 006's 2.1 (spec §8) — with per-requirement fixtures attributing each behavioural change to its requirement, and a **before/after benchmark comparison** against a baseline captured on the pre-P2 engine before any P2 code merges. If the benchmark cannot run the comparison at that moment, capture the baseline and record why; do not compare against a benchmark re-pinned after the change as if it were the before state (Spec 004 plan P4's rule, applied again).
- Claims answered: TA-007-10, TA-007-11. Acceptance: the positive control — a `test`-mode claim planned, frozen, and accepted end-to-end on a test verdict against a named artifact — passes the gate; the negative controls — forged verdict, hash-mismatched test, test verdict offered for an oracle claim, human act offered for a test claim — are each refused; headline outcome logic and scores on pre-doctrine bundles are unchanged outside the attributed fixtures.

## Phase P3 — Reporting (R6, R3 record halves)

- Assessments report claims by mode, stage read against §R4's definitions, tripwire events, and assumption counts (R6.1); tripwire events (R3.2) and assumption records (R3.3) are written by the recording paths and serialised inside the ledger-sealed assessment hash (R5.5).
- The acceptance report is a pair (R6.2): established / not-established, with each requirement's "does not establish" line verbatim; a report missing the second half is flagged under the Spec 004 R5.3 precedent.
- Held-out checks at acceptance (R6.3, R2.9): verdicts reported by identity; checks that never ran are reported as a gap. Executor-visible serialisation is audited so held-out *contents* appear in no bundle, plan, or log the executor reads (TA-007-09's falsifier, run as a test).
- Claims answered: TA-007-09, TA-007-12, TA-007-13, TA-007-14. Acceptance: an acceptance report for the P2 positive-control bundle shows both halves of the pair and the held-out verdicts; stripping a "does not establish" line makes the framework's own completeness check flag the report.

## Phase P4 — Extension surfaces (spec-kit-aee)

- Under that repo's own spec/claims discipline, engine first: planning-package authoring support (modes, behaviour statements, frozen-test records), mode + stage-basis display in the assess/gate surfaces, the amendment flow (R3.5), and the runner's engine floor moved to the P2 engine release.
- The extension must not present pre-doctrine acceptance as settled (spec §8): where the engine reports a stage-basis defect or a lane-qualified outcome, the extension shows it, in the pair form Spec 004 R6.2 requires.
- Claims answered: the extension half of TA-007-06 and TA-007-14 (display). Acceptance: an assessment produced through the extension on the P2 control bundle shows the same modes, bases, and pair report as the bare CLI on the same bundle.

## Phase P5 — Benchmark protocol adoption

- The benchmark's records carry tripwire events natively under the shared halt taxonomy (spec §8): premise / equipment / integrity faults halt the whole study; a model's own scored outcome ends only its run, classified mechanically (the machinery proves the work reached the model intact before a failure may be scored as the model's own). This phase adopts the *taxonomy and record shape*; the stop-policy decision was the owner's, pending separately until ruled (see the next bullet), and this phase no longer pre-empts anything — records are written so either ruling can be applied to future studies without re-instrumenting.
- **Stop policy — ruled by the owner (2026-10-20).** The pending decision named above is decided: the owner adopted Option B with a nil-review checkpoint (decision paper `2026-10-20-benchmark-stop-policy-decision.md`, RULING section). A failure proven to be the model's own ends only that run and is scored as its result; equipment faults, integrity problems, and anything unexplained still stop the whole study. Every study plan names its nil checkpoint(s) in advance: at a checkpoint, an *earned* nil (the instrument demonstrably worked — controls pass, results were eligible to succeed — and the effect is not there) is the finding; the study closes and further spend on that question needs a new, separately approved plan, never a tuning of the frozen study until it turns non-nil. A *manufactured* nil (nothing was ever eligible to succeed) is an instrument fault: it halts like an integrity fault, and the instrument is fixed and reviewed before anything resumes. The ruling applies prospectively, to fresh studies under new plans; P5's adoption work now implements this policy instead of awaiting it.
- The known protocol gap rides this phase as a protocol revision, prospective only: live-run claim prompts must ask models for the fields the current engine requires (stage at minimum, acceptance mode once P0 lands), so live bundles stop depending on lenient loading. Frozen episodes, frozen inputs, and published reports are not modified.
- Claims answered: TA-007-12 (benchmark half), TA-007-15 (record half). Acceptance: a stopped study's public report is generated from tripwire records with the taxonomy classes intact, and the offline suite stays green against the revised protocol.

## Phase P6 — Release gating: no release ships unproven

**The rule (owner directive, 2026-10-20).** No release of the framework — engine, extension, or evaluator — ships without passing a benchmark battery on the exact candidate build. The battery and its bars are fixed *before* any results are seen: the doctrine's frozen-test rule applied to releases themselves. A failure does not lower the bar and does not ship anyway; it routes back as fixes, and the battery re-runs on the new candidate. Releases of the framework are planned-and-proven work under the doctrine (spec §8), and this phase is where that stops being a sentence and becomes machinery.

- **The battery** (all offline — no new inference, no model calls):
  - the frozen benchmark bundles re-scored on the exact candidate build, compared against the accepted baseline;
  - the offline test suites of the engine, the extension, and the evaluator, run against the candidate build;
  - composition checks: the extension installed with the candidate engine and the evaluator from their exact archives into a fresh project, the pair exercised end to end (the standing two-sided install proof, mechanised);
  - positive and negative controls: the current control set (Spec 006 A6's lane controls; this spec's P2 stage-basis controls once they exist) run against the candidate.
- **The bars, pre-registered**: the battery's pass bars — which bundles, which score/outcome tolerances against baseline, which suites at zero failures, which controls must pass — are written into a versioned battery record and frozen before the battery first runs on a candidate. Changing a bar is an amendment (§R3.5's discipline): a new recorded act with a reason, never an edit after results are seen.
- **The loop**: a failed bar produces fix work, a new candidate build, and a full battery re-run. Partial re-runs do not promote a candidate; the record keeps every failed run, not just the passing one.
- **Promotion**: a candidate that passes is promoted through the benchmark repo's exact-build release queue (`benchmark-release-queue.json`) — the queue entry names the exact build, the battery record it passed, and the accepted baseline it was compared against. The queue's accepted-baseline index, empty today, gains its first accepted baseline under this rule, recorded as a gate act by the owner or the owner's delegate.
- This phase authors its own claims at phase start (claims-first, like every phase here); its acceptance evidence also feeds P7's close-out re-assessment of TA-007-10 and TA-007-11, since a release accepted under the battery is the doctrine's acceptance semantics operating on the framework itself.
- Acceptance: a candidate with a deliberately broken control is refused promotion by the queue record; the first real release under the rule (expected: the release that ships P2) shows a complete battery record — bars frozen before the run, every run kept, promotion naming the exact build.

## Phase P7 — Close-out: re-assessment and a fresh retro-audit sample

- Re-assess this spec's claims (after_implement) on implementation evidence, including the P6 battery record. Statuses change only on evidence, per the standing rule; the BEFORE record in `assessment.json` is not edited.
- Fresh retro-audit sample, in the Spec 004 P6 pattern: a sample of post-doctrine bundles checked for mode assignment honesty (test-mode claims that plainly needed an oracle), frozen-test discipline, tripwire records, and pair-report completeness — filed as a dated audit addendum in this spec's directory, append-only.
- Verify the historical record is untouched: frozen assessments and prior specs' files remain byte-identical (sha256 spot-check).
- Claims answered: all, by evidence. Acceptance: the close-out bundle itself satisfies the doctrine it ships — planned in full, approved once, accepted on its frozen tests or their named human acts — or the gaps are recorded as findings, not waived.

## Sequencing notes

- Everything waits for Spec 006 to merge (see Prerequisites). P0 → P1 → P2 are engine-only and sequential (shared model/recording surfaces). P3 depends on P2's records. P4 depends on P2/P3 (it presents their vocabulary) and runs in the extension repo under its own flow. P5 is benchmark-repo work and can run parallel to P4 once P0's record shapes are frozen. P6 depends on P5's queue mechanics and P2's controls; its first full application is the release that ships P2. P7 depends on everything.
- The methodology bump lives in exactly one place: P2. No other phase changes what a score, an outcome, or a stage means.
- OD-007-1…OD-007-4 gate the phases named in §0; the recommended defaults are recorded in spec §9 so one owner ruling unblocks them.
