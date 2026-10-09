# First assessment, recovery, and verification

Complete the README installation first. All shell commands here run from your
initialized project root with the engine environment active. No paid inference is
needed for these deterministic adapter operations.

## Start with an unsupported claim

Copy `.specify/extensions/aee/templates/aee-claims.json` to `claims.json`. Use
`cp` on macOS/Linux or `Copy-Item` in PowerShell. Edit the stable ID, requirement,
boundary, and falsification test for your project. In this unreleased patch the template intentionally has no evidence. If you installed published v1.0.0, first replace its illustrative `evidence` list with `[]`, set `status` to `draft`, and set `uncertainty` to `insufficient_evidence`. Do not retain the sample load-test observation as your own result. The resulting unsupported claim should ask for recovery; a passing outcome is not the goal of this
first smoke check.

```bash
python .specify/extensions/aee/scripts/python/run_aee.py assess --input claims.json --phase after_specify
```

The printed JSON lists `assessment`, `evaluator_result`, `ledger`, and
`aee_exit_code`. Open both result files and inspect their `outcome`, findings, and
recovery actions. AEE scores the evidence you supply; it does not independently
verify the content of every evidence reference. Do not invent an observed result
to make an assessment pass. Keep source artifacts unchanged during assessment.

Agent equivalent: `/speckit.aee.assess artifact=claims.json phase=after_specify`.
Use your installed agent's rendered command spelling if it uses a different separator.

## Challenge, repair, and reassess

```bash
python .specify/extensions/aee/scripts/python/run_aee.py challenge --input claims.json --phase after_specify
python .specify/extensions/aee/scripts/python/run_aee.py graph --input claims.json
```

Challenge writes failure modes and bounded recovery proposals under
`.specify/extensions/aee/challenges/`; graph writes Mermaid under `graphs/`.
Choose a recovery, gather independently inspectable evidence, and update the
claims JSON explicitly. Preserve counterevidence. Reassess with the same phase and
compare outcomes and evidence, not just confidence scores. Graph edges represent
declared relationships and are not proof of causality or reference validity.

For example, an actual test report can be represented as an evidence entry with
`ref`, `kind`, `direction`, `source_quality`, `description`, and `source_id`. Use
`kind: observed` only for an observation you actually inspected; model-written
claims remain `asserted`. See the [engine documentation](https://github.com/electrohire/applied-epistemic-engineering)
for its JSON model and scoring rules. Markdown extraction does not populate
structured observed evidence from ordinary prose.

## Verify the ledger and apply a gate

```bash
python .specify/extensions/aee/scripts/python/run_aee.py verify
python .specify/extensions/aee/scripts/python/run_aee.py gate --input <assessment-path-from-first-command>
```

Replace the angle-bracket placeholder with the actual rich assessment path.
Verify reports chain validity, entry count, head hash, and errors. A valid chain
establishes continuity of retained records, not truth, identity, trusted time, or
completeness before the first record.

Assessment/gate exit codes:

| Code | Meaning |
| --- | --- |
| 0 | `pass` or `warn`; inspect warnings before proceeding |
| 1 | `iterate`, `clarify`, or `gather_evidence`; recovery is needed |
| 2 | `block` or an engine-reported input/usage error |

The adapter also reports ordinary Python/process errors for missing or invalid
paths; inspect stderr. Do not interpret every nonzero process code as a scored
assessment outcome. Do not globally suppress failures in CI to accommodate an
expected recovery outcome: assert the expected outcome and inspect the artifacts.

For multiple evaluator results, use `/speckit.evaluator.compose phase=after_specify
strategy=strict`, then `/speckit.evaluator.report phase=after_specify format=terminal`.
These agent commands come from the separate Evaluator extension. AEE does not
silently compose results or run every other evaluator for you.

## Generate a gap register

Create `docs/verification-matrix.md` with engine-compatible test IDs:

```markdown
| Test ID | Requirements | Layer | Gate |
| --- | --- | --- | --- |
| T-API-001 | Valid request returns 200 | integration | gate-1 |
```

Create an `evidence/` directory. After actually running your test, a JSON report
can use this shape (the `pass` below is a format illustration, not test evidence):

```json
{"results": [{"test_id": "T-API-001", "status": "pass"}]}
```

```bash
python .specify/extensions/aee/scripts/python/run_aee.py gaps --matrix docs/verification-matrix.md --evidence evidence --output GAPS.md
```

Inspect open and closed entries. An empty evidence directory leaves the example
gap open. Without `--output`, the engine prints the register and creates no gap
file. To retain closed entries on regeneration, explicitly add `--existing GAPS.md`
and review whether their original evidence still applies. The register tracks
coverage; it does not rerun tests or certify their results.

Manual `--close GAP-001` changes the existing register selected by `--output`.
The engine does not validate new passing evidence in this mode; inspect evidence
before choosing manual closure. Prefer generation from recorded test results.
(Engine 1.0.3 and later refuse to close a gap ID that does not exist; earlier
releases reported success anyway.)

## Route evidence and report token savings

Two commands support the optional token-economy tools (`rtk`, `headroom`,
`token-router`, `ollama` — see `docs/token-economy.md`). Neither is required;
both degrade gracefully when a tool is absent.

`speckit.aee.route-evidence` triages an oversized log or source file into raw
evidence slices before an assessment consumes it:

```bash
python .specify/extensions/aee/scripts/python/aee_token_economy.py --project-root . route --file build.log --mode error_log
```

Gates always reason over the raw slices, never over router prose or compressed
summaries. Without a router backend, deterministic line ranges are used.

`speckit.aee.report-savings` reports **measured** savings from RTK and
Headroom, each on its own line, never estimated and never double-counted:

```bash
python .specify/extensions/aee/scripts/python/aee_token_economy.py --project-root . report
```

## Configuration

`aee-config.yml` is currently a reference for the agent/operator, not an automatically
loaded runner configuration. The runner does not merge local YAML or `SPECKIT_*`
environment overrides. Use explicit flags:

| Reference setting | Runner setting | Default / scope |
| --- | --- | --- |
| `threshold` | `assess/challenge --threshold` | `0.70` |
| `ledger.enabled` | `assess --no-ledger` disables it | Enabled for assess only |
| `ledger.actor` | `assess/challenge --actor` | `spec-kit-aee` |
| `phases.*` | Host workflow/extension hook configuration | Optional hooks; not read by the runner |
| `gap_register.matrix_path` | `gaps --matrix` | Required |
| `gap_register.evidence_dir` | `gaps --evidence` | Required |
| `gap_register.output_path` | `gaps --output` | Omitted means stdout |

`--project-root` is a global option and goes **before** the operation, for example
`python <runner-path> --project-root <project-dir> assess --input claims.json`.
Input and output paths are resolved relative to that root. Assessment/challenge
filenames use second-resolution UTC timestamps: avoid concurrent same-phase runs
in one project, since they can overwrite a same-second result. Archive results
before force-reinstalling an extension. Do not commit private evidence or generated
ledger data merely because it is under `.specify/`.

See the README troubleshooting table and [security boundary](../SECURITY.md).
