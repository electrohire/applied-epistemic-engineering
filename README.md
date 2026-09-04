# Applied Epistemic Engineering for Python

[![CI](https://github.com/electrohire/applied-epistemic-engineering/actions/workflows/ci.yml/badge.svg)](https://github.com/electrohire/applied-epistemic-engineering/actions/workflows/ci.yml)
[![CodeQL](https://github.com/electrohire/applied-epistemic-engineering/actions/workflows/codeql.yml/badge.svg)](https://github.com/electrohire/applied-epistemic-engineering/actions/workflows/codeql.yml)
[![Documentation](https://readthedocs.org/projects/applied-epistemic-engineering/badge/?version=latest)](https://applied-epistemic-engineering.readthedocs.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An evidence-centered Python toolkit for turning important claims into inspectable engineering
artifacts. It makes boundaries, evidence, provenance, uncertainty, contradictions,
falsification tests, recovery work, and decision history explicit.

This is an original, ground-up ElectroHire implementation. Its result model aligns directly with
ElectroHire's Spec Kit Evaluator Contract while the domain engine remains independently packaged.

## Why it exists

Ordinary validation asks whether an artifact is formatted correctly. AEE asks harder questions:

- What exactly is being claimed?
- Under what conditions does it hold?
- What was observed, inferred, or merely asserted?
- What evidence would prove the claim wrong?
- Which claims depend on uncertain foundations?
- What contradicts the current conclusion?
- What bounded work would improve the decision?

The library does not call a confidence number “truth.” Every score is a transparent decision aid
derived from recorded evidence and explicit rules.

## Installation

```bash
pip install applied-epistemic-engineering
```

For development:

```bash
pip install -e ".[dev,docs]"
```

## Five-minute example

```python
from aee import (
    AEESession,
    ClaimKind,
    ClaimStatus,
    Evidence,
    EvidenceKind,
    SourceQuality,
)

session = AEESession(
    "checkout-service",
    phase="after_plan",
    ledger_file=".aee/epistemic-ledger.jsonl",
)

claim = session.add_claim(
    "REQ-PERF-001",
    "Checkout p95 latency remains below 300 ms",
    kind=ClaimKind.REQUIREMENT,
    boundary=["production", "nominal load", "30-minute observation window"],
    source_ref="spec.md#REQ-PERF-001",
)
claim.status = ClaimStatus.SUPPORTED
claim.falsification_tests.append("Observe p95 latency at or above 300 ms")

session.add_evidence(
    claim.id,
    Evidence(
        ref="reports/load-test-2026-09-04.json",
        kind=EvidenceKind.OBSERVED,
        source_quality=SourceQuality.TEST,
        source_id="load-test-2026-09-04",
        description="Observed p95 latency was 241 ms",
    ),
)

assessment = session.assess()
print(assessment.outcome, assessment.summary)
```

## CLI

```bash
aee assess --input claims.json --phase after_plan --output assessment.json \
  --evaluator-output evaluator-result.json --ledger .aee/epistemic-ledger.jsonl

aee verify-ledger --ledger .aee/epistemic-ledger.jsonl
aee graph --input claims.json --output claim-graph.mmd
aee gate --input assessment.json
```

Exit codes are CI-friendly: `0` for pass/warn, `1` for iteration/clarification/evidence
collection, and `2` for a hard block or invalid ledger.

## Architecture

| Layer | Responsibility |
|---|---|
| `aee` Python package | Claims, evidence, scoring, challenge, recovery, graph, ledger |
| [`spec-kit-aee`](https://github.com/electrohire/spec-kit-aee) | Spec Kit commands, hooks, and artifact discovery |
| [`spec-kit-evaluator`](https://github.com/electrohire/spec-kit-evaluator) | Shared result envelope, composition, reports, and model routing |

## Core principles

1. Assertions never become observations because a model repeats them.
2. Counterevidence and contradictions remain visible.
3. Unsupported claims remain explicitly unsupported.
4. Confidence propagates through dependencies by the weakest-link rule.
5. Every failure produces a bounded recovery proposal with a verification condition.
6. Deterministic checks run before probabilistic review.
7. Hash chains establish tamper evidence—not truth, identity, or trusted time.

## Documentation

Full documentation is configured for Read the Docs at
[applied-epistemic-engineering.readthedocs.io](https://applied-epistemic-engineering.readthedocs.io).
Users adopting AEE from another implementation can follow the [migration guide](docs/migration.md).

## Ownership and license

Designed and implemented by **ElectroHire Inc.** Copyright © 2026 ElectroHire Inc.
Released under the [MIT License](LICENSE).
