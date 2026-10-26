# Plan: Realignment of the AEE Framework (Spec 004)

**Input**: `specs/004-framework-realignment/spec.md` + `claims.json` (21 claims, assessed after_specify, ITERATE) + `audit-2026-10-12.md` (retroactive audit) + `stage-reclassifications-2026-10-12.json`

**Prerequisites**: claims.json (required, assessed), spec.md (required), OD-T1 decided (2026-10-12, interleave — see spec §9). OD-T2/T3/T4 were proposed defaults in §0 below and are now **RATIFIED**. Ratified by owner directive 'Do all that remains' 2026-10-12, applied to the enumerated remaining items including this gate; defaults adopted as proposed.

**Organization**: Model before meaning, meaning before surfaces. The stage model (P0) is the vocabulary every later phase speaks; attribution and decomposition (P1) give claims their structure; the policy gates (P2) enforce the anti-gradability rules on that structure; lane-separated reporting (P3) makes the two lanes visible everywhere a verdict is shown. The joint phase with Spec 003 FR-8 (P4) is where scoring *semantics* change — once, under a single methodology bump. Cross-repo vocabulary alignment (P5) follows the engine, per the repo's standing engine-first precedent, and close-out (P6) re-runs the discipline on the realigned framework itself, including a fresh retro-audit sample.

**Sequencing against Spec 003 (OD-T1, decided)**: Spec 003's orthogonal lane-1 phases (FR-3 reliability, FR-4 ledger, FR-5 CLI/schema, FR-6 evaluator composition, FR-7 benchmark) proceed in parallel on the current vocabulary and are **not** blocked by this plan. Spec 003 FR-8 does not proceed separately: it is implemented inside P4 of this plan, jointly with this spec's semantics work.

## 0. Proposed defaults for the open owner decisions

Each default below was **PROPOSED — PENDING OWNER RATIFICATION** and is now **RATIFIED**. Ratified by owner directive 'Do all that remains' 2026-10-12, applied to the enumerated remaining items including this gate; defaults adopted as proposed.

The interlocked audit decisions are also adopted: OD-A1 stage rules as audited, OD-A3 Spec 001 standing reading = checked-not-complete, and OD-A4 digestion-record practice adopted for framework specs going forward. OD-A2 was already satisfied by the merged close-out re-assessments.

