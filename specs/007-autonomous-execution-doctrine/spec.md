# Feature Specification: The Autonomous Execution Doctrine

**Feature Branch**: `spec007/autonomous-execution-doctrine`

**Created**: 2026-10-20

**Status**: Draft — claims assessed (after_specify; see §10). This spec is a formal write-up only: claims, requirements, and a plan. No tasks, no implementation.

**Input**: The owner's adoption, on 2026-10-20, of the autonomous-execution doctrine (recorded as claim TA-007-16). The doctrine, in the owner's words as adopted: *we cannot constantly gate on humans. The human states an expectation; a spec is written for it; every requirement carries a test case; the spec and its tests are understood and approved before work begins; then the agent works through the entire project with no intervention; when the task is done, the tests run against the delivered thing, and passing is the approval. A human is involved where a reliable test cannot be determined, and where the act is too consequential to delegate.* The doctrine was red-teamed before adoption, and its revised form (v2) is what this spec formalises: the planning gate approves a package, execution is governed by tripwires rather than by questions, and acceptance is a computed verdict, not a granted one.

## Why a new spec, and why after Spec 006

Spec 006 (lane outcomes and stage recording, in flight on its own branch) builds machinery: a lane-1 outcome computed from lane-1 facts, and recorded commands — `aee stage`, `aee ratify` — by which a claim's stage and declared status can finally move. That machinery deliberately keeps one rule from the older framework: advancing a claim to `accepted` requires a recorded act by a named human, for every claim alike. Spec 006 does not decide whether that rule is right; it makes the recorded act *possible*.

This spec decides the rule. Under the adopted doctrine, a purely testable requirement that was planned, frozen, and then proven by its own test on the delivered artifact should not wait for a human signature — the test verdict *is* the acceptance, recorded as an act with the test's identity attached. Human acts remain where the doctrine puts them: on requirements no reliable test can carry (a named human is the test), and on acts too consequential to delegate (a named human consents, regardless of tests). That is a change to what acceptance *means*, so it gets its own spec, its own claims, and its own assessment, sequenced after Spec 006 because it is written entirely in 006's vocabulary — lanes, recorded acts, basis, ledger — and extends 006's commands rather than adding parallel ones.

Nothing in this spec re-opens Spec 004's stage vocabulary (OD-T2, ratified) or its demote-only rule: stage caps still only lower a reported posture. What changes is the *basis* on which a stage may legitimately be recorded as advanced (§R4).

Every current-state statement below was grounded in a read of the code on main at `8211643` on 2026-10-20, and of Spec 006's spec on its branch the same day; citations are in the claims bundle's evidence.

## Current state against the doctrine (summary)

| Doctrine element | State | Basis (detail in claims TA-007-01…05) |
|---|---|---|
| Acceptance mode per requirement | **Absent** | No field records whether a claim is accepted by test, by oracle, or by gate; every acceptance defaults to a human act (TA-007-01). |
| Test-verdict acceptance | **Absent** | Advancing to `accepted` is gated on a named human for every claim alike, including purely testable ones (TA-007-02). |
| Tests as checkable evidence | **Absent** | Falsification tests are plain strings — no identity, no hash — and no evidence kind carries a verdict, so "the frozen test passed" cannot be checked against the test that was frozen (TA-007-03). |
| The planning package | **Unrepresented** | Restatement, tripwires, discretion envelope, and per-requirement "does not establish" lines have no fields anywhere (TA-007-04). |
| Execution events in the record | **Absent** | No tripwire event and no assumption record exists, so a halt's cause and an executor's assumptions cannot ride in the assessment (TA-007-05). |
| Recorded acts to build on | **Present (Spec 006, in flight)** | Basis-carrying, ledger-sealed stage/ratify commands; this spec extends their basis vocabulary, it does not replace them. |

## R1 — Acceptance modes

**Current state (verified).** A claim declares text, posture, evidence, and falsification tests; nothing declares *how it would be accepted*. The only acceptance-shaped act in the framework is a recorded human act (Spec 004 R1.2's acceptance event; Spec 006 A4's commands). A bundle therefore cannot say "this requirement is settled by its test" — the doctrine's central sentence is unrepresentable (TA-007-01).

