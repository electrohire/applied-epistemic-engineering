# Tasks: AEE Red-Team Remediation (Spec 003)

**Input**: Design documents from `specs/003-aee-red-team-remediation/`

**Prerequisites**: spec.md (required), plan.md (required), claims.json (assessed — after_specify, ITERATE)

**Status**: Draft. Tasks unchecked except T801 (the OD-1 decision record, done 2026-10-12 by this amendment); implementation is future, separately-approved work. FR-8 was decision-gated at drafting; **OD-1 was decided in the affirmative by the owner on 2026-10-12**, so the full FR-8 task set (T801–T815) is now listed. Each task names its repo: **engine** = `electrohire/applied-epistemic-engineering`, **evaluator** = `electrohire/spec-kit-evaluator`, **benchmark** = `electrohire/spec-kit-aee-benchmark`. Extension (spec-kit-aee) work is **not** in this list — RT3 is implemented separately (spec §10).

**Format**: `[ID] [Repo] Description` — grouped by finding (FR-1…FR-8), per the spec.

## Phase 0 — Baseline

- [ ] T001 [engine] Re-run the full red-team probe suite (RT1 p1–p7, RT2 p01–p14) against the current engine; archive outputs as the pre-change baseline in the spec's hidden work records.
- [ ] T002 [evaluator] Re-run RT4 probe suite (`probe_compose`, `probe2`, `probe_engine`, `probe_engine_compose`) and archive as baseline.
- [ ] T003 [benchmark] Re-run RT4 `probe_bench` + benchmark unit tests; record the stale-stack baseline (pins, failures) before any re-pin.

## FR-1 — Outcome integrity [engine]

- [ ] T101 [engine] Empty-bundle rule in `src/aee/engine.py` per OD-2: zero claims never yields `pass`; explicit empty-bundle failure or exit-2 input error, decision recorded in the PR.
- [ ] T102 [engine] Duplicate claim ids: reorder/guard assess so the CRITICAL duplicate-identity challenge produces a completed assessment (expected `block`) instead of the `ClaimGraph` `ValueError`.
- [ ] T103 [engine] `AEESession.load()` applies the same duplicate rule (refuse/report, never last-wins) in `src/aee/session.py`.
- [ ] T104 [engine] `aee gate` cross-checks: outcome vs. scores/summary/threshold metadata, and assessment hash against the ledger where one is present; fabricated files gate as input errors.
- [ ] T105 [engine] Tests inverting RT1 `p2` §§A/C, RT2 `p09` §6, `p05` §§2–3 (empty, fabricated gate, duplicates) including exit-code assertions (never traceback, never exit 1 for input errors).

## FR-2 — Score-inflation kit [engine]

- [ ] T201 [engine] Evidence deduplication in `src/aee/scoring.py` by canonical item identity; score notes record collapsed duplicate counts.
- [ ] T202 [engine] Polarity coherence: kind/direction mismatch challenge in `src/aee/challenge.py`; `context` items excluded from scoring penalties' evasion, independence, and corroboration.
- [ ] T203 [engine] Draft outcome cap in the engine outcome layer: `status: draft` claims cannot take an outcome above `gather_evidence`/`iterate`; cap visible in assessment output.
- [ ] T204 [engine] Zero-weight exclusion: independence (`scoring.py`) and `min_independent_sources` (`policy.py`) count only positive-weight supporting items.
- [ ] T205 [engine] Source-identity normalisation (path `./`/case, URL trailing slash, whitespace) shared by `scoring.py` and `policy.py`; normalised identity reported in score notes (builds on Spec 002 FR-6).
- [ ] T206 [engine] Widen `is_model_self_attestation` (`src/aee/model.py`/`policy.py`): model-quality asserted-like support counts toward the gate; one human `asserted` self-report does not disable it.
- [ ] T207 [engine] Empty/missing evidence `ref` earns no evidence weight and draws a note/finding (interim guard ahead of Spec 002 FR-3).
- [ ] T208 [engine] Cross-claim shared-evidence reporting in the assessment summary (any outcome effect is decided and implemented with the FR-8 phase, per OD-1 as decided 2026-10-12).
- [ ] T209 [engine] Tests inverting RT1 `p1` §§B/C/D/G/J, `p6` §C, the `p7` kill chain end-to-end, and RT2 `p04` §1 (string-list explosion fixture, riding on Spec 002 FR-1 strict loading).

