# Feature Specification: AEE Trust Hardening

**Feature Branch**: `spec/002-aee-trust-hardening`

**Created**: 2026-10-12

**Status**: Draft — claims assessed (after_specify, outcome **iterate**; see §9). No implementation in this spec.

**Input**: A week of production use of spec-kit + AEE across the Tekmerion/Axiomere build (2026-10-11/12), in which the stack was run hard across three repositories and its own failure modes were observed directly: a claims bundle the engine silently emptied, a founding claims file the engine could not load at all, an irreducibility challenge that fired on 28 of 28 claims, and shipped-vs-unbuilt capability made numeric by the scoring engine. Each finding below was then verified against the current code in this repo (and in `electrohire/spec-kit-aee` and `electrohire/spec-kit-evaluator`) before being specced; where the code contradicted the finding as first framed, the correction is recorded in the finding's evidence note and in the claims bundle.

## Purpose

AEE's value proposition is that claims should fail loudly, evidence should be inspectable, and records should be tamper-evident. The engine's seams — where a human hands it input and trusts its output — do not yet fully meet that standard. This spec hardens those seams across the three ElectroHire repos that make up the stack: the engine (`applied-epistemic-engineering`), the lifecycle adapter (`spec-kit-aee`), and the evaluator contract (`spec-kit-evaluator`). It defines eight work packages, one per finding. Every requirement group carries acceptance criteria and at least one claim in `claims.json`; the program's own discipline (claims first, assessment on record) applies to the program itself.

## FR-1 — Strict, loud validation (engine)

**Current state (verified).** `Claim.from_dict`, `Evidence.from_dict`, and `FailureMode.from_dict` (`src/aee/model.py`) read every field with a silent default and ignore unknown keys entirely; only an empty claim `id` raises. A bundle writing `statement` for `text` loads with empty text and is assessed as "no inspectable proposition" instead of failing at load. Enum failures raise Python's bare `ValueError` (`'design' is not a valid ClaimKind`) with no list of valid values. The single loud failure today is container-level: a JSON object without a `claims` key is refused (`src/aee/extract.py`). There is no `validate` or `migrate` subcommand (`src/aee/cli.py`).

**Requirements.**
- FR-1.1 Strict loading is the default for `assess` (and any other bundle-consuming command): unknown fields are errors; a missing-or-empty `text` is an error; every error names the claim id, the field, and the problem. Near-miss field names produce a did-you-mean suggestion (edit-distance over the known field set).
- FR-1.2 Enum errors list the full valid value set for that enum in the message.
- FR-1.3 A non-strict compatibility mode may exist only as an explicitly named flag (e.g. `--lenient`) whose use is echoed into the assessment metadata; silence is never the compatibility strategy.
- FR-1.4 `aee validate <bundle>` runs strict loading plus structural checks without assessing; exit codes follow the CLI contract (0 valid, 2 invalid) so CI can gate on it.
- FR-1.5 `aee migrate <bundle>` converts pre-engine legacy bundles (free-vocabulary kinds/statuses such as `design`/`asserted-design`, `statement`/`falsifier` field names) into the current format, printing every mapping it applied and refusing — loudly — any value it cannot map.
- FR-1.6 The assess command's input errors never surface as tracebacks; they use the existing clean-error path in `cli.main`.

**Acceptance.** Regression fixtures committed under `tests/fixtures/`: (a) the renamed-field bundle (`statement` for `text`) fails strict load naming the field, and migrates cleanly; (b) a bad-enum bundle fails with the valid-values list in the message; (c) the legacy Tekmerion Spec 001 founding bundle loads only via `aee migrate`, and the migrated output assesses. The benchmark guard is FR-1.7 / claim TH-002-21 (tasks T810).

## FR-2 — Claims drafting (extension + engine)

**Current state (verified).** The extension's nine commands contain no drafting capability; `templates/aee-claims.json` is a static file. The engine's Markdown extraction (`extract_markdown_claims`) surfaces only claims an author already marked with claim ids. In the Tekmerion/Axiomere catch-up, 28 claims were hand-written in one evening; that authoring tax is the stack's adoption bottleneck.

