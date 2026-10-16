# Names and assurance boundaries

## Which name belongs where?

| Surface | Name | What it identifies |
| --- | --- | --- |
| PyPI distribution | `applied-epistemic-engineering` | The independently usable Python engine; install with `python -m pip install applied-epistemic-engineering` |
| Python import | `aee` | The module installed by that distribution; for example, `from aee import AEESession` |
| Engine CLI | `aee` | The executable installed by that distribution; for example, `aee --version` |
| Spec Kit extension repository | `electrohire/spec-kit-aee` | The adapter distributed as a GitHub release archive |
| Spec Kit extension ID | `aee` | The adapter selected by `specify extension add aee` |
| Evaluator extension repository / ID | `electrohire/spec-kit-evaluator` / `evaluator` | The companion contract, composer, reports, and routing |

The Python module and the Spec Kit extension share the short name `aee`, but they
are different components. **Do not use `pip install aee` as an installation command
for this engine.** The distribution name is `applied-epistemic-engineering`.
Neither Spec Kit extension is installed with pip. The `aee` extension installs a
compatible engine and its evaluator companion automatically on first use; see
the [Spec Kit integration guide](spec-kit.md).

## What does an AEE result establish?

AEE records claims, their declared boundaries, evidence references, verification
results, uncertainty, and decisions. The record can contain mistakes: a source
may be wrong, a boundary incomplete, or an observation misinterpreted. A passing
gate means the configured policy accepted the recorded assessment. A score is a
decision aid, not a calibrated probability that a proposition is true. Human
acceptance remains distinct from machine verification.

| Result | Defensible interpretation | What it does not establish |
| --- | --- | --- |
| Schema validation | This input satisfies the checked structural rules | Its assertions are true |
| Evidence verification | The configured reference/hash checks passed for the inspected artifacts | The source is truthful or the experiment is sound |
| Ledger verification | The retained entries form a valid hash chain | Truth, author identity, trusted time, or absence of an unanchored rewrite |
| Passing tests | These test cases passed on the recorded artifact and environment | Correct behavior for every possible input or deployment |
| Policy acceptance | The configured decision rules accepted this assessment | Independent safety, compliance, or correctness certification |

## Could AEE certify truth?

There is no general engineering procedure that turns arbitrary empirical claims
into an unconditional guarantee of truth. Evidence can support a bounded claim
and expose counterexamples; finite observations do not establish every future
case. This does not mean tools cannot prove anything. A formal proof checker can
establish a precisely stated proposition relative to its logic, definitions,
axioms, and trusted implementation. That proof does not by itself establish that
the formal model describes a particular real deployment. See the Lean reference
on [axioms](https://lean-lang.org/doc/reference/latest/Axioms) and
[validating proofs](https://lean-lang.org/doc/reference/latest/ValidatingProofs/).

AEE currently provides neither a general theorem prover nor an independent
certification authority. To support a stronger **bounded assurance claim**, a
future integration would need:

1. A precise property, artifact version, operating boundary, and explicit assumptions.
2. A suitable independent verifier, with reproducible proof or measurement artifacts,
   recorded verifier versions, and a stated trusted computing base.
3. Checks that the inspected artifacts match the deployed system and that the model
   and measurements cover the claimed boundary, including counterevidence.
4. A domain-appropriate review or certification process, where one is claimed,
   with a responsible decision maker and clear expiration/reassessment conditions.

Such an integration should report, for example, “verifier V checked property P
for artifact hash H under assumptions A,” with links to inspectable evidence.
AEE could retain and challenge that result. It should not relabel the result as
“AEE certifies truth,” or infer certification from an `accept`, `pass`, or
high-confidence status.

## Why can the public pages differ?

GitHub `main` and RTD `latest` describe ongoing development. RTD `stable` describes
the latest tagged release. PyPI's project description comes from the README
embedded in an uploaded distribution; pushing a README change to GitHub does not
change that published metadata. Documentation-only corrections are collected in
the changelog's Unreleased section for the next planned release. Existing tags,
archives, and package files remain unchanged.
