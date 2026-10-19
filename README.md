# Applied Epistemic Engineering for Python

[![CI](https://github.com/electrohire/applied-epistemic-engineering/actions/workflows/ci.yml/badge.svg)](https://github.com/electrohire/applied-epistemic-engineering/actions/workflows/ci.yml)
[![CodeQL](https://github.com/electrohire/applied-epistemic-engineering/actions/workflows/codeql.yml/badge.svg)](https://github.com/electrohire/applied-epistemic-engineering/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/electrohire/applied-epistemic-engineering/badge)](https://securityscorecards.dev/viewer/?uri=github.com/electrohire/applied-epistemic-engineering)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/15598/badge)](https://www.bestpractices.dev/en/projects/15598)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/applied-epistemic-engineering.svg)](https://pypi.org/project/applied-epistemic-engineering/)
[![Documentation](https://readthedocs.org/projects/applied-epistemic-engineering/badge/?version=latest)](https://applied-epistemic-engineering.readthedocs.io/en/latest/)

OpenSSF Best Practices Passing criteria: 100% met (self-assessment, verified 2026-10-16).

An evidence-centered Python toolkit for turning important claims into inspectable engineering
artifacts. It makes boundaries, evidence, provenance, uncertainty, contradictions,
falsification tests, recovery work, and decision history explicit.

The result model aligns directly with the Spec Kit Evaluator Contract while the
domain engine remains independently packaged.

## Choose your interface

- **CLI or Python:** install `applied-epistemic-engineering`, then use `aee` or
  `from aee import AEESession`.
- **Agent:** give your agent the maintained
  [standalone SKILL.md](https://github.com/electrohire/applied-epistemic-engineering/tree/main/src/aee/skills/applied-epistemic-engineering)
  and ask it to inspect your claims and evidence in ordinary language. The agent
  handles commands and setup; no Spec Kit is required. The packaged skill is
  included from engine 1.5.3.
- **Spec Kit:** install extension ID `aee`, then ask the project's agent to use
  its installed AEE skills. The extension provisions the engine and evaluator.

See [CLI, agent, and Spec Kit](https://applied-epistemic-engineering.readthedocs.io/en/latest/agent/)
for discovery, installation, example requests, and dependency boundaries.

## Why it exists

Use AEE to challenge an agent's “done” claim against real test artifacts, keep
uncertainty visible across agent handoffs, review conflicting findings, and focus
the next evidence-gathering step. Separating assertions from observations and
preserving source identity can help expose unsupported claims in agent loops;
it is not a guaranteed hallucination detector. See
[use cases and evaluation](https://applied-epistemic-engineering.readthedocs.io/en/latest/use-cases/)
for concrete workflows, limitations, and how to measure improvement.

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

## Names and installation

The **PyPI distribution** is `applied-epistemic-engineering`. It installs the
**Python module** `aee` (`from aee import AEESession`) and the **engine CLI** `aee`
(`aee --version`). The separate `spec-kit-aee` repository provides a Spec Kit
extension whose **extension ID** is also `aee`. These names identify different
layers; do not install this engine with `pip install aee`.

```bash
python -m pip install applied-epistemic-engineering
```

Requires Python 3.11 or later; tested on Linux, macOS, and Windows with Python 3.11, 3.12,
and 3.13.

Using [Spec Kit](https://github.com/github/spec-kit)? You don't need to install this
package yourself. Install the Spec Kit extension, which installs a compatible engine
(`applied-epistemic-engineering>=1.5.0,<2`, the latest available) and its other
dependencies automatically on first use:

First register the [ElectroHire publisher catalog](https://github.com/electrohire/spec-kit-aee#installation)
once per project (or use an organization catalog containing AEE). The default
community catalog is discovery-only, including in Specify 1.2.2. Then install by name:

```bash
specify extension add aee
```



`spec-kit-aee` is the independently versioned adapter, installed by Spec Kit.

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
  --evaluator-output evaluator-result.json
# assess ledgers by default (Spec 002 FR-8.1): the assessment above was
# also appended to .specify/extensions/aee/ledger/epistemic-ledger.jsonl
# under the project root (the CWD, or --project-root when given) — the
# same default the spec-kit-aee runner uses. --ledger <path> selects a
# different ledger; --no-ledger opts out, and the choice is echoed into
# the assessment metadata either way.
aee verify-ledger --ledger .specify/extensions/aee/ledger/epistemic-ledger.jsonl

aee challenge --input claims.json --phase after_plan --output challenge.json
aee validate claims.json   # strict load + structural checks (CI: 0 valid, 2 invalid)
aee verify-evidence claims.json --project-root .   # refs resolve, hashes recompute, quality is derived vs declared
aee assess --input claims.json --verify-evidence --project-root .   # the same checks, folded into the assessment
aee gaps --matrix specs/verification-matrix.md --evidence evidence/ --output GAPS.md
aee graph --input claims.json --output claim-graph.mmd
aee gate --input assessment.json
aee demo   # self-contained demonstration assessment

# With the epistemic-ledger policy gates and measured source reliability:
aee assess --input claims.json --policy --reliability reliability.json
# Diff two assessments into a materiality-filtered review queue:
aee review --previous assessment-t1.json --current assessment-t2.json
```

Exit codes are CI-friendly: `0` for pass/warn, `1` for iteration/clarification/evidence
collection/abstention, and `2` for a hard block or invalid ledger.

**The ledger is the record; the JSON is a working copy** (Spec 002 FR-8.3). Each ledger
entry stores the assessment's SHA-256 alongside its project, phase, outcome, and claim
ids, so the entry — not the assessment file, which tools routinely overwrite on the
next run — is the durable record of what was assessed. The documented loop is
`aee assess` → `aee verify-ledger --ledger <path>`; the CLI and the spec-kit-aee
runner describe identical semantics (ledger by default, same default path,
`--no-ledger` as the explicit opt-out).

## Architecture

| Component | Install name / access name | Responsibility |
|---|---|---|
| Python engine | PyPI: `applied-epistemic-engineering`; import and CLI: `aee` | Claims, evidence, scoring, challenge, recovery, graph, ledger |
| [`spec-kit-aee`](https://github.com/electrohire/spec-kit-aee) | GitHub archive; Spec Kit extension ID: `aee` | Spec Kit commands, hooks, and artifact discovery |
| [`spec-kit-evaluator`](https://github.com/electrohire/spec-kit-evaluator) | GitHub archive; Spec Kit extension ID: `evaluator` | Shared result envelope, composition, reports, and model routing |

## What AEE can establish

AEE does not certify truth, compliance, safety, or general correctness. It records
claims, the evidence and checks supporting them, remaining uncertainty, and what
would change the decision. Records can be mistaken. A passing gate establishes
acceptance by the configured rules; a valid hash chain establishes continuity of
the retained records, not their truth. Formal proof tools can establish precisely
stated properties under explicit assumptions, but AEE is not a theorem prover or
an independent certification authority. See
[names and assurance boundaries](https://applied-epistemic-engineering.readthedocs.io/en/latest/names-and-assurance/)
for the distinctions and requirements for stronger, bounded assurance claims.

## Core principles

1. Assertions never become observations because a model repeats them.
2. Counterevidence and contradictions remain visible.
3. Unsupported claims remain explicitly unsupported.
4. Confidence propagates through dependencies by the weakest-link rule.
5. Every failure produces a bounded recovery proposal with a verification condition.
6. Deterministic checks run before probabilistic review.
7. Hash chains establish tamper evidence—not truth, identity, or trusted time.

## Documentation

Full documentation is published on Read the Docs at
[applied-epistemic-engineering.readthedocs.io](https://applied-epistemic-engineering.readthedocs.io).
How the engine, extension, and catalog versions relate is specified in the
[version policy](https://github.com/electrohire/applied-epistemic-engineering/blob/main/docs/versioning.md).

GitHub `main` and RTD `latest` can include unreleased documentation corrections.
RTD `stable` and the PyPI README reflect the tagged/uploaded release; a Git push
does not update PyPI metadata. See [development setup](https://github.com/electrohire/applied-epistemic-engineering/blob/main/DEVELOPMENT.md) for this
repository's own Spec Kit/AEE installation.

## Ownership and license

Designed and implemented by **ElectroHire Inc.** Copyright © 2026 ElectroHire Inc.
Released under the [MIT License](LICENSE).