**Requirements.**
- FR-2.1 A new extension command `speckit.aee.draft-claims` proposes atomic claims from a spec's requirements (FRs, user stories, acceptance criteria), emitting a bundle in engine format.
- FR-2.2 Every drafted claim is born `status: draft` with `source_quality` of its evidence no higher than `model`/`asserted`; the tool contains no code path that ratifies, supports, or upgrades a claim. Ratification is a recorded human edit.
- FR-2.3 Drafts carry the source requirement reference in `source_ref` and a proposed falsification test per claim (marked as proposed); a draft with no falsifier is emitted only with an explicit `TODO` marker the strict loader will reject until a human completes it — drafts cannot sneak past FR-1.
- FR-2.4 Engine support is limited to what the command needs (e.g. a drafting helper in `extract.py` reusing `derived_claim_id`); the engine gains no opinion about ratification.

**Acceptance.** On a fixture spec with known requirements, the command emits one draft per requirement, all `status: draft`; strict `aee validate` passes on completed drafts and rejects a draft whose falsifier is still a TODO; an assessment of unedited drafts scores them as drafts (no outcome above `gather_evidence`/`iterate` attributable to the tool).

## FR-3 — Verifiable evidence (engine)

**Current state (verified).** Nothing resolves an evidence `ref`; `content_hash` is declared and serialized but never consumed outside `model.py` and the JSON schema; scoring weights evidence by the author-declared `source_quality` verbatim (`src/aee/scoring.py` `_SOURCE_WEIGHTS`).