**Requirements.**
- R1.1 Every claim in a plan bundle carries an `acceptance_mode` with exactly the values `test`, `human_oracle`, `gate`, loaded strictly (an unknown mode is a loud error under the Spec 002 FR-1 rules). Pre-doctrine bundles load under the lenient path with the mode absent and the absence recorded in assessment metadata — silence is never the compatibility strategy, following the stage migration precedent (Spec 004 R1.1).
- R1.2 The mode is assigned at planning time and is part of the frozen record (§R2). It can change only by amendment (§R3.5).
- R1.3 The assessment reports each claim's mode beside its stage and status, and the bundle summary counts claims by mode — so a reader can see how much of a result rests on tests, how much on named humans, and how much on gates, without opening the claims.
- R1.4 A claim with no determinable reliable test must not be left in `test` mode by default: the planning record must show it assigned to `human_oracle` (with the oracle named) or `gate`. "We could not write a test" forces the choice into the open; it never quietly demotes the requirement.

## R2 — The prove-ready package

**Current state (verified).** The framework's planning artefact is the claim bundle itself. It carries no restatement, no record of how a falsification test was derived, no proof a test can fail, no tripwires, no discretion envelope, and no residual-risk lines (TA-007-04). The doctrine's planning gate therefore has nothing to approve and nothing to check.

**Requirements.**
- R2.1 A plan bundle carries a **restatement**: the planner's plain-language statement of what will be built and what each requirement means. The restatement — not the raw bundle — is the artefact a human approves at the planning gate, and the approval is a recorded act (Spec 006's basis-typed act machinery) naming the restatement's hash.
- R2.2 Each requirement carries a **behaviour statement** in ordinary words, separate from any test code. Tests are approved at the level of behaviour statements; test code is an appendix to the package, never the approved surface itself.
- R2.3 For each `test`-mode requirement, the acceptance test is **derived twice, independently**, from the requirement alone. Both derivations are recorded. A divergence between them is the operational definition of ambiguity for that requirement: an unresolved divergence blocks the planning gate, and its resolution is recorded.
- R2.4 Each frozen test is **proven able to fail** before work begins: the planning record carries the deliberate-violation run — the requirement broken on purpose in a scratch copy — and the test going red against it. A test with no red record is not frozen; it is a draft, and the gate refuses it.
- R2.5 A frozen test is an **identified, hashed record**: test identity plus a content hash of the test as frozen. Any later change to the test is a hash mismatch in every downstream record — visible as a changed test, never absorbed as an edit (TA-007-07).
- R2.6 The package carries **tripwires**: pre-agreed conditions that halt execution and report (§R3.2). Each tripwire names its class from the shared halt taxonomy (§8) and the state the work is left in.
- R2.7 The package carries a **bounded-discretion envelope**: the classes of small decisions the executor may make alone, with examples, and the hard line — any assumption that would change a test's outcome is outside the envelope by definition (§R3.3).
- R2.8 Each requirement carries a **"does not establish" line**: what its test, passing, will not prove. The line is part of the frozen record and is carried verbatim into the acceptance report (§R6.2).
- R2.9 The package carries **held-out acceptance checks**: checks written at planning time, recorded in executor-visible records by identity and hash only, whose contents are not serialised into anything the executor can read before acceptance. At acceptance they run, and their verdicts join the record (§R6.3). How many is owner decision OD-007-2 (§9).

## R3 — Execution rules

**Current state (verified).** The framework assesses bundles; it has no record of an execution at all — no halt events, no assumption log, no amendment record (TA-007-05). The doctrine's execution discipline therefore has nothing to attach to.

