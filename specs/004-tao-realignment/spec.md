# Feature Specification: Tao Realignment of the AEE Framework

**Feature Branch**: `spec/004-tao-realignment`

**Created**: 2026-10-12

**Status**: Draft — claims assessed (after_specify; see §10). No plan, no tasks, no implementation in this spec.

**Input**: The owner's realignment directive of 2026-10-12, applying Terence Tao's points — from his September 11, 2026 Caltech Science × AI keynote, the 25-Fields-Medalist declaration "A Severe Misalignment of AI in Mathematics," and his New Scientist interview — to the AEE framework itself. The eight points: (1) a result passes through five stages — created, checked, explained, accepted, digested — and creation plus checking alone never settles it; (2) a headline result decomposes into sub-claims (faithful statement, verified evidence, genuinely open or novel, attribution clean, significance), each scored on its own evidence with its own falsifier; (3) digestion is first-class work — explanation by named humans is tracked, and verified-but-unexplained is a risk state, not a finish line; (4) attribution is itself a claim — contested attribution keeps the parent contested; (5) easily graded metrics must never stand in for understanding, and every verdict states what remains not understood; (6) machine-speed verification and human-paced acceptance are two lanes, tracked separately, and lane-1 completion must never display as lane-2 completion; (7) provenance and registration protect priority, so openness is rewarded rather than raced against; (8) every verdict ships an inspectable evidence trail.

## Why a new spec, not an amendment