**Requirements.**
- FR-3.1 `aee verify-evidence <bundle>` resolves each evidence ref: local refs must exist as files (resolved inside the project root, with the path-safety rules the extension already uses); URL refs are reported as unresolvable-offline rather than fetched silently.
- FR-3.2 Where `content_hash` is present, it is recomputed and mismatches are reported; where `observed_at` is present it must parse (unparseable dates are already noted by scoring's freshness path — verify-evidence surfaces them as findings, not notes).
- FR-3.3 The report derives a corroborated quality from ref type by deterministic rules (e.g. a path under `tests/` corroborates `test`; a path to a design record corroborates `primary`/`artifact`) and reports declared-vs-derived mismatches as challenges.
- FR-3.4 An undeclared `source_quality` stays `unknown`. Derivation may corroborate or challenge a declaration; it never silently upgrades an absent one.
- FR-3.5 `assess --verify-evidence` runs the same checks inline and folds mismatches into the assessment as failure modes.

**Acceptance.** Fixture bundle with (a) a dangling ref, (b) a corrupted `content_hash`, (c) a `tests/` ref declared as `tertiary`: verify-evidence reports all three; a clean fixture passes; an evidence item with no declared quality remains `unknown` in all outputs.

## FR-4 — Version coherence (engine + extension)

**Current state (verified).** `Assessment.metadata` is assembled as `{threshold, input}` (`src/aee/cli.py`, `src/aee/engine.py`); `methodology_version` is a constant `"1.0"` dataclass default unrelated to the package `__version__` (1.4.0). The extension pins an engine floor (`>=1.4.0,<2` in `extension.yml`) but passes no version information to the engine. Installed engines already diverge in the field (1.0.2 in one venv, 1.0.4-era and 1.4.0 elsewhere), and the upstream catalog entry (1.0.1) lags the released extension (1.2.0).

**Requirements.**
- FR-4.1 Every assessment stamps `metadata.engine_version` (the producing package's `__version__`) and keeps `methodology_version` as a distinct, separately-versioned field.
- FR-4.2 The extension runner passes its own version through, recorded as `metadata.extension_version`; assessments produced outside the extension omit the key rather than fabricating it.
- FR-4.3 A documented version policy (in this repo's README/docs): engine versioning is the source of truth; the extension's `requires` floor is the compatibility contract; the catalog entry is updated in the same release PR as the extension version bump.
- FR-4.4 `aee --version` output and the stamped metadata are the same string from the same source (`aee.__version__`); a test asserts they cannot drift.

**Acceptance.** Assessments from both the bare CLI and the extension runner carry the required stamps; a test fails if `__version__` and the stamp diverge; the policy doc exists and names the catalog-update step.

## FR-5 — Challenge dispositions (engine + extension format)

**Current state (verified).** The irreducibility challenge is `_COMPOUND = [,;]|\b(and|or|while|unless|except)\b` (`src/aee/challenge.py`) — it fires on any comma in claim text, i.e. on essentially every prose claim (28/28 in the Tekmerion/Axiomere catch-up). `FailureMode.resolved` exists as output state, but failures are regenerated deterministically by the stress tester on every run; there is no disposition record type (kind, author, date, reason) in the bundle format, so a human judgment cannot persist or be audited.

**Requirements.**
- FR-5.1 The bundle format gains a `dispositions` record per claim: `{challenge_category, kind: split|accepted-atomic|waived, reason, author, date}`. A disposition without a non-empty reason is invalid under strict loading (FR-1).
- FR-5.2 On assessment, a regenerated challenge matching a stored disposition is reported as resolved, with the disposition's reason inspectable in the assessment output; the underlying claim text still shows the challenge was raised (history is not erased, it is answered).
- FR-5.3 A `split` disposition must name the resulting claim ids; the assessment warns if a named successor does not exist in the bundle.
- FR-5.4 Assessment summaries report disposition coverage (challenges raised / dispositioned / open).
- FR-5.5 The `_COMPOUND` heuristic itself is recalibrated as part of this package: a claim whose only "compound" signal is punctuation, with a single falsification test and a single proposition structure, should not draw a MEDIUM challenge. (The disposition system is the durable fix; recalibration reduces noise at the source. Both are specced; neither substitutes for the other.)

**Acceptance.** A claim dispositioned `accepted-atomic` with a reason re-assesses with that challenge resolved and the reason visible; the same claim with an empty reason fails strict load; deleting the disposition restores the open challenge; coverage numbers appear in the summary.

## FR-6 — Dependency & independence on-ramps (engine + extension)

**Current state (verified — corrected from the finding as first framed).** Independence is **not** a flat silent 1.0 default. `src/aee/scoring.py` computes `min(1.0, |distinct source strings| / 2)` from `item.source_id or item.ref`, and emits a "Fewer than two independent supporting sources" note below two. The real gaps: (a) `Evidence.independent_of` is never read by scoring — the declared field is write-only; (b) distinct *strings* are counted, not distinct *origins* — two items tracing to one study under different refs score as fully independent; (c) no warning class exists for claims sharing the same evidence items; (d) `depends_on` is rendered by the graph command but nothing scaffolds it.

**Requirements.**
- FR-6.1 Scoring consumes `independent_of`: declared independence between evidence items is honored; absent declarations, the score notes state that independence was inferred from distinct references and may overstate it when references share an origin.
- FR-6.2 Assess emits a shared-evidence warning (failure mode, category `independence_unmodeled`) when two claims' supporting evidence overlaps by ref/source_id with no independence declarations.
- FR-6.3 Draft-claims (FR-2) scaffolds `depends_on` from spec structure where the spec states it (e.g. a requirement referencing another requirement id), as proposals under the same draft rules.
- FR-6.4 The independence component in score output names its basis (`declared`, `inferred-from-references`, or `none`) in the score notes — an assumption surfaced, not buried.

**Acceptance.** A bundle with two same-origin items under different refs and no declarations no longer reports an unqualified independence of 1.0 — it reports the inferred basis with the caveat note; adding `independent_of` declarations changes the computation observably; the shared-evidence warning fires on the overlap fixture and is silent on a disjoint fixture.

## FR-7 — Evaluator layer: one real reference evaluator (spec-kit-evaluator)

**Current state (verified).** `electrohire/spec-kit-evaluator` ships the result contract (JSON schema), four prompt commands, a composition script (`scripts/python/compose_results.py`), and a demo — but no `evaluators.yml` and no executable evaluator. The `speckit.evaluator.run` command's discovery therefore finds nothing in a stock install; the layer is a contract without a tenant. (Recorded earlier in the Glossa program's governance notes: "evaluator has no registered evaluators.")

**Requirements.**
- FR-7.1 Ship **one** deterministic reference evaluator in spec-kit-evaluator: a spec-structure evaluator that checks a feature directory for the contract's basics (spec/plan/tasks presence, claims bundle presence and strict-load validity, assessment presence) and emits a schema-valid evaluator result.
- FR-7.2 Ship the `evaluators.yml` registration for it and a fixture spec (one passing, one failing case) demonstrating discovery → run → compose end-to-end via the shipped commands/scripts.
- FR-7.3 The reference evaluator is deliberately small and deterministic (no model calls): its job is to prove the contract composes, not to judge epistemics — that remains AEE's role.
- FR-7.4 If the owner descopes FR-7.1, the fallback is documentation that states plainly the layer is contract-only and no evaluators ship — recorded as a decision, not left as an implication.

**Acceptance.** In a clean checkout, following only the repo's README: register nothing by hand, run the shipped flow against the passing fixture → schema-valid result, compose exit 0; against the failing fixture → result records the structural failures. Schema validation of the emitted result is part of the walkthrough.

## FR-8 — Ledgered assessments and Axiomere anchoring (engine + extension)

**Current state (verified — corrected from the finding as first framed).** The engine already has a working append-only SHA-256 JSONL ledger (`src/aee/ledger.py`, `HashChainLedger.append_assessment`, `aee verify-ledger`), and the extension runner already ledgers by default (`run_aee.py`: `--no-ledger` is the opt-out; default path `.specify/extensions/aee/ledger/epistemic-ledger.jsonl`). What is missing: (a) the bare engine CLI ledgers only with an explicit `--ledger` flag, so the two entry points behave differently and the difference is undocumented; (b) no Axiomere path exists anywhere (zero hits for `axiomere`/`axmr` in either repo).

**Requirements — WP-8a (consistency).**
- FR-8.1 The engine CLI adopts the same default as the runner: `assess` ledgers by default to a documented default path, with `--no-ledger` as the explicit opt-out; `--ledger <path>` continues to select a different ledger.
- FR-8.2 The documented loop (CLI help + extension assess command) is assess → verify-ledger; the runner verifies the chain after appending and reports the verification result alongside the assessment path (it already reports paths; add the verdict).
- FR-8.3 The assessment JSON file remains a working copy; the ledger entry (which already records the assessment's SHA-256) is the record of what was assessed. Docs say so.

**Requirements — WP-8b (Axiomere anchoring; separate, later, non-blocking).**
- FR-8.4 A new optional command (engine `aee anchor` or an extension script) deposits an assessment's SHA-256 as an event in an Axiomere `.axmr` ledger via the `axiomere` Python package (AXIOVEX/axiomere + axiomere-python), recording project, phase, outcome, and the ledger's own checkpoint data.
- FR-8.5 The anchor receipt (ledger path, event/snapshot identifier, resulting checkpoint root if produced) is written back into the assessment metadata as `metadata.anchor`.
- FR-8.6 WP-8b is an optional dependency: its absence degrades to a clear "anchor unavailable" message, never to an assess failure. It has its own claim (TH-002-20) and falsifier, and blocks no other work package.

**Acceptance.** WP-8a: a default CLI assess run leaves a ledger entry that `verify-ledger` validates; `--no-ledger` leaves none; CLI and runner docs describe identical semantics. WP-8b: anchoring a real assessment produces a receipt whose hash matches the assessment, verifiable in the `.axmr` ledger with the axiomere package's own `verify_file`.

## 9. Claims and assessment record

Claims were authored **before** plan and tasks, per the owner's instruction and this repo's flow: `claims.json` (21 claims, TH-002-01…TH-002-21). The eleven problem claims (TH-002-01…TH-002-11) are observations verified against the code on 2026-10-12 and marked `supported`; the ten outcome claims (TH-002-12…TH-002-21) are requirements/predictions for unbuilt work and marked `draft`.

Assessment (AEE engine 1.0.4, `aee assess --phase after_specify --threshold 0.70`, record in `assessment.json`):

- **Outcome: ITERATE** — the expected, correct state for an after_specify draft.
- Problem claims scored 0.845–0.999 (all above threshold): the defects are real and evidenced.
- Outcome claims scored 0.481 (all below threshold): they rest on this spec's assertion alone, which is precisely what the threshold exists to say.
- 48 failure modes were raised, dominated by the engine's standing heuristic challenges against new prose — including, fittingly, the irreducibility challenge that FR-5 addresses.

No statuses were inflated to chase a PASS. This spec is ready for planning (see `plan.md`); implementation is future, separately-approved work.

## 10. Out of scope

- Any change to the scoring weights or outcome thresholds themselves.
- Model-backed evaluators (FR-7's reference evaluator is deterministic by design).
- Publishing or releasing anything: version bumps, catalog submissions, and PRs for implementation are separate owner-gated steps.
- Changes to the `.axmr` format (WP-8b consumes Axiomere as-is).
