# Feature Specification: AEE Red-Team Remediation

**Feature Branch**: `spec/003-aee-red-team-remediation`

**Created**: 2026-10-12

**Status**: Draft — claims assessed (after_specify; see §11). No implementation in this spec.

**Input**: A four-team red-team exercise against the AEE stack on 2026-10-12, run against the Spec 002 branch tip (`59589c3`, engine 1.4.0 from repo source). RT1 attacked the engine core (26 findings), RT2 the engine trust surfaces — ledger, CLI, model coercion, reliability sidecar (24 findings), RT3 the spec-kit-aee extension (20 findings; cross-referenced in §10 only — extension fixes are being implemented separately), and RT4 the evaluator and benchmark repos plus cross-repo contracts (20 findings). Every finding below was produced by an executable probe, not a code read alone; probe paths are cited as evidence in `claims.json`. Findings already covered by Spec 002 FR-1..FR-8 are not re-specced; sharper variants are recorded as variants and mapped to the Spec 002 work they sharpen.

## Purpose

Spec 002 hardened the seams it knew about. The red team tested whether the *outcomes* those seams produce can be forged, inflated, laundered, or silently lost — and in several composable ways, they can: an empty bundle passes, a two-field fabricated file passes `aee gate`, twenty copies of one worthless evidence item cross the confidence threshold, a poisoned reliability sidecar produces a perfect score, the ledger cannot see its own newest entries being deleted, and the evaluator layer composes the absence of evidence into a PASS in three implementations. This spec groups the ~70 engine, evaluator, and benchmark findings into eight work packages. Scoring-semantics findings whose fix would change scoring weights or challenge heuristics are **not** silently absorbed: they are grouped in FR-8 and flagged as owner decisions, because Spec 002 §10 explicitly excluded scoring-weight changes.

## FR-1 — Outcome integrity: no vacuous pass, no forged gate, no crash instead of a verdict (engine)

**Current state (verified).** An explicitly empty claim bundle assesses as `pass`, healthy, CLI exit 0 (RT1-01: `_outcome` is vacuously true over empty collections). `aee gate` trusts a hand-written `outcome` string — `{"outcome": "pass"}` with no claims, scores, hash, or ledger check exits 0 (RT2-H1). Duplicate claim ids crash `assess` with a bare `ValueError` from graph construction, so the stress tester's designed CRITICAL duplicate-identity challenge (which would route to `block`) is unreachable; `AEESession.load()` instead silently discards all but the last duplicate (RT1-12, RT2-M4).

**Requirements.**
- FR-1.1 An empty bundle (zero claims) never produces `pass`: assess refuses it as an input error (exit 2) or returns a non-pass outcome with an explicit empty-bundle failure mode. The chosen behavior is recorded as a decision in the implementation PR and tested either way.
- FR-1.2 `aee gate` does not trust the `outcome` string alone: it cross-checks outcome against the assessment's scores, summary counts, and threshold metadata, and — where a ledger is present — that the assessment's hash is ledgered. A file failing cross-checks gates as an input error, never as pass.
- FR-1.3 Duplicate claim ids produce a completed assessment routed by the CRITICAL duplicate-identity challenge (expected: `block`), never an exception; `AEESession.load()` applies the same rule instead of last-wins merging.
- FR-1.4 No input error in this package surfaces as a traceback or as exit 1 (the scored-verdict code); input errors use the clean-error exit-2 path (extends Spec 002 FR-1.6 to the gate and session surfaces).

**Acceptance.** Probes RT1 `p2_engine.py` §A/§C, RT2 `p09_cli_io.py` §6 and `p05_json_dupes.py` §§2–3, inverted: empty bundle does not pass; fabricated gate file does not pass; duplicate-id bundle yields a `block` assessment naming the duplicated id.

## FR-2 — The score-inflation kit: deduplication, polarity coherence, draft cap, weight-gated independence (engine)