Spec 002 (AEE Trust Hardening) is **implemented and merged** (PRs #22–#26; engine work for FR-1 through FR-8a landed on main). Amending it would rewrite a closed record — its claims, assessment, and tasks describe work that has already been done and verified. This realignment is a framework evolution, not a correction to Spec 002: it changes what a claim *is* (a thing with a lifecycle stage) and what a verdict *means* (a statement capped by stage, split by lane, and carrying its own residual unknowns). It therefore gets its own spec, its own claims, and its own assessment, in the same claims-first discipline.

The realignment also interacts with Spec 003 (AEE Red-Team Remediation), which is merged as a spec but **not yet implemented**. Spec 003 FR-8 changes scoring and challenge *semantics* under an explicit methodology-version rule (its FR-8.2). The stage-gating in R1 below changes semantics at least as deeply. Whether the realignment is implemented before, after, or interleaved with Spec 003 is a genuine sequencing question with methodology-version consequences, and it is recorded as owner decision OD-T1 (§9) rather than decided here.

Every current-state statement below was grounded in a read of the code on main at `5327915` on 2026-10-12; file and symbol citations are in the claims bundle's evidence.

## Current state against the standard (summary)

| Tao point | State | Basis (detail in claims TA-004-01…11) |
|---|---|---|
| 1. Five stages | **Absent** | `Claim` (src/aee/model.py) has no stage field; `ClaimStatus` is an evidence-posture vocabulary only, and scoring, policy, and the outcome logic never read status (TA-004-01, TA-004-02). |
| 2. Decomposition | **Partial** | `depends_on` plus weakest-link propagation (src/aee/scoring.py) caps a claim by its declared dependencies, but no decomposition template exists and undeclared structure is invisible (TA-004-03). |
| 3. Digestion tracked | **Absent** | `EvidenceKind` has five values and no exposition kind; nothing tracks per-claim explanation by a named human, and no output flags verified-but-unexplained (TA-004-04). |
| 4. Attribution is a claim | **Absent** | No attribution record, contributor record, or dispute state exists anywhere in `src/aee/`; `conflicts_with` is claim-vs-claim only (TA-004-05). |
| 5. Anti-gradability | **Partial** | Policy verdicts layer above scores and can only demote (src/aee/policy.py), but no verdict or assessment carries a residual-unknowns statement; `Assessment.to_dict` has no such field (TA-004-06). |
| 6. Two lanes | **Absent** | An assessment reports one blended outcome and one blended score per claim; no lane-1 or lane-2 quantity is computed or reported (TA-004-07). |
| 7. Openness / priority | **Partial** | The hash-chain ledger (src/aee/ledger.py) timestamps and seals assessment records and Spec 002 FR-8a made ledgering the default, but the timestamp is priority evidence for *assessments*, not for claims, and nothing in the framework recognises a public-first disclosure as priority evidence (TA-004-08, TA-004-09). |
| 8. Inspectable records | **Satisfied in substance, one delta** | Assessments embed claims, scores, verdicts, and failure modes with evidence refs and `content_hash`, and ledger entries record each assessment's SHA-256 (TA-004-10). The delta is R5's residual-unknowns statement, which is part of the trail Tao's point requires a verdict to ship. |

## R1 — Lifecycle stage on the claim model (Tao point 1)

**Current state (verified).** A claim's only lifecycle-adjacent field is `status: ClaimStatus` (`draft, supported, partially_supported, unsupported, contradicted, unverifiable, superseded`) — an evidence-posture label the author sets. There is no stage field (not in the `Claim` dataclass, not in `Claim._FIELDS`, so strict loading would reject one). Scoring (`src/aee/scoring.py`), policy (`src/aee/policy.py`), and the outcome logic (`src/aee/engine.py` `_outcome`) never read `status` at all: a claim's computed score, verdict, and the bundle outcome are identical whatever posture the author declares. Nothing stops a freshly created claim with machine-checkable evidence from reaching `pass` in a single run (TA-004-01, TA-004-02).

**Requirements.**
- R1.1 The claim model gains a `stage` field with exactly the values `created, checked, explained, accepted, digested`, loaded strictly (unknown stage values are loud errors under the Spec 002 FR-1 rules) and serialised in `to_dict`. Existing bundles without a stage load with stage `created` under the lenient path only; strict loading names the missing field, following the FR-1 migration precedent (`aee migrate` gains a stage backfill that writes `created` and reports every claim it touched).
- R1.2 Stage is advanced only by recorded events, never by score: checking (an assessment run), explanation (exposition evidence under R3), acceptance (a recorded human acceptance — the disposition mechanism of Spec 002 FR-5 is the precedent for a stored, reasoned, authored record), and digestion (R3's digestion record). The event that advanced a claim's stage is inspectable in the claim's record.
- R1.3 **Stage-gated vocabulary.** The assessment reports a claim's status and verdict capped by its stage, per this proposed mapping:

  | Stage | Status values the assessment may report | Policy verdict ceiling |
  |---|---|---|
  | `created` | `draft` only | no verdict issued (reported as unjudged) |
  | `checked` | `draft`, `partially_supported`, `unsupported`, `contradicted`, `unverifiable` | `challenge` |
  | `explained` | the above, plus `supported` | `challenge` |
  | `accepted` | the above, plus `supported` unqualified | `accept` |
  | `digested` | the above, plus `superseded` as a terminal state | `accept` |

  A claim whose computed posture exceeds its stage cap is reported at the cap, with a score note and a failure mode (category `stage_cap`, R3.3's sibling) naming the cap and the stage event that would lift it. The cap never raises a posture; it only lowers the reported one — mirroring the policy layer's demote-only rule.
- R1.4 The bundle outcome inherits the caps: an assessment whose claims are all at stage `created` or `checked` cannot report an outcome worded as settlement. Concretely, `pass` is reported only when every claim it covers is at stage `explained` or beyond, or the outcome is emitted in its lane-qualified form under R6 (e.g. lane-1 pass, lane-2 open).
- R1.5 Whether `supported` is *renamed*, *capped* as above, or stage is kept *orthogonal* to status is owner decision OD-T3 (§9). This spec proposes the cap (R1.3) because an orthogonal stage that nothing enforces would repeat the present defect — a field that is written and never read, as `Evidence.independent_of` once was (Spec 002 FR-6).

## R2 — Decomposition template for headline claims (Tao point 2)

**Current state (verified).** The only structure a claim can declare is `depends_on`, and scoring's propagation caps a claim's propagated score at its weakest *declared* dependency (src/aee/scoring.py, `ScoringEngine.score`). There is no notion of a headline claim, no required sub-claim structure, and no check that a decomposed claim's parts cover what the headline asserts. A claim that declares no dependencies is capped by nothing (TA-004-03; the omission limit is also recorded in Spec 003 FR-8.14 for the general dependency case).

**Requirements.**
- R2.1 A claim may be marked as a headline claim (`metadata` role or a dedicated field — the representation is an implementation choice; the requirement is the behaviour). A headline claim requires five sub-claims, linked by `depends_on`, one in each role: **statement-fidelity** (the claim as written faithfully states the result), **evidence-verification** (the cited evidence verifies what it is cited for), **novelty** (the result was genuinely open, or is new, as claimed), **attribution** (per R4), and **significance** (the result matters for the stated reason).
- R2.2 Each sub-claim is an ordinary claim: its own text, boundary, evidence, falsification test, score, and stage. No sub-claim inherits its parent's evidence or posture.
- R2.3 **Weakest-link rule for required sub-claims.** The parent's propagated score is capped by the weakest required sub-claim — this reuses the existing `depends_on` propagation precedent exactly, with one strengthening: for a headline claim, the five links are *required*, so a missing role is not an invisible omission but a failure mode (category `decomposition_incomplete`, severity HIGH) and the parent's stage is capped at `created` until all five roles exist.
- R2.4 The decomposition check is structural, not semantic: the engine verifies that the five roles exist, are linked, and are independently scored and staged. Whether a sub-claim's text actually discharges its role remains a human judgment, recorded through the acceptance events of R1.2. The spec claims the structural guarantee only.

## R3 — Exposition evidence and digestion tracking (Tao point 3)

**Current state (verified).** `EvidenceKind` (src/aee/model.py) is `observed, inferred, asserted, contradicted, unsupported`. There is no exposition kind; `grep` for `exposition`, `digested`, and `lifecycle` across `src/aee/` returns zero hits. `Evidence.source_id` is a free string with no identity semantics: nothing distinguishes a named human explainer from a tool, a model, or an arbitrary label. No assessment output reports which claims have been explained, by whom, or which verified claims remain unexplained (TA-004-04).

**Requirements.**
- R3.1 A new evidence kind `exposition` is added to `EvidenceKind`. An exposition item is evidence that a named human has explained the claim — what it asserts, why the evidence supports it, and where its boundary lies.
- R3.2 Exposition evidence **requires a named human**: its `source_id` must resolve to a person identity under the identity standard of OD-T4 (§9) — a person, not a tool, model, team alias, or empty string. Strict loading rejects an exposition item whose `source_id` cannot resolve, with the FR-1 error shape (claim id, field, problem, valid alternatives where enumerable). A model-generated explanation attached as exposition evidence is a load error, not a judgment call.
- R3.3 Digestion is tracked per claim: the assessment reports, per claim, whether exposition evidence exists, who the explainers are, and the claim's stage consequence (R1.2). A claim at stage `checked` or beyond with **no** exposition evidence is flagged as a named risk state — failure-mode category `verified_unexplained`, severity MEDIUM, with a recovery hint naming the missing exposition. The flag is a risk state, not a failure of correctness: it does not lower the claim's score; it is reported wherever failure modes are reported and counted in the summary line.
- R3.4 Digestion (stage `digested`) requires more than one exposition: at least one exposition by a human other than the claim's author, recorded after the explanation entered whatever shared record the deployment uses (a merged document, a published note, a recorded review). The exact evidence of incorporation is deployment-defined; the framework requirement is that the digester is named, is not the author, and is inspectable.

## R4 — Attribution as claims (Tao point 4)

**Current state (verified).** The framework has no attribution surface: no prior-work record, no contributor record, no dispute state (`grep` for `attribution` across `src/aee/` returns zero hits). `Claim.conflicts_with` expresses claim-vs-claim contradiction only; a dispute about *whose* work a result is has no representation, and nothing about attribution can affect a claim's score, stage, or outcome (TA-004-05).

**Requirements.**
- R4.1 Attribution is registered as claims. For any claim (and mandatorily for a headline claim, as its R2 attribution sub-claim), the attribution record consists of claims with evidence covering: the prior work the claim builds on, the human contributors and their contributions, and any known dispute over either.
- R4.2 An attribution sub-claim carries the same machinery as any claim — evidence with inspectable refs, a falsification test (what record would show the attribution wrong), a stage, and a status. A dispute is registered by marking the attribution claim `contested` through recorded contradicting evidence, not by a flag with no evidence behind it.
- R4.3 **Stage cap rule (precise).** A claim whose attribution sub-claim is in a contested state — status `contradicted`, or carrying an unresolved HIGH or CRITICAL failure mode in the `contradiction` category arising from attribution evidence — cannot advance beyond stage `checked`, regardless of its other evidence or score. The cap is reported in the score notes with the attribution claim's id, mirroring R1.3's reporting shape. The cap lifts only when the attribution claim leaves the contested state through new evidence or a recorded disposition with a reason (Spec 002 FR-5 precedent).
- R4.4 Attribution claims are scored on their own evidence (R2.2 applies). A parent claim may not borrow its attribution claim's evidence to raise its own score, and the attribution claim's weakness caps the parent through R2.3's weakest-link rule in addition to R4.3's stage cap — the two mechanisms are distinct and both apply.

## R5 — Anti-gradability: stage caps and the residual-unknowns statement (Tao point 5)

**Current state (verified).** The policy layer (src/aee/policy.py) is the framework's existing anti-gradability mechanism in embryo: verdicts layer above scores, state reasons, and can only demote the outcome, never promote it. But no gate examines *what kind* of evidence produced a score, and no verdict, score record, or assessment carries any statement of what remains not understood — `Assessment.to_dict` (src/aee/engine.py) serialises claims, scores, verdicts, recoveries, and metadata, and nothing else. A reader of an assessment cannot tell what the assessment does not know (TA-004-06).

**Requirements.**
- R5.1 **Machine-only cap (policy-gate form).** A claim whose supporting evidence is exclusively machine-checkable — proposed definition: every supporting item has kind `observed` or `inferred` *and* source quality `test`, `artifact`, or `model` — is capped at stage `checked` regardless of score, under a policy gate in the `aee.policy` sense: the gate produces a reasoned, inspectable cap record (mirroring `ClaimVerdict`), it can only demote, and its reason names the evidence composition that triggered it. Human-paced support — evidence of source quality `human`, `primary`, or `secondary` from a named human source — is what lifts the cap, via R3 exposition and R1.2 acceptance events. The exact evidence-kind/quality partition is part of what implementation must state in the scoring documentation; changing it is a methodology change under §8.
- R5.2 **Mandatory `not_understood` statement.** Every assessment carries a `not_understood` field: a residual-unknowns statement naming, per claim or per bundle, what the assessment does not establish — unexamined boundaries, evidence not inspected, sub-claims at draft, the gap between the score and understanding. The field is generated from inspectable assessment state (open failure modes, stage caps, draft sub-claims, unparseable or unexamined evidence) plus any author-supplied text; it is never a free-floating disclaimer disconnected from the record.
- R5.3 Absence of the statement is itself a finding: an assessment serialised without a `not_understood` field (or with an empty one where open items exist) is flagged in the assessment output and by `aee verify`-style checks, in the same spirit as Spec 002 FR-1's rule that silence is never the compatibility strategy. Consumers rendering a verdict must render the statement with it (R6.3).

## R6 — Two lanes, reported separately (Tao point 6)

**Current state (verified).** Scoring (src/aee/scoring.py) computes one direct and one propagated score per claim, blending evidence quality, independence, falsifiability, and boundary presence into a single number; the engine reports one outcome string per bundle. No field anywhere separates what machines verified from what humans explained or accepted — because the model has no stage (R1) and no exposition evidence (R3), the human lane is not merely blended, it is unrepresented (TA-004-07).

**Requirements.**
- R6.1 Assessment output reports two lane quantities per claim and per bundle: **lane 1** (machine verification — score, checks run, evidence verified, in the existing scoring sense) and **lane 2** (human-paced progress — stage, exposition coverage under R3, acceptance state under R1.2, attribution state under R4). Lane 2 is reported as state, not collapsed into a second pseudo-score, unless a future methodology decision defines one explicitly.
- R6.2 No single headline number may blend the lanes. The existing score is re-labelled as a lane-1 quantity wherever it is presented (assessment JSON, CLI summary, extension commands), and any surface that today shows one outcome shows the pair — lane-1 outcome and lane-2 state — instead.
- R6.3 **Lane-2 lag is reported, not hidden.** Where lane 1 is complete and lane 2 is not — a claim passing every machine check with no exposition, no acceptance, a contested attribution — the assessment summary states the lag explicitly (counts of claims by stage, count flagged `verified_unexplained`, count stage-capped and why). A green lane-1 result displayed without its lane-2 state is a reporting defect under this spec, in the CLI and in the extension's command output alike (see §8, extension interaction).

## R7 — Openness and priority (Tao point 7)

**Current state (verified).** The hash-chain ledger (src/aee/ledger.py) already provides a tamper-evident, timestamped registration record, and Spec 002 FR-8a made ledgering the default for assessments: each entry carries a UTC timestamp, a sequence number, and the SHA-256 of the assessment it records, chained to every prior entry. That is a priority record *for assessments*. What does not exist: any treatment of a **claim's** registration — a claim is timestamped only as a member of whichever assessment last scored it — and any recognition of public-first disclosure as priority evidence. Nothing in scoring or provenance rewards disclosing early; equally, nothing penalises it today (TA-004-08, TA-004-09).

**Requirements.**
- R7.1 The ledger registration timestamp of a claim — the earliest ledger entry whose assessment contains that claim id — is recognised as the claim's **priority record**: the framework can report, for any claim, when it was first registered and in which assessment. This is a read over existing ledger data; it requires no new ledger format.
- R7.2 Claims may cite their own or another claim's registration as **priority evidence**: an evidence item whose ref resolves to a ledger entry (by entry hash or ledger path plus sequence) and whose kind records that the cited work was public at that time. `aee verify-evidence` (Spec 002 FR-3) learns to resolve this ref shape and recompute the entry hash, so a priority citation is inspectable rather than asserted.
- R7.3 The framework must not penalise public-first disclosure. Concretely: (a) a claim's freshness computation (src/aee/scoring.py) judges evidence age against the evidence's own `observed_at`, never against a claim's registration time — registering early cannot make a claim look stale; (b) prior public registration of the same material by the same source counts toward priority and attribution (R4), never as duplicate or self-plagiarised evidence under the shared-evidence warning (Spec 002 FR-6.2) — sameness of origin is exactly what a priority claim asserts; (c) no policy gate may treat disclosure-before-acceptance as a defect. Where any existing mechanism is found to penalise disclosure under this reading, that is a defect against R7.3 and is reported as such.

## R8 — Inspectable records (Tao point 8)

**Current state (verified — largely satisfied).** This point is the framework's present strength, and this spec says so rather than inventing work. An assessment today embeds the full claim records with their evidence (refs, `content_hash`, source quality, independence declarations), every score with its components and notes, every failure mode with its challenge and recovery hint, stored dispositions with their reasons (Spec 002 FR-5), policy verdicts with their reasons, and metadata stamping threshold, engine version, and methodology version (Spec 002 FR-4). The ledger seals each assessment's SHA-256 into the hash chain (Spec 002 FR-8a), and `verify-ledger` re-checks the chain. A verdict can already be audited back to the evidence and the challenges that shaped it (TA-004-10).

**Requirements (the delta only).**
- R8.1 The trail gains the realignment's own records: stage and stage-advance events (R1.2), decomposition structure (R2), exposition and digestion records (R3), attribution claims and caps (R4), gate cap records (R5.1), and the `not_understood` statement (R5.2) are all serialised in the assessment and covered by the ledger's assessment hash, so the sealed record is the whole verdict, not the numeric part of it.
- R8.2 No realignment mechanism may exist only in a side channel: if a stage cap, lane state, or attribution contest affects a reported verdict and is not visible in the assessment record, that is a defect against this requirement.

## 8. Interactions

- **Spec 003 FR-8 and the methodology version.** Spec 003 FR-8.2 already rules that any change altering scores on existing bundles bumps the distinct `methodology_version` field (mechanism from Spec 002 FR-4) and ships with a before/after benchmark comparison. Stage-gating (R1.3), the machine-only cap (R5.1), and lane re-labelling (R6.2) change what scores and outcomes *mean* at least as deeply as FR-8's changes, even where the lane-1 numbers themselves are untouched — a `pass` that previously could be earned at stage `created` no longer means the same thing. The realignment therefore requires **its own methodology-version bump**, distinct from FR-8's, and the two must not be folded into one bump that makes it impossible to tell which change moved a given bundle's result. This is the technical core of sequencing decision OD-T1.
- **Spec 003 FR-2 (draft cap).** Spec 003 FR-2 groups the red team's score-inflation findings and includes capping what draft-status claims can achieve. R1.3's stage caps overlap that work: a `created`-stage cap is close kin to a draft cap, and implementing both naively would stack two cap mechanisms with different vocabularies. Implementation planning (a future phase, not this spec) must state whether the draft cap is subsumed by the stage cap, layered under it, or kept distinct — and the assessment must report which cap bound a claim, in the R8.2 spirit.
- **The extension's verdict vocabulary.** The spec-kit-aee extension's commands (`speckit.aee.assess`, `speckit.aee.gate`, and siblings in electrohire/spec-kit-aee) present the engine's status and outcome vocabulary to spec-kit users; the extension's assess command documents the `ClaimStatus` values verbatim. Stage caps (R1.3), the `not_understood` statement (R5.2), and lane-paired outcomes (R6.2) all change what those commands should display. The extension therefore needs a coordinated update when this spec is implemented — its own spec/claims work in that repo, sequenced after the engine changes, following the precedent that Spec 002's FR-2/FR-4/FR-6 work packages spanned both repos with the engine first. No extension change is specified in detail here; the requirement recorded is that engine-first must not silently leave the extension presenting the old, uncapped vocabulary as settled.

## 9. Owner decisions

- **OD-T1 — Sequencing vs Spec 003.** Implement the realignment (a) before Spec 003 FR-1…FR-8, (b) after it, or (c) interleaved per work package? Consequences recorded: Spec 003 is unimplemented, so building stage-gating first means FR-8's semantics work lands on a stage-capped engine (one methodology bump sequence, but a larger first step); building Spec 003 first gives the realignment a settled scoring base but means its own later bump re-opens FR-8's before/after benchmark comparisons. This spec takes no position; claims and assessment proceed either way.
- **OD-T2 — Stage vocabulary.** The five terms `created, checked, explained, accepted, digested` are adopted verbatim from the standard in this draft. Does the owner keep them verbatim in the public model (with the documentation burden that carries), or map them to framework-native terms (with the fidelity loss that carries)?
- **OD-T3 — Status relationship.** R1.3 proposes capping the *reported* status/verdict by stage. Alternatives: rename `supported` so its settled sense is unambiguous, or keep stage fully orthogonal to status (rejected in R1.5's reasoning, but the owner's call).
- **OD-T4 — Named-human identity standard.** R3.2 requires exposition `source_id` to resolve to a person. What resolution standard: a project-local registry of named humans, an identifier shape (e.g. an email or an ORCID-style id), or deployment-defined with only the not-a-tool/not-a-model/not-empty rules enforced by the engine?

## 10. Claims and assessment record

Claims were authored before any plan or tasks, per this repo's flow — and this spec has no plan or tasks by design: `claims.json` holds 20 claims (TA-004-01…TA-004-20). The eleven problem claims (TA-004-01…TA-004-11) are observations about the current framework grounded in code reads on main at `5327915` on 2026-10-12 and marked `supported`; two of them (TA-004-09, TA-004-10) record partial credit and existing strength honestly rather than as defects. The nine outcome claims (TA-004-12…TA-004-20) are the realignment's requirements and predictions, marked `draft`.

Assessment (engine 1.4.0 from repo source, `aee assess --phase after_specify --threshold 0.70 --no-ledger`, record in `assessment.json`):

- **Outcome: ITERATE** — the expected, correct state for an after_specify draft.
- Problem claims scored 0.997–1.0 (all above threshold): the gaps against the standard are real and code-evidenced.
- Outcome claims scored 0.481 (all below threshold): they rest on this spec's assertion alone, which is precisely what the threshold exists to say.
- 79 failure modes were raised, dominated by the engine's standing heuristic challenges against new prose.

No statuses were inflated to chase a PASS.

## 11. Out of scope

- Any plan, task list, or implementation (this spec is claims and requirements only).
- Changes to scoring weights or outcome thresholds themselves (Spec 003's territory and exclusions stand).
- Evaluator-repo and benchmark-repo changes; the benchmark before/after comparison a future methodology bump requires is noted in §8 but not specified here.
- Any change to the ledger's entry format (R7 works over the existing format by design).
