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

The keeper's runbook (cadence, start/stop, amendment-driven cadence
change) lands with the keeper in Phase 3 of
`specs/008-agent-board/tasks.md`.
