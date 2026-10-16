# Applied Epistemic Engineering Constitution

This constitution governs `electrohire/applied-epistemic-engineering` — the
evidence-centered Python toolkit that turns important claims into inspectable
engineering artifacts (README.md). It is grounded in the project's own
materials: the seven core principles in README.md, the epistemic invariants
in `docs/concepts.md`, the scoring model in `docs/scoring.md`, the ledger
limits in `docs/ledger.md`, the trust boundaries in `docs/security.md`, the
threshold-provenance rule in `docs/scoring.md`, and
the contribution rules in CONTRIBUTING.md. Where this document and those
sources disagree, the sources win until this constitution is amended.

The library does not certify truth, compliance, safety, or correctness
(`docs/index.md`). It records what is known, why it is believed, what
remains uncertain, and what evidence would change the decision.

## Core Principles

### I. Assertions Never Become Observations

A model's statement about its own work is `asserted`, not `observed`
(README principle 1; `docs/concepts.md`). No repetition, paraphrase, or
model agreement upgrades an assertion to observed evidence. Model-backed
enrichment, where a host application adds it, enters the same claim model
labeled by how it was obtained, and is classified `asserted` or `inferred`
(`docs/security.md`). The core library itself contacts no model and has
no network dependencies.

**Falsifier:** any code path, test, or document in this repo that records
model output — or a repeated assertion — with `EvidenceKind.OBSERVED`
without an independently inspectable source violates this principle.

### II. Claims Are Bounded, Atomic, and Evidence-Linked

Every consequential claim separates its proposition from its source, its
applicable boundary from universal language, observed evidence from
inference and assertion, supporting evidence from counterevidence, direct
confidence from dependency-propagated confidence, and current status from
historical ledger events (`docs/concepts.md`). The extractor only promotes
prose with stable identifiers into claims; unidentified prose is never
silently promoted (`docs/quickstart.md`). A supported claim requires
inspectable evidence, and an accepted claim needs a falsification
condition.

**Falsifier:** a claim accepted as supported with no inspectable evidence
ref, no explicit boundary, or no falsification test.

### III. Counterevidence and Contradictions Stay Visible

Counterevidence and contradictions remain visible records to resolve, not
noise to average away (README principle 2; `docs/concepts.md`). Scoring
subtracts a contradiction penalty rather than hiding disagreement, and the
ported contested gate surfaces a contradiction penalty at or above the
policy threshold as a CHALLENGE verdict instead of letting it disappear
into an averaged score (`docs/scoring.md`).

**Falsifier:** a change that drops, merges away, or silently re-weights
contradicting evidence so a contested claim reports as uncontested.

### IV. Unsupported Stays Unsupported; Confidence Propagates by the Weakest Link

Unsupported claims remain explicitly unsupported (README principle 3), and
the absence of evidence is represented as insufficient evidence, not a
fabricated answer (`docs/concepts.md`). A dependent claim cannot be more
certain than its weakest required premise:
`propagated(claim) = min(direct(claim), propagated(each required
dependency))` (README principle 4; `docs/scoring.md`). Forced abstention
applies where there is no supporting evidence, or support consisting
solely of model self-attestation: unknown means ABSTAIN, not a near-zero
score that reads downstream as measured-and-weak
(`docs/scoring.md`).

**Falsifier:** a propagated score above the propagated score of any
required dependency, or an evidence-free claim reported as measured
rather than unsupported / abstained.

### V. Deterministic Before Probabilistic; Scores Are Transparent Decision Aids

Deterministic checks run before probabilistic review (README principle
6). The Python engine performs transparent deterministic checks; any
model-backed reviewer runs after them and inside the same model
(`docs/concepts.md`). The library does not call a confidence number
"truth": every score is a transparent decision aid derived from recorded
evidence and explicit rules (README.md). The direct score formula and its
weights are published in `docs/scoring.md`
(`0.55 × evidence quality + 0.20 × source independence + 0.15 ×
falsifiability + 0.10 × explicit boundary − contradiction penalty −
freshness penalty`), and assessments are replayable — freshness is
judged against a pinnable `as_of` instant, so identical input pinned to
the same `as_of` scores identically (CHANGELOG 1.0.3).

**Falsifier:** a scoring change whose formula, weights, or inputs are not
stated in `docs/scoring.md` / code, or an assessment that gives different
results for identical input pinned to the same `as_of`.

### VI. Every Failure Produces Bounded Recovery

Every failure produces a bounded recovery proposal with a verification
condition (README principle 5). Recovery work is scoped to the failing
claim — narrow, clarify, gather evidence, resolve a contradiction, or
supersede (`docs/concepts.md`, Reconstruct stage) — never an unbounded
"try harder" instruction. The materiality review queue applies the same
boundedness between assessments: only score moves at or above the
materiality threshold, verdict flips, and added/removed claims are owed
reviewer attention (CHANGELOG 1.3.0).