## FR-3 — Reliability validation and credit assignment [engine]

- [ ] T301 [engine] `ReliabilityTable.from_dict`/`SourceRecord.from_dict` validation in `src/aee/reliability.py`: finite `brier_sum` in `[0, observations]`, non-negative integer `observations`; violations are loud errors naming the source id.
- [ ] T302 [engine] Range guarantees: `reliability()` and `blended_weight` confined to `[0, 1]` by construction; `evidence_score` invariant asserted in tests.
- [ ] T303 [engine] Non-finite rejection at load for reliability files (with FR-5.5 strict-JSON outputs).
- [ ] T304 [engine] `observe_claim` credit assignment: only positive-contribution sources credited, weighted by contribution; module docstring updated to the implemented rule.
- [ ] T305 [engine] `record()` provenance: resolution source/authority field required on the direct path; loaded tables record per-entry provenance; unattributed records only via an explicitly named compatibility path.
- [ ] T306 [engine] Tests inverting RT1 `p6` §E, `p4` §§E–G, RT2 `p07`; regression: honest Brier records stay in `[0, 1]`.

## FR-4 — Ledger integrity and anchoring [engine]

- [ ] T401 [engine] Head commitment per OD-3: `verify`/assess report tip hash + entry count in anchorable form; `verify-ledger` accepts expected-tip/expected-count assertions that fail on tail truncation.
- [ ] T402 [engine] Content-keyed tip cache in `src/aee/ledger.py` (tip-line hash, not `(size, mtime_ns)`); cached append onto a forged tip refused.
- [ ] T403 [engine] `verify()` validates `ledger_version`, timestamps, and entry shape; verify output states its semantics (self-consistency; completeness only against an anchor).
- [ ] T404 [engine] Canonical serialisation escapes U+2028/U+2029/U+0085 in ledger lines (or ASCII-safe dumps); writer/reader round-trip regression test.
- [ ] T405 [engine] `verify()` line-numbered errors for non-object JSON lines (no crash); `entries()` and `verify()` agree on line handling.
- [ ] T406 [engine] Duplicate-append reporting for an already-ledgered assessment hash (explicit flag or duplicate event, per the PR design decision).
- [ ] T407 [engine] Tests inverting RT2 `p01`, `p02`, `p03` §§A/B; regression on `p14` held tamper classes (middle edit/delete, reorder, renumber, genesis tamper).

## FR-5 — CLI artifact safety, input and schema coherence [engine]

