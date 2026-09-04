# Migration guide

This package is a ground-up ElectroHire implementation, not a drop-in replacement for other AEE
packages. The concepts remain recognizable, while the types, serialization format, scoring model,
CLI, and Spec Kit boundary are intentionally explicit and independently versioned.

## Concept mapping

| Prior concept | ElectroHire AEE equivalent | Important change |
| --- | --- | --- |
| Belief/claim | `aee.Claim` | Stable IDs, sources, boundaries, dependencies, conflicts, and falsifiers are first-class |
| Evidence refs | `aee.Evidence` | Kind, direction, source quality, independence, observation time, and content hash are separate |
| Stress tester | `aee.StressTester` | Checks are deterministic and every breakpoint has a stable failure ID |
| Failure graph | `aee.ClaimGraph` | Missing dependencies, cycles, conflicts, order, and Mermaid rendering share one graph |
| Certainty engine | `aee.ScoringEngine` | Published weights replace opaque confidence; dependencies use weakest-link propagation |
| Recovery operator | `aee.RecoveryOperator` | Every recovery includes a verification condition and deterministic priority |
| AEE session | `aee.AEESession` | Library-first orchestration with an optional append-only ledger |
| Trace vault | `aee.HashChainLedger` | Canonical JSONL SHA-256 chain establishes continuity, not truth or identity |
| Result | `aee.Assessment` | Rich output converts to Evaluator Contract 1.0 through `EvaluatorAdapter` |

## Minimal migration

Instead of importing `epistemic`, install the new distribution and import `aee`:

```bash
pip install applied-epistemic-engineering
```

```python
from aee import AEESession, ClaimKind

session = AEESession("my-system", phase="after_plan")
session.add_claim(
    "ASM-IDENTITY-001",
    "The upstream identity is verified",
    kind=ClaimKind.ASSUMPTION,
    boundary=["production OAuth callback"],
    source_ref="plan.md#ASM-IDENTITY-001",
)
assessment = session.assess()
```

The initial outcome remains evidence-seeking until independently inspectable evidence and a
falsification test are attached. That is deliberate.

## Deliberate exclusions

- No private runtime dependency or backend coupling.
- No ChronoMemory code or commercial storage integration.
- No model-generated confidence masquerading as observed evidence.
- No compatibility aliases that obscure which implementation produced a record.

For Spec Kit projects, install `spec-kit-evaluator` and `spec-kit-aee`; keep domain logic in this
package and lifecycle orchestration in the extension.
