# Feature Specification: Baseline — Current State of the AEE Engine (v1.4.0)

**Feature Branch**: `chore/speckit-onboarding`

**Created**: 2026-10-08

**Status**: Baseline (complete — describes shipped behavior, not new work)

**Input**: The repo's own materials at v1.4.0 (commit `31f39af` on `main`):
README.md, `docs/` (concepts, scoring, ledger, security, spec-kit,
quickstart, api, porting-from-epistemic-ledger), CHANGELOG.md through
1.4.0, `pyproject.toml`, and the test suite in `tests/`. This spec records
the current state so future specs diff against a grounded baseline.
No scope is invented here: every requirement below names the shipped
module, CLI subcommand, or doc that already implements it.

## Purpose

Applied Epistemic Engineering (AEE) is an evidence-centered Python toolkit
for turning important claims into inspectable engineering artifacts
(README.md). It makes boundaries, evidence, provenance, uncertainty,
contradictions, falsification tests, recovery work, and decision history
explicit. This baseline captures what the engine at **1.4.0** actually
does — the claim/evidence model, deterministic stress-testing and scoring,
the tamper-evident ledger, the three mechanisms ported from the
epistemic-ledger program (policy gates, per-source reliability,
materiality review queue), the gap register, and the CLI / Evaluator
Contract surface — so that a future change can be assessed as a diff
against recorded, falsifiable claims rather than against memory.

