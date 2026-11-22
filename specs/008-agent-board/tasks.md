# Tasks: Agent Board — Execution Substrate with the Spec-Kit Kernel (AB-001)

**Input**: Design documents from `specs/008-agent-board/` — [plan.md](plan.md) (required), [spec.md](spec.md) (pointer to ratified spec AB-001 as amended; the spec's section numbers are cited per task)

**Prerequisites**: plan.md (required), spec.md (required). The canonical
spec text governs wherever a task summary and the spec differ.

**Tests**: Every build task is test-first or test-accompanied in
`tests/test_board_*.py`; drills named in the spec (concurrent append,
kill-mid-append, retry-after-lost-confirmation, torn tail, fork,
lost-wakeup race, genesis fold) are automated tests, not manual rituals.
Weekly audits are GATEs: they run on the pilot's rhythm and their
findings halt pilot expansion until explained.

**Organization**: Phases 1–4 build in this repo (`board/` family). Phase 5
builds in `electrohire/spec-kit-aee` and lands as separate PRs there.
Phase 6 is the pilot: two boards in the owning program's workspace.
Registration of claims KB-1..KB-6 is **not** in this task list; it is a
separate governed motion (plan.md, "What this plan does not do").

## Format: `[ID] [P?] [Phase] Description`

- **[P]**: Can run in parallel with sibling tasks (different files, no dependencies)
- Every task carries a **Behavior** line, an **Acceptance** line naming its
  mode (TEST / HUMAN-AS-ORACLE / GATE), and a **This does not establish**
  line, per the Autonomous Execution Doctrine.
- Each task is sized at one PR or less, in the repo named in its phase.

---

## Phase 1: Substrate (this repo, `board/`)

**Purpose**: The append-only log, its one write path, the fold, state
snapshots, recovery, and the generated view.

- [x] T001 [P] [SUB] Canonical serialization and hashing in `board/canonical.py`: an event serializes as JSON with sorted keys, Unicode NFC, separators `,` and `:`, UTF-8, LF line ending, excluding `event_hash`; `event_hash` is the SHA-256 of that canonical form concatenated with `prev_hash`; the state file uses the same rule applied to the state object (spec 3.2, FR-S1)
  - Behavior: the same logical event hashes identically on any host and checkout, including a checkout that would otherwise introduce CRLF.
  - Acceptance: TEST — known-answer vectors, including a CRLF-poisoned input that must normalize before hashing.
  - This does not establish: protection against an actor who rewrites the whole log and recomputes the chain; committed state snapshots (T005) are the answer to that, not the chain.

- [x] T002 [P] [SUB] Pinned schema in `board/schema.json` plus its validator: the row fields of spec 3.1 (including `amendment_seq` as a fold-derived field, never an event payload), the event fields (`event_id`, `board_id`, `row_id`, `actor`, `writer`, `kind`, `payload`, `prev_hash`, `event_hash`), and the board genesis fields (`wip_limit`, `keeper_cadence`, `detector_chat`, `escalation_target_2`)
  - Behavior: a row or event missing a pinned field, or carrying `amendment_seq` or a caller-supplied `writer` in a payload, is refused by name before any write.
  - Acceptance: TEST — schema acceptance and refusal cases per field class.
  - This does not establish: that events admitted under the schema were truthful when written.

- [x] T003 [SUB] The append command in `board/append.py` (spec 3.2, FR-S3): all appends go through it; it (1) takes an OS advisory lock (`flock`) on the board's lock file, held for one append, failing with `LOCK_TIMEOUT` after 30 seconds, with a metadata line (holder pid, host, acquisition time) on the lock file; (2) reads the head hash and refuses with `HEAD_MOVED` when the caller's expected `prev_hash` differs, the caller re-reading and retrying; (3) returns the existing event and writes nothing when the caller's `event_id` is already in the log; (4) appends by verified append (single line, O_APPEND full-write loop, fsync, file-size growth verified, bounded retries); (5) stamps `writer` itself and rejects any caller-supplied value; (6) before releasing the lock, re-folds the event into the state file via T005
  - Behavior: concurrent appends serialize; a killed writer leaves no stale lock; a retry of an append that landed but was never confirmed produces exactly one event; a write-denial wave fails the append loudly at the command, and no event is ever backdated.
  - Acceptance: TEST — concurrent-append drill, kill-mid-append drill, retry-after-lost-confirmation drill (exactly one event lands), `HEAD_MOVED` and `LOCK_TIMEOUT` refusal tests.
  - This does not establish: availability while the board's host is down; that state is visible as log staleness (T017, T024), not hidden.

- [x] T004 [SUB] Fold and chain verification in `board/fold.py` (spec 3.2, FR-S1/FR-S2): folding replays events into row and board state (including derived `amendment_seq` and the halt flag); a chain failure or a kernel-illegal transition (legality from T008's table) stops the fold at the offending event and reports it, never repairing silently; a repeated `event_id` in a recovered log is reported as a finding against the recovery record, not a fold refusal
  - Behavior: any tampering or reordering breaks the fold at a named event; state is a pure function of the log.
  - Acceptance: TEST — chain-break and illegal-transition refusal tests; the fold performance drill: a synthetic 10,000-event log folds in under 60 seconds on the owning VM.
  - This does not establish: that the events themselves were truthful; provenance is the actor field plus the verdict rules (Phase 2), not the chain.

- [x] T005 [SUB] State snapshots in `board/state.py` (spec 3.3, FR-S4): the state file is written only by the append holder, inside the append lock, by verified write with read-back hash, and carries the head `event_hash` it folded; whenever no append is in flight the served state's head hash equals the log head, and a state file whose head differs is labeled stale wherever surfaced, with both hashes shown; every generated surface prints the head hash it was generated from
  - Behavior: readers never see a silently stale state presented as current.
  - Acceptance: TEST — concurrent-append drill asserting no state regression; stale-state labeling test.
  - This does not establish: that the folded state is correct; that is the KB-6 audit's question (T020).

- [x] T006 [SUB] Recovery procedures in `board/recover.py` (spec 3.2, FR-S3a): a torn tail (final line unparseable or chain-failing) is truncated to the last chain-valid event, the discarded bytes preserved to a recovery file beside the log with their SHA-256 recorded; a fork or mid-log break halts the board (T008) and is recovered only by a planner-authorized `recovery` event — the canonical head is the branch folded into the last committed state snapshot, still-legal discarded events are re-appended as new events citing the originals, the rest are recorded as discarded in the recovery file, and the `recovery` event cites the recovery file's hash and the authorizing planner
  - Behavior: recovery is a visible procedure with preserved evidence; a log that needed recovery says so in its own chain.
  - Acceptance: TEST — torn-tail drill and fork drill on synthetic boards.
  - This does not establish: that recovery is cheap; it establishes that it is never invisible.

- [x] T007 [SUB] Generated tasks view in `board/view.py` (spec 3.3, FR-S5; 4.3, FR-K2): the human tasks rendering is generated from board state by script, carries a generated-file header and the head hash it was generated from, and is never hand-edited; any surface showing a row's state shows `status` and `execution_state` together or neither, and `execution_state` is never rendered as completion
  - Behavior: the human surface and the log cannot disagree silently, and transport state can never masquerade as completion.
  - Acceptance: TEST — view-generator tests including the FR-K2 rendering constraint; the byte-compare itself runs as the KB-5 audit (T019).
  - This does not establish: that board state is correct, only that the two surfaces never disagree silently.

**Checkpoint**: A board can be created, appended to under concurrency and
failure drills, folded, snapshotted, recovered, and rendered — with every
refusal loud and named.

---

## Phase 2: Kernel (this repo, `board/`)

**Purpose**: The legal transitions and their guards, in one canonical
machine form (spec 4.7): the fold implementation in this repo. T008 is a
data dependency of T004 and is pulled forward accordingly.

- [x] T008 [KER] Canonical transition table in `board/kernel.py` (spec 4.1, 4.2): the nine statuses with `done`/`withdrawn`/`superseded` terminal; the pinned transition table including genesis (one genesis event per board generation, recording `spec_hash`; generated rows trace to lines of the frozen artifact, untraceable rows are violations), planner-only promotion to `ready` behind the dependencies-done guard, single-holder take behind the board's `wip_limit` count, block behind a registered wait and a non-empty resumption note, the rework path `in_review → in_progress`, and halt/resume as a board-level flag pair (halt by planner or a tripwire event only; resume by planner only, referencing the halt event)
  - Behavior: a transition not in the table, or failing its guard, is refused by the fold; a halted board folds normally and refuses transitions.
  - Acceptance: TEST — one test per table row, plus a refusal test per guard.
  - This does not establish: enforcement of the actor column. Actor-based rules are accountability controls in the pilot (spec 4.2 honesty note): violations are detectable from the log and reported, not structurally prevented, and no surface may claim otherwise.

- [x] T009 [P] [KER] Resumption-note validation (spec 4.4, FR-K3): a block or handoff event without a `resumption_note` is refused; the note must carry the four labeled parts — current position, next action, the records that matter, what would change the plan — checked for presence as labeled sections
  - Behavior: no row can be left blocked or handed off without a written resumption position.
  - Acceptance: TEST — refusal tests for a missing note and for each missing labeled part.
  - This does not establish: that notes will be good; KB-3 measures whether they pay (T030), and the pilot may find they do not.

- [x] T010 [KER] Verdict attachment and favorable-outcome checks in `board/verdicts.py` (spec 4.3, FR-K1/FR-K1a/FR-K1b): `verdict_ref` is set only by a verdict-attachment event, fired by the row's reviewer or the keeper, never the row's current holder; attachments are immutable once folded, replacement only by a superseding attachment recording the reason and the previous reference; the pinned reference formats and favorable outcomes per class — engine evaluation or gate result (`engine:<path>#<sha256 at citation time>`; every claim in the row's `claim_ids` supported/pass, none contradicted or violated), gatekeeper record (`gatekeeper:<job-id>#<sha256 of the payload exit record at citation time>`; the payload's own exit code is 0 — a wrapper completion state, or a non-zero or absent payload exit code, is not favorable), CI run (`ci:<run-id>#<head SHA>`; conclusion success and head SHA equal to the work-product commit in the row's `in_review` transition), gate decision (`gate:<record-path>#<sha256 at citation time>`; the record states approve, names the decider, and lives outside the board — a gate record is never a board event); a record may serve a row only if its own cited work references cover the work product in the row's `in_review` transition; an unfavorable or unresolvable reference routes the row only to `in_progress` or `withdrawn`, recorded in the transition event, which carries the full `verdict_ref` including its hash
  - Behavior: `done` is reachable only through a real, favorable, hash-bound external verdict; later changes to a cited record are detectable by comparison.
  - Acceptance: TEST — per-class favorable and unfavorable cases, holder-attachment refusal, superseding-attachment chain, coverage-rule refusal.
  - This does not establish: that a favorable verdict was wise, only that completion cites a real record whose own verdict was favorable.

- [x] T011 [KER] Amendment mechanics (spec 4.5, FR-K4): plan changes after genesis are amendment events with reason and authority, effective at planner-named phase boundaries (halt excepted, immediate); the amendable fields are exactly `depends_on`, `assignee_kind`, `assignee_instance`, `body`, `wait`, and `verdict_ref` by superseding attachment only — any other field change is a supersede-and-replace of the row; the fold refuses a genesis or amendment event that creates a cycle in the `depends_on` graph, checked over the full graph at that event; when a dependency row is superseded, the same motion re-points every dependent at the replacing row by amendment event; a dependent whose dependency is withdrawn without replacement surfaces as a finding in the weekly metrics (T024) until re-pointed or withdrawn
  - Behavior: plan changes cannot be exercised invisibly, and the dependency graph can never contain a cycle or a silent dangling edge.
  - Acceptance: TEST — cycle-refusal tests at genesis and at amendment, re-pointing test, non-amendable-field refusal test.
  - This does not establish: that amendment discipline will be exercised wisely, only that it cannot be exercised invisibly.

- [x] T012 [P] [KER] Assignment rules (spec 4.6, FR-K5): worker rows take `assignee_kind`; gate rows (gates, adjudications, external sends, and every reserved act in the grants registry, consumed by reference) take `assignee_instance` naming a person or a specific agent, and the fold refuses a gate row with a kind assignee
  - Behavior: no gate can be assigned to a capability class instead of a named decider.
  - Acceptance: TEST — gate-row kind-assignee refusal; worker-row kind assignment accepted.
  - This does not establish: the grants registry's contents; the kernel consumes the reserved-act list by reference.

**Checkpoint**: The kernel refuses every illegal transition and every
unfavorable completion in tests, with the actor-honesty boundary stated
in code and docs, not implied away.

---

## Phase 3: Keeper (this repo tooling + scheduled jobs)

**Purpose**: Event carriage, matching, wake mechanics, sweep defense,
and the independent dead-keeper detector (spec 5).

- [x] T013 [KEE] Keeper core in `board/keeper.py` (spec 5.1, FR-P1): the keeper polls the board's named external sources (gatekeeper queue and ledger, CI run records, message and mail arrivals a wait names, clock events for armed moments) and posts keeper events citing the record read (identifier, and hash where the record carries one); a keeper post asserting an outcome without a record reference is a kernel violation, flagged by audit (T018 rhythm); every keeper run, including an empty one, appends a heartbeat event; a dead source is a reportable keeper finding, not a silent gap
  - Behavior: external outcomes reach the board only as cited records, and a live keeper is distinguishable from a dead one in the log itself.
  - Acceptance: TEST — citation-format tests and uncited-assertion flagging; the audit sampling of keeper posts runs as a GATE in the pilot rhythm (T031).
  - This does not establish: source availability; a dead source is reported, not repaired, by the keeper.

- [x] T014 [KEE] Matching and wake mechanics (spec 5.1, FR-P2/FR-P3): mechanical waits (`dependency`, `named_event`) match on exact fields only; prose matching is confined to `external_prose` waits and forbidden for the mechanical kinds; dependency wakes are the append path's — when a `done` transition is appended, the append operation appends, in the same locked operation, a system wake event for every dependent whose `dependency` wait that transition satisfies (`actor` = `system`, `writer` = the append service); wake-on-watch is also the append path's — when a wait registration is appended, the append operation evaluates the wait's `wake_falsifier` against the target record inside the same lock and records the result in the wait event, firing the wake in the same operation if the ending condition already holds
  - Behavior: no wait can be lost between the decision to wait and its registration, and dependency wakes do not depend on the keeper being alive.
  - Acceptance: TEST — the lost-wakeup race drill (event lands between decision to wait and registration); exact-match and prose-confinement tests.
  - This does not establish: that prose matching is accurate; its misses are bounded by the sweep defense (T015) and counted as KB-4 evidence.

- [x] T015 [KEE] Sweep defense (spec 5.1, FR-P4): the append path refuses a wait registration whose `sweep_deadline` is less than two keeper-cadence intervals after registration (pilot minimum 60 minutes; `external_prose` default 4 hours); when a wait passes its deadline unwoken, the keeper's next sweep re-reads the underlying record directly and posts what it finds; a wait surviving its sweep unresolved gets an escalation post to its named target; each sweep re-read that finds an already-satisfied wait records a missed-wake finding with the wait's age; between sweeps the missed-wake count is a lower bound and is reported as one, never as counted from the log alone
  - Behavior: every wait has a bounded time to a direct re-read and an escalation, and missed wakes are measured by procedure, not inferred from absence.
  - Acceptance: TEST — deadline-minimum refusal, sweep re-read, escalation, and missed-wake finding tests.
  - This does not establish: keeper liveness; a keeper that never sweeps is caught by the detector (T017), not by this task.

- [x] T016 [KEE] Keeper scheduled job: one scheduled job per board, staffed by the program's own chat (ratified staffing decision), running the keeper on the board's genesis `keeper_cadence` (pilot: 30 minutes), with the runbook recorded in `board/README.md` — start, stop, cadence change by amendment event, and the rule that the job's completion state is never the keeper's verdict (heartbeat events in the log are)
  - Behavior: the keeper runs unattended on cadence, and its operation is provable from the board's own log.
  - Acceptance: GATE — the first live runs append heartbeat events on cadence on a pilot board (T027/T028 genesis), verified from the log, not from the scheduler's status.
  - This does not establish: that the scheduler itself cannot die silently; that is the detector's job (T017), owned by a different chat.

- [x] T017 [KEE] Dead-keeper detector: a scheduled job running every 2 hours, owned by the board's genesis `detector_chat` — a different chat from the keeper's owning chat, named at genesis; it reads only the log's heartbeat events; if no heartbeat has been appended for more than two cadence intervals (pilot: 60 minutes) while any wait is open or any non-terminal row exists, it escalates to the wait's named target and to the board's `escalation_target_2`, so escalation is never single-hop and never depends on the keeper or its chat being alive; the escalation is posted outside the board and recorded as a board event when appends resume
  - Behavior: a dead keeper is detected and escalated by a component that does not share the keeper's failure modes.
  - Acceptance: GATE — drill on a pilot board: keeper disabled, detector escalation fires to both targets within one detector interval of the threshold.
  - This does not establish: fleet recovery; the board can refuse to let a dead fleet look alive, it cannot revive one.

**Checkpoint**: Waits are woken mechanically where possible, swept where
not, and a dead keeper is itself a detected, escalated event.

---

## Phase 4: Audits and Metrics (this repo, `board/audits.py`, `board/metrics.py`)

**Purpose**: The weekly GATEs of spec 6 and the metrics of spec 5.3. No
board goes live (Phase 6) before the audits that watch it exist.

- [x] T018 [AUD] KB-2 audit (done means a favorable record): weekly, every row that entered `done` since the last audit — all of them, at any count; resolution is scripted: resolve each `verdict_ref`, compare the record's current content hash against the hash captured at citation time, and check the outcome is favorable under spec 4.3's table; a reference that does not resolve, whose hash has changed, or whose outcome is not favorable is a finding that halts the pilot's expansion until explained
  - Behavior: every completion is re-verified against the record it cited, not just sampled.
  - Acceptance: GATE — the audit runs in the pilot's weekly rhythm (T031); script behavior is TEST-covered in `tests/test_board_audits.py`.
  - This does not establish: the authority of the actor who fired `done`; actor-based guards are accountability controls (T008), and the claim registration must say so.

- [x] T019 [AUD] KB-5 audit (the view agrees): weekly, regenerate the tasks view from the log and byte-compare with the published view; divergence not explained by an in-flight event is a finding
  - Behavior: the human surface is proven against the log on a rhythm, not trusted.
  - Acceptance: GATE — weekly run in the pilot rhythm (T031).
  - This does not establish: that board state is correct, only that the two surfaces never disagree silently.

- [x] T020 [AUD] KB-6 audit (state is the log): weekly, fold the log from genesis into a fresh state and byte-compare against the served state file; any difference is a finding of the highest severity this spec defines, and a KB-6 failure is a pilot tripwire (spec 7.5)
  - Behavior: the substrate's load-bearing guarantee is re-proven from genesis every week.
  - Acceptance: GATE — weekly run in the pilot rhythm (T031).
  - This does not establish: that the log's events were truthful; KB-6 is a self-consistency proof and is not described as more.

- [x] T021 [AUD] Artifact-trace audit: weekly, every row traces to a line of the genesis artifact named by `spec_hash`, or to a chain of amendment events ending at such a line; rows whose lineage cannot be reconstructed are findings
  - Behavior: the board is proven to still be the plan it was generated from, plus its recorded amendments.
  - Acceptance: GATE — weekly run in the pilot rhythm (T031).
  - This does not establish: that the plan was good; it establishes that the board is that plan, amended only on the record. This is the only audit that compares the board against something outside itself.

- [x] T022 [AUD] Boundary audit (the contamination detector): weekly, run by the owning program's coordinator chat as part of the weekly rhythm — a script check that no governance-board row's `spec_ref` or `task_ref` resolves into a registered study-arm artifact of the ninety-day program, and that no board exists whose rows belong to a study arm; a hit is the spec 7.5 tripwire firing, not a lesser finding
  - Behavior: the contamination boundary has a detector, not just a rule.
  - Acceptance: GATE — weekly run in the pilot rhythm (T031); the check itself is TEST-covered against synthetic violating boards.
  - This does not establish: that the boundary held between audits; it establishes that a leak is detected within one weekly cycle and halts the pilot.

- [x] T023 [AUD] Kernel drift check: weekly, until generation replaces pinning (T026) — the extension's shipped kernel definitions (Phase 5) hash-compare against the canonical table in this repo (T008); divergence is a finding of the same class as a stale catalog entry
  - Behavior: the two kernel homes can never diverge silently.
  - Acceptance: GATE — weekly run in the pilot rhythm (T031); the comparison is TEST-covered.
  - This does not establish: that the canonical table is right; it establishes that there is only one table in effect.

- [x] T024 [AUD] Weekly metrics and overhead report generator in `board/metrics.py` (spec 5.3): per board, generated from the log by script under the view discipline (T007) — rows by status and age; waits by kind with wake outcomes (woken by match, woken by sweep, escalated, still waiting); planner overrides of blocked rows as their own category; keeper missed-wake and false-wake counts (as lower bounds between sweeps, per T015); board staleness flag (no event for 24 hours while non-terminal rows exist); and the pilot overhead metric in the same rhythm — keeper session cost (agent tokens and wall time), audit labor, genesis and amendment event counts, note-authoring cost where KB-3 instrumentation is active
  - Behavior: the pilot's cost is reported beside what it prevented, as a metric, in the same weekly rhythm as its benefits.
  - Acceptance: TEST — generator tests over synthetic logs, including the staleness flag and the override category.
  - This does not establish: that the board pays for itself; it produces the numbers the verdict report (T032) must answer with.

**Checkpoint**: Every guarantee the pilot will claim has a weekly,
scripted check that can falsify it.

---

## Phase 5: Extension Kernel Definitions (electrohire/spec-kit-aee — separate PRs in that repo)

**Purpose**: The kernel definitions shipped by the extension, kept in
lockstep with the canonical form in this repo (spec 4.7).

- [x] T025 [EXT] Ship the kernel definitions in the spec-kit-aee extension: the transition table and guard definitions from T008's canonical form, pinned by hash in the extension, with a freshness test in the extension's test suite (in the style of its catalog-freshness test) that fails when the shipped definitions diverge from the canonical table's hash; any extension version bump this requires ships its tag, release, and catalog update in the same motion, per catalog stewardship
  - Behavior: an extension user gets exactly the kernel this repo's fold enforces, and drift fails a test in the extension's own CI.
  - Acceptance: TEST — the freshness test passes on the pinned definitions and fails on a deliberately perturbed copy.
  - This does not establish: that generation (T026) exists; pinning is the pilot's mechanism and is named as such.
  - Landed (2026-11-22): spec-kit-aee PR #50 (merge 6614e37) — templates/board-kernel-definitions.json generated from this repo's canonical form at 2e36f7a, pinned at canonical hash ac47b06e700417c7d4155b0dceda20160b191bf6615f32d3ee7f3d93e743e8ce; tests/test_kernel_freshness.py carries the pin leg and a live leg against the real kernel_definitions() output (CI checks the engine out at the pinned commit, sparse board/ only). No extension version bump was required, so the catalog stewardship motion was not triggered. With the shipped file present, T023's drift check runs at full scope and passes.

- [x] T026 [EXT] Generation replacing pinning (later, not a pilot blocker): a generator in this repo emits the extension's kernel definitions from the canonical form; the extension's freshness test switches from hash-pin comparison to generated-output comparison; the weekly drift check (T023) retires when generation lands
  - Behavior: the second kernel home becomes a build artifact, removing the drift class rather than detecting it.
  - Acceptance: TEST — generated output byte-matches the previously pinned definitions at the switch.
  - This does not establish: anything about the pilot; the pilot runs correctly on pinning alone, and this task may land after the pilot's verdict report without invalidating it.
  - Disposition (2026-11-22): deferred by design, as this task's own text provides — later, not a pilot blocker, and it may land after the pilot's verdict report. This check-off records the disposition, not the work: generation is NOT built, the extension's freshness test still compares against the hash pin (T025), and the weekly drift check (T023) still stands. The task reopens when generation is scheduled.

**Checkpoint**: The extension and the engine fold speak one kernel, with
drift as a failing test rather than a discovered fact.

---

## Phase 6: Pilot (owning program's workspace)

**Purpose**: Two boards, run under the weekly rhythm, ending in a verdict
report per claim (spec 7). **Task-level constraint on every task in this
phase — the contamination boundary (hard)**: the board does not enter the
ninety-day program's study arms' execution path at any point; no pilot
board carries a study-arm row; a proposal to change this is a proposal to
amend the program's registration and goes through that process or not at
all.

- [x] T027 [PIL] Governance board genesis: create the ninety-day program's governance board in the program's workspace — one canonical board directory, `.gitattributes` `eol=lf` lines set as a genesis checklist item, genesis event recording the frozen artifact's hash, genesis fields pinned per Amendment 1 Part 4 (`wip_limit` 4, `keeper_cadence` 30 minutes, `detector_chat` named and different from the keeper's chat, `escalation_target_2` named); rows for gates G2b and G3, reviewer-pool commitments, the Day 14 registration signing, and Phase 0 completion waits; daily git commit of the board directory wired as backup
  - Behavior: the program's governance waits live on a board whose state reproduces from its log from day one.
  - Acceptance: GATE — genesis drill: fold from genesis reproduces the served state (KB-6 passes at genesis), and the boundary audit (T022) passes on the genesis rows.
  - This does not establish: that governance will use the board well; it establishes that its waits are visible, bounded, and auditable.
  - Landed (2026-11-22): board `ninety-day-governance` created in the program's workspace (`boards/governance/`) through the real append path; genesis event hash `0be986801f2a50ea75eef84e9214472220116d8210c856cffc754a201c35a7ba`, traced artifact Amendment 1 (sha256 `43c5b545e199a752d7c1dfd931b7baf4e917dacf363c294e5e235192fc4cfce1`); fields per Part 4 (wip_limit 4, cadence 30m, detector_chat "main-chat", escalation_target_2 named). Five rows: reviewer-pool commitments and Day 14 registration signing (both blocked on registered external_prose waits with four-part resumption notes), Phase 0 completion, gates G2b and G3. Genesis drill PASS: KB-6 at genesis, artifact-trace, boundary audit, KB-5 all clean. Daily backup commit wired (cron `agent-board-daily-backup`); the boards directory is a local git repo with no remote, recorded as a flagged limitation in the genesis record (program workspace is not a git repo; no program repo exists to push to).

- [x] T028 [PIL] Suite campaign board genesis: the next non-study spec-kit feature effort in the suite repos is stood up board-first from its frozen tasks artifact — genesis event with the artifact's hash, `wip_limit` 3, same cadence and detector fields as T027; no task of that campaign executes off-board once the board exists
  - Behavior: one ordinary campaign runs its whole life as board rows, giving the pilot its second, differently-shaped board.
  - Acceptance: GATE — genesis drill as T027, plus the campaign's own completion recorded as board rows reaching terminal states.
  - This does not establish: that board-first execution suits every campaign; the pilot's verdict report (T032) is where that is judged, per board.
  - Landed as genesis (2026-11-22): board `generation-campaign` created in the program's workspace (`boards/generation-campaign/`); the campaign is generation replacing pinning (T026), the next non-study spec-kit feature effort in the suite repos, stood up board-first from this file as its frozen tasks artifact (sha256 `27cb5ca2e0caba3eadf2001fb70d0a8ed07ef266f117409f703dd50f270b7cd7` at genesis); genesis event hash `1fd701e7b5e953763411f7b236c068cb6fc38a073f8a74c7836ed800e16a101c`; wip_limit 3, same cadence and detector fields as T027. Genesis drill PASS (KB-6, trace, boundary, KB-5). This check-off records the genesis state only: the campaign has not executed yet, its four rows stand planned, and its completion (rows reaching terminal states) remains outstanding and will be scored in the T032 final report. No task of the campaign executes off-board from this genesis.

- [x] T029 [PIL] KB-1 baseline pass (spec 7.2): count stalled items (spec Section 2 definition) in the two most recent comparable suite campaigns — comparability pinned before counting (same program family; a frozen tasks artifact or equivalent task list; at least five working days; at least one wait on an external system or person crossed) — read from their chat transcripts and gatekeeper records by a documented manual pass, checked by a second reader, with a transcript-completeness check per campaign (a campaign whose chat record is known to be compaction-truncated for the counted window fails the standard); the instrument-asymmetry caveat is recorded with the count: the baseline instrument undercounts stalls relative to the board's log, the expected bias direction is against the board, and a KB-1 result within the caveat's reach is reported as UNMEASURED (resolution)
  - Behavior: the pilot's headline comparison rests on a baseline counted to a stated standard, or honestly reports that it cannot be.
  - Acceptance: HUMAN-AS-ORACLE — the manual pass and second-reader check are the instrument; if the standard cannot be met, KB-1 reports UNMEASURED with the reason and the pilot proceeds on KB-2..KB-6. Estimating the baseline from impressions is forbidden.
  - This does not establish: a stall count for any campaign whose record fails the completeness check; those are excluded, not estimated.
  - Completed (2026-11-22): KB-1 reports **UNMEASURED (resolution)**. The documented pass (baseline packet in the program's workspace, `hidden_files/agent-board-pilot-2026-11-22/KB-1-BASELINE-PACKET.md`) pinned comparability before counting — the Agent Board line (2026-11-12 to 22) and the Phase 0 stand-up plus stack red team application (2026-11-11 to 18) are the two most recent comparable campaigns and both meet the criteria — and the transcript-completeness check then failed for both: their chat record survives only in compacted form and no complete transcript exists on disk. A second reader independently confirmed the comparability pinning (with one correction, seven weekdays for Campaign A, applied to the packet), the completeness finding, and the spec application. No stall count is reported or implied; the instrument-asymmetry caveat is recorded in the packet for the verdict report to carry. The pilot proceeds on KB-2..KB-6.

- [x] T030 [PIL] KB-3 sampling instrumentation (spec 7.3): every wake is eligible; the sample is all wakes up to 20 per board per week, taken in log order; for each sampled wake, resumption cost is the waking agent's token usage from the wake event's timestamp to its first productive action, read from that agent's session record where the runtime exposes it — a wake whose session record exposes no usage is excluded and counted as unmetered, never estimated; the classification rule is applied identically on both sides (orientation = reads, searches, and lookups that change no state outside the reading agent; first productive action = the first tool call that changes state outside the board, produces a work product, or sends a message); a second rater independently classifies a 25% subsample, and disagreement above 10% downgrades KB-3 to UNMEASURED (resolution) for that period; the baseline is the same protocol over a sample of compaction-resumption events in the governance chats during the pilot window; note-authoring cost is measured on the blocking side under the same rule and reported beside the saving, never netted silently
  - Behavior: resumption cost is a sampled measurement with a stated instrument, or an honest UNMEASURED.
  - Acceptance: HUMAN-AS-ORACLE — the double-rating and classification judgments are the instrument; the sampler's selection (log order, cap, exclusions) is TEST-covered.
  - This does not establish: a continuous or complete metering of resumption cost; the claim is judged only on the sampled protocol.
  - Instrumented (2026-11-22): the protocol record stands in the program's workspace (`hidden_files/agent-board-pilot-2026-11-22/KB-3-SAMPLING-PROTOCOL.md`) and the weekly rhythm applies it. Stated plainly on that record: the sampler's selection runs over the metrics generator's test-covered wake enumeration (T024), but there is no standalone sampler program — selection (log order, cap 20 per board per week, unmetered exclusions) is a documented human-applied protocol under the double-rating rule, and the acceptance line above is met only to that extent. At genesis the sample is empty (no wake has occurred on either board); KB-3 is UNMEASURED so far and will be judged only if a metered sample exists.

- [x] T031 [PIL] Weekly rhythm live: keeper metrics (T024), the KB-2, KB-5, and KB-6 audits, the artifact-trace audit, the boundary audit, and the kernel drift check run weekly per board; tripwires (spec 7.5) halt the pilot and are reported, never fixed mid-flight — a KB-6 audit failure; a done row citing a fabricated or unresolvable verdict reference; a keeper post asserting an outcome it could not cite; a boundary-audit hit
  - Behavior: the pilot runs under its own falsification machinery for its whole life.
  - Acceptance: GATE — each weekly cycle's audit results are board events or program records, present for every week the pilot runs.
  - This does not establish: that the pilot will pass; it establishes that failure will be detected and named by the machinery, not by impression.
  - Live (2026-11-22): cron `agent-board-weekly-rhythm` (Mondays about 09:00 ET, owned by the program's goal, reporting to the Spec-Kit AEE chat) runs metrics, KB-2, KB-5, KB-6, artifact-trace, boundary, and the kernel drift check at full scope for both boards, saves each cycle's results as program records under `boards/reports/<date>/`, applies the KB-3 sampling step, and carries the Section 7.5 tripwires as halt-and-report, never fix mid-flight. First cycle Monday 2026-11-23. The genesis cycle's audits were run at genesis and are recorded in the pilot genesis record; the rhythm's own cycles are outstanding by definition and accrue weekly.

- [x] T032 [PIL] Pilot verdict report: at the earlier of the suite campaign's completion or Day 30 of the ninety-day program, a verdict per claim KB-1..KB-6 in plain language, each with its evidence and its "this does not establish" line; the two boards scored separately (the suite campaign board at its completion; the governance board's claims marked preliminary if any of its rows are still open, and re-scored when its last row terminates); the pilot overhead metric (T024) carried beside KB-1's stall count; the report is red-teamed before it goes to the owner; a falsified claim retires the corresponding part of the design by amendment to the design note, not by quiet abandonment
  - Behavior: the pilot ends in earned verdicts, including the legitimate outcome that a claim fails.
  - Acceptance: GATE — red team pass completed and the report delivered to the owner.
  - This does not establish: anything beyond the two pilot boards; wider adoption is a new decision on this report's evidence, not a consequence of it.
  - Preliminary report landed (2026-11-22): `files/2026-11-22-agent-board-pilot-verdict-report-PRELIMINARY.md` in the program's workspace records the pilot as RUNNING — genesis proven on both boards, KB-1 settled as UNMEASURED (resolution) with its evidence, KB-3 UNMEASURED so far (empty sample), KB-2/KB-4/KB-5/KB-6 outstanding or genesis-cycle-only, both boards scored preliminary, the pilot overhead position stated without inventing a total, and the dead-keeper detector gap named. This check-off records the preliminary report, not the final verdicts: the final report remains due at the earlier of the campaign's completion or Day 30 (about 2026-12-15), red-teamed before it goes to the owner, and this task's acceptance GATE is met only then.

**Checkpoint**: The pilot has run, been audited weekly, and reported
earned verdicts per claim — or has halted on a named tripwire, which is
also a reportable outcome.

---

## Not in this task list

- **Claim registration (KB-1..KB-6)** into the engine program ledger —
  a separate governed motion through the program-ledger intake (spec
  Section 8), with all six claims at status `draft`, evidence refs, and
  falsifiers in the registration shape the spec pins. It is not a side
  effect of any task above, and a registration that marks any claim
  supported before pilot evidence exists is to be rejected by the intake.
- Caller authentication for actors (spec 4.2 honesty note), a fleet
  keeper service, and cross-team boards — out of the pilot's scope.
- Any change to the gatekeeper, the engine's ledgers, or the ninety-day
  program's study machinery.