**Requirements.**
- R3.1 **No guidance intervention.** Once the planning gate approves the package, execution proceeds without consulting any human. The framework's part of this rule is negative and testable: no execution record may contain a request for guidance, and no stage or status may advance on the basis of an unrecorded conversation.
- R3.2 **Tripwires halt and report.** A tripwire event is a first-class record in the assessment (§R5, §R6): the condition that fired, its class, when, and the state work stopped in. The classes are the shared halt taxonomy of §8: a premise fault, an equipment fault, or an integrity fault halts the whole execution; a model's own scored outcome ends only its own run. A halted execution never reports a pass, and a halt is a report, never a request for instructions — the plan already answered what happens next.
- R3.3 **Assumptions are logged.** Every assumption the executor makes inside its discretion envelope is recorded against the affected claim. An assumption that would change any test's outcome is not discretion: recording one is a tripwire event (§R3.2), and an assessment that finds an outcome-changing assumption recorded as ordinary discretion raises a defect.
- R3.4 **Proportionality tiers.** A plan record carries its tier — `light`, `standard`, or `full`. A light plan (small, reversible work) may carry a single requirement and a single test, approved by the no-objection window of OD-007-1. Tier relaxes package bulk only: a `gate`-mode requirement inside a light plan keeps its human gate in full.
- R3.5 **Amendments are new mini-gates.** A change to a frozen test, an acceptance mode, or a tripwire is recorded only as a superseding amendment — a small new package with its own approval act, in the append-only reclassification discipline the framework already uses for corrections. The frozen record is never edited. Execution continues on the frozen package, or halts at a tripwire, until an amendment is approved.
- R3.6 **Bounded exploration.** Work that cannot honestly be specified in advance runs as an exploration phase: time-boxed, and its deliverable is a specification — what was learned, the claims it supports, the proposed tests. A plan record marks the exploration phase as such; its output enters the normal planning gate like any other package. Exploration produces specifications, never product that skips the gate.

## R4 — Acceptance semantics: the stage re-anchoring

**Current state (verified).** Spec 004 made stage *positional*: a stage is where a claim sits in created → checked → explained → accepted → digested, advanced only by recorded events. Spec 006 gave those events commands. Neither defines the stages by *what acceptance is*: under the shipped rules, `accepted` means "a named human recorded acceptance", full stop — for a claim about whether a box is red exactly as for a claim about whether a merger is wise (TA-007-02).

**Requirements.** The stage names stay (OD-T2); their recorded basis is re-anchored to the doctrine:
- R4.1 **`checked`** means: a frozen test exists for the claim and has been shown able to fail (§R2.4, §R2.5). A stage event recording `checked` must reference the frozen test's identity and hash and its red record. An assessment cross-checks this the way Spec 006's gate cross-checks lane 1: a `checked` claim with no frozen, proven-able-to-fail test is reported as a defect, not silently re-labelled.
- R4.2 **`explained`** means: the restatement covering the claim was approved (§R2.1). The approval act is the basis; exposition evidence remains what it was under Spec 004 R3 — a named human's explanation — and a claim whose restatement was never approved cannot sit at `explained` on any other basis.
- R4.3 **`accepted`** means: the acceptance the plan assigned has happened, by mode —
  - `test`: a recorded act whose **basis type is a test verdict** — naming the frozen test's identity and hash, the run record, and the identity of the delivered artifact the test ran against (its build stamp or content signature, per the standing served-artifact identity rule: a verdict against an unnamed artifact advances nothing). The verdict must be a pass of the test *as frozen*; a hash mismatch is a tripwire, never an acceptance.
  - `human_oracle`: a recorded act by the named oracle (Spec 006's named-human rule, unchanged).
  - `gate`: a recorded consent act by the named human, regardless of any test result (unchanged in kind; the mode now *says* that is what it is).
- R4.4 A test verdict never advances a `human_oracle` or `gate` claim, and a human act never substitutes for a missing test verdict on a `test` claim. Mode confusion in either direction is refused at recording time (exit 2 in the command contract Spec 006 established) and, if found in a record, reported as a defect by the gate.
- R4.5 **`digested` is unchanged**: human-paced, recorded as before, and never required for acceptance. A result can be fully accepted with no digestion; its digestion state is reported as lane-2 state, exactly as Spec 004 R6 requires, and verified-but-undigested remains a visible risk state rather than a blocker.
- R4.6 Nothing here promotes by score. Stage still moves only by recorded acts (Spec 004 R1.2); this section changes which acts are *admissible bases* for which stages, not the recorded-act discipline itself.

## R5 — Data the engine must carry

**Requirements.** The model and the record formats gain, with strict loading and the FR-1 migration discipline throughout:
- R5.1 `acceptance_mode` per claim (§R1.1), plus the mode's named human where the mode requires one (oracle name, gate name).
- R5.2 A **frozen-test record**: test identity, content hash, the two derivation records (§R2.3), and the able-to-fail (red) run record (§R2.4), carried on or beside the claim it accepts.
- R5.3 **Test verdicts as first-class evidence**: a record kind carrying the frozen test's identity and hash, the run (when, by what runner, against which artifact identity), and the verdict. A verdict record is evidence the engine can *check* — hash against the frozen record, artifact identity against the delivery record — not an assertion it must take on trust.
- R5.4 **Basis-typed recorded acts**: Spec 006's act machinery already records actor, basis, and time and seals acts in the ledger. It gains an explicit basis *type* — `human_act`, `test_verdict`, `restatement_approval`, `amendment_approval` — with the payload each type must carry (a test-verdict act carries §R5.3's record; a human act carries the registry-resolving name). The gate recomputes admissibility from the record, as it already recomputes outcomes (Spec 006 A3's pattern).
- R5.5 **Tripwire events** in the assessment record (§R3.2) and **assumption records** on claims (§R3.3), both inside the ledger-sealed assessment hash — no doctrine mechanism may live in a side channel (Spec 004 R8.2, applied here).
- R5.6 **Plan-record fields**: tier (§R3.4), exploration marker (§R3.6), restatement reference and hash (§R2.1), discretion envelope (§R2.7), per-requirement "does not establish" lines (§R2.8), held-out check identities and hashes (§R2.9).

## R6 — Reporting

- R6.1 Assessment and acceptance surfaces report the doctrine's quantities beside the existing ones: claims by mode (§R1.3), stage read against §R4's definitions, tripwire events, and the assumption count. Lane separation (Spec 004 R6) is untouched: a test verdict is a lane-1 fact about a test-mode claim and is never displayed as lane-2 progress.
- R6.2 **The acceptance report is a pair.** What the tests established, and what they did not — every requirement's "does not establish" line, verbatim from the frozen plan. A report missing the second half is flagged the way a missing residual-unknowns statement already is (Spec 004 R5.3's precedent): absence is itself a finding.
- R6.3 Held-out check verdicts (§R2.9) appear in the acceptance report by identity, with their pass/fail — and a bundle whose held-out checks never ran reports that as a gap, never as silence.

