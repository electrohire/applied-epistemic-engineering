# Implementation Plan: Baseline — Current State of the AEE Engine (v1.4.0)

**Branch**: `chore/speckit-onboarding` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-baseline-current-state/spec.md`

## Summary

Record the shipped v1.4.0 state of the `aee` Python engine as a grounded
Spec Kit baseline and complete the project's spec-kit + AEE onboarding:
install the Spec Kit scaffold (specify 1.0.10, Copilot integration, `sh`
scripts), install the `aee` (v1.2.0) and `evaluator` (v1.0.0) extensions,
replace the template constitution with a project-specific one grounded in
README.md / `docs/`, and write this baseline spec trio + `claims.json`.
No engine code changes: the "implementation" is verification that the
spec's claims hold on disk and in the test suite.

## Technical Context

**Language/Version**: Python ≥ 3.11 (`pyproject.toml` `requires-python`);
baseline verified on Python 3.12

**Primary Dependencies**: None at runtime — the package is
dependency-free by design (CHANGELOG 1.0.0; `docs/security.md`). Dev /
docs extras only: pytest, pytest-cov, ruff, mypy, build; mkdocs +
mkdocs-material + mkdocstrings (`pyproject.toml` optional-dependencies)

**Storage**: Files only, caller-provided: claims JSON / Markdown in,
assessment / evaluator-result / challenge / graph (Mermaid) JSON and
Markdown out, and the hash-chained JSONL ledger at a configured path
(conventionally `.aee/epistemic-ledger.jsonl`, git-ignored)

**Testing**: pytest (`tests/`, 12 modules, `--strict-markers`), ruff
(`line-length = 100`, rules E/F/I/UP/B/SIM/RUF), mypy `strict = true`
over `src/aee`

**Target Platform**: Cross-platform library + CLI (`aee` console script,
`aee.cli:main`); CI on GitHub Actions with CodeQL (README badges)

**Project Type**: Single-project Python library + CLI (src-layout,
hatchling build, `src/aee/`)

**Performance Goals**: No throughput target is claimed by the project.
The one recorded performance property is algorithmic: ledger appends are
O(1) after the first verification via the verified-tip cache, instead of
O(n) per append / O(n²) per session (CHANGELOG 1.0.4)

**Constraints**: Deterministic and offline core; no model contact in the
library; scores must be replayable (pinnable `as_of`); CLI exit codes
0 / 1 / 2 are a public contract; hash chain claims tamper evidence only

**Scale/Scope**: Baseline covers the shipped surface at 1.4.0:
16 modules in `src/aee/` plus the evaluator adapter and the assessment
JSON schema (`src/aee/schemas/aee-assessment.schema.json`), 8 CLI
subcommands, 118 tests

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.0.0.*

- **I. Assertions Never Become Observations** — PASS. This plan asserts
  nothing as observed: every baseline fact cites a file, a command
  output, or a test run recorded in `tasks.md`.
- **II. Bounded, Atomic, Evidence-Linked Claims** — PASS. The baseline
  claims (C-001…C-006 in `claims.json`) are atomic, bounded to v1.4.0 /
  this checkout, and each carries a falsification test.
- **III. Counterevidence Stays Visible** — PASS. Known frictions found
  during onboarding (nested extension `.git` copies, untracked
  `.github/skills` symlinks) are recorded as tasks, not hidden.
- **IV. Unsupported Stays Unsupported** — PASS. Anything not verified
  (e.g. a live `aee` install on the system interpreter) is stated as
  unverified, with the `PYTHONPATH=src` workaround named.
- **V. Deterministic Before Probabilistic** — PASS. Verification is
  entirely deterministic: pytest, CLI runs, and on-disk checks. No model
  judgment is used as evidence.
- **VI. Bounded Recovery** — PASS. Each open task is scoped to one
  artifact with a verification condition.
- **VII. Tamper Evidence, Not Truth** — PASS. Nothing in this baseline
  treats the ledger — or a git commit — as proof that contents are true.
- **VIII. Threshold Provenance** — PASS. No new thresholds are introduced;
  the thresholds named (0.70 confidence, 0.05 materiality, policy
  defaults) are the shipped ones with their documented provenance.

No violations; Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-baseline-current-state/
├── spec.md       # Baseline specification (this trio's source)
├── plan.md       # This file
├── tasks.md      # Verification + onboarding tasks
├── claims.json   # AEE claims C-001…C-006 with falsifiers
└── assessment.json  # `aee assess` run over claims.json (outcome: iterate — see tasks.md T024)
```

### Source Code (repository root)

```text
src/aee/
├── __init__.py        # Public API exports; __version__ = "1.4.0" (single source)
├── __main__.py        # python -m aee entry
├── model.py           # Claim, Evidence, enums (FR-001, FR-002)
├── extract.py         # JSON / Markdown claim extraction (FR-007)
├── challenge.py       # StressTester — deterministic failure modes (FR-004)
├── scoring.py         # ScoringEngine — transparent formula, weakest link (FR-003)
├── graph.py           # ClaimGraph — iterative cycle detection (FR-005)
├── recovery.py        # RecoveryOperator — bounded proposals (FR-004)
├── engine.py          # AEEEngine, Assessment
├── session.py         # AEESession — ledger-backed workflow facade
├── policy.py          # AssessmentPolicy gates, 1.1.0 (FR-008)
├── reliability.py     # ReliabilityTable, 1.2.0 (FR-009)
├── review.py          # build_review_queue, 1.3.0 (FR-010)
├── gaps.py            # GapEngine / GapRegister (FR-011)
├── ledger.py          # HashChainLedger (FR-006)
├── cli.py             # aee CLI — 8 subcommands, exit contract (FR-012)
├── adapters/
│   └── evaluator.py   # EvaluatorAdapter → Evaluator Contract (FR-013)
└── schemas/
    └── aee-assessment.schema.json

tests/                 # 12 pytest modules, 118 tests at baseline
docs/                  # concepts, scoring, ledger, security, spec-kit,
                       # quickstart, api, migration, porting-… (MkDocs, strict)
.specify/              # Spec Kit scaffold added by this onboarding:
                       # memory/constitution.md, extensions/{aee,evaluator},
                       # extensions.yml, templates/, scripts/bash/, workflows/
```

**Structure Decision**: The existing single-project src-layout is the
structure; onboarding adds only `.specify/` and `specs/` and touches no
source, test, or doc file. Extension install copies under
`.specify/extensions/` were pruned of nested `.git/`, `.venv-hatch/`,
`__pycache__`, and cache directories before commit so they commit as
plain files, following the precedent used in the sibling onboarding
passes in this program.

## Complexity Tracking

No constitution violations — table intentionally empty.
