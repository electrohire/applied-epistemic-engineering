# board/ — Agent Board substrate and kernel (spec AB-001 as amended)

One board is one directory: `events.jsonl` (the append-only,
hash-chained log), `state.json` (the folded state, written only by
the append holder), `board.lock` (the append lock, with holder
metadata), `tasks.md` (the generated human view), and, after any
recovery, `recovery-<timestamp>.json` files preserving discarded
bytes. The board directory carries `.gitattributes` `eol=lf` lines,
written at creation, so checkouts cannot reintroduce CRLF divergence.

## Entry points

- Create a board: `python3 -m board.append create <board_dir> <genesis.json>`
  where the JSON file is `{"actor": ..., "payload": {genesis fields}}`
  (see `board/schema.json` for the pinned genesis fields).
- Append an event: `python3 -m board.append append <board_dir> <event.json>`
  where the JSON file is `{"event": {caller event fields},
  "expected_prev_hash": ...}`. Refusals are named: `LOCK_TIMEOUT`,
  `HEAD_MOVED` (re-read and retry), `SCHEMA` (the problem, per field).
  A retry with an `event_id` already in the log returns the existing
  event and writes nothing.
- Generate the human view: `board.view.generate_view(board_dir)`
  writes `tasks.md` from the served state, labeled with the head hash
  it was generated from (and labeled STALE, with both hashes, when the
  state lags the log).
- Recovery: `board.recover.recover_torn_tail(board_dir)` for a torn
  final line; `board.recover.recover_fork(board_dir, planner)` for a
  fork or mid-log break, under planner authority. Both preserve the
  discarded bytes in a recovery file; neither repairs silently.

## Discipline

Events are the only way state changes; the fold
(`board/fold.py`) is a pure function of the log and refuses divergence
at a named event. Transition legality is injected into the fold: raw
list folds default to the substrate's structural checker, and the
board-level fold (`fold_board`, used by the append path, recovery,
and audits) enforces the kernel's table (`board/kernel.py`, spec
Section 4.2) through the same seam. The append command checks the
fold before it writes: an event the fold refuses never enters the
log. `execution_state` is a transport fact and is never rendered as
completion; the generated view always shows `status` and
`execution_state` together.

The kernel (`board/kernel.py`) is the canonical machine form of the
transition table and its guards: creation rows, planner promotion
behind the dependencies-done guard, single-holder takes behind the
board's `wip_limit`, blocks behind a registered wait and a four-part
resumption note (FR-K3), the rework path, verdict-gated `done`
(FR-K1, with `board/verdicts.py` resolving the cited records),
amendments restricted to the amendable fields with cycle refusal
(FR-K4), gate rows taking named assignees only (FR-K5), and
halt/resume as a board-level flag pair. Actor-column rules are
accountability controls in the pilot, not authentication (spec 4.2
honesty note): the fold enforces the state-based guards and records
the rest.

The substrate is POSIX-only: the append lock is `fcntl.flock`, and
boards live on Linux hosts. Off POSIX, appends refuse by name
(`UNSUPPORTED_PLATFORM`).

## Keeper and detector runbook (spec 5.1/5.4, tasks T013–T017)

The keeper is one scheduled job per board, staffed by the program's
own chat; the dead-keeper detector is one scheduled job per board,
staffed by the board's genesis `detector_chat` — a different chat.
Their scheduling definitions live in `board/jobs/keeper-job.json`
and `board/jobs/detector-job.json`; live jobs for a board are
created when the board is (Phase 6 genesis instantiates them).

**Start the keeper.** Create the board's sources file (a JSON
object naming `gatekeeper_queue_dir`, `gatekeeper_ledger`,
`ci_records_dir`, and `detector_outbox_dir` — the detector's outbox
for this board), then schedule:

```
python3 -m board.keeper run <board_dir> <sources.json>
```

on the board's genesis `keeper_cadence` (pilot: every 30 minutes).
External-prose waits are judged by the staffing chat: the job's
caller passes its judgment into the run as the prose evaluator (see
`board/jobs/keeper-job.json`); the machinery confines prose to
`external_prose` waits and refuses to post a prose match without a
record citation.

**Stop the keeper.** Disable the schedule. Nothing else is needed:
the board keeps its state, and the detector escalates the silence
while any wait is open or any non-terminal row exists.

