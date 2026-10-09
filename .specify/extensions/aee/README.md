# Applied Epistemic Engineering for Spec Kit

[![Test](https://github.com/electrohire/spec-kit-aee/actions/workflows/test.yml/badge.svg)](https://github.com/electrohire/spec-kit-aee/actions/workflows/test.yml)
[![CodeQL](https://github.com/electrohire/spec-kit-aee/actions/workflows/codeql.yml/badge.svg)](https://github.com/electrohire/spec-kit-aee/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/electrohire/spec-kit-aee/badge)](https://securityscorecards.dev/viewer/?uri=github.com/electrohire/spec-kit-aee)

`spec-kit-aee` applies evidence-centered claim engineering to Spec-Driven Development. It turns explicit requirements, assumptions, hypotheses, decisions, and compliance claims into a challengeable claim graph; distinguishes observations from assertions; preserves contradictions; propagates weakest-link uncertainty; proposes bounded recovery work; and emits results that conform to ElectroHire's [Evaluator Contract](https://github.com/electrohire/spec-kit-evaluator).

The implementation is an original ElectroHire design split into two deliberate layers:

- [`applied-epistemic-engineering`](https://github.com/electrohire/applied-epistemic-engineering) owns the Python model, deterministic engine, CLI, and ledger.
- `spec-kit-aee` is the thin lifecycle adapter, command surface, hooks, and evaluator-result integration.

## What it does

1. Extracts only explicitly identified claims; ordinary prose is never silently promoted into evidence.
2. Challenges claim atomicity, observability, boundaries, falsifiability, dependencies, contradictions, and evidence independence.
3. Scores evidence using published weights and caps dependent confidence at the weakest supporting claim.
4. Records recovery actions instead of manufacturing certainty.
5. Writes a rich AEE assessment and a provider-neutral Evaluator Contract result.
6. Optionally appends assessments to a tamper-evident SHA-256 ledger.

AEE is a decision aid. It does **not** prove truth, certify compliance, replace domain review, or make a model's self-attestation into observed evidence.

## Installation

Start with an initialized [Spec Kit](https://github.com/github/spec-kit) project and
Python 3.11 or later. Run shell commands below in the project root. Agent slash
commands belong in your coding agent's chat, not in PowerShell or Bash.

| Required component | Install name / version | Repository and purpose |
| --- | --- | --- |
| Spec Kit | `specify-cli>=1.0.0` | [github/spec-kit](https://github.com/github/spec-kit): project and command installation |
| Python | `python>=3.11` | Runs the adapter and engine |
| AEE engine | `applied-epistemic-engineering>=1.4.0,<2`, exposes `aee` | [electrohire/applied-epistemic-engineering](https://github.com/electrohire/applied-epistemic-engineering): deterministic assessment, graph, ledger, and gaps |
| Evaluator Contract | extension ID `evaluator`, version `>=1.0.0,<2` | [electrohire/spec-kit-evaluator](https://github.com/electrohire/spec-kit-evaluator): result contract, composition, reporting, and routing |
| This adapter | extension ID `aee` | [electrohire/spec-kit-aee](https://github.com/electrohire/spec-kit-aee): eight agent commands and optional lifecycle hooks |

The engine needs 1.4.0 for the policy-gate, reliability, and review CLI surface (1.0.2 introduced the `gaps` command). Evaluator
is a Spec Kit extension, **not** a PyPI package or shell executable. Spec Kit's
`requires.tools` metadata documents dependencies; it does not install them or
verify their versions. Install both dependencies explicitly before this adapter.

For a new project, install Spec Kit using its [official installation
instructions](https://github.com/github/spec-kit#-get-started), then run
`specify init my-project` and `cd my-project`. Choose your agent during setup.
For an existing project, use its current Python environment or create one:

```bash
python -m venv .venv
```

Activate with `source .venv/bin/activate` on macOS/Linux, or
`.\.venv\Scripts\Activate.ps1` in PowerShell. If PowerShell policy prevents
activation, use `.\.venv\Scripts\python.exe` for pip and put
`.\.venv\Scripts` on the agent process's PATH. Keep the same environment active
when launching your coding agent so it can find both `python` and `aee`.

```bash
python -m pip install "applied-epistemic-engineering>=1.4.0,<2"
aee --version
specify extension add evaluator --from https://github.com/electrohire/spec-kit-evaluator/archive/refs/tags/v1.0.0.zip
specify extension add aee --from https://github.com/electrohire/spec-kit-aee/archive/refs/tags/v1.0.1.zip
specify extension list
```

The commands above install the current published releases. This branch prepares
**1.1.0 (unreleased)**; do not use a nonexistent `v1.1.0.zip` URL. To test these
changes, clone this repository, check out the PR branch, then run
`specify extension add --dev /absolute/path/to/spec-kit-aee` from a disposable
initialized project. Back up generated assessments before replacing an existing
installation; `--force` can overwrite its extension directory.

The community catalog is discovery-only by default. Explicit `--from` URLs select
the published archives. Installation downloads code; deterministic AEE operations
make no model API calls. Your chosen coding agent has its own inference setup.

## First run and configuration

The [step-by-step walkthrough](docs/usage.md) covers all eight commands, expected
exit codes, output files, gap evidence format, and recovery. Start with the
unsupported-claim template; replace its example requirement with your own and add
real evidence only after inspecting it. The published v1.0.1 template ships with
draft status and empty evidence. Copying the template is not evidence.

The runner currently reads **CLI flags, not `aee-config.yml` or environment
configuration overrides**. The installed YAML is a reference for agent/operator
choices. See the [configuration table](docs/usage.md#configuration) for exact flags
and defaults. Optional hooks depend on the host workflow emitting their events;
`after_verify` is not guaranteed in every Spec Kit workflow.

## Brief example

Use stable IDs in a specification:

```markdown
## REQ-LATENCY-001 — Search responds within 250 ms

- **Boundary:** Production, p95, 50 requests/second
- **Falsification test:** A 30-minute load test observes p95 above 250 ms
```

Then run:

```text
/speckit.aee.assess phase=after_specify artifact=specs/001-search/spec.md
```

The assessment is stored under `.specify/extensions/aee/assessments/`; the shared result is stored under `.specify/extensions/evaluator/results/`. A claim without inspectable evidence remains unsupported even when generated prose says it passed.

## Commands

| Command | Purpose |
| --- | --- |
| `speckit.aee.assess` | Run the complete deterministic AEE pipeline |
| `speckit.aee.challenge` | Focus on breakpoints and recovery work |
| `speckit.aee.trace` | Render dependencies and review provenance |
| `speckit.aee.verify` | Verify ledger integrity |
| `speckit.aee.gate` | Return CI-friendly exit status from an assessment |
| `speckit.aee.gaps` | Generate or update the gap register from a verification matrix and test evidence |
| `speckit.aee.route-evidence` | Route oversized logs and sources into raw evidence slices for AEE gates |
| `speckit.aee.report-savings` | Report measured RTK and Headroom token savings, never estimated |

Compose AEE with other evaluators using `/speckit.evaluator.compose`, render it with `/speckit.evaluator.report`, or use `/speckit.evaluator.route` for the next-phase model recommendation. Invocation separators vary by integration; Spec Kit renders the installed command files appropriately.

## Files written

```text
.specify/extensions/aee/
├── assessments/aee-<phase>-<timestamp>.json
├── challenges/aee-<phase>-<timestamp>.json
├── graphs/aee-claims-<timestamp>.mmd
├── evidence/route notes with file paths, line ranges, and backend used
├── reports/measured token-savings reports
├── telemetry/shell-calls.jsonl
└── ledger/epistemic-ledger.jsonl

.specify/extensions/evaluator/results/
└── aee-<phase>-<timestamp>.json
```

The command adapter rejects paths outside the project root and symlinked path components supplied to it. Source artifacts are read-only. Assessments, challenges, graphs, and ledgers use extension-owned directories; `gaps --output` can write another explicitly chosen in-project path. Use a trusted evidence directory: the adapter does not recursively validate every file the engine discovers inside it.

## Benchmarks and limitations

The companion [Spec Kit + AEE benchmark repository](https://github.com/electrohire/spec-kit-aee-benchmark)
contains the protocol, runtime measurements, token accounting, repair loops, and
preserved failures. Its [versioned results](https://github.com/electrohire/spec-kit-aee-benchmark/tree/835573aff15520a580c7c3862b3534b347101e18/reports/local)
show a six-task local study and a staged TinyDB build. After small-task repairs,
all three arms passed 5/6 tasks; none fully accepted a long-study hidden milestone.
Timeouts interrupted the adapted workflows; only three combined-arm planning
assessments completed. These results establish **no general correctness or
cost-saving advantage**. They are a reproducible starting point for a bounded
trial, not a claim that the complete Spec Kit + AEE workflow was validated.

AEE scores declared structured evidence; it does not independently run a load test,
fetch every evidence reference, or prove an assertion true. Markdown extraction
collects explicit IDs, boundaries, dependencies, and falsifiers; use JSON to supply
structured evidence. Review findings and references before acting on an outcome.

## Troubleshooting

| Symptom | Next step |
| --- | --- |
| `aee` is missing or `gaps` is unrecognized | Activate the engine environment, run `aee --version`, and install engine `>=1.0.2,<2`. |
| Evaluator commands are missing | Install `evaluator` using the explicit archive URL, run `specify extension list`, then restart the coding agent if needed. |
| No project / unknown slash command | Run `specify init` first and use the command spelling rendered for your selected agent. |
| Exit 1 from an assessment | Read the result: `iterate`, `clarify`, and `gather_evidence` are expected recovery outcomes, not installation errors. |
| Editing YAML has no effect | Pass the corresponding CLI flag; the adapter does not load that YAML. |
| No gap file appears | `gaps` prints to stdout unless `--output` is supplied. |
| A claim is unsupported | Inspect its ID, boundary, falsification test, and evidence; do not relabel generated assertions as observations. |
| Path is refused | Use a real file inside the project, with no symlinked path components. |

## Development

Follow [CONTRIBUTING.md](CONTRIBUTING.md) for the hash-locked environment, real-engine
integration tests, Spec Kit installation smoke, and release/catalog update process.
See [SECURITY.md](SECURITY.md) for the trust boundary and [CHANGELOG.md](CHANGELOG.md)
for released versus pending changes.

## License

MIT © 2026 ElectroHire Inc.
