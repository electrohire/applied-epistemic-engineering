# Three ways to use AEE

| Route | What the user does | What executes |
| --- | --- | --- |
| CLI / Python | Run `aee` commands or call the Python API | Standalone engine from PyPI `applied-epistemic-engineering` |
| Direct agent skill | Ask an agent to inspect claims and evidence in ordinary language | Standalone engine, guided by `applied-epistemic-engineering/SKILL.md`; no Spec Kit required |
| Spec Kit extension | Ask the project's agent to assess a spec, plan, tasks, or implementation | Installed AEE lifecycle skills, adapter runner, engine, and evaluator companion |

These are interfaces to the same evidence model, not three different scoring
systems. None turns an agent's assertion into observed evidence.
The [use-case guide](use-cases.md) shows where these interfaces fit in agent
loops and how to measure, rather than assume, hallucination-reduction benefits.

## Direct agent use

The maintained standalone skill is
[`src/aee/skills/applied-epistemic-engineering/SKILL.md`](https://github.com/electrohire/applied-epistemic-engineering/tree/main/src/aee/skills/applied-epistemic-engineering).
Ask your agent to install that folder in its supported project skill directory
(for example `.agents/skills/applied-epistemic-engineering/` for Codex), or give
it the file explicitly. Reload the agent if required by its skill discovery.
Do not replace a customized installed skill without reviewing the changes.

Then ask, for example:

> Use the applied-epistemic-engineering skill to review the claims in
> `specs/search/spec.md` against `evidence/search/`. Explain what is supported,
> what is uncertain, and the smallest next checks. Keep the source artifacts unchanged.

The agent resolves scope, prepares draft claims where needed, runs assessment
and ledger verification, and explains saved results. It handles CLI syntax and
dependency setup within your request; you supply the artifacts and judgment.
Scores cannot ratify a draft or stand in for human acceptance.

The standalone skill is included in engine 1.5.3 and later.
The package source includes the skill under `aee/skills/` so wheels and source
distributions can carry the same instructions; installation of a Python package
alone does not register a skill with every agent.

## Use through Spec Kit

Ask the agent to initialize Spec Kit and install AEE for the project, preserving
your existing work. The preferred catalog command is `specify extension add aee`
for the project. For errors on an older installation, see the
[troubleshooting guide](https://github.com/electrohire/spec-kit-aee/blob/main/DEVELOPMENT.md#troubleshooting-older-installations).

Spec Kit renders ten AEE skills from the adapter's command documents and four
evaluator skills from the companion's commands into the active integration's
directory. The agent should read the installed `SKILL.md` for the operation;
the user need not type a slash command or use a terminal. For example:

> Assess this feature's spec with AEE, challenge unsupported requirements, and
> tell me what evidence is missing before planning.

The optional onboarding skill in
[`spec-kit-aee/skills/spec-kit-aee`](https://github.com/electrohire/spec-kit-aee/tree/main/skills/spec-kit-aee)
helps an agent set up and discover those operation skills. The evaluator also
provides a
[`evaluator-contract` skill](https://github.com/electrohire/spec-kit-evaluator/tree/main/skills/evaluator-contract)
for composition/reporting. The onboarding skills are included from AEE extension
1.5.2 and evaluator 1.1.2. Operation skills are generated during extension installation.

An agent needs permission and working tools to execute the workflow. If it can
only chat, it can explain the artifacts but cannot truthfully claim it ran checks.
Deterministic AEE checks require no model API key, while your chosen agent's
inference service has its own setup. See [names and assurance boundaries](names-and-assurance.md).
