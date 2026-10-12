# Plan: AEE Red-Team Remediation (Spec 003)

**Input**: `specs/003-aee-red-team-remediation/spec.md` + `claims.json` (assessed, after_specify, ITERATE — problem claims 1.0, outcome claims 0.481)

**Prerequisites**: claims.json (required, assessed), spec.md (required), Spec 002 (its FR-1 strict loading, FR-3 verify-evidence, FR-4 version stamps, and FR-8a ledger parity land first where this plan builds on them)

**Organization**: Engine first, because the evaluator and benchmark packages consume engine outcomes, evaluator results, and digests — hardening the consumers before the producer would freeze the defects in. Within the engine: outcome integrity (FR-1) and the score-inflation kit (FR-2) before reliability (FR-3), ledger (FR-4), and CLI/schema coherence (FR-5), since FR-3–FR-5 all touch the loading/scoring/serialisation surfaces FR-1/FR-2 stabilise. Evaluator composition (FR-6) and benchmark integrity + re-pinning (FR-7) follow. FR-8 (scoring/challenge/review semantics) was held at drafting pending OD-1; **the owner decided OD-1 in the affirmative on 2026-10-12** (Spec 003 §12), its claims amendment has landed (RT-003-30…RT-003-35), and it is now sequenced as Phase 8 below — in dependency order it executes **immediately after Phase 2** (it builds on Phase 2's scoring changes and must not be built on the pre-FR-2 scoring surfaces) and **before the Phase 9 close-out**, regardless of its phase number, which is retained so existing task/spec references (T801+, §9, Phase 7) do not break.

## Phase 0 — Baseline before changes (guard rail)

- Re-run every red-team probe (RT1 p1–p7, RT2 p01–p14, RT4 probe suite) against the current engine/evaluator/benchmark and archive the outputs as the pre-change baseline, so each FR's acceptance is a probe inversion, not a new invention.
- Capture the current benchmark state (stale pins and all) as the FR-7 before picture; Spec 002's T810 guard is explicitly **not** run as a meaningful check until Phase 6 re-pins.

## Phase 1 — Engine: outcome integrity (FR-1)

- `src/aee/engine.py`: empty-bundle rule (per OD-2); duplicate-id path reordered so the stress tester's CRITICAL challenge produces the assessment (expected `block`) instead of graph construction raising.
- `src/aee/cli.py`: `gate` cross-checks outcome against scores/summary/threshold and, where present, the ledger; clean exit-2 errors throughout the gate path.
- `src/aee/session.py`: duplicate ids refused/reported on load, same rule as assess.
- Tests invert RT1 `p2` §§A/C, RT2 `p09` §6, `p05` §§2–3.

## Phase 2 — Engine: score-inflation kit (FR-2)

- `src/aee/scoring.py`: evidence deduplication by canonical identity; zero-weight exclusion from independence; empty-ref earns no weight; source-identity normalisation shared with policy.
- `src/aee/policy.py`: corroboration counts positive-weight, normalised sources only; widened model self-attestation (with `src/aee/model.py`).
- `src/aee/challenge.py` + scoring: polarity-coherence challenge for kind/direction mismatch; `context` items excluded from independence/corroboration.
- Draft outcome cap (engine outcome layer): a draft claim cannot take an outcome above `gather_evidence`/`iterate` — this is the engine guarantee Spec 002 FR-2's drafting command will rely on, so it lands before or with Spec 002 Phase 4.
- Shared-evidence reporting across claims (summary-level; any outcome effect is decided and implemented with the FR-8 phase, per OD-1 as decided 2026-10-12).
- String-for-list rejection rides on Spec 002 FR-1 strict loading; its score-inflation fixture is tested here.
- Tests invert RT1 `p1` §§B/C/D/G/J, `p6` §C, `p7` (kill chain), RT2 `p04` §1.

## Phase 3 — Engine: reliability validation and credit assignment (FR-3)

- `src/aee/reliability.py`: `from_dict` range/finiteness validation with named-source errors; `reliability()`/`blended_weight` range guarantees with invariant tests; `observe_claim` contribution-weighted credit; `record()` provenance field.
- Non-finite rejection at load ties into Phase 5's strict-JSON work; the reliability fixtures land here.
- Tests invert RT1 `p6` §E, `p4` §§E–G, RT2 `p07`; held behaviour (honest Brier records in [0,1]) regression-tested.

## Phase 4 — Engine: ledger integrity and anchoring (FR-4)

- `src/aee/ledger.py`: head-commitment design per OD-3 (tip hash + count reporting; `verify-ledger` expected-tip/count assertions); content-keyed tip cache; entry-shape/version/timestamp validation with plainly stated verify semantics; canonical serialisation escaping Unicode separators; line-numbered errors for non-object lines and `entries()`/`verify()` agreement; duplicate-append reporting.
- Interplay: FR-4.1's anchor is the natural consumer of Spec 002 FR-8b Axiomere anchoring if the owner pulls it forward (OD-3); otherwise a recorded local anchor suffices for this spec.
- Tests invert RT2 `p01`, `p02`, `p03` §§A/B; `p14` held tamper classes regression-tested.

## Phase 5 — Engine: CLI artifact safety, input and schema coherence (FR-5)

- `src/aee/cli.py`: path-collision refusal before any write (output vs. input/ledger/evaluator-output), resolved-symlink reporting, out-of-root warning discipline; atomic temp+rename writes ordered artifact-before-ledger; exhaustive clean-error catch with a nesting/size guard.
- Loaders: duplicate-key rejection everywhere; `utf-8-sig` Markdown reads; strict type coercion and position-named errors (with Spec 002 FR-1); single claim-id normalisation rule across JSON/Markdown/session loaders.
- Serialisation: `allow_nan=False` on all outputs; `--as-of` pinning; digest computed over content excluding `created_at`.
- Schemas: assessment schema reconciled (`abstain`, `verdicts`, `components`); new claims-bundle input schema; CI test validating real output and real bundles. Unverified `content_hash` marked as declared-not-verified until Spec 002 FR-3 lands.
- Tests invert RT2 `p04`, `p05` §1, `p06`, `p08`, `p09` §§1–5, `p10`, `p11`, `p13`.

## Phase 6 — Evaluator: composition contract (FR-6) [evaluator repo + engine adapter]

- `spec-kit-evaluator`: fail-closed empty composition in all three composers and both command documents; real schema validation in the shipped Python path (`jsonschema` declared; absence is a hard error); invalid files wrapped as block findings; composed output schema-valid (no `_evaluator_id` injection, no `model_routing: null`, summary cap) with a compose→validate regression test on the real engine path; payload phase and payload evaluator identity authoritative; non-gating marks for `majority`/`optimistic` and a documented compose exit contract; cross-implementation fixture suite (py/sh/ps1 identical outcomes); demo in CI.
- Engine `src/aee/adapters/evaluator.py`: validator delegates to the real schema or is renamed a pre-check; emitted results stamp the producing engine version (with Spec 002 FR-4).
- The RT3-04/OD-4 decision on the evaluator dependency is taken in the extension work and assumed here, not re-decided.
- Tests invert RT4 `probe_compose`, `probe2`, `probe_engine_compose`, `probe_engine`.

## Phase 7 — Benchmark: integrity and re-pinning (FR-7) [benchmark repo]

- First synchronise the local checkout with origin (31 commits behind at red-team time) and re-verify RT4 H4–H7/M2/M3/M7 against the current code before changing it.
- Event-stream integrity (hash-chained or artifact-bound grades), `check_evidence.py` extended to the streams; `resolved` bound to one identified grader run with its exit code; freeze verification addition-aware with honest trust semantics; archived-run disclosure in reporting.
- Re-pin and re-freeze on the current stack (engine 1.4.0 line, extension 1.2.0, current evaluator commit); vendored extensions updated; CI drift check on pins vs. vendored bytes; grounding applied to every evidence kind.
- Tests invert RT4 `probe_bench`; benchmark unit suite green on the re-pinned stack.

## Phase 8 — Scoring, challenge, and review semantics (FR-8) — AUTHORIZED under OD-1; execution order: after Phase 2, before Phase 9 close-out

- **Sequencing**: this phase is numbered 8 to preserve existing references, but its dependency position is directly after Phase 2 (FR-2 scoring changes) and before the Phase 9 close-out. It may overlap Phases 3–7 only where surfaces do not collide (challenge lexicons and review queue are FR-8-only surfaces; scoring.py and policy.py changes must serialise against Phases 2, 3, and 5 work). Owner authorization: OD-1, decided 2026-10-12 (spec §12); claims: RT-003-30…RT-003-35 (this amendment); decision claim RT-003-29 updated to the decided state.
- **Methodology implication (binding)**: several FR-8 items change what a score means (freshness basis FR-8.6, substance criteria FR-8.7, unrounded threshold comparison FR-8.13). Per FR-8.2 and Spec 002 FR-4, the implementation of the first score-altering FR-8 item **bumps the distinct `methodology_version` field** (it is not the package version and must not be conflated with it), and every score-altering item ships with a before/after comparison on the Phase 7 re-pinned benchmark — if Phase 7 has not landed yet, the comparison is run at Phase 7 completion against the Phase 8 baseline captured here, and recorded in the close-out.
- `src/aee/scoring.py` + `src/aee/graph.py`: cycle-local propagation (FR-8.3) — propagation suppression scoped to the cyclic component; suppressed/degraded propagation marked per claim in the score record.
- `src/aee/policy.py` (+ `engine.py` verdict plumbing): failure-aware verdicts (FR-8.4) — no ACCEPT alongside HIGH/CRITICAL failures, demotion reasons named; contested-penalty basis aligned with scoring (FR-8.5) with two-direction engine/policy agreement tests.
- `src/aee/scoring.py`: freshness basis over the supporting set (FR-8.6) — undated/unparseable/future dates never beat honest old dates, basis documented; falsifiability/boundary substance criteria (FR-8.7) — placeholder entries earn no full credit, partial component documented, failed criterion named in score notes.
- `src/aee/challenge.py` + lexicon data: connective/vague lexicons as versioned data with a two-direction regression corpus (FR-8.8); negation detector subject binding (FR-8.9, residual limit documented); absolute-language gate requires a relevant boundary (FR-8.10); atomic/noun-phrase and proper-noun precision recalibration (FR-8.15, owned here per the OD-1 amendment; Spec 002 FR-5.5 corpus adopted if it lands first).
- `src/aee/review.py`: failure-mode channel in `AssessmentView`, band-crossing items, cumulative-drift (baseline) comparison, rename surfacing (FR-8.11); top-k integrity — adverse priority, reported omissions (FR-8.12).
- Score records: declared-state block (`uncertainty`/`severity`/`status`/`conflicts_with`) surfaced verbatim (FR-8.13a); threshold comparison on the unrounded score under the documented inclusive boundary (FR-8.13b).
- Documentation only: RT1-22 design limitation stated where propagation is documented, with Spec 002 FR-6.3 / FR-2.8 cross-references (FR-8.14). **No task in this phase claims an in-engine fix for RT1-22.**
- Tests invert RT1 `p5` §B, `p4` §§C/D, `p1` §§E/F/I, `p3` §§A–F, `p6` §§A/D, `p4` §§H–K/J.

## Phase 9 — Verification close-out

- Full red-team probe suite re-run against the hardened stack; every probe inverted or explicitly recorded as a remainder (the only expected standing remainder is RT1-22, a documented design limitation under FR-8.14, not a fix).
- Benchmark regression check (re-pointed Spec 002 T810) on the re-pinned benchmark vs. the Phase 0 baseline (claim RT-003-28).
- Full test suites in engine, evaluator, and benchmark repos; re-assessment of this spec's claims (after_implement) with outcome claims re-scored on implementation evidence; records updated honestly (no status changes without evidence).

## Sequencing notes

- Phases 1–5 are engine-only and sequential (shared model/scoring/ledger/CLI surfaces); Phase 2's draft cap coordinates with Spec 002 Phase 4 (draft-claims) so neither spec assumes the other's unbuilt guarantee.
- Phase 6 is independent of Phases 3–5 except for the adapter version stamp (Spec 002 FR-4) and may run parallel to them.
- Phase 7 depends on Phase 6 only for the composed-output contract it consumes; its re-pinning should land after the engine phases it will measure (1–5) are merged, or the re-pin will chase a moving engine.
- RT3 extension work runs in parallel throughout under its own plan; the shared contracts are the exit-code contract (Phase 1/5) and the evaluator-dependency decision (Phase 6, OD-4).
- Phase 8 (FR-8) executes after Phase 2 in dependency order (see its header): its scoring/policy work serialises against Phase 2/3/5 changes to the same files, its `methodology_version` bump (FR-8.2) is a precondition for merging any score-altering FR-8 item, and its benchmark before/after comparison consumes Phase 7's re-pinned benchmark (or is completed at Phase 7 against the Phase 8 baseline).