## R7 — Non-goals, and what stays human

**Non-goals.**
- This spec does not build a test runner, a planner, or an executor. It defines the records those tools must produce and the checks the engine performs on them.
- It does not change scoring weights, thresholds, or Spec 006's lane computation. Acceptance semantics change what a stage *means*; §8 records the methodology consequence.
- It does not retire human acceptance. It scopes it to the requirements the plan assigned it to.
- It does not apply retroactively: frozen bundles, issued verdicts, and published benchmark results keep the meanings they were issued under.

**What stays human, by design.**
- **Oracle and gate assignments**: which requirements are `human_oracle` or `gate`, and who the named humans are, are planning decisions a human owns.
- **Amendment approval**: every amendment (§R3.5) is approved by a recorded human act.
- **The planning gate itself**: approving the prove-ready package (§R2) is the doctrine's one standing human moment.
- **Doctrine changes**: this spec and its successors change only by the owner's recorded decision — the same class of act as TA-007-16.

## 8. Interactions

- **Spec 006 (dependency).** Every mechanism here is written against 006's as-built interfaces: the lane-1 outcome and its gate recompute, the `aee stage` / `aee ratify` recorded-act commands, methodology 2.1, engine 1.6.0. Implementation of this spec starts only after 006 merges; where 006's stage command refuses a test-verdict basis today (its A4 named-human rule for `accepted`), that refusal is exactly the delta §R4.3 removes for `test`-mode claims — and only for them.
- **Methodology version.** §R4 changes what `accepted` means on existing bundles at least as deeply as Spec 004's stage-gating did, even where no score moves. Implementation therefore carries its own `methodology_version` bump with per-requirement fixtures attributing each behavioural change, and a before/after benchmark comparison against the pre-change baseline, under Spec 003 FR-8.2's rule — the joint-bump lesson of Spec 004 §8 (OD-T1) applies in reverse: this change must *not* be folded into 006's 2.1 bump, because 006's before/after evidence was captured against the human-act rule this spec replaces.
- **The benchmark stop policy (shared halt taxonomy).** §R3.2's tripwire classes are the same taxonomy the benchmark program uses for its stopped studies: premise, equipment, and integrity faults halt everything; a model's own scored outcome ends only its own run, and that classification is mechanical — the machinery must first prove the work reached the model intact before a failure may be scored as the model's own. One taxonomy, two programs: a benchmark episode's halt and an execution's tripwire are the same kind of record, so the benchmark's adoption phase (plan.md) can carry tripwire events natively instead of translating them. **Ruled (owner, 2026-10-20): the stop policy is no longer pending.** The owner adopted Option B with a nil-review checkpoint (decision paper `2026-10-20-benchmark-stop-policy-decision.md`, RULING section): a failure proven to be the model's own ends and is scored for only its own run, while equipment faults, integrity problems, and anything unexplained stop the whole study; every study plan names its nil checkpoint(s) in advance; an *earned* nil (the instrument demonstrably worked and the effect is not there) is the finding — the study closes and further spend on that question needs a new, separately approved plan; and a *manufactured* nil (nothing was ever eligible to succeed) is an instrument fault that halts like an integrity fault. The benchmark's adoption phase (plan.md P5) therefore implements this policy rather than awaiting it; the shared taxonomy itself is unchanged.
- **The extension.** The spec-kit-aee extension presents this vocabulary to spec-kit users; its surfaces (planning-package authoring, mode display, amendment flow) are sequenced after the engine in plan.md, under that repo's own spec discipline, engine first as always. No extension change is specified in detail here; the requirement recorded is that the extension must not present pre-doctrine acceptance as settled once the engine moves.
- **Self-application: releases are doctrine work.** By the owner's directive of 2026-10-20, no release of the framework ships without passing a benchmark battery on the exact candidate build, looping on fixes until the battery's pre-registered bars pass. That makes the doctrine self-applying: a release of the framework is itself planned-and-proven work under this spec — its battery is a frozen test set whose bars are fixed before results are seen (the §R2 rule, applied to releases), its failures route back as amendments and fixes rather than as lowered bars, and its promotion is a recorded act through the benchmark repo's exact-build release queue. The machinery is specified as Phase P6 of plan.md; the requirement recorded here is that a framework release claimed as doctrine-accepted must name the battery record and the exact build it passed on, the same artifact-identity discipline §R4.3 demands of any test verdict.