- [ ] T501 [engine] Path-collision refusal in `src/aee/cli.py`: `--output` resolving to `--input`/`--ledger`/`--evaluator-output` (or any read path) is refused before any write; symlink targets resolved and reported; out-of-root writes warn loudly (hard-refuse for input/ledger collisions).
- [ ] T502 [engine] Atomic writes (temp file + rename) for assessment/evaluator/gaps outputs; ledger append ordered after the artifact it attests exists.
- [ ] T503 [engine] Exhaustive clean-error handling: `RecursionError`/`OverflowError` and a nesting/size guard map to exit 2 with no traceback; exit 1 reserved for scored verdicts.
- [ ] T504 [engine] Duplicate JSON keys rejected (`object_pairs_hook`) at every load site with the key named; Markdown extraction reads `utf-8-sig`.
- [ ] T505 [engine] Strict type coercion under Spec 002 FR-1: `null` is not `"None"`, bools/strings are not numbers, `observed_at`/`content_hash` type-checked; errors name row index and claim id where known.
- [ ] T506 [engine] Single claim-id normalisation rule applied by JSON loader, Markdown extractor, and session loader; `source_ref` derived from the normalised id.
- [ ] T507 [engine] Strict-JSON outputs: `allow_nan=False` in CLI, ledger, and evaluator-result serialisation.
- [ ] T508 [engine] `--as-of` CLI flag pinning the scoring clock; ledgered digest computed over assessment content excluding `created_at`.
- [ ] T509 [engine] Schema reconciliation: assessment schema gains the `abstain` outcome and specified `verdicts`/`components`; new claims-bundle input schema shipped in `src/aee/schemas/`; CI validates real engine output and real bundles against both.
- [ ] T510 [engine] Unverified `content_hash` marked declared-not-verified (or omitted) in assessment output until Spec 002 FR-3 lands.
- [ ] T511 [engine] Tests inverting RT2 `p04`, `p05` §1/§§6–7, `p06`, `p08`, `p09` §§1–5, `p10`, `p11`, `p13`.

## FR-6 — Evaluator composition contract [evaluator + engine]

- [ ] T601 [evaluator] Fail-closed empty composition (non-pass outcome + non-zero exit) in Python, Bash, and PowerShell composers; command documents (`speckit.evaluator.compose.md`, `speckit.evaluator.run.md`) amended from pass-on-empty.
- [ ] T602 [evaluator] Python composer always schema-validates: shipped schema loaded and passed at the production call site; `jsonschema` declared as a dependency; its absence is a hard error, never a silent skip.
- [ ] T603 [evaluator] Invalid result files wrapped as block findings per the run command's specification — never skipped toward pass, never a composer traceback (covers RT4-H7 crash shapes).
- [ ] T604 [evaluator] Composed output schema-valid: no `_evaluator_id` injection into findings, `model_routing` omitted rather than `null`, summary within the schema cap; compose→validate regression test on the real engine→extension path (Spec 002 claims fixture).
- [ ] T605 [evaluator] Bash and PowerShell composers validate the same minimum contract and fail closed on unknown outcomes; cross-implementation fixture suite asserting identical composed outcomes for identical inputs.
- [ ] T606 [evaluator] Payload `phase` must equal the requested phase (mismatch = invalid result); evaluator identity for dedup/counting is payload `evaluator.id` + `version`, never the filename; per-evaluator finding ids namespaced against collisions.
- [ ] T607 [evaluator] `majority`/`optimistic` composed results marked non-gating in output; compose exit contract documented in the command files and implemented (non-zero on gating failure under `strict`); merged-routing inconsistencies (RT4-L1) fixed or the block marked advisory-only.
- [ ] T608 [evaluator] `examples/demo.py` fixed to the current compose output shape and executed in CI end-to-end.
- [ ] T609 [engine] `validate_evaluator_result` (`src/aee/adapters/evaluator.py`) delegates to the real schema or is renamed/documented as a structural pre-check; emitted results stamp the producing engine version alongside the contract version (with Spec 002 FR-4).
- [ ] T610 [evaluator] Command↔script drift close-out for composition: priority-ordering promise implemented or removed from the command documents; report/route executability recorded as a decision with Spec 002 FR-7.4 / OD-4.

## FR-7 — Benchmark integrity and version re-pinning [benchmark]

