# Implementation Plan: Agent Board — Execution Substrate with the Spec-Kit Kernel (AB-001)

**Branch**: `agent-board-plan-2026-11-19` | **Date**: 2026-11-19 | **Spec**: [spec.md](spec.md) (pointer to ratified spec AB-001 as amended by Amendment 1)

**Input**: Spec AB-001 as amended, SHA-256 `213cf42fff149f0a3e6f4472efb2dbb26d22b84ce007393233f271d3a195c473`; design note as amended, SHA-256 `8b471ff895fc53887c3f4723f65c8b051b30f064005c96175706b5ac691570ff`. Ratification and the Section 9 decisions as taken are recorded in the spec's Sections 11 and 12.

## Summary

Build the Agent Board in two code homes. In this repo, a new top-level
module family `board/` beside `lifecycle/` and `program-ledger/` carries
the substrate (hash-chained append-only event log, single append command,
fold, state snapshots, generated tasks view, recovery), the kernel
(transition table in canonical machine form, verdict-gated completion,
amendments, assignment rules), the keeper, and the weekly audit scripts.
In `electrohire/spec-kit-aee`, the extension ships the kernel definitions,
hash-pinned to the canonical form in this repo with a freshness test until
generation replaces pinning. The pilot then stands up two boards in the
owning program's workspace: the ninety-day program's governance board and
one ordinary suite campaign board, under a hard contamination boundary —
no board row may belong to, or resolve into, a study arm of the
ninety-day program.

This plan artifact and its task list are the deliverable of the
ratification's planning step. No task in this plan is executed by the PR
that lands the plan.

## Technical Context

**Language/Version**: Python ≥ 3.11 (`pyproject.toml` `requires-python`),
following the `lifecycle/` and `program-ledger/` families: standalone
modules with their own `schema.json`, run directly
(`python3 board/intake.py`-style entry points), tested from `tests/`.

**Primary Dependencies**: None at runtime — the engine is dependency-free
by design and the board family inherits that. The append command uses the
standard library only (`fcntl.flock` on POSIX; the pilot's boards live on
Linux hosts). Dev/test: pytest, ruff, mypy as per repo CI.

**Storage**: Files only, caller-provided. One canonical board directory
per board in the owning program's workspace (ratified storage decision):
`events.jsonl` (the log), the folded state file, the lock file, the
generated tasks view, and, after any recovery, a recovery file beside the
log. The daily git commit of the board directory is a backup snapshot,
never a sync mechanism; any other checkout is read-only.

**Testing**: pytest (`tests/test_board_*.py`), one test per kernel
transition-table row plus refusal tests per guard; drills as tests
(concurrent append, kill-mid-append, retry-after-lost-confirmation,
torn-tail recovery, fork recovery, lost-wakeup race, genesis fold). Ruff
(line-length 100) and the program gate (`tools/gate.py`) run as on every
change in this repo.

**Target Platform**: Linux VM hosts of the fleet (the append lock and the
verified-append discipline are specified against the gatekeeper's proven
patterns on those hosts). The keeper and the dead-keeper detector run as
scheduled jobs, each owned by a named chat; the detector's chat is never
the keeper's chat.

**Project Type**: Single-repo module family in this repo (`board/`), plus
a definitions surface in the spec-kit-aee extension repo. No changes to
`src/aee`: the engine's claim machinery and ledger formats are consumed by
reference and are unchanged.

**Performance Goals**: One bound, from the spec: at pilot scale (a log of
at most 10,000 events) a fold from genesis completes in under 60 seconds
on the owning VM, drill-tested. The normal read path is the state file; a
full fold is an audit and recovery operation only. A board whose log
exceeds 10,000 events raises archival at its weekly audit; it does not
silently change the read path.

**Constraints**:

- Append-only history. Events are the only way state changes; corrections
  and recoveries are new events, never edits. The fold never repairs
  silently and is never edited into passing.