**Falsifier:** a failure mode emitted with no recovery proposal, or a
recovery proposal with no verification condition that would close it.

### VII. Hash Chains Are Tamper Evidence, Not Truth

Hash chains establish tamper evidence — not truth, identity, or trusted
time (README principle 7). `HashChainLedger` detects modification,
reordering, insertion, and deletion from the middle of a local history.
It does not prove who wrote an entry, when an event occurred, that a
payload is true, or that the ledger head was not replaced wholesale
(`docs/ledger.md`, `docs/security.md`). Stronger guarantees require
external anchoring, signatures, and trusted timestamps added explicitly,
never implied by the chain.

**Falsifier:** any doc, CLI output, or API text that presents ledger
verification as proof of truth, authorship, or time.

### VIII. Thresholds Carry Measured Provenance

No mechanism is ported, and no threshold is set, on intuition
(`docs/scoring.md`). Each ported mechanism names
the measurement behind it: the policy gates from STANCE-02 production
analysis, per-source reliability as `1 − Brier` over resolved outcomes,
and the 0.05 materiality default validated as the hysteresis point
(CHURN-01 / TRIGGER-STRESS-01). Threshold defaults state their
provenance in code, and a future threshold change cites the workload
that moved it; a bar breached by a healthy workload is reset from
observed data with the old value recorded, never tightened on a hunch.

**Falsifier:** a new gate, threshold, or ported mechanism merged without
a named measurement, study, or workload justifying its value.

## Architecture and Separation of Concerns

The three-layer split in README.md and `docs/spec-kit.md` is constitutional:

| Layer | Owns | Must not own |
|---|---|---|
| `aee` Python package (`src/aee/`) | Claims, evidence, scoring, challenge, recovery, graph, ledger, policy, reliability, review, gaps, extraction, session, and the Evaluator adapter | Spec Kit artifact discovery or command UX |
| `spec-kit-aee` extension | Spec Kit commands, hooks, and artifact discovery; drives this engine through the `aee` CLI | The domain engine or scoring rules |
| `spec-kit-evaluator` extension | The shared, provider-neutral result envelope, composition, reports, and model routing | AEE-specific epistemic rules |

Rich AEE data is preserved inside the Evaluator Contract's opaque
`state.aee` field; actionable failures become normal evaluator findings.
AEE stays opinionated and independently versioned without forking or
weakening the neutral Evaluator Contract. This repo is the domain-engine
repo: changes to the other two layers belong in their own repos.

The package is dependency-free at runtime, offline, and only reads files
explicitly provided by the caller and writes to explicitly configured
output paths (`docs/security.md`, CHANGELOG 1.0.0).

## Quality Gates and Development Workflow

From CONTRIBUTING.md and `pyproject.toml`, every behavior change must:

1. Start from an issue describing the change and its epistemic impact.
2. Add or update tests for every behavior change (`tests/`, pytest with
   `--strict-markers`).
3. Pass `ruff format --check .`, `ruff check .`, `mypy src/aee`
   (mypy `strict = true`, Python ≥ 3.11), and `pytest`.
4. Keep deterministic checks separate from model-generated judgments
   (Principle V).
5. Never upgrade an assertion to observed evidence without an
   independently inspectable source (Principle I).

CLI exit codes are a public, CI-facing contract (README.md): `0` for
pass/warn, `1` for iteration / clarification / evidence collection /
abstention, `2` for a hard block or invalid ledger — and, per the CLI
error contract (CHANGELOG 1.0.3), malformed input and usage errors also
exit `2` with a clean message, never a traceback exiting `1`.

Releases follow Keep a Changelog and Semantic Versioning (CHANGELOG.md);
the package `__version__` in `src/aee/__init__.py` is the single source
for `--version`. Spec-driven work in this repo follows the Spec Kit flow
(specify → plan → tasks → implement) with the AEE and evaluator
extensions installed under `.specify/extensions/`; a spec's claims are
themselves subject to Principles I–VIII.

## Security Boundaries

Do not place secrets, export-controlled material, personal data, or
privileged evidence in a public repository; AEE records may reveal
architecture, risks, and unresolved weaknesses (`docs/security.md`).
Host applications that add model-backed review must retain the model and
policy identity in metadata, require independent evidence for high-impact
gates, and preserve counterevidence and human overrides.

## Governance

This constitution supersedes ad-hoc practice inside this repo.
Amendments require: a stated reason tied to project evidence (Principle
VIII), an edit to this file in the same change as any practice it
authorizes, and a version bump below. Changes that weaken Principles
I–VII require explicit owner approval recorded in the change, not just
a passing test suite. The baseline state of the project at adoption is
recorded in `specs/001-baseline-current-state/`.

**Version**: 1.0.1 | **Ratified**: 2026-10-08 | **Last Amended**: 2026-10-16

Amendment 1.0.1: update documentation references after removing retired porting
guides; the evidence, threshold-provenance, and governance requirements are unchanged.
