# Applied Epistemic Engineering

Applied Epistemic Engineering (AEE) treats consequential claims as engineering artifacts:
identifiable, bounded, challengeable, evidence-linked, recoverable, and auditable.

The PyPI distribution **`applied-epistemic-engineering`** installs the Python
module and CLI **`aee`**. The separate **`spec-kit-aee`** repository supplies the
Spec Kit extension whose ID is also **`aee`**. See
[names and assurance boundaries](names-and-assurance.md) for installation names
and the limits of verification.

The Python engine provides:

- a typed claim and evidence model;
- deterministic stress tests;
- explicit contradictions and dependency graphs;
- transparent evidence-quality scoring;
- bounded recovery proposals;
- a tamper-evident decision ledger; and
- native conversion to the Spec Kit Evaluator Contract.

!!! important
    AEE does not certify truth, compliance, safety, or general correctness. It records
    claims, the evidence and checks supporting them, what remains uncertain, and what
    evidence would change the decision. The record itself can be incomplete or mistaken.
    A passing policy gate or valid ledger is not an independent certification.

Choose [CLI, direct agent, or Spec Kit](agent.md), then use the
[quickstart](quickstart.md) and [foundations](concepts.md).
See [use cases and agent loops](use-cases.md) for evidence-aware completion gates,
handoffs, disagreement review, and how to evaluate effects on unsupported claims.