**Current state (verified).** These defects compose into a kill chain (RT1 `p7_combined.py`): a draft claim supported only by twenty copies of one model self-attestation plus one human assertion reaches `pass`, healthy, score 0.837, policy ACCEPT. Individually: the evidence score `1 − Π(1 − wᵢ)` never deduplicates identical items, so 20 copies of the weakest item move a claim from 0.378 to 0.703 (RT1-02); relabelling contradicting evidence `direction: "context"` erases it from scoring, challenge, and policy simultaneously — score 0.25 becomes 1.0 (RT1-03); `status: "draft"` exempts a claim from the falsifiability challenge and no rule caps a draft's outcome, inverting Spec 002 FR-2's assumption that drafts cannot take `pass` (RT1-04); zero-weight `unsupported`/`contradicted`-kind items mint independence and policy corroboration for free (RT1-06); the model-only abstention gate is defeated by relabelling one item `asserted`→`inferred` or adding one human self-report (RT1-13); same-origin refs differing only by `./`, case, trailing slash, or trailing space score independence 1.0 and satisfy policy corroboration — in **both** scoring and policy, so a scoring-only fix leaves the gate fooled (RT1-14, variant of Spec 002 FR-6); the same evidence items reused across N split claims score fully in each (RT1-21, sharper than Spec 002 FR-6.2's warning-only framing); an evidence item with an empty `ref` earns full evidence weight (RT1-23, variant of Spec 002 FR-3); and a string where a list belongs (`"boundary": "production"`) is exploded into characters by `Claim.from_dict` and awards full boundary/falsifiability credit (RT2-H5, variant of Spec 002 FR-1).

**Requirements.**
- FR-2.1 Evidence scoring deduplicates items by a canonical identity (ref + kind + source + direction, after the normalisation in FR-2.5): duplicate items contribute once, and the score notes record how many duplicates were collapsed.
- FR-2.2 Polarity coherence is validated: an evidence item whose `kind` is `contradicted` (or whose linked content is a refutation) cannot be routed by `direction` into invisibility; a kind/direction mismatch is a challenge (failure mode), and `context` items never feed independence or corroboration.
- FR-2.3 Draft claims have an engine-enforced outcome cap: a claim with `status: draft` cannot contribute to, or receive, an outcome above `gather_evidence`/`iterate` (the cap Spec 002 FR-2 assumed), regardless of its score; the cap is visible in the assessment.
- FR-2.4 Independence and policy corroboration count only supporting items with positive evidence weight; zero-weight items are excluded from `source_ids`, independence, and `min_independent_sources` alike.
- FR-2.5 Source identity is normalised before counting (path `./` and case, URL trailing slash, surrounding whitespace) in **both** `scoring.py` and `policy.py`; the normalised identity is what score notes report (builds on, and does not replace, Spec 002 FR-6's `independent_of` consumption).
- FR-2.6 `is_model_self_attestation` is widened beyond the exact `asserted`+`model` pair: model-quality support of any asserted-like kind counts toward the gate, and a single human `asserted` self-report does not by itself switch the gate off.
- FR-2.7 An evidence item with an empty or missing `ref` earns no evidence weight and draws a scoring note/finding (interim guard ahead of Spec 002 FR-3's full verify-evidence).
- FR-2.8 Cross-claim evidence reuse is surfaced with outcome effect, not only the Spec 002 FR-6.2 warning: a bundle whose claims share one supporting evidence set reports that fact in the summary, and the owner decides (FR-8) whether it also caps the outcome.
- FR-2.9 List-typed fields reject a bare string under strict loading rather than exploding it into characters (lands with Spec 002 FR-1 strict mode; the score-inflation consequence is tested here).

**Acceptance.** The RT1 `p7_combined.py` kill chain, re-run, yields no `pass`, no ACCEPT, and a score attributable only to distinct, positive-weight, polarity-coherent evidence; each RT1 §B/§C/§D/§G and RT2 `p04` §1 probe inverted individually.

## FR-3 — Reliability input validation and credit assignment (engine)

**Current state (verified).** `ReliabilityTable.from_dict` / `SourceRecord.from_dict` perform no range or finiteness checks: `brier_sum=-99, observations=3` yields reliability 34.0 and a blended model weight of 17.1 (RT1-05); a `NaN` Brier sum — in JSON the CLI itself can emit — collapses `min`/`max` clamps so a single model assertion scores a perfect 1.0 and `pass`, and the assessment serialises bare `NaN` that strict JSON parsers reject (RT2-C1, the same root defect through a second input). Credit assignment is abusable independently: `observe_claim` credits **every** distinct supporting source with the claim's full score, so a zero-weight junk source riding three claims carried by real test evidence is canonised at reliability 1.0 in the 3-observation cold start; symmetrically, attaching a victim source to three false claims destroys its measured reliability; and `record()` accepts caller-asserted predicted/outcome pairs with no provenance (RT1-07).

**Requirements.**
- FR-3.1 `from_dict` validates: `observations` is a non-negative integer, `brier_sum` is finite and within `[0, observations]` (the Brier bound), and any violation is a loud input error naming the source id — never a silent clamp into validity.
- FR-3.2 `reliability()` is guaranteed in `[0, 1]` by construction and asserted in tests; a blended weight can never leave `[0, 1]`, and `evidence_score` can never leave `[0, 1]` (the documented invariant, enforced, not hidden by the final clamp).
- FR-3.3 Non-finite numbers (`NaN`, `Infinity`) are rejected at load in reliability files, claim bundles, and metadata alike; engine outputs are strict-JSON safe (see FR-5.5).
- FR-3.4 `observe_claim` credits only sources whose evidence carried positive weight in the claim's score, weighted by their contribution — coattail sources earn nothing; the credit rule is documented in the module docstring that today promises the poisoning cannot happen.
- FR-3.5 `record()` gains a provenance expectation: directly recorded pairs must carry a resolution source/authority field, and tables loaded from disk record how each entry was produced; unattributed records are accepted only in an explicitly named compatibility path.

**Acceptance.** RT1 `p6_refinements.py` §E and `p4` §§E–G and RT2 `p07_reliability_poison.py` inverted: poisoned tables fail load loudly; coattail farming leaves the junk source at cold-start; honest Brier records still produce reliability in `[0, 1]` (the held behaviour in RT1/RT2).

## FR-4 — Ledger integrity: anchoring against tail truncation and cache forgery (engine)

**Current state (verified).** The hash chain detects middle edits, middle deletions, reordering, and mid-line truncation (held, RT2 `p14`) — but deleting the **newest** entries at a line boundary verifies `valid`: there is no external head commitment, count anchor, or signed tip anywhere in the design, so rollback of exactly the most forge-worthy entries is invisible (RT2-H2). The verified-tip cache is keyed on `(st_size, st_mtime_ns)`, both attacker-settable: a same-size, same-mtime forgery is accepted by a cached instance, which then appends onto the forged chain (RT2-H3). Whole-chain rehash forgery verifies, and `verify()` never validates `ledger_version`, timestamps, or payload shape — its `valid: true` is self-consistency only, a semantics the output never states (RT2-M1). The ledger's own writer can permanently corrupt it: payloads containing U+2028/U+2029/U+0085 are serialised unescaped by `_canonical` but split by `read_text().splitlines()`, after which every append is refused — a one-character permanent denial of service created by the writer (RT2-M2). `verify()` crashes with `AttributeError` on non-object JSON lines (no line number), while `entries()` happily returns the same lines — the two read paths disagree (RT2-M5). Duplicate appends of the same assessment chain in silently, with no idempotency signal for retried runs (RT2-L1).

**Requirements.**
- FR-4.1 The ledger gains an external head commitment: `verify` reports the tip hash and entry count in a form a caller can anchor elsewhere (file, CI artifact, or — later — the Spec 002 FR-8b Axiomere anchor), and `verify-ledger` accepts an expected-tip/expected-count assertion that fails on tail truncation. (Design choice — sidecar head file vs. anchored tip — is recorded in the implementation PR; the requirement is that truncation becomes detectable by a consumer who kept the anchor.)
- FR-4.2 The tip cache is keyed on content, not `(size, mtime_ns)`: a cache hit requires a hash of the tip line (or the whole file below a size bound); a forged same-size/same-mtime file is re-verified and refused.
- FR-4.3 `verify()` validates `ledger_version`, timestamp parseability, and entry shape, and its output states its semantics plainly: self-consistent chain, not proof of actor or of completeness without an FR-4.1 anchor.
- FR-4.4 Canonical serialisation escapes the Unicode line/paragraph separators (or writes with `ensure_ascii=True` for ledger lines) so the writer can never produce a file its own reader splits differently; regression test with a U+2028 payload appends and re-verifies.
- FR-4.5 `verify()` never crashes on a malformed line: non-object JSON, like invalid JSON, is a per-line error with its line number; `entries()` and `verify()` agree on what a line is.
- FR-4.6 Appending an assessment whose hash is already the ledger's recorded assessment (same artifact, same actor) is reported as a duplicate — appended only under an explicit flag or recorded as a duplicate event, per the design decision in the implementation PR.

**Acceptance.** RT2 `p01` (tail truncation now fails against an anchor), `p03` §B (cached instance refuses the forgery), `p03` §A (Unicode payload round-trips), `p02` (non-object lines produce line-numbered errors), all inverted; the `p14` held tamper classes still detected.

## FR-5 — CLI artifact safety, input coherence, and schema coherence (engine)

**Current state (verified).** The CLI can destroy the artifacts the trust story rests on: `--output` equal to the input path replaces the claims bundle with the assessment; `--output` equal to `--ledger` overwrites the entire hash chain with one assessment JSON; symlink targets outside the project are truncated and rewritten without any check (RT2-H4); no CLI output/ledger/state path has any confinement or even a warning (RT2-L3). State is partial on failure: the ledger is appended **before** the assessment is written, by non-atomic `write_text`, so a failed run leaves a ledger attesting to an assessment file that was never produced (RT2-M3). Input coherence residuals beyond Spec 002 FR-1's named set: `RecursionError`/`OverflowError` leak tracebacks with exit 1, indistinguishable from a scored verdict (RT2-M6); duplicate JSON keys are silently last-wins at every `json.loads` site — bundles, reliability files, and ledger lines (RT2-M7); a UTF-8 BOM silently deletes the first Markdown claim (RT2-M8); type coercion turns `null` text into the proposition `"None"`, `"confidence": true` into 1.0, and an integer `observed_at` into a scoring crash (RT2-M10); malformed rows produce opaque errors with no row index or claim id (RT2-L5); claim-id identity differs across loaders (case, whitespace, Unicode normalisation; the Markdown path uppercases ids, the JSON path does not) so `depends_on` cross-references silently miss (RT2-L2). The engine also emits non-standard JSON (bare `NaN`/`Infinity` from metadata) in assessments and ledger lines (RT2-M11); assessment hashes are not a function of the input because `created_at` is baked into the ledgered digest and the CLI exposes no `--as-of` (RT2-M12); the shipped assessment schema **rejects** engine output (policy-demoted outcome `abstain` is absent from its enum; code-accepted `ref: ""` fails its `minLength: 1`; emitted `verdicts` appear in no schema property) and no input-bundle schema exists at all, so Spec 002 FR-1.4's `aee validate` has nothing machine-checkable to validate against (RT2-M9, RT2-L4). Finally, `content_hash` is republished verbatim into assessment output without ever being computed — a hash-shaped value in a field readers will take as a verification result (RT2-L6, variant of Spec 002 FR-3).

**Requirements.**
- FR-5.1 Before any write, the CLI refuses when `--output` resolves to the same file as `--input`, `--ledger`, `--evaluator-output`, or any other path the run reads; symlink targets are resolved and reported before writing, and writes outside an explicit opt-in follow the project-root discipline Spec 002 FR-3.1 already articulates for evidence refs (at minimum: warn loudly on stderr and in the run record; hard-refuse for the input/ledger collisions).
- FR-5.2 Writes are atomic (temp file in the same directory + rename) and ordered so the ledger append happens only after the assessment artifact it attests to exists; a failed write leaves no ledger entry for a missing artifact.
- FR-5.3 The CLI's clean-error catch is exhaustive for input-driven failures (including `RecursionError` and `OverflowError`, with a depth/size guard for nested JSON); exit 1 is reserved for scored verdicts.
- FR-5.4 All engine JSON loads reject duplicate keys (`object_pairs_hook`) with an error naming the duplicated key; Markdown extraction reads `utf-8-sig`.
- FR-5.5 All engine JSON outputs are strict-JSON: dumps use `allow_nan=False` (failing loudly at write time rather than emitting bare `NaN`/`Infinity`), for assessments, evaluator results, and ledger lines alike.
- FR-5.6 Type coercion is strict under Spec 002 FR-1: explicit `null` for a required string is an error (not `"None"`); booleans and strings are not numbers; `observed_at`/`content_hash` are type-checked at load. Errors name the row index and, once known, the claim id.
- FR-5.7 Claim-id identity is defined once (normalisation rule for case/whitespace/Unicode) and applied identically by the JSON loader, Markdown extractor, and session loader; `source_ref` derivation uses the same normalised id.
- FR-5.8 Determinism: the CLI exposes `--as-of` (pinning the scoring clock that `scoring.py` already accepts), and the ledgered digest is computed over the assessment **content** with `created_at` excluded or separately recorded — identical input replayed produces an identical digest.
- FR-5.9 Schema coherence: the assessment schema is reconciled with the code (outcome enum includes `abstain`; `verdicts` and score `components` are specified, not open), a claims-bundle input schema is shipped in `src/aee/schemas/`, and a CI test validates real engine output against the assessment schema and real bundles against the input schema.
- FR-5.10 Until Spec 002 FR-3 lands, assessment output marks an unverified `content_hash` as declared-not-verified (or omits it); a republished hash must never read as a verification result.

**Acceptance.** RT2 `p09` §§1–5, `p08`, `p13`, `p05` §1, `p06` (BOM), `p04`, `p11` inverted; two identical CLI runs with `--as-of` pinned produce byte-identical digests (RT2 `p10`).

## FR-6 — Evaluator composition contract: schema enforcement and no pass-on-empty (spec-kit-evaluator + engine adapter)

**Current state (verified).** Absence composes to PASS in all three implementations and **by command design**: missing results directory, zero files for the phase, zero *valid* files, and no registered evaluators each produce `outcome: "pass"`, exit 0 — a typo'd phase, crashed evaluator, or deleted directory reads downstream as a green gate (RT4-C1). The Python composer never schema-validates in its shipped path (its only call site omits the `schema` argument; the validation branch is dead code, silently skipped on `ImportError`, and `jsonschema` is not a declared dependency); its hand fallback checks five keys, so a hostile fixture with `severity: "catastrophic"`, an unknown finding kind, and extra properties composes to `pass` with the finding preserved verbatim (RT4-C2). The composed output then violates its own schema — injected `_evaluator_id` against `additionalProperties: false`, `model_routing: null` against `type: object`, summary past the 500-char cap — proven on the real engine→extension path with Spec 002's own claims, and the benchmark already carries workarounds stripping both defects (RT4-C3). The Bash composer performs zero validation and defaults unknown outcomes to PASS (RT4-C4). Phase is taken from the filename glob, never compared with the payload's `phase` (RT4-H1); evaluator identity is the filename while summaries use the payload id, so one evaluator duplicated under two filenames outvotes a block under `majority` (RT4-H2); `majority` and `optimistic` compose a BLOCK into PASS with nothing marking the result non-gating, and compose's exit code is always 0 under every strategy (RT4-H3); schema-adjacent payloads crash the composer with tracebacks instead of the run command's specified wrap-in-a-block-finding behaviour (RT4-H7); `examples/demo.py` — the repo's only end-to-end exhibit — crashes on `composed['composed_outcome']` (RT4-M1); the three composers diverge semantically (dedup, validation, contradiction, `next_action`) while `extension.yml` advertises them as one capability (RT4-M4); command documents promise priority ordering and report/route behaviour no shipped executable implements (RT4-M5); the engine's own `validate_evaluator_result` is a subset validator that accepts schema-invalid results and stamps a hard-coded evaluator version unrelated to the producing engine (RT4-M6); merged model routing is internally inconsistent (RT4-L1); and the evaluator dependency declared by the extension is unenforceable and unchecked at assess time, so a missing/mismatched evaluator surfaces only at compose — where absence passes (RT4-L2; cross-reference RT3-04).

**Requirements.**
- FR-6.1 Empty composition fails closed: zero valid results for a phase composes to a non-pass outcome (expected: `block` or an explicit `no_results` error outcome) and a non-zero exit, in the Python, Bash, and PowerShell composers **and** in the command documents that today specify pass-on-empty (`speckit.evaluator.compose.md`, `speckit.evaluator.run.md`).
- FR-6.2 The Python composer always loads and applies the shipped schema (`jsonschema` becomes a declared dependency; its absence is a hard error, never a silent skip), and invalid files are wrapped as block findings per the run command's specification instead of being skipped toward pass or crashing the composer.
- FR-6.3 Composed output validates against the shipped schema: no `_evaluator_id` injection into findings (evaluator identity lives at the result level or in a schema-declared property), `model_routing` is omitted rather than `null`, and the composed summary respects the schema cap. A compose→validate regression test runs on the real engine→extension path (Spec 002 claims as the fixture).
- FR-6.4 The Bash and PowerShell composers validate the same minimum contract (required keys, outcome enum, evaluator shape) and fail closed on unknown outcomes; a cross-implementation fixture suite asserts identical composed outcomes for identical inputs on all three.
- FR-6.5 The payload's `phase` must equal the requested phase; a mismatch invalidates the result (block finding), and evaluator identity for dedup and counting is the payload `evaluator.id` + `version`, never the filename; duplicates of one evaluator count once under every strategy.
- FR-6.6 Composed results produced under `majority` or `optimistic` are marked non-gating in the output, and compose exits non-zero when the composed outcome is a gating failure under `strict`; the exit-code contract is documented in the command files, not only in prose examples.
- FR-6.7 The engine's `validate_evaluator_result` either delegates to the real schema or is renamed/documented as a structural pre-check; emitted evaluator results stamp the producing engine version (ties into Spec 002 FR-4) alongside the evaluator contract version.
- FR-6.8 `examples/demo.py` runs end-to-end in CI against the current compose output shape.
- FR-6.9 Command↔script drift is closed for the items composition owns: finding order and identity are namespaced by evaluator so ids cannot collide across results; the priority-ordering promise is either implemented or removed from the command documents (report/route executability is recorded as a decision alongside Spec 002 FR-7.4).

**Acceptance.** RT4 `probe_compose.txt`, `probe2.txt`, `probe_engine_compose.txt` inverted: empty/all-invalid/unknown-outcome directories do not pass; the hostile fixture is rejected or wrapped as block; a real engine result composes to schema-valid output with no consumer workarounds; phase-mismatched and duplicated-evaluator fixtures cannot move the outcome; demo exits 0.

## FR-7 — Benchmark integrity and version re-pinning (spec-kit-aee-benchmark)

**Current state (verified, local checkout — noted 31 commits behind origin, not pulled, per the red-team brief).** The event streams that determine scores (`attempts`/`grades`/`budget` JSONL) are unauthenticated plaintext: one hand-written attempts line plus `{"resolved": true}` in `grades` — no grader run, no log — makes `aggregate()` report `resolved_rate: 1.0`, while `check_evidence.py` verifies only content-addressed objects, never the streams (RT4-H4). The benchmark measures an obsolete stack: it pins engine `==1.0.2`, records extension/evaluator 1.0.0 and a stale evaluator commit, and vendors extension 1.0.0 requiring engine `>=1.0.0`, against current truth engine 1.4.0 / extension 1.2.0 (floor `>=1.4.0,<2`); run locally, 5 of 11 probed unit tests fail, including the real-extensions test with "AEE emitted no evaluator result" — so Spec 002's T810 regression guard, run against this benchmark, validates the 1.0.x-era stack rather than the hardened one (RT4-H5). Evidence grounding in the benchmark adapter verifies only `kind == "observed"`: identical forged evidence labelled `inferred` or `asserted` keeps its declared `test`/`primary` quality and inflates the AEE arm's own assessment (RT4-H6). `verify_freeze` is addition-blind (new files under frozen paths are never noticed) and `freeze_id` is self-signed by whoever edits the manifest (RT4-M2). SWE-bench `resolved` is taken from any `report.json` found by `rglob`, last-boolean-wins, independent of `grader_exit_code` and run identity (RT4-M3). Host-setup archives a stale scored run aside on manifest mismatch and restarts clean — by design, on every rerun — with no reporting requirement to disclose how many archived attempts preceded the reported run (RT4-M7).

**Requirements.**
- FR-7.1 Benchmark event streams gain integrity: append-only hash chaining (reusing the engine ledger pattern) or signed grade records bound to grader artifacts; `aggregate()` refuses or flags grades with no corresponding grader artifact. `check_evidence.py` extends to the streams.
- FR-7.2 The benchmark is re-pinned and re-frozen on the current stack (engine 1.4.0 line, extension 1.2.0, evaluator at its current commit) with `manifests/versions.json` regenerated, the vendored extensions updated, and a CI drift check that fails when recorded pins diverge from the vendored bytes (the faithful-today vendoring held in RT4 becomes guarded).
- FR-7.3 The local-checkout staleness is resolved as part of re-pinning (pull/rebase to origin first; findings H4–H7/M2/M3/M7 were verified against the stale checkout and are re-verified against origin during implementation).
- FR-7.4 Evidence grounding applies to every kind: any evidence whose ref cannot be verified is downgraded regardless of its declared `kind`; kind labels confer no exemption.
- FR-7.5 `verify_freeze` detects additions under frozen paths, not only modifications of listed files; the manifest's trust semantics are documented honestly (tamper-evidence against accidents, anchoring per FR-4.1 if tamper-resistance is required).
- FR-7.6 `resolved` is bound to one grader run: the report must match the run/instance identity and a zero (or recorded-success) `grader_exit_code`; conflicting reports are an error, not last-wins.
- FR-7.7 Reporting discloses archived/stale run counts alongside headline metrics; an archived scored run is never silently absent from the denominator's provenance.

**Acceptance.** RT4 `probe_bench.txt` inverted (a forged grade with no grader artifact does not aggregate); benchmark unit suite green on the re-pinned stack; Spec 002 T810 is re-pointed at the re-pinned benchmark in this spec's close-out tasks (T710/T711).

## FR-8 — Scoring, challenge, and review semantics — ⚠️ OWNER DECISION REQUIRED (engine)

**Current state (verified).** Spec 002 §10 excluded "any change to the scoring weights or outcome thresholds themselves." The findings below are real, probe-verified defects, but their fixes change scoring or challenge *semantics* — what a score means — and several shade into weights. They are grouped here so the owner can admit them into scope explicitly, item by item, rather than having them smuggled into FR-1..FR-7 implementation or silently dropped. **No FR-8 item is authorised by this spec's drafting; each needs the owner's named go-ahead.**

- RT1-08 — One unrelated dependency cycle disables weakest-link propagation for the **entire** graph; per-claim scores/verdicts report an unconditional 1.0/ACCEPT for a claim whose real dependency scores 0.378. (Fix direction — per-component propagation — is arguably integrity, FR-1-adjacent; the owner classifies it.)
- RT1-09 — Policy verdicts are computed blind to failure modes: ACCEPT is issued alongside HIGH failures and a `clarify` outcome. (Fix direction — verdicts demote on failures — mirrors the outcome rule; owner classifies with RT1-08.)
- RT1-10 — Freshness is gameable four ways: only the newest `observed_at` matters, missing/unparseable/future dates are all free, and the honest author recording real old dates is the only one penalised (max penalty 0.10 regardless).
- RT1-11 — Falsifiability and boundary scores are pure presence booleans: `["x"]` / `["y"]` earn the full components. Presence-vs-substance is a validation gap that shades into weight semantics.
- RT1-15 — Challenge recall holes: compound claims evade via unlisted connectives ("plus", "together with", "as well as"); vague claims evade via unlisted synonyms ("seamless", "intuitive", "optimal", "world-class").
- RT1-16 — Negation-conflict detector: paraphrased true contradictions evade completely; different subjects sharing tokens false-fire.
- RT1-17 — The absolute-language gate is suppressed by **any** boundary string, however unrelated; presence, not coverage.
- RT1-18 — The review queue is blind to everything except propagated-score deltas and verdict changes: salami-sliced declines (0.90→0.50 in 0.04 steps), band crossings, and a claim gaining a CRITICAL failure at the same score are all invisible; failures are not part of `AssessmentView` at all.
- RT1-19 — Review-queue top-k flooding: equal/larger decoy deltas push a real collapse past `limit`; ties break by claim-id order.
- RT1-20 — Scoring ignores `uncertainty`, claim `severity`, `status`, and `conflicts_with` entirely: a claim its own author marked `contradicted`/`insufficient_evidence` scores an identical 1.0.
- RT1-22 — Dependency laundering by omission: `depends_on` is purely author-declared, so the weakest-link cap is voluntary. Recorded as a **design limitation**: undetectable in-engine; mitigation is Spec 002 FR-6.3 scaffolding plus FR-3-style verification, and no FR-8 fix should claim to close it.
- RT1-24 — Threshold boundary: exactly 0.70 passes (defensible), but 6-decimal rounding of `direct` before comparison widens the pass band (a true 0.6999996 becomes 0.700000). The boundary should be a documented decision, not a rounding artefact.
- RT1-25 — Contested-gate asymmetry: a real contradiction in a weak kind costs ~0.05 penalty, under policy's 0.25 contested threshold, so standalone policy returns ACCEPT for a claim the engine routes to `clarify`.
- RT1-26 — Atomic claims false-fire irreducibility on lists/alternatives inside a single proposition (units of measure, demographic phrasing), and a listed vague word inside a proper noun false-fires precision. (Precision-side companion to Spec 002 FR-5.5's recalibration — may be folded into Spec 002's FR-5 work by the owner instead of held here.)

**Requirements (conditional on owner admission).**
- FR-8.1 Each admitted item gets its own claims amendment and falsification fixture before implementation; no FR-8 item rides along inside an FR-1..FR-7 task.
- FR-8.2 Any admitted change that alters scores on existing bundles is recorded as a methodology-version change (Spec 002 FR-4's distinct `methodology_version` field), with a benchmark before/after comparison (FR-7's re-pinned benchmark).

**Acceptance.** The owner's decision on each RT1 item above is recorded in §12 (admit / defer / reject / fold into Spec 002 FR-5); admitted items are specced by amendment, not by this draft.

## 9. Triage table — every red-team finding, mapped

Nothing is silently dropped. "Spec 002" means the finding is a variant of, or already covered by, that spec's FR — the Spec 003 FR named is where the sharper consequence is handled.

### RT1 — engine core (26)

| ID | Sev | Primary FR | Note |
|---|---|---|---|
| RT1-01 | Critical | FR-1 | Empty bundle vacuous pass |
| RT1-02 | Critical | FR-2 | Duplicate-evidence inflation |
| RT1-03 | Critical | FR-2 | Contradiction laundering via `direction: context` |
| RT1-04 | Critical | FR-2 | Draft-status inversion; kill chain with RT1-02/06/13 |
| RT1-05 | Critical | FR-3 | `ReliabilityTable.from_dict` unbounded |
| RT1-06 | High | FR-2 | Zero-weight items mint independence/corroboration |
| RT1-07 | High | FR-3 | Reliability coattail farming / framing |
| RT1-08 | High | FR-8 ⚠️ | One cycle disables all propagation; owner classifies |
| RT1-09 | High | FR-8 ⚠️ | Policy verdicts blind to failure modes; owner classifies |
| RT1-10 | High | FR-8 ⚠️ | Freshness gameable four ways |
| RT1-11 | High | FR-8 ⚠️ | Presence booleans for falsifiability/boundary |
| RT1-12 | High | FR-1 | Duplicate ids crash assess; CRITICAL challenge unreachable |
| RT1-13 | High | FR-2 | Model-only gate defeated by one relabel |
| RT1-14 | Medium | FR-2 | Same-origin string variants; variant of Spec 002 FR-6, policy side |
| RT1-15 | Medium | FR-8 ⚠️ | Compound/vague recall holes (evasion) |
| RT1-16 | Medium | FR-8 ⚠️ | Negation detector: paraphrase evades, subjects false-fire |
| RT1-17 | Medium | FR-8 ⚠️ | Absolute gate suppressed by any boundary string |
| RT1-18 | Medium | FR-8 ⚠️ | Review queue blind beyond score deltas |
| RT1-19 | Medium | FR-8 ⚠️ | Review-queue top-k flooding |
| RT1-20 | Medium | FR-8 ⚠️ | Scoring ignores uncertainty/severity/status/conflicts |
| RT1-21 | Medium | FR-2 | Cross-claim evidence double-counting; sharper than Spec 002 FR-6.2 |
| RT1-22 | Medium | FR-8 ⚠️ | Dependency laundering by omission — design limitation, no in-engine fix claimed |
| RT1-23 | Medium | FR-2 | Empty `ref` earns full weight; variant of Spec 002 FR-3 |
| RT1-24 | Low | FR-8 ⚠️ | Threshold rounding widens pass band; document the boundary |
| RT1-25 | Low | FR-8 ⚠️ | Contested-gate asymmetry in standalone policy |
| RT1-26 | Low | FR-8 ⚠️ | Atomic false-fires; may fold into Spec 002 FR-5.5 |

### RT2 — engine trust surfaces (24)

| ID | Sev | Primary FR | Note |
|---|---|---|---|
| RT2-C1 | Critical | FR-3 | NaN reliability table → perfect score + non-standard JSON (same root as RT1-05) |
| RT2-H1 | High | FR-1 | `aee gate` trusts fabricated `outcome` |
| RT2-H2 | High | FR-4 | Ledger tail truncation undetectable |
| RT2-H3 | High | FR-4 | Tip-cache same-size/same-mtime forgery |
| RT2-H4 | High | FR-5 | CLI path collisions destroy input/ledger; symlink targets truncated |
| RT2-H5 | High | FR-2 | String list fields explode to characters, award full credit; variant of Spec 002 FR-1 |
| RT2-M1 | Medium | FR-4 | Whole-chain rehash verifies; verify validates no version/timestamp/shape |
| RT2-M2 | Medium | FR-4 | Unicode separators: writer corrupts its own ledger permanently |
| RT2-M3 | Medium | FR-5 | Ledger appended before assessment written; non-atomic writes |
| RT2-M4 | Medium | FR-1 | Duplicate ids unreachable challenge (engine) + silent session discard |
| RT2-M5 | Medium | FR-4 | `verify()` crashes on non-object lines; `entries()` disagrees |
| RT2-M6 | Medium | FR-5 | Recursion/Overflow tracebacks at exit 1; variant of Spec 002 FR-1.6 |
| RT2-M7 | Medium | FR-5 | Duplicate JSON keys last-wins everywhere |
| RT2-M8 | Medium | FR-5 | UTF-8 BOM silently deletes first Markdown claim |
| RT2-M9 | Medium | FR-5 | Engine emits assessments its own schema rejects (`abstain`, `ref:""`, `verdicts`) |
| RT2-M10 | Medium | FR-5 | Coercion residuals: `null`→`"None"`, bool/string numbers, typed-field crash; variant of Spec 002 FR-1 |
| RT2-M11 | Medium | FR-5 | Engine emits bare `NaN`/`Infinity` in assessments and ledger lines (ledger aspect under FR-4.4/FR-5.5) |
| RT2-M12 | Medium | FR-5 | `created_at` in ledgered digest; no `--as-of`; hashes not a function of input |
| RT2-L1 | Low | FR-4 | No append idempotency; duplicate assessments chain silently |
| RT2-L2 | Low | FR-5 | Claim-id identity inconsistent across loaders |
| RT2-L3 | Low | FR-5 | No path confinement/warning for CLI outputs |
| RT2-L4 | Low | FR-5 | No input-bundle schema exists; variant of Spec 002 FR-1 |
| RT2-L5 | Low | FR-5 | Malformed rows: opaque errors, no position; variant of Spec 002 FR-1 |
| RT2-L6 | Low | FR-5 | `content_hash` republished unverified; variant of Spec 002 FR-3 |

### RT4 — evaluator + benchmark (20)

| ID | Sev | Primary FR | Note |
|---|---|---|---|
| RT4-C1 | Critical | FR-6 | Pass-on-empty in all three composers and by command design |
| RT4-C2 | Critical | FR-6 | Python composer never schema-validates in the shipped path |
| RT4-C3 | Critical | FR-6 | Composed output violates its own schema (real engine path) |
| RT4-C4 | Critical | FR-6 | Bash composer zero validation; unknown outcomes → PASS |
| RT4-H1 | High | FR-6 | Phase from filename, never from payload |
| RT4-H2 | High | FR-6 | Duplicate-evaluator counting games `majority` |
| RT4-H3 | High | FR-6 | `majority`/`optimistic` compose BLOCK→PASS; compose exit always 0 |
| RT4-H4 | High | FR-7 | Benchmark event streams unauthenticated; forged grade inflates headline |
| RT4-H5 | High | FR-7 | Benchmark pins obsolete stack (engine 1.0.2); T810 guard validates wrong stack |
| RT4-H6 | High | FR-7 | Benchmark grounding covers only `observed`; other kinds keep forged quality |
| RT4-H7 | High | FR-6 | Schema-adjacent payloads crash composer with tracebacks |
| RT4-M1 | Medium | FR-6 | `examples/demo.py` broken (`composed_outcome` KeyError); no CI runs it |
| RT4-M2 | Medium | FR-7 | `verify_freeze` addition-blind and self-signed |
| RT4-M3 | Medium | FR-7 | SWE-bench `resolved` loosely bound to grader run |
| RT4-M4 | Medium | FR-6 | Three composers diverge semantically |
| RT4-M5 | Medium | FR-6 | Command↔script drift: priority ordering, report/route executability |
| RT4-M6 | Medium | FR-6 | Engine adapter validator is a schema-invalid-accepting subset; hard-coded version |
| RT4-M7 | Medium | FR-7 | Host-setup stale-run archiving silently resets the denominator |
| RT4-L1 | Low | FR-6 | `_merge_model_routing` merges inconsistently (advisory only) |
| RT4-L2 | Low | FR-6 | Evaluator dependency of spec-kit-aee unenforceable/unchecked; cross-ref RT3-04 |

## 10. RT3 — cross-reference only (extension; implemented separately)

RT3 red-teamed `spec-kit-aee` (20 findings: 6 High, 7 Medium, 7 Low; verdict: yes, the extension needs updating) and produced its own implementation plan (Phases A–F in `~/workspace/aee-redteam/rt3/FINDINGS.md`). That work is being implemented separately and is **not** duplicated as tasks here. This spec only records the interfaces where Spec 003 and the RT3 work touch:

| RT3 ID(s) | Subject | Interface with this spec |
|---|---|---|
| RT3-01, RT3-02, RT3-07, RT3-21 | Runner error/output contract (tracebacks at exit 1, phantom paths, gaps stdout) | Same exit-code contract as FR-1.4/FR-5.3 — engine and runner must agree that input errors are exit 2 and scored verdicts are exit 1 |
| RT3-03 | No engine version enforcement in the runner | Consumes FR-6.7/Spec 002 FR-4 version stamps; the runner's floor check (`>=1.4.0,<2`) is extension-side |
| RT3-04 | Evaluator is a phantom required dependency | Same contract question as FR-6 / RT4-L2; the decision (downgrade to optional vs. presence-check) is taken once, in the extension work, and FR-6.1's fail-closed compose assumes it |
| RT3-05 | `gaps` symlinked evidence escapes project root | Engine-side companion (`GapEngine` follow-symlinks discipline) may be filed against FR-5.1 during implementation; runner-side fix is extension work |
| RT3-06, RT3-10 | Token-economy secret guard and router confinement | Extension-only; no engine interface |
| RT3-08 | Second-resolution filename collisions (ledger attests overwritten files) | Same artifact-identity concern as FR-5.2/FR-5.8; filename uniqueness is extension-side |
| RT3-09, RT3-11 | Token-economy `shell` confinement; no subprocess timeouts | Extension-only |
| RT3-12, RT3-13, RT3-14, RT3-16, RT3-19, RT3-20 | Command templates, hooks, docs/install drift, check_install, config template, version bounds | Extension-only; FR-6.9's command-drift items are evaluator-repo documents, not these |
| RT3-15 | Runner delegates numeric validation, mints phantom paths | Pairs with RT3-02; engine ranges are enforced engine-side per FR-5 |
| RT3-17, RT3-18 | `_safe_output` unresolved path; `route` whole-file read | Extension-only |

## 11. Claims and assessment record

Claims were authored before plan and tasks, per this repo's flow: `claims.json` (29 claims, RT-003-01…RT-003-29). The twenty problem claims (RT-003-01…RT-003-20) are observations verified by the red team's executable probes on 2026-10-12 and marked `supported`; the nine outcome claims (RT-003-21…RT-003-29) are requirements/predictions for unbuilt work and marked `draft`. RT-003-29 is a `decision`-kind claim recording that the FR-8 items are **not** authorised by this draft — it is marked `draft` like the other outcome claims, because the decision itself is the owner's to make.

Assessment (`assessment.json` in this directory is the authoritative record): produced by the real assessor — engine 1.4.0 from repo source, `PYTHONPATH=src python3 -m aee assess --input specs/003-aee-red-team-remediation/claims.json --project applied-epistemic-engineering --phase after_specify --threshold 0.70`. (Spec 002's assessment was produced with the then-installed engine 1.0.4 CLI; the command surface is unchanged in 1.4.0 — same subcommand and flags — so no flag adaptation was needed, only the engine version differs, and `metadata` in the output records the run.) The run's outcome is **ITERATE** — the expected, correct state for an after_specify draft of unbuilt remediation work: the twenty problem claims scored **1.0** (all above the 0.70 threshold; the defects are real and probe-evidenced), the nine outcome claims scored **0.481** (all below threshold; they rest on this spec's assertion alone, which is precisely what the threshold exists to say), and 117 failure modes were raised, dominated by the engine's standing heuristic challenges against new prose. No statuses were inflated to chase a PASS.

## 12. Owner decisions recorded / required

- **OD-1 (FR-8, blocking only FR-8):** admit, defer, reject, or fold into Spec 002 FR-5 each of RT1-08, RT1-09, RT1-10, RT1-11, RT1-15, RT1-16, RT1-17, RT1-18, RT1-19, RT1-20, RT1-22, RT1-24, RT1-25, RT1-26. Spec 002 §10 excluded scoring-weight changes; this spec does not override that.
- **OD-2 (FR-1.1):** empty bundle as input error (exit 2) vs. non-pass outcome — either satisfies the claim; the choice sets the CLI contract.
- **OD-3 (FR-4.1):** head-anchor design (sidecar head file vs. external anchor, including whether to pull Spec 002 FR-8b Axiomere anchoring forward for the tip).
- **OD-4 (FR-6.9 / RT3-04):** evaluator layer decision shared with the extension work — required-and-checked vs. optional-and-honest.

## 13. Out of scope

- Implementation of anything in this spec (draft only; implementation is future, separately-approved work).
- Extension (spec-kit-aee) fixes: RT3's 20 findings are implemented separately (§10 cross-references only).
- Any scoring-weight or outcome-threshold change not admitted by the owner under OD-1.
- Publishing or releasing anything: version bumps, catalog submissions, and implementation PRs are separate owner-gated steps.
- Spec 002's own FR-1..FR-8 work: this spec sharpens and extends it; it does not re-plan it. Where both specs touch a surface (strict loading, verify-evidence, ledger defaults), Spec 002 lands first and Spec 003 builds on its result.