## 9. Owner decisions

Each decision below is **OPEN**, with a recommended default. The defaults exist so a single owner ruling unblocks implementation, not so implementation can proceed undecided.

- **OD-007-1 — Light-tier veto window.** §R3.4 lets a light plan be approved by a no-objection window instead of an explicit act. How long? **Recommended default: 24 hours** from recorded delivery of the light package, with delivery itself a recorded act; silence after the window approves the light package only — never amendments to it, and never any `gate`-mode element inside it.
- **OD-007-2 — Held-out check count.** §R2.9 requires held-out checks but the doctrine paper says only "a small set". **Recommended default: at least one held-out check per headline claim, and never zero for a bundle containing any `test`-mode headline claim**; the planner's red-team pass may require more where it names a specific way the executor could aim at the visible tests.
- **OD-007-3 — Independence of the second derivation.** §R2.3 requires two independent derivations. **Recommended default: the second derivation is produced by a different agent run or a different person than the test's author, working from the requirement text alone**; a fresh-context re-derivation by the same agent is the floor for light-tier plans only.
- **OD-007-4 — Delegation of gate acts.** May a `gate`-mode consent ever be delegated to a standing rule (for example, pre-authorised low-value releases)? **Recommended default: never.** A gate act is a named human's recorded act each time; a gate that fires routinely is a mis-moded requirement, and the fix is an amendment that re-modes it in the open — not a quiet delegation.

## 10. Claims and assessment record