**Change the cadence.** Append a board-level amendment event
changing exactly `keeper_cadence`, with FR-K4's reason and
authority recorded:

```
{"kind": "amendment", "row_id": null,
 "payload": {"changes": {"keeper_cadence": "15m"},
             "reason": "...", "authority": "..."}}
```

then update the job's schedule to the new cadence. Any other
genesis field changes only by a new board generation.

**The verdict rule.** The scheduling job's completion state is
never the keeper's verdict. The keeper's verdict is the heartbeat
events in the board's own log: every run, including an empty one,
ends by appending a heartbeat, and a run without one did not
complete, whatever the scheduler reports. Keeper health is checked
from the log (`heartbeat` events' `run_at`), never from the
scheduler's status.

**The detector.** Schedule, owned by the `detector_chat`:

```
python3 -m board.detector run <board_dir> <outbox_dir>
```

every 2 hours. It reads only heartbeat events; if none has landed
for more than two cadence intervals while work is open, it writes
one escalation record per target (every open wait's target, plus
genesis `escalation_target_2`) into the outbox, keyed by episode so
repeat runs do not duplicate. The staffing job delivers each record
to its target's channel. When appends resume, the records land on
the board as `detector_escalation` events — the keeper records any
pending ones at the start of each run, or directly:

```
python3 -m board.detector record <board_dir> <outbox_dir>
```

## Weekly audits (spec 6, tasks T018–T023)

The audits are scripted checks in `board/audits.py`, run per board
in the weekly rhythm. Each prints a JSON report and exits 0 only
when it ran to completion and found nothing; an audit that cannot
read its inputs reports failure, never a pass.

```
python3 -m board.audits kb2 <board_dir> [--since N]
    [--gatekeeper-queue-dir D] [--ci-records-dir D]
python3 -m board.audits kb5 <board_dir>
python3 -m board.audits kb6 <board_dir>
python3 -m board.audits trace <board_dir> <artifact_path>
python3 -m board.audits boundary <registry.json> <board_dir>...
python3 -m board.audits drift [--extension-definitions PATH]
```

- **KB-2** re-resolves the `verdict_ref` of every row that entered
  `done` since the last audit (pass the previous report's
  `audited_through_index` as `--since`); a record swapped after
  citation, or one whose outcome is not favorable, is a finding.
- **KB-5** regenerates the tasks view from the log at the head the
  view names and byte-compares; later events are in-flight and
  explain themselves.
- **KB-6** folds the log from genesis and byte-compares the fresh
  state against the served state file; any difference is a finding
  of the highest severity.
- **Trace** checks every row against the genesis artifact, which
  is identified by hash (the genesis `spec_hash`); a row traces to
  a line carrying its `task_ref`, or through a supersede chain or
  a recovery citation to a row that does.
- **Boundary** is the contamination detector: the registry file
  (`{"study_arm_artifacts": [...]}`) names the ninety-day
  program's registered study-arm artifacts, and any board genesis
  or row reference resolving into one is the Section 7.5 tripwire.
- **Drift** compares the kernel's two homes. Until the extension
  ships its pinned definitions (Phase 5), the check runs its
  schema pre-check leg (canonical definitions against
  `board/schema.json`'s pinned enums) and says so in its report's
  `scope`; with `--extension-definitions` it also hash-compares
  the shipped definitions against the canonical table.

## Weekly metrics (spec 5.3, task T024)

`board/metrics.py` generates the weekly metrics and pilot
overhead report from the log:

```
python3 -m board.metrics <board_dir> [--since N]
    [--overhead overhead.json] [--sources sources.json]
    [--render report.md]
```

The report covers rows by status and age, waits by kind with
wake outcomes (match, sweep, escalated, closed without a wake,
still waiting), planner overrides of blocked rows as their own
category, keeper missed wakes (a lower bound between sweeps, and
the report says so), false wakes re-verified against the log, the
board staleness flag (24 hours without stamped log activity while
non-terminal rows exist), and the pilot overhead section. Ages
and staleness are computed from the log's stamped time evidence
(keeper heartbeat `run_at`, wait registrations' `wake_check`
stamps, detector `detected_at`); where the log carries no such
evidence the report says unknown rather than guessing. Keeper
session cost, audit labor, and note-authoring cost are not in
the log: the weekly rhythm supplies them in the overhead input
and they are carried verbatim, null when not supplied, never
estimated.
