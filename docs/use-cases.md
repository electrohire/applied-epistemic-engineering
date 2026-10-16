# Use cases and agent loops

AEE helps make consequential claims inspectable. It is useful when an agent or
team needs to distinguish “someone said this” from “we checked this,” preserve
disagreement, and identify the next evidence needed. Use it through the
[CLI, direct agent skill, or Spec Kit extension](agent.md).

## Where it helps

| Situation | AEE workflow | Practical benefit and boundary |
| --- | --- | --- |
| An agent says a feature is finished | Link requirement claims to real test/build artifacts; assess before a completion gate | Unsupported completion claims become visible; passing tests cover only their recorded scope |
| A multi-step research or coding loop reuses earlier output | Carry source references, claim dependencies, contradictions, and uncertainty across iterations | Repetition does not become independent corroboration; the sources still require inspection |
| A spec contains ambiguous or unverifiable requirements | Draft atomic claims, challenge boundaries and falsification conditions, propose recovery | Focuses clarification and evidence collection before implementation |
| Several agents or tools disagree | Retain separate evaluator findings and compose with an explicit policy | Makes disagreement reviewable instead of manufacturing consensus |
| A long-running task changes hands | Preserve assessment artifacts and a tamper-evident decision history | Supports an inspectable handoff; a hash chain does not make the recorded claims true |
| Evidence is missing or changes | Compare assessments, inspect gaps, and target bounded follow-up work | Helps direct review effort; missing evidence remains unresolved until checked |
| A review needs a defensible decision trail | Record what was assessed, boundaries, versions, findings, and human acceptance separately | Supports review and audit work; does not itself grant compliance or safety certification |

## How this relates to hallucinations

An agent can invent a source, misread a file, claim tests ran when they did not,
or repeat an earlier guess as if it were verified. AEE's workflow can help expose
these unsupported claims before they drive another action:

- Classify model-generated statements as assertions until supported by inspectable
  artifacts; extraction alone creates drafts, not observations.
- Check evidence references and available hashes where appropriate. A resolvable
  reference establishes access/integrity checks, not that its contents are correct.
- Preserve source identity and dependencies. Multiple agents repeating one source
  are not automatically independent evidence.
- Challenge contradictions, unbounded language, and claims without a way to falsify
  them; turn defects into specific recovery work.
- Keep configured policy outcomes and machine verification separate from human
  acceptance. A high score cannot promote a claim to accepted or digested.
- Retain uncertainty and `not_understood` with the verdict instead of hiding them
  in a summary or a successful tool exit.

These controls **may reduce the propagation of unsupported claims when the agent
actually follows them**. They are not a hallucination detector with a guaranteed
recall rate, a truth oracle, or a replacement for source validation. An agent can
still choose a wrong claim, invent evidence metadata, inspect evidence badly, or
ignore a result. Stronger workflows execute independent tools, preserve their
real outputs, and make the decision gate enforceable rather than merely advisory.
No project-wide quantitative hallucination-reduction claim is established here.

## Example loop

1. Ask the agent to implement a bounded requirement and preserve the source/test artifacts.
2. Before accepting “done,” ask it to identify explicit claims, observed results,
   counterevidence, and what remains uncertain. New claims start as drafts.
3. Run the engine's assessment and relevant evidence checks. An agent skill handles
   the commands; Spec Kit can place the same check after a lifecycle phase.
4. Inspect recovery requests or blocks. Run the missing test, narrow the claim, or
   request a decision. Do not synthesize an observed result to clear the gate.
5. Reassess after the evidence changes, retain the records, and ask a responsible
   human to accept the bounded conclusion where human acceptance is required.

For example: “Use AEE to check whether the implementation satisfies REQ-SEARCH-1.
Inspect the actual test output, challenge unsupported conclusions, and explain
what must be checked before I accept it.” This is useful even if the result is
“insufficient evidence.” The goal is a better-supported decision, not a green score.

## How to measure improvement

Evaluate a representative, held-out set of tasks with known claim-level outcomes.
Define an unsupported or false claim and how independent reviewers adjudicate it.
Compare paired baseline and AEE-assisted runs with recorded model/tool versions,
prompts, budgets, and equivalent access to evidence. Include invented references,
repeated/circular sources, real contradictions, missing evidence, and genuine passes.

Report false/unsupported claims that reach the final answer or next action, missed
defects, false alarms, abstentions, task success, review effort, latency, and cost,
with denominators and uncertainty. Retain raw artifacts and distinguish “a check
flagged it” from “the agent corrected it” and “the downstream gate stopped it.”
Do not generalize one benchmark's results to every model, task, or deployment.
See [assurance boundaries](names-and-assurance.md) for what stronger verification
claims would require.
