# Transparent scoring

The default direct confidence score is:

```text
0.55 × evidence quality
+ 0.20 × source independence
+ 0.15 × falsifiability
+ 0.10 × explicit boundary
- contradiction penalty
- freshness penalty
```

Evidence quality combines evidence kind and source quality. Multiple supporting sources use a
bounded cumulative calculation; repeated weak assertions cannot inflate confidence without limit.

After direct scoring, required dependencies apply the weakest-link rule:

```text
propagated(claim) = min(direct(claim), propagated(each required dependency))
```

Scores communicate the state of the recorded evidence. They do not measure metaphysical truth,
legal sufficiency, or safety certification.

## Optional decision policies and review

An explicit assessment policy can require independent corroboration, abstain
when support is absent or solely model self-attestation, and challenge claims
with counterevidence. Stage caps still apply; a score never ratifies a claim.
Source reliability can blend recorded resolved outcomes into evidence quality.
The review queue highlights material changes between assessments rather than
requiring an unbounded re-review of every unchanged claim.

Defaults are decision rules, not probabilities of truth or universal constants.
Their measurement provenance is recorded with the implementations in
`aee.policy`, `aee.reliability`, and `aee.review`; a changed workload needs its own
validation before changing a threshold. Record policy identity, thresholds,
source provenance, and counterevidence with the decision. See
[use cases and evaluation](use-cases.md) for evaluating an agent-loop benefit.

## Scoring methodology and lexicon versions

These version numbers describe different parts of an assessment; they are not
competing versions of AEE.

| Version | What it identifies | Current value |
| --- | --- | --- |
| Engine package | The installed `applied-epistemic-engineering` software release, reported as `metadata.engine_version` | 1.5.2 |
| Scoring methodology | The meaning of scores and decision rules, recorded as `methodology_version` | 2.0 |
| Lexicon data | The vocabulary lists used by challenge/scoring heuristics, defined as `LEXICON_VERSION` in `src/aee/lexicons.py` | 1.0 |

The methodology is 2.0 because its semantics changed from the earlier methodology.
The vocabulary dataset remains 1.0 because it follows its own change history.
An engine bug fix or documentation update does not automatically increment either.
If a lexicon change alters scores on existing inputs, the methodology version
must also change so consumers know that the scores are no longer comparable.

Do not rename the published methodology 2.0 to 1.0 merely to make the labels
match. Earlier 1.0 results and current 2.0 results would then share a label with
different meanings. A future methodology change needs an explicit compatibility
policy and recorded versions; historical assessment records must not be relabeled.

The semantics below describe scoring methodology **2.0**.

**Threshold.** The confidence threshold is *inclusive* — a
propagated score of exactly the threshold passes — and the
comparison is performed on the **unrounded** score. Rounding is a
display concern only and can never move a claim across the
threshold (FR-8.13).

**Declared state.** Every score record carries the author's
declared `status`, `uncertainty`, `severity`, and `conflicts_with`
verbatim (`declared_state`), whether or not they move the number,
so a score-only consumer can distinguish a claim its author marked
`contradicted` from a settled claim with the same evidence
(FR-8.13).

**Freshness (FR-8.6).** The freshness basis is the whole supporting
set, never its newest member. Each supporting item is classified
*fresh* (observed ≤ 90 days before the assessment), *recent*
(91–365 days), *stale* (> 365 days), or *unknown* — no date, an
unparseable date (a finding in its own right), or a future date
(invalid input; a future date can never make a claim fresher than
present evidence). The penalty is the mean of the tier penalties
(0 / 0.05 / 0.10) across the set, with **unknown counting as
stale**: unknown freshness is reported as unknown in the score
notes, and is never treated as fresh. One fresh item therefore no
longer erases the staleness of the rest of the set, and omitting
dates no longer scores better than honestly dating old evidence.
The set composition behind every penalty is named in the score
notes.

