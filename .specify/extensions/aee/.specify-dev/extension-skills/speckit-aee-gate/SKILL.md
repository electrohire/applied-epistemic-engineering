---
name: speckit-aee-gate
description: Apply a CI-friendly decision gate to an AEE assessment
compatibility: Requires spec-kit project structure with .specify/ directory
metadata:
  author: ElectroHire
  source: extension:aee
---

# Aee Gate Skill

# AEE Gate

Apply the AEE exit-code contract to an existing rich assessment.

## User input

```text
$ARGUMENTS
```

Resolve `assessment=<path>` inside `.specify/extensions/aee/assessments/` unless an explicit in-project path is supplied. Refuse symlinks and run:

```bash
python .specify/extensions/aee/scripts/python/run_aee.py gate --input <assessment>
```

Exit semantics are: 0 for `pass` or `warn`, 1 for `iterate`, `clarify`, or `gather_evidence`, and 2 for `block` or malformed input. For multi-evaluator release policy, use `/speckit-evaluator-report format=gate` on a composed result.
