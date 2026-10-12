# Changelog

All notable changes follow Semantic Versioning.

## 1.2.0 - Unreleased

- Wire the engine's epistemic-ledger ports into the assess flow: the runner's
  `assess` gains `--policy` (per-claim ACCEPT / CHALLENGE / ABSTAIN verdicts,
  with `--min-independent-sources` / `--contested-threshold` overrides) and
  `--reliability <table.json>` (measured per-source reliability blended into
  scoring); a new `speckit.aee.review` command diffs two assessments into a
  materiality-filtered review queue via the runner's `review` subcommand.
- Require `applied-epistemic-engineering>=1.4.0,<2` (dev pin 1.4.0): the CLI
  surface for the gates, reliability, and review landed in engine 1.4.0, on
  top of the 1.1.0-1.3.0 library ports.

## 1.1.0 - Unreleased

- Integrate the token-economy policy into AEE core: declare optional `rtk`,
  `headroom`, `token-router`, and `ollama` tools; add `speckit.aee.route-evidence`
  (local triage to raw slices; assess gates reason over slices only, never over
  router prose) and `speckit.aee.report-savings` (measured-only, RTK and Headroom
  reported separately, never estimated or double-counted). The tools stay external
  runtimes; AEE cores the policy and degrades gracefully when a tool is absent.
- Add `scripts/python/aee_token_economy.py` (tool status, evidence routing with
  deterministic fallback, measured savings aggregation, shell telemetry wrapper)
  with fail-closed secret-file refusal and path safety mirroring `run_aee.py`.
- Document headroom integration points for long-horizon sessions
  (`docs/token-economy.md`): proxy/wrap/SharedContext hook-in points and the hard
  rule that gates see raw slices, never compressed summaries.
- Fix the branch's own checks to match the surface it ships: manifest tests and
  `check_install.py` now assert eight commands and the required/optional tool
  split (they still asserted the 1.0.1 surface and failed).
- Token-router discovery anchors on `--project-root`, not the caller's working
  directory; the `shell` wrapper validates `--telemetry` before running the
  wrapped command instead of raising after its side effects.

## 1.0.1 - 2026-09-23

- Declare Python, AEE engine 1.0.2 (needed for `gaps`), and Evaluator Contract dependencies using Spec Kit's documented tool metadata.
- Replace the unsupported `requires.commands` field with explicit installation guidance; dependencies are informational and are not auto-installed by Spec Kit.
- Add newcomer setup, configuration limitations, troubleshooting, and a link to the benchmark's measured results and failures.
- Install the actual engine in hash-locked CI, validate with Spec Kit's own manifest parser, and exercise every adapter operation without silently skipping missing-engine integration tests.
- Document the exact AEE claim field vocabulary in `speckit.aee.assess` so agents emit schema-valid claims on the first attempt.
- Trim the extension description to under 100 characters per the Spec Kit extension publishing guide.
- Add deterministic `extension.yml` and documentation compliance tests.

## 1.0.0 - 2026-09-09

- Add six Spec Kit AEE commands and five optional lifecycle hooks.
- Integrate `applied-epistemic-engineering` 1.x with Evaluator Contract 1.0.
- Add path-safe execution, structured claim template, ledger verification, and CI validation.
- Add the `speckit.aee.gaps` command and `after_verify` hook to generate and maintain the gap register from a verification matrix and test evidence.
- Add dependency review, Dependabot, OpenSSF Scorecard, and hash-locked CI installs.
- Document the private disclosure process and response timeline.
