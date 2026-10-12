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