Out of scope for this baseline (by the project's own docs): LLM
extraction and stance classification, bitemporal event sourcing, and
the ledger program's newsroom simulator and corpora — all deliberately
not transferred (`docs/porting-from-epistemic-ledger.md`). Spec Kit
artifact discovery / command UX (owned by `spec-kit-aee`) and the shared
evaluator envelope / composition / routing (owned by
`spec-kit-evaluator`) are also out of scope here; this repo owns only
the domain engine (`docs/spec-kit.md`).

## User Scenarios & Testing

### User Story 1 - Assess a bounded claim set and get a transparent verdict (Priority: P1)

A developer or reviewer has a set of consequential claims (from a spec,
a plan, or a JSON file) and wants to know — deterministically — which
claims are supported, which are weak, contradicted, or unsupported, and
what bounded work would improve the decision, without a model in the loop.

**Why this priority**: This is the core loop of the library
(`docs/concepts.md`: Frame → Disassemble → Stress-test → Reconstruct)
and the first example in README.md and `docs/quickstart.md`.

**Independent Test**: Run `aee demo` (self-contained) or
`aee assess --input claims.json --phase after_plan` on the quickstart
claims file; the output assessment names each claim's score, band,
failures, and recovery proposals, and `PYTHONPATH=src python -m pytest -q`
passes (118 tests at baseline, verified 2026-10-08).

**Acceptance Scenarios**:

1. **Given** a claims JSON file with bounded, falsifiable claims and
   observed test evidence, **When** `aee assess` runs, **Then** the
   assessment reports an outcome, per-claim direct and propagated
   scores, and preserves the rich model in the evaluator result's
   `state.aee` field.
2. **Given** a claim with no supporting evidence, **When** assessed
   without a policy, **Then** it remains explicitly unsupported; **When**
   assessed with `AssessmentPolicy()` attached, **Then** it receives an
   ABSTAIN verdict and the assessment outcome is `abstain`, not `pass`.
3. **Given** malformed input, an invalid enum, or an unsupported phase,
   **When** any CLI subcommand runs, **Then** it exits `2` with a clean
   message and no traceback (CHANGELOG 1.0.3 CLI error contract).

---

### User Story 2 - Challenge claims and receive bounded recovery work (Priority: P1)

A reviewer wants only the failure modes — ambiguity, hidden assumptions,
counterexamples, contradictions, missing evidence, circular inference,
unfalsifiable claims — plus the bounded recovery proposal for each, with
no scoring internals leaking into the projection.

**Why this priority**: `challenge` is the adversarial half of the
Frame/Stress-test loop and a distinct CLI surface since 1.0.2.

**Independent Test**: `aee challenge --input claims.json --phase
after_plan` emits failures + recoveries only; `tests/test_challenge.py`
pins that no scoring keys leak into the projection.

**Acceptance Scenarios**:

1. **Given** a claim set containing an unfalsifiable claim, **When**
   `aee challenge` runs, **Then** that claim appears with a failure mode
   and a bounded recovery proposal carrying a verification condition.
2. **Given** two claims whose dependency graph contains a cycle, **When**
   assessed, **Then** propagation is recorded as skipped on the affected
   scores instead of silently leaving them uncapped (CHANGELOG 1.0.3),
   and `ClaimGraph.cycles()` does not raise `RecursionError` on deep
   (>1,000-claim) chains.

---

### User Story 3 - Keep a tamper-evident decision history (Priority: P2)

A team records assessment decisions in the SHA-256 hash-chained JSONL
ledger and later verifies the chain, understanding exactly what
verification does and does not prove.

**Why this priority**: The ledger is one of the seven README core
artifacts, and its limits are a constitutional principle (VII).

**Independent Test**: `aee verify-ledger --ledger
.aee/epistemic-ledger.jsonl` verifies every link; `tests/test_ledger.py`
covers append locking, corruption reporting, and the O(1)-append
verified-tip cache (CHANGELOG 1.0.4).

**Acceptance Scenarios**:

1. **Given** a ledger whose middle entry was edited, **When** verified,
   **Then** verification fails and `entries()` reports corruption as a
   `ValueError` naming the line.
2. **Given** a valid ledger, **When** verified, **Then** the result
   claims tamper evidence only — never truth, authorship, or trusted
   time (`docs/ledger.md`).

---

### User Story 4 - Apply measured policy, reliability, and review mechanisms (Priority: P2)

An adopter who wants the epistemic-ledger program's measured production
rules enables them explicitly: policy gates on assessment, measured
per-source reliability blended into scoring, and a materiality-filtered
review queue diffing two assessments.

**Why this priority**: These are the 1.1.0–1.4.0 additions and the
current version's headline surface; they are opt-in and must not change
default behavior.

**Independent Test**: `aee assess --policy --reliability table.json`,
`aee review --previous A.json --current B.json`;
`tests/test_policy.py`, `tests/test_reliability.py`,
`tests/test_review.py`, and `tests/test_cli_policy.py` pass at baseline.

**Acceptance Scenarios**:

1. **Given** no policy and no reliability table, **When** assessed,
   **Then** scoring is bit-identical to the pre-1.1.0 behavior and
   `Assessment.to_dict()` still includes a `verdicts` object (empty).
2. **Given** a claim supported by a single independent source, **When**
   a policy is attached, **Then** the corroboration gate verdicts it
   CHALLENGE; a contradiction penalty ≥ 0.25 also caps it at CHALLENGE.
3. **Given** two assessments of the same claim set, **When**
   `build_review_queue` runs with the default 0.05 materiality, **Then**
   only claims whose propagated score moved ≥ 0.05 (largest first),
   verdict flips, and added/removed ids appear in the queue.

---

### User Story 5 - Maintain a gap register from a verification matrix (Priority: P3)

A project cross-references its verification matrix against test evidence
and maintains a `GAPS.md` register whose closed gaps survive regeneration.

**Independent Test**: `aee gaps --matrix specs/verification-matrix.md
--evidence evidence/ --output GAPS.md`; `tests/test_gaps.py` passes.

**Acceptance Scenarios**:

1. **Given** a matrix row is inserted or reordered, **When** the register
   regenerates with `--existing`, **Then** a preserved closure stays on
   the same test — preservation is keyed on the stable `test_id`, not
   the positional `GAP-XXX` id (CHANGELOG 1.0.3).
2. **Given** `--close` with a nonexistent gap id, **When** `aee gaps`
   runs, **Then** it errors with exit `2`; `close_gap` raises `KeyError`.

### Edge Cases

- A JSON object without a `claims` key is refused by `load_claims`
  instead of silently producing a vacuous assessment (1.0.4).
- Markdown `depends_on` refs are uppercased to match uppercased claim
  IDs; a lowercase ref previously never resolved (1.0.4).
- Mermaid claim-graph node IDs are injective (`A-B` vs `A_B` do not
  merge) and labels escape quotes / flatten newlines (1.0.4).
- Corrupt evidence JSON produces a stderr warning, not silent
  "no evidence" (1.0.3).
- Unparseable `observed_at` values are noted on the score instead of
  silently skipped; freshness can be pinned with `as_of` for replay
  (1.0.3).
- The `abstain` outcome maps to soft exit code `1`, not the hard-block
  code `2` (1.4.0 fix).

## Requirements

### Functional Requirements

- **FR-001**: The engine MUST represent claims with proposition, kind,
  status, explicit boundary, dependencies, conflicts, falsification
  tests, uncertainty, and source ref, separate from their evidence
  (`src/aee/model.py`; `docs/concepts.md`).
- **FR-002**: The engine MUST distinguish observed, inferred, and
  asserted evidence, and supporting from contradicting evidence, with
  source quality and a stable `source_id` per source
  (`src/aee/model.py`).
- **FR-003**: Scoring MUST follow the published transparent formula and
  weakest-link propagation, and MUST be replayable via a pinned `as_of`
  (`src/aee/scoring.py`; `docs/scoring.md`).
- **FR-004**: Stress-testing MUST seek ambiguity, hidden assumptions,
  counterexamples, contradictions, missing evidence, circular
  inference, and unfalsifiable claims, and every failure MUST carry a
  bounded recovery proposal with a verification condition
  (`src/aee/challenge.py`, `src/aee/recovery.py`).
- **FR-005**: The dependency graph MUST detect cycles iteratively and
  record skipped propagation on cyclic claims (`src/aee/graph.py`).
- **FR-006**: The ledger MUST write canonical JSONL hash-chained entries,
  verify the complete chain, lock appends against concurrent forks, and
  claim tamper evidence only (`src/aee/ledger.py`; `docs/ledger.md`).
- **FR-007**: Extraction MUST only promote stably identified claims from
  JSON or Markdown; unidentified prose MUST NOT become a claim, and a
  JSON object without a `claims` key MUST be refused
  (`src/aee/extract.py`).
- **FR-008**: Policy gates, when attached, MUST verdict each claim
  ACCEPT / CHALLENGE / ABSTAIN with reasons, layer above scores without
  mutating them, and MUST leave behavior unchanged when not attached
  (`src/aee/policy.py`).
- **FR-009**: Reliability, when a table is supplied, MUST blend a
  supporting source's static weight toward its measured `1 − Brier`
  reliability only at or above `min_observations` (default 3), MUST
  keep contradicting evidence at its static weight, and MUST note every
  substitution on the claim score (`src/aee/reliability.py`).
- **FR-010**: The review queue MUST diff two assessments by materiality
  (default 0.05), largest move first, with an optional top-k limit, plus
  verdict flips and added/removed claim ids (`src/aee/review.py`).
- **FR-011**: The gap engine MUST generate and update a gap register
  keyed on stable `test_id`, preserve documented `in_progress` /
  `blocked` / closed states across regeneration, and error on closing
  a nonexistent gap (`src/aee/gaps.py`).
- **FR-012**: The CLI MUST expose `assess`, `challenge`,
  `verify-ledger`, `gate`, `graph`, `gaps`, `review`, and `demo`, with
  exit codes `0` = pass/warn, `1` = iterate / clarify / gather evidence
  / abstain, `2` = hard block / invalid ledger / usage error
  (`src/aee/cli.py`; README.md).
- **FR-013**: Assessments MUST convert to the Spec Kit Evaluator
  Contract via `EvaluatorAdapter`, preserving rich AEE data in the
  opaque `state.aee` field (`src/aee/adapters/evaluator.py`;
  `docs/spec-kit.md`).
- **FR-014**: The core package MUST remain runtime-dependency-free and
  offline, reading only caller-provided files and writing only to
  explicitly configured outputs (`pyproject.toml`; `docs/security.md`).

### Key Entities

- **Claim** (`aee.model.Claim`): an atomic, bounded proposition with
  kind, status, boundary, dependencies, conflicts, falsification tests,
  uncertainty, and source ref.
- **Evidence** (`aee.model.Evidence`): a ref typed by kind
  (observed / inferred / asserted), direction (supports / contradicts),
  source quality, and `source_id`.
- **Assessment** (`aee.engine.Assessment`): the result of an engine run —
  outcome, summary, per-claim scores, failures, and, when a policy is
  attached, per-claim verdicts.
- **ClaimScore** (`aee.scoring.ClaimScore`): direct and propagated
  scores, band, and components (evidence, independence, falsifiability,
  boundary, penalties), with notes for reliability substitutions and
  skipped propagation.
- **ReliabilityTable** (`aee.reliability.ReliabilityTable`): per-source
  resolved-outcome records deriving measured reliability as `1 − Brier`.
- **ReviewQueue** (`aee.review.ReviewQueue`): the materiality-filtered
  diff of two assessments.
- **HashChainLedger** (`aee.ledger.HashChainLedger`): the append-only,
  hash-chained JSONL decision history.
- **GapRegister** (`aee.gaps.GapRegister`): verification-matrix gaps
  keyed by stable test id.

## AEE Claims

The full machine-readable set is in `claims.json` alongside this spec
(schema following `.specify/extensions/aee/templates/aee-claims.json`).
Summary — each claim carries its falsifier in that file:

- **C-001** — The engine assesses bounded, evidence-linked claims
  deterministically and preserves the rich model through the Evaluator
  adapter. *Falsifier:* identical pinned input scoring differently, or
  rich claim data lost in the evaluator result.
- **C-002** — Scoring is transparent and weakest-link: no dependent claim
  outscores its weakest required premise. *Falsifier:* a propagated
  score above any required dependency's propagated score.
- **C-003** — The ledger is tamper-evident only. *Falsifier:* ledger
  verification presented as proof of truth, authorship, or time, or a
  mid-chain edit that still verifies.
- **C-004** — The ported mechanisms (policy, reliability, review) are
  opt-in and leave default behavior bit-identical. *Falsifier:* an
  assessment without policy/table differing from pre-1.1.0 scoring.
- **C-005** — The CLI is a CI contract: the eight subcommands above with
  the 0 / 1 / 2 exit-code semantics. *Falsifier:* a subcommand missing,
  or a usage error exiting `1` / with a traceback.
- **C-006** — The core is deterministic, offline, and runtime
  dependency-free; assertions are never recorded as observations.
  *Falsifier:* a runtime dependency or network call in `src/aee/`, or
  model output recorded as `observed` without an inspectable source.

## Success Criteria

### Measurable Outcomes

- **SC-001**: At baseline, `PYTHONPATH=src python -m pytest -q` passes
  with **118 tests, 0 failures** (verified 2026-10-08 on this checkout).
- **SC-002**: `aee --version` reports the single-sourced package version
  **1.4.0**, matching `pyproject.toml` and `src/aee/__init__.py`.
- **SC-003**: `aee demo` completes with outcome `pass` on its
  self-contained claim (verified 2026-10-08).
- **SC-004**: Every FR above traces to a named shipped module and at
  least one test file in `tests/` (12 test modules at baseline).
- **SC-005**: Spec Kit onboarding is present and verifiable on disk:
  `.specify/memory/constitution.md` (project-specific, v1.0.0),
  `.specify/extensions/aee` (v1.2.0) and
  `.specify/extensions/evaluator` (v1.0.0) with
  `.specify/extensions.yml` listing both.

## Assumptions

- This is a baseline / current-state spec: requirements describe shipped
  v1.4.0 behavior, so "implementation" tasks in `tasks.md` are
  verification and onboarding tasks, not feature work.
- The repo's flow is branch + PR on GitHub (`electrohire/
  applied-epistemic-engineering`); this onboarding lands on a dedicated
  branch and is not merged by the onboarding pass.
- Python ≥ 3.11 is the supported runtime (`pyproject.toml`); the
  baseline verification ran on Python 3.12 with `PYTHONPATH=src`
  because the package is not installed into the system interpreter on
  this machine.
