# Spec 004 — P2 implementation record (policy gates)

Branch `impl/004-p2-policy-gates` off P1 head b0f6958. Ratified
2026-10-12 (see spec §9 / plan §0). Claims first: the Spec 004
bundle was assessed before and after with the real assessor.

## Claims before / after

| Measure | Before (P1 build) | After (P2 build) |
|---|---|---|
| TA-004-12..20 mean (after_specify, 0.70) | 0.481 | 0.481 |
| TA-004-21 | 0.997 | 0.997 |
| Outcome | ITERATE | ITERATE |
| `not_understood` on the bundle | field did not exist | 63 entries |
| Suite | 584 passed | **597 passed** (+13 P2 tests; fixture updates below) |

P2 changes policy and reporting, not lane-1 scores — the numbers
holding is the acceptance signal. On this bundle every claim sits
at the lenient-load default `created`, so no verified-unexplained
flag fires (the flag starts at `checked`) and all 21 verdicts are
unjudged; the 63 not-understood entries enumerate the defaulted
stages, open challenge categories, and declared-but-unrecomputed
content hashes. That is the field working as specified on an
un-migrated bundle, not noise.

## What landed

- **R5.1 machine-only gate** (`policy.machine_only_reason` /
  `machine_only_overrides`): a claim whose supporting evidence is
  exclusively machine-checkable — kind ∈ {observed, inferred} AND
  source quality ∈ {test, artifact, model} — is capped at effective
  stage `checked`, whatever its stored stage says. The cap record
  names the evidence composition ("2 observed/test"). Any
  human-paced supporting item (exposition, asserted, or a
  human/primary/secondary source) lifts it. A claim with no
  supporting evidence is not machine-only — absence belongs to the
  abstention path. Scores are untouched: the gate moves stages,
  verdicts, and reports only (pinned by test).
- **R3.3 verified-but-unexplained** (`verified_unexplained`
  category, MEDIUM): one risk record per claim at stage `checked`+
  with no exposition evidence. It is a state, not a correctness
  failure: `_NON_OUTCOME_CATEGORIES` excludes it (and `stage_cap`)
  from outcome routing, from the summary's disposition counts, and
  the gate's recompute mirrors the same exclusion.
- **R5.2 mandatory `not_understood`**: `Assessment.not_understood`
  is always serialised. Entries are generated from inspectable
  state — stage-cap notes, verified-unexplained flags, incomplete
  decompositions, lenient stage defaults, open challenge
  categories, sub-threshold scores, declared-but-unrecomputed
  content hashes — plus author-supplied entries via assessment
  metadata. The summary carries the count line whenever entries
  exist ("Not understood: N residual unknown(s)…"), so the
  statement travels with the verdict text (R5.3/R6.3).
- **R5.3 gate completeness**: `aee gate` rejects an assessment
  with no `not_understood` field, a malformed one, or an empty one
  while the record carries open items (exit 2). Pre-realignment
  assessments fail here by design — the gate is where silence
  stops being a compatibility strategy.
- **Gate consistency fix (found by P2 tests)**: the gate's R1.3
  cross-check and R1.4 recompute previously recomputed caps from
  the STORED stage, so any assessment carrying a P1/P2
  effective-stage override failed its own gate. The gate now reads
  the recorded `stage_caps` as the effective-stage record,
  validates each record against its own stage (a record may only
  lower a stage, and its stated cap must equal the cap of the
  author status at that stage), and falls back to the stored stage
  when no record exists.

## Fixture updates (tests changed, with reasons)

R5.1 is a semantic change to what an all-machine bundle earns, so
fixtures written before it — "clean"/ratified bundles built from
observed/test evidence only — now cap exactly as the rule says.
Eight test files gained one human-paced item (observed/primary or
equivalent) in the fixture whose intent is an uncapped claim, each
annotated in place: test_tao_p0 (strong_claim helper),
test_policy (clean_claim), test_cli_policy (JSON strong_claim;
the single-source test slices back to one item), test_review,
test_score_inflation, test_tao_p1 (headline), test_engine_adapter,
test_dispositions_independence. No assertion was weakened; the
fixtures now model the human-paced support they always claimed to
represent.

## Honest limits

- The machine-only partition is a composition rule over declared
  kind/quality labels. An author can launder machine output through
  a `primary`-labelled item; the labels are claims, and the cap
  record names the composition so a reviewer can see exactly what
  lifted the cap. Catching mislabelled provenance is RT1-07's open
  design question, not something P2 pretends to solve.
- `not_understood` is generated from assessment state; it cannot
  name unknowns the record itself does not carry. The
  author-supplied channel exists for those, and the gate can only
  require presence, not insight.
- No CLI flag for author-supplied entries in this phase (metadata
  via the API suffices); surface alignment is P5.