- Verified writes are the standard for the log append and the state file:
  full-write loop, fsync, size/read-back verification, loud failure.
- Canonical hashing is pinned per event (JSON, sorted keys, Unicode NFC,
  separators `,` and `:`, UTF-8, LF), and board directories carry
  `.gitattributes` `eol=lf` lines so checkouts cannot reintroduce the CRLF
  divergence the engine's Stage 2 defect documented.
- A payload's verdict is its own record, never a wrapper's completion
  state. `execution_state` is transport fact only and may never be
  rendered as completion (both fields shown, or neither).
- Actor-based guards are accountability controls in the pilot (actors are
  self-attested; the append service stamps only the `writer`). Mechanical
  guards — legal transitions, state-based guards, the favorable-verdict
  requirement, WIP counts, cycle refusal — are enforced by the fold.
- Contamination boundary: the board does not enter the ninety-day
  program's study arms' execution path. The boundary is a task-level
  constraint on every pilot task and has a weekly scripted detector (the
  boundary audit); without that audit running, the boundary is policy
  only and must be described as such.

**Scale/Scope**: Pilot scale only: two boards, each far below the
10,000-event fold bound; keeper cadence 30 minutes; WIP limits 4
(governance board) and 3 (suite campaign board), pinned in Amendment 1
Part 4 and recorded at each board's genesis.

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md`.*

- **I. Assertions Never Become Observations** — the board records what it
  is told; completion requires an external verdict record, and the fold's
  refusal discipline keeps unprovenanced state changes out. PASS.
- **II. Claims Are Bounded, Atomic, and Evidence-Linked** — the pilot's
  claims KB-1..KB-6 each carry a falsifier and a boundary line in the
  spec; their registration is a separate governed motion, not assumed by
  this plan. PASS.
- **III. Counterevidence and Contradictions Stay Visible** — unfavorable
  verdicts route rows back to `in_progress` or `withdrawn` on the record;
  missed wakes, planner overrides, and discarded recovery branches are
  counted and reported, never silently absorbed. PASS.
- **IV. Unsupported Stays Unsupported** — verdict favorability is checked
  per claim in a row's `claim_ids`; a row whose claims are not all
  favorably resolved cannot reach `done`. PASS.
- **V. Deterministic Before Probabilistic** — routing, matching for
  mechanical wait kinds, folding, and auditing are deterministic; prose
  matching is confined to `external_prose` waits and is forbidden for
  dependency and named-event waits. PASS.
- **VI. Every Failure Produces Bounded Recovery** — recovery is a
  procedure with preserved evidence (torn tail, fork), a halt state, and
  named authorization; no silent repair path exists. PASS.
- **VII. Hash Chains Are Tamper Evidence, Not Truth** — the spec's own
  framing: the chain detects tampering and reordering; it does not
  establish that events were truthful, and whole-log rewrite is answered
  by committed, gate-checked state snapshots, not by chain claims. PASS.
- **VIII. Thresholds Carry Measure Provenance** — every pinned pilot
  number (cadence, deadlines, WIP limits, sample caps, the fold bound)
  comes from Amendment 1 Part 4 with a one-line justification and is
  recorded at genesis. PASS.

No violations. No complexity exceptions required: the design reuses the
repo's existing family pattern (`lifecycle/`, `program-ledger/`) and the
gatekeeper's proven append and lock discipline rather than adding new machinery.

## Project Structure

```text
board/                          # this repo, new module family
    README.md                   # layout, entry points, operating rhythm
    schema.json                 # pinned row + event + genesis-field schema
    canonical.py                # canonical serialization + per-event hashing
    append.py                   # the append command (lock, idempotency, verified append)
    fold.py                     # fold + chain verification
    state.py                    # state snapshots, freshness labeling
    recover.py                  # torn-tail / fork recovery procedures
    kernel.py                   # canonical transition table + guards (Section 4.7 form)
    verdicts.py                 # verdict attachment + per-class favorable checks
    view.py                     # generated tasks view
    keeper.py                   # keeper: carriage, matching, sweeps, heartbeat
    metrics.py                  # weekly metrics + pilot overhead report generator
    audits.py                   # KB-2 / KB-5 / KB-6 / trace / boundary / drift checks