Claims were authored before any plan, per this repo's flow: `claims.json` holds **16 claims** (TA-007-01…TA-007-16). The five problem claims (TA-007-01…TA-007-05) are observations about the current framework, grounded in code reads on main at `8211643` and of Spec 006's spec on its branch, both on 2026-10-20, and marked `supported`. The ten requirement claims (TA-007-06…TA-007-15) state this spec's commitments and are marked `draft`. **TA-007-16** is a `decision` claim recording the owner's 2026-10-20 adoption of the doctrine, marked `supported` on the recorded directive. Following the repo's current convention (Spec 006), `claims.json` carries no stage fields; the assessed bundle is `claims-migrated.json`, produced by `aee migrate` (stage `created` backfilled for all 16 claims, each one reported by the migration).

Assessment (engine 1.5.3 from repo source on main at `8211643`, `aee assess --phase after_specify --threshold 0.70 --no-ledger`, record in `assessment.json`):

- **Outcome: ITERATE** — the expected, correct state for an after_specify draft.
- Problem claims TA-007-01…TA-007-04 scored **0.85–0.89** (above threshold): the gaps against the doctrine are real and code-evidenced.
- Problem claim TA-007-05 scored **0.695**, just below threshold: it rests on a single evidence item, and the record says so rather than rounding it up.
- The decision claim TA-007-16 scored **0.7725** (above threshold), on the recorded owner directive.
- Requirement claims scored **0.256–0.381** (all below threshold): they rest on this spec's assertion alone, which is precisely what the threshold exists to say.
- 52 failure modes were raised, dominated by the engine's standing heuristic challenges against new prose.

No statuses were inflated to chase a PASS. This is the BEFORE record; any after-implement re-assessment belongs to the implementation phases in `plan.md`, not to this spec.

## 11. Out of scope

- Any task list or implementation (this spec is claims, requirements, and a plan only).
- Changes to scoring weights, thresholds, or lane computation (Specs 003 and 006 territory, standing).
- The benchmark's stop-policy decision itself (an owner decision, pending separately); this spec adopts its halt *taxonomy* as shared vocabulary, not its outcome.
- Engine changes on Spec 006's branch; this spec's implementation waits for 006 to merge.

## Appendix A — The adopted doctrine, mapped to this spec

The adoption trail, so a reader can check that the formalisation covers the doctrine and adds nothing silently:

| Doctrine element (v2, adopted 2026-10-20) | Where it lands in this spec |
|---|---|
| Nothing starts until the whole job is planned; spec + tests understood and approved first | §R2 (the prove-ready package), §R2.1 (restatement is the approved artefact) |
| The human approves a package, not a document — restatement, behaviour-level tests, named interpretation choices, residual risk | §R2.1, §R2.2, §R2.8; interpretation choices surface as derivation divergences, §R2.3 |
| Each test derived twice independently; disagreement is the ambiguity, resolved before execution | §R2.3, OD-007-3 |
| Every test proven able to fail (deliberate violation, test goes red) | §R2.4 |
| Tests frozen; the implementer cannot edit them; a changed test is visible | §R2.5, §R4.3 (hash mismatch is a tripwire) |
| Held-out checks, written at planning, never shown to the executor, run at acceptance | §R2.9, §R6.3, OD-007-2 |
| Tripwires: zero intervention means zero guidance, not zero stopping | §R3.1, §R3.2, §8 (shared halt taxonomy) |
| Bounded discretion; assumptions logged; an assumption that changes a test is a tripwire | §R2.7, §R3.3 |
| "This does not establish" lines, carried into the final report verbatim | §R2.8, §R6.2 |
| Proportionality tiers; small reversible work stays light; gates inside any tier stay gates | §R3.4, OD-007-1 |
| Changes never enter mid-flight; amendments are new mini-gates | §R3.5 |
| Bounded exploration whose deliverable is a specification | §R3.6 |
| Acceptance modes: test / human-as-oracle / gate, chosen at planning | §R1 |
| Stage re-anchoring: checked = frozen test exists + can fail; explained = restatement approved; accepted = frozen test passes on the delivered artifact, or the assigned oracle/gate act | §R4.1–§R4.3 |
| Digestion stays human-paced and is never required for acceptance | §R4.5 |
| Acceptance is computed, not granted; the report is the pair (proven / not proven) | §R4.3, §R6.2 |
| Data the framework must carry: mode per claim, test identity/hash + verdict records, basis-typed acts, tripwire events | §R5 |
| What stays human: oracle/gate assignment, amendment approval, the planning gate, doctrine changes | §R7 |