- [ ] T701 [benchmark] Synchronise the local checkout with origin; re-verify RT4 H4–H7/M2/M3/M7 against current code and record any deltas before changing code.
- [ ] T702 [benchmark] Event-stream integrity: hash-chained (or artifact-bound signed) `attempts`/`grades` records; `aggregate()` refuses or flags grades with no corresponding grader artifact; `scripts/check_evidence.py` extended to the streams.
- [ ] T703 [benchmark] `resolved` bound to one grader run: report identity must match the run/instance and `grader_exit_code` must record success; conflicting reports are an error, not last-wins.
- [ ] T704 [benchmark] `verify_freeze` detects additions under frozen paths; manifest trust semantics documented honestly (accident-evidence vs. tamper-resistance, FR-4.1 anchoring if required).
- [ ] T705 [benchmark] Reporting discloses archived/stale scored-run counts alongside headline metrics (host-setup archiving provenance).
- [ ] T706 [benchmark] Evidence grounding applies to every kind: unverifiable refs downgrade `inferred`/`asserted`/any kind, not only `observed` (`workflow.py grounded_claims`).
- [ ] T707 [benchmark] Re-pin and re-freeze on the current stack: engine 1.4.0 line, extension 1.2.0, current evaluator commit; `manifests/versions.json` regenerated; vendored extensions updated.
- [ ] T708 [benchmark] CI drift check: recorded pins vs. vendored bytes divergence fails the build.
- [ ] T709 [benchmark] Tests inverting RT4 `probe_bench` (forged grade, forged non-observed evidence); full benchmark unit suite green on the re-pinned stack.

## FR-8 — Scoring/challenge/review semantics [engine] — AUTHORIZED under OD-1 (decided 2026-10-12; see T801)

Execution order (plan Phase 8): after the FR-2 tasks, before close-out. Claims RT-003-30…RT-003-35 govern this set; FR-8.2's methodology-version discipline applies to every score-altering task.