tests/
    test_board_canonical.py
    test_board_append.py        # incl. concurrency + kill + retry drills
    test_board_fold.py          # incl. 10,000-event fold bound drill
    test_board_kernel.py        # one test per table row + guard refusals
    test_board_verdicts.py
    test_board_recovery.py      # torn-tail + fork drills
    test_board_keeper.py        # incl. lost-wakeup race drill
    test_board_view.py
    test_board_audits.py
specs/008-agent-board/          # this plan trio (spec pointer, plan, tasks)
```

The spec-kit-aee side (Phase 5 of the task list) adds the shipped kernel
definitions and their freshness test inside that repo's existing layout;
it does not change this repo.

**Structure Decision**: The substrate is a module family beside
`lifecycle/`, per the ratified hosting decision — not a package under
`src/aee`, because the engine's shipped library surface and its claim
machinery are consumed unchanged, and the repo's record families
(`lifecycle/`, `program-ledger/`) already establish the standalone-family
pattern with pinned schemas and intake-style entry points.

## Phases

- **Phase 1 — Substrate** (tasks T001–T007): canonical hashing, schema,
  the append command, fold and chain verification, state snapshots,
  recovery, the generated view. The fold's transition legality depends on
  the kernel table's machine form, so T008 (Phase 2) is pulled forward as
  a data dependency of T004; the phases are an accounting order, not a
  claim that Phase 1 finishes before Phase 2 starts.
- **Phase 2 — Kernel** (T008–T012): the transition table including
  genesis and halt/resume, resumption-note checks, verdict attachment and
  per-class favorable checks, amendment mechanics with cycle refusal,
  assignment rules.
- **Phase 3 — Keeper** (T013–T017): event carriage with citation
  discipline, matching and the append-path wake mechanics, sweep defense,
  the scheduled keeper job, and the dead-keeper detector owned by a
  different chat.
- **Phase 4 — Audits and metrics** (T018–T024): the weekly GATEs (KB-2,
  KB-5, KB-6, artifact-trace, boundary, kernel drift) and the weekly
  metrics and overhead report generator.
- **Phase 5 — Extension kernel definitions** (T025–T026), in
  electrohire/spec-kit-aee: ship the definitions hash-pinned to the
  canonical form with a freshness test; generation from the canonical
  form is a named later task, not a pilot blocker.
- **Phase 6 — Pilot** (T027–T032): genesis of both boards, the KB-1
  baseline pass, KB-3 sampling instrumentation, the weekly rhythm live,
  and the pilot verdict report. Every pilot task carries the
  contamination boundary as a constraint.

## Sequencing and sizing

Each task is sized at one PR or less, in its own repo. The critical path
is T001 → T002 → T008 → T003 → T004 → T005, then kernel completion
(T009–T012), keeper (T013–T015), audits (T018–T023), and only then pilot
genesis (T027–T028): no board goes live before the audits that watch it
exist. The extension tasks (Phase 5) can proceed in parallel with Phases
3–4 once T008 lands, because the pin is over T008's canonical form.

## What this plan does not do

- **Claim registration is not a build task.** Registering KB-1..KB-6 in
  the program ledger (all six at status `draft`, with evidence refs and
  falsifiers per the spec's Section 8 registration shape) is a separate
  governed motion through the program-ledger intake, taken on its own
  after ratification. It appears in no phase above.
- No task changes a running system: the gatekeeper, the engine's ledgers,
  and the ninety-day program's study machinery are untouched. The keeper
  reads the gatekeeper's records; it does not modify the gatekeeper.
- No task builds caller authentication, a fleet keeper service, or
  cross-team boards; all three are out of the pilot's scope by the spec.