**Falsifiability and boundary: substance over presence (FR-8.7).**
Presence alone earns no full credit. A falsification test earns
full credit only if it (i) is at least four words, (ii) is not a
placeholder (single token, repeated character, or a placeholder
token), and (iii) states a checkable condition — a numeric bound
or unit, a comparator, or an observation/action term from the
falsifiability lexicon. A boundary entry earns full credit only if
it is not a placeholder and names a scope or limit — a term from
the boundary scope lexicon or a numeric bound. Below-bar entries
earn partial credit (0.5), the component is the mean over entries,
and the score notes name the criterion each below-bar entry
failed. The lexicons are versioned data, not code (FR-8.8).

**Propagation is cycle-local (FR-8.3).** A dependency cycle
suppresses propagation only inside its strongly connected
component: members keep their direct score as their propagated
score, marked `suppressed_cycle` with the component named on
their score records. Every other claim propagates normally —
including claims that depend on a cycle component, whose weakest
link is the members' direct scores. The bundle-level cycle failure
still fires.

**Verdicts are failure-aware (FR-8.4) and contested shares one
basis (FR-8.5).** A claim carrying an unresolved HIGH or CRITICAL
failure mode cannot receive an ACCEPT verdict; the verdict's
reasons name the failures that demoted it. "Contested" means the
claim's record carries counterevidence — any item directed
against it, whatever its kind weight, or a contradicted-kind item
routed in any other direction — the same basis on which the
challenge layer routes a claim to `clarify`, so the standalone
policy gate and the engine agree.

**Challenge lexicons and their limits (FR-8.8, FR-8.9, FR-8.15).**
The compound-connective and vague-term lexicons are versioned
data (`src/aee/lexicons.py`). Noun-phrase-internal lists and
alternatives (version lists, unit alternatives such as "Celsius or
Fahrenheit", range idioms such as "65 and older") and vague words
inside proper nouns do not draw challenges. The negation-conflict
detector requires a shared *subject* plus shared content tokens;
it is a heuristic, not a semantic contradiction proof — a
paraphrase that changes both the subject's surface form and the
vocabulary remains undetectable, and that residual limit is
accepted and recorded rather than papered over.


## The two lanes (Spec 004 R6/R8)

Every assessment reports two lanes as a pair, per claim and per
bundle, under `lanes` in the assessment JSON and as two sentences in
the summary. **Lane 1 (machine verification)** is the score, the
threshold comparison, and the outcome — everything this document
describes. **Lane 2 (human acceptance)** is state, never a score:
each claim's effective lifecycle stage and whether it was capped
(and why), whether a named human has explained it (exposition), the
verified-but-unexplained count, and contested attributions. The
lanes are never blended into one number, and the lane-2 sentence is
emitted wherever the lane-1 outcome is stated — a green lane 1 with
a lagging lane 2 (claims still at `created`/`checked`, or checked
but unexplained) is reported as exactly that, not as settled work.

## Lifecycle stage and stage caps (Spec 004)

Scores are lane-1 quantities: what machine checking established.
Separately, every claim carries a lifecycle **stage** — `created`,
`checked`, `explained`, `accepted`, `digested` — advanced only by
recorded stage events, never by score. The stage caps the vocabulary
an assessment may report (OD-T3, R1.3): at `created` a claim reports
`draft` only and receives no policy verdict (`unjudged`); at
`checked` it cannot report `supported` and its verdict ceiling is
`challenge`; at `explained` it may report `supported` in qualified
form (ceiling still `challenge`); `accept` requires stage `accepted`
or `digested`. A bundle `pass` is reported only when every covered
claim is at stage `explained` or beyond. Caps never change a score
and never raise a posture; a binding cap is recorded on the
assessment (`stage_caps`, plus a `stage_cap` failure mode naming the
recorded event that would lift it).

Exposition evidence — a named human's explanation of a claim —
resolves its `source_id` against a project-local identity registry
(OD-T4): only entries of kind `person` resolve; tools, models, and
team aliases are rejected at load time.

Dependencies are author-declared: propagated scores are conditional
on the declared `depends_on` set, and an omitted dependency is
undetectable by the engine (Spec 003 FR-8.14).
