---
name: applied-epistemic-engineering
description: Assess explicit project claims against their evidence with the standalone AEE Python engine, challenge unsupported conclusions, and report uncertainty and recovery work. Use for evidence audits requested in ordinary language, without requiring Spec Kit.
---

# Standalone AEE assessment

Turn a request such as “check the evidence for these requirements” into a bounded
assessment. Perform the tool operations yourself; the user need not learn CLI
syntax. This is the standalone engine skill, not the Spec Kit extension.

## Choose the route

- If the user asks for Spec Kit lifecycle integration, use that project's installed
  AEE extension skills instead. See the adapter's
  [installation guide](https://github.com/electrohire/spec-kit-aee#installation).
- Otherwise use the Python engine directly. Its PyPI distribution is
  `applied-epistemic-engineering`; its import and executable are `aee`.
  Do not install a distribution named `aee`. Spec Kit, the evaluator extension,
  `jsonschema`, and model API keys are not standalone engine prerequisites.
- Check `aee --version` in the intended Python environment. If the engine is
  absent and setup is within the user's request, install it in a project-local
  environment. Explain an actual dependency or access failure; do not invent results.

## Frame and assess

1. Identify the project root, requested artifacts, decision, and boundary. Ask only
   when missing information changes the assessment. Keep all reads and outputs
   inside that root; refuse symlink escapes and keep source artifacts unchanged.
2. Read the actual artifacts. Reuse valid structured claims, or write an explicit
   claim bundle to `.aee/claims.json`. Record stable IDs, source references,
   boundaries, falsification conditions, and dependencies. Newly extracted claims
   begin with `status: draft`, `stage: created`, and empty evidence unless you have
   inspected supporting artifacts. Never promote the user's prose or your own
   assessment into observed evidence or human acceptance.
3. Run the engine with an argument vector (quote paths in shell examples):

   ```bash
   aee validate .aee/claims.json
   aee assess --input .aee/claims.json --project-root . --phase after_plan --output .aee/assessment.json
   aee verify-ledger --ledger .specify/extensions/aee/ledger/epistemic-ledger.jsonl
   ```

   The default ledger path uses `.specify/` even without Spec Kit; it is a storage
   convention, not a requirement to install Spec Kit. Do not overwrite an input
   with an output. Do not reset or repair a ledger silently. Use `aee --help` and
   the selected subcommand's help for additional operations such as challenge,
   evidence verification, graph, review, or an explicitly requested policy gate.
4. Interpret exit 0 as pass/warn, 1 as recovery/evidence needed, and 2 as block,
   invalid input, or execution failure. A nonzero code must not disappear from
   the report. Check the produced JSON and ledger verdict, not just stdout.
5. For an unsupported claim, propose the smallest real observation, test, or
   clarification that would change the decision. Do not fabricate evidence to
   turn an expected recovery outcome green.

## Explain the result

Give the requested user a plain-language account: what was checked, what the
evidence supports, contradictions, uncertainty, verification failures, next
actions, and links to the exact saved artifacts. Preserve the engine's
`reported_statuses`, stage caps, `not_understood`, and separate machine verification
and human acceptance lanes; never infer accepted/digested status from a score.
Scores and policy acceptance are not truth or compliance certificates. A valid
hash chain does not establish that its contents are true. State assumptions and
the inspected boundary; distinguish formal proof under assumptions from evidence
about a real deployment. See [assurance boundaries](https://applied-epistemic-engineering.readthedocs.io/en/latest/names-and-assurance/).