- [x] T801 [engine] OD-1 decision record — **DONE 2026-10-12**: the owner (Tristen Pierson) decided OD-1 in the affirmative in the AEE improvement program chat, verbatim "Authorize FR-8: reopen scoring semantics in Spec 003", admitting RT1-08, RT1-09, RT1-10, RT1-11, RT1-15, RT1-16, RT1-17, RT1-18, RT1-19, RT1-20, RT1-22, RT1-24, RT1-25, RT1-26 into scope. Recorded in spec §12; claim RT-003-29 updated to the decided state; RT1-22 admitted as documentation-only (T814) and RT1-26 owned by this spec (T815). Claims amendment RT-003-30…RT-003-35 landed with this task, satisfying FR-8.1 for the task set below.
- [ ] T802 [engine] Cycle-local propagation (FR-8.3, RT1-08): scope propagation suppression to the cyclic component in `src/aee/scoring.py`/`graph.py`; claims outside the component keep weakest-link propagation; suppressed/degraded propagation marked per claim in the score record. Test inverts RT1 `p5` §B (STRONG capped 0.378 despite the unrelated cycle; cycle still reported).
- [ ] T803 [engine] Failure-aware policy verdicts (FR-8.4, RT1-09): `evaluate_policy` receives failure modes; no ACCEPT alongside HIGH/CRITICAL failures; demotion reasons name the triggering failures. Test inverts RT1 `p4` §C.
- [ ] T804 [engine] Contested-gate alignment (FR-8.5, RT1-25): one documented contested-penalty basis shared by `scoring.py` and `policy.py`; whatever routes the engine to `clarify` on counterevidence also trips the contested gate standalone. Test inverts RT1 `p4` §D in both directions.
- [ ] T805 [engine] Freshness semantics (FR-8.6, RT1-10): penalty basis over the supporting evidence set in `src/aee/scoring.py`; undated = unknown (never fresh), unparseable = finding + unknown/stale, future = flagged and never negative-age; penalty basis documented at the scoring site. Test inverts RT1 `p1` §F (no variant beats honestly dated old evidence).
- [ ] T806 [engine] Falsifiability/boundary substance criteria (FR-8.7, RT1-11) — **methodology change**: implement the spec-defined minimum content criteria and documented partial credit in `src/aee/scoring.py`; failed criterion named in score notes; **bump `methodology_version` per FR-8.2** and record the benchmark before/after comparison. Test inverts RT1 `p1` §E (`["x"]`/`["y"]` earn no full credit).
- [ ] T807 [engine] Challenge recall (FR-8.8, RT1-15): move connective/vague lexicons to versioned data loaded by `src/aee/challenge.py`, expanded to the RT1 evasion corpus; two-direction regression corpus committed (evasion must fire, atomic corpus must not). Lexicon changes recorded with the methodology version where behaviour changes.
- [ ] T808 [engine] Negation-conflict subject binding (FR-8.9, RT1-16): detector requires a shared subject in addition to shared content tokens; paraphrase support via the normalised lexicon data; residual heuristic limit documented. Tests invert RT1 `p3` §§E/F.
- [ ] T809 [engine] Absolute-language gate relevance (FR-8.10, RT1-17): suppression only by a boundary relevant to the claim's absolute scope (shared content/scope tokens or explicit scoping of the absoluted dimension). Test inverts RT1 `p3` §D (unrelated boundary string no longer suppresses).
- [ ] T810 [engine] Review-queue completeness (FR-8.11, RT1-18): failure-mode channel in `AssessmentView` (new/escalated failures queue at zero delta; new CRITICAL always surfaces), band/threshold-crossing items below materiality, cumulative-drift comparison against the review baseline (baseline advances only on review), rename surfacing for id changes. Tests invert RT1 `p4` §§H/I/K.
- [ ] T811 [engine] Review-queue top-k integrity (FR-8.12, RT1-19): adverse items (collapses, failure-channel) take selection priority over favourable deltas under `limit`; gameable claim-id tie-breaking removed; omitted items counted and kinded in the output. Test inverts RT1 `p4` §J (TARGET present at limit 5).
- [ ] T812 [engine] Declared-state surfacing (FR-8.13a, RT1-20): score records (and review views) carry author-declared `uncertainty`/`severity`/`status`/`conflicts_with` verbatim in a declared-state block, whether or not the numeric score changes. Test inverts RT1 `p1` §I (declared-state twins produce distinguishable score records).
- [ ] T813 [engine] Threshold boundary decision (FR-8.13b, RT1-24): threshold comparison on the unrounded score; inclusive boundary (>= threshold passes) documented at `_outcome`/scoring and in the scoring documentation; rounding confined to display/serialisation. Regression test: 0.6999996 does not pass, exactly 0.70 does (inverts RT1 `p6` §A's rounding artefact).
- [ ] T814 [engine] RT1-22 documentation (FR-8.14): propagation/scoring documentation states the weakest-link cap is conditional on author-declared dependencies and that omissions are undetectable in-engine, cross-referencing Spec 002 FR-6.3 scaffolding and FR-2.8 reporting. **Documentation only — no in-engine fix is claimed for RT1-22, in this task or any release note.**
- [ ] T815 [engine] Atomic-claim precision (FR-8.15, RT1-26), owned by this spec: irreducibility/precision recalibration for noun-phrase-internal lists/alternatives and proper-noun vague words, on the T807 two-direction corpus; cross-reference Spec 002 FR-5.5 (adopt its corpus if it lands first; Spec 002 itself is not edited). Tests invert RT1 `p3` §§B/C.

## Close-out

- [ ] T901 [benchmark] Re-run spec-kit-aee-benchmark against the T003 baseline on the re-pinned stack (this also carries FR-8.2's before/after comparison for score-altering FR-8 items); confirm no diagnostic-rate regression and that Spec 002's T810 guard now measures the hardened stack (claims RT-003-28, TH-002-21); record results in the benchmark repo.
- [ ] T902 [engine] Full red-team probe suite re-run: every RT1/RT2/RT4 probe inverted, or explicitly recorded as a remainder (the only expected standing remainder is RT1-22, documented under FR-8.14/T814 — a limitation, not a fix).
- [ ] T903 [engine] Re-assess Spec 003 claims (after_implement) on implementation evidence; update `assessment.json` and spec §11 honestly.
- [ ] T904 [engine] Full test suites green in engine, evaluator, and benchmark repos before any release step is proposed (releases remain owner-gated).