- **OD-T2 — Stage vocabulary: the five terms verbatim** (`created`, `checked`, `explained`, `accepted`, `digested`). Rationale: all four realigned projects (AEE, the Research Engine, Glossa-Lab, the projected-constraints program) already use these terms; framework-native synonyms would create cross-project translation drift at exactly the boundary the realignment exists to unify.
- **OD-T3 — `supported` is capped by stage** (spec R1.3's proposal). Rationale: the status vocabulary stays unchanged — no bundle migration, no renamed enum — but the *reported* status and policy verdict ceiling are bounded by the claim's stage, so `supported` can never again be read as settled beyond what the stage allows.
- **OD-T4 — Deployment-defined identity registry + engine-enforced shape rules.** Rationale: the engine cannot own a global person registry, so identity resolution is against a project-local registry file the deployment supplies; the engine enforces the shape rules on every exposition item — `source_id` non-empty, resolvable in the registry, and never a tool, a model, a team alias, or an empty string (spec R3.2).

## Phase P0 — Vocabulary and model (R1, R3 model parts)

- `src/aee/model.py`: `stage` field on `Claim` with the five-value stage vocabulary (§0, OD-T2 default); stage-advance events recorded on the claim (event kind, author, date, basis) in the dispositions precedent of Spec 002 FR-5 — a stage is a stored record, never recomputed silently.
- New evidence kind `exposition` (R3.1) with strict-loading enforcement of the named-human rule (R3.2, OD-T4 default): unresolvable or tool/model `source_id` on an exposition item is a load error in the FR-1 error shape.
- Stage-gated verdict caps (R1.3, OD-T3 default): the assessment's reported status and policy verdict ceiling are capped per the spec's stage→status/verdict table; the bundle outcome inherits the caps (R1.4) or is emitted lane-qualified (completed in P3).
- Bundle format migration path under Spec 002 FR-1 discipline: pre-realignment bundles load with stage defaulted to `created` and the default recorded in assessment metadata — silence is never the compatibility strategy.
- Claims answered: TA-004-12, TA-004-15 (model half). Acceptance: fixture bundles at each stage report exactly the capped vocabulary the spec's table allows; a claim cannot reach a settlement-worded status at stage `created`/`checked`.

## Phase P1 — Attribution and decomposition (R2, R4, R7)

- Decomposition template for headline claims (R2): the five required sub-claim roles (statement-fidelity, evidence-verification, novelty/openness, attribution, significance), each an independently scored claim with its own falsifier; a missing required role raises failure category `decomposition_incomplete`; the parent is capped by its weakest required sub-claim via the existing weakest-link propagation precedent.
- Attribution claims (R4): prior work, human contributors, and disputes registered as claims with evidence; contested attribution (the attribution claim contradicted, or carrying an unresolved HIGH/CRITICAL contradiction failure) caps the parent's stage at `checked` until resolved — the cap and its reason are inspectable in the assessment (R8.2).
- Priority records (R7): the claim-level priority read over existing ledger data (earliest registration per claim id) and priority-evidence refs resolvable by `aee verify-evidence`; the R7.3 no-penalty rules audited against scoring freshness and the shared-evidence warning, with any penalty found filed as a defect against this phase.
- Claims answered: TA-004-13, TA-004-16, TA-004-19. Acceptance: the audit's corpus pattern — a scored headline claim with no attribution claim — is impossible to produce silently after this phase; the fixture parent with a contested attribution cannot advance past `checked`.

## Phase P2 — Policy gates: anti-gradability (R5)

- Machine-only cap (R5.1): a claim whose evidence is exclusively machine-checkable kinds (the spec's proposed partition — kind `observed`/`inferred` with quality `test`/`artifact`/`model`) caps at stage `checked` in the policy layer, regardless of score; the cap record names the evidence partition that bound it.
- Mandatory `not_understood` (R5.2, R5.3): every assessment serialises a residual-unknowns statement generated from inspectable state (open failure modes, stage caps, draft sub-claims, unexamined evidence) plus author-supplied text; an assessment serialised without it — or with it empty while open items exist — is itself flagged, and `aee verify`-style checks catch it downstream.
- Verified-but-unexplained risk flag (R3.3): failure category `verified_unexplained` (MEDIUM, risk state, no score effect) for claims at stage ≥ `checked` with no exposition evidence; digestion state reported per claim.
- Claims answered: TA-004-15 (gate half), TA-004-17. Acceptance: the red-team-era pattern — a perfect score on purely machine evidence presenting as settled — is capped and labelled; every emitted assessment in the test suite carries a non-empty `not_understood` where open items exist.

## Phase P3 — Lane-separated scoring and reporting (R6, R8)

- Lane quantities (R6.1): per claim and per bundle, lane 1 (machine verification — the existing score, checks, verified evidence) and lane 2 (human-paced state — stage, exposition coverage, acceptance state, attribution state) reported as a pair; lane 2 is state, never a blended second score.
- Re-labelling (R6.2): the existing score and outcome are presented as lane-1 quantities in assessment JSON, the CLI summary, and (via P5) extension output; no headline number blends the lanes.
- Lane-2 lag stated (R6.3): the summary reports counts by stage, `verified_unexplained` counts, and stage-cap reasons wherever lane 1 is green and lane 2 is not.
- Trail completeness (R8.1, R8.2): stage events, decomposition structure, exposition/digestion records, attribution caps, gate cap records, and `not_understood` are all serialised inside the assessment and therefore inside the ledger's assessment hash — no realignment mechanism lives in a side channel.
- Claims answered: TA-004-18, TA-004-20's trail half. Acceptance: no output surface in the engine can render a lane-1 pass without its lane-2 state adjacent; a side-channel-only cap is a test failure, not a style issue.

## Phase P4 — JOINT phase: Spec 003 FR-8 + realignment semantics (one methodology bump)

- **This phase is the OD-T1 joint work.** Spec 003 FR-8's items (cycle-local propagation, failure-aware verdicts, freshness basis, falsifiability/boundary substance, challenge lexicon recall/precision, review-queue completeness, declared-state surfacing, threshold documentation — Spec 003 FR-8.1…FR-8.15) are implemented **together with** P0–P3's semantics-bearing changes as **one** designed change.
- **One `methodology_version` bump** covers both specs (Spec 003 FR-8.2's rule, applied jointly per OD-T1 as amended in Spec 004 §8): the bump is recorded with both specs named, and per-requirement fixtures attribute each behavioural change to its requirement so the joint bump stays auditable.
- **Benchmark before/after**: one comparison, run against the pre-joint baseline, on the re-pinned benchmark. **Dependency**: this requires Spec 003 FR-7 (benchmark integrity + re-pinning to the current engine/extension) to have landed, **or** a pre-joint baseline capture on the current benchmark explicitly recorded as the before-picture (the Spec 003 plan's Phase 0 pattern). If FR-7 has not landed when P4 is ready, capture the baseline — do not let the joint phase chase a moving benchmark, and do not run the comparison against a benchmark re-pinned *after* the change as if it were the before state.
- The Spec 003 FR-2 draft cap interaction (Spec 004 §8) is resolved here, in writing, in the implementation record: whether the draft cap is subsumed by the stage cap, layered under it, or kept distinct — and assessments report which cap bound a claim.
- Sequencing inside the program: P4 executes only after P0–P3 (its semantics sit on the stage model) and serialises against any in-flight Spec 003 engine work touching `scoring.py`/`policy.py`.
- Claims answered: TA-004-12…TA-004-20 (semantics half, jointly with Spec 003's RT-003-30…RT-003-35). Acceptance: one bump, one before/after, every FR-8 probe inversion and every Spec 004 semantics fixture green under the same engine build.

## Phase P5 — Extension and evaluator vocabulary alignment

- `spec-kit-aee`: the commands' verdict language updated to the realigned vocabulary — stage-capped statuses, lane-paired outcomes, `not_understood` rendered with every verdict (R5.3, R6.3) — under that repo's own spec/claims discipline, engine first per precedent; the extension version floor for the engine moves to the realigned engine and the runner's version enforcement (already live) refuses older engines cleanly.
- `spec-kit-evaluator`: the composition contract checked against lane-paired outcomes — a composed result must not re-blend the lanes into a single headline; any contract change is specced in that repo, not smuggled into this one.
- Catalog consequence: the extension's next release follows the release runbook (GitHub Release for the tag, fresh-template submission, values regenerated from the new `extension.yml`); this plan does not release anything.
- Claims answered: the extension half of TA-004-18. Acceptance: an assessment produced through the extension displays the same caps, lanes, and residual-unknowns as the bare CLI on the same bundle.

## Phase P6 — Close-out: re-assessment and a fresh retro-audit sample

- Re-assess this spec's claims (after_implement) on implementation evidence; re-assess Spec 003's claims for the joint P4 work under the same build. Statuses change only on evidence, per the standing rule.
- **Fresh retro-audit sample**: re-run the 2026-10-12 audit method over a sample of post-realignment bundles (this spec's own close-out bundle first) — stage assignments, falsifier coverage, attribution presence, `not_understood` presence — and file the result as a dated audit addendum beside `audit-2026-10-12.md`, append-only. The framework's first digestion-era records are expected to be mostly `checked` with lane-2 lag stated; anything claiming `explained` or beyond must name its human evidence.
- Verify the historical record is untouched: the frozen assessments and the 2026-10-12 audit files remain byte-identical (sha256 spot-check against §8 of the audit report).
- Claims answered: all, by evidence. Acceptance: the close-out bundle itself satisfies the discipline it ships — or the gaps are recorded as findings, not waived.

## Sequencing notes

- P0 → P1 → P2 → P3 are engine-only and sequential (shared model/scoring/policy surfaces).
- P4 depends on P0–P3 and on the Spec 003 FR-7 re-pin or a recorded baseline capture; it is the single point where scoring semantics change.
- P5 depends on P3/P4 (it presents their vocabulary) and runs per-repo under those repos' own flows.
- P6 depends on everything and produces the program's first post-realignment audit evidence.
- OD-T2/T3/T4 ratification was required before P0 merges and has now been given (see §0); the defaults existed so that a single owner decision unblocked the phase, not so the phase could proceed undecided.
