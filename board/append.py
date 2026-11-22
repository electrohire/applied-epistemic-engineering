#!/usr/bin/env python3
"""The append command: the log's one write path (spec AB-001 3.2, FR-S3).

All appends to a board's log go through this module; no process writes
the log file by any other path. Per append, under one OS advisory lock:

1. ``flock`` on the board's lock file, held for one append only, failing
   with ``LOCK_TIMEOUT`` after the timeout (30 seconds by default). The
   kernel releases the lock if the holder dies, so a killed writer
   leaves no stale lock. The lock file carries a metadata line (holder
   pid, host, acquisition time) for observability.
2. The head hash is read; a caller's expected ``prev_hash`` that
   differs is refused with ``HEAD_MOVED``; the caller re-reads and
   retries.
3. Idempotency: an ``event_id`` already in the log returns the existing
   event and writes nothing, so a retry of an append that landed but
   was never confirmed produces exactly one event.
4. The line is appended by verified append (single line, O_APPEND
   full-write loop, fsync, file-size growth verified, bounded retries).
5. Before the lock is released, the log is re-folded and the state file
   rewritten inside the lock, so the served state's head hash equals
   the log head whenever no append is in flight.
6. System wakes are the append path's own events (spec 5.1 as
   amended): a wait registration is evaluated inside the same lock
   (wake-on-watch, FR-P3; the result is stamped into the event as
   ``wake_check`` before hashing, and a registration whose
   ``sweep_deadline`` leaves less than two cadence intervals is
   refused, FR-P4), and a ``done`` transition appends, in the same
   locked operation, a system wake for every dependent whose
   ``dependency`` wait it satisfies.

The command stamps ``writer`` itself (service, host, board) and rejects
any caller-supplied value. A write failure (including a write-denial
wave) fails the append loudly; no event is ever backdated.

Usage:
    python3 -m board.append create <board_dir> <genesis.json>
    python3 -m board.append append <board_dir> <event.json>
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import canonical, fold, records, state, validate

try:  # The substrate is POSIX-only (plan: fcntl.flock; boards live on
    # Linux hosts). The guarded import keeps the package importable on
    # other platforms, where appends refuse by name instead.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms
    fcntl = None  # type: ignore[assignment]

LOCK_FILE = "board.lock"
GITATTRIBUTES = "(.gitattributes is written by create_board)"
DEFAULT_LOCK_TIMEOUT = 30.0
SERVICE_NAME = "board-append"


class BoardRefusal(Exception):
    """A named refusal: LOCK_TIMEOUT, HEAD_MOVED, or a schema problem."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def writer_stamp(board_id: str) -> str:
    return f"{SERVICE_NAME}@{socket.gethostname()}:{board_id}"


def _append_verified(path: Path, line: bytes, attempts: int = 8) -> bool:
    """The gatekeeper's verified-append discipline (gk.py _append_verified):
    one line, O_APPEND full-write loop, fsync, size growth verified."""
    for i in range(attempts):
        try:
            before = path.stat().st_size if path.exists() else 0
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                view = memoryview(line)
                while view:
                    n = os.write(fd, view)
                    view = view[n:]
                os.fsync(fd)
            finally:
                os.close(fd)
            if path.stat().st_size == before + len(line):
                return True
        except OSError:
            pass
        if i + 1 < attempts:
            time.sleep(min(0.25 * (2**i), 8.0))
    return False


class _AppendLock:
    def __init__(self, board_dir: Path, timeout: float) -> None:
        self.path = Path(board_dir) / LOCK_FILE
        self.timeout = timeout
        self.fd: int | None = None

    def __enter__(self) -> _AppendLock:
        if fcntl is None:
            raise BoardRefusal(
                "UNSUPPORTED_PLATFORM",
                "the board append lock requires POSIX fcntl.flock; boards live on Linux hosts",
            )
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(self.fd)
                    self.fd = None
                    raise BoardRefusal(
                        "LOCK_TIMEOUT",
                        f"append lock not acquired within {self.timeout:g} seconds",
                    ) from None
                time.sleep(0.05)
        metadata = (
            f"pid={os.getpid()} host={socket.gethostname()} "
            f"acquired={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        )
        os.ftruncate(self.fd, 0)
        os.write(self.fd, metadata.encode("utf-8"))
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


def _read_events(board_dir: Path) -> list[dict[str, Any]]:
    path = Path(board_dir) / fold.EVENTS_FILE
    if not path.exists():
        return []
    events = []
    for raw in path.read_bytes().splitlines():
        if raw.strip():
            events.append(json.loads(raw.decode("utf-8")))
    return events


def _stamped_attachment_payload(
    board_dir: Path,
    events: list[dict[str, Any]],
    event: dict[str, Any],
    verdict_context: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate the cited verdict record and stamp the outcome.

    FR-K1a: the attachment event carries the append service's own
    evaluation of the record the reference cites — the row's claims
    and the work products from its latest in_review transition are
    read from the folded log, the record is resolved by
    ``board.verdicts`` under the per-class rules, and the outcome is
    stamped into the stored event. The fold then enforces the
    favorable requirement as a pure function of the log (KB-6). A
    caller-supplied evaluation is refused at schema validation.
    """
    from . import kernel, verdicts

    current = fold.fold_events(events, kernel.kernel_checker)
    if not current.ok:
        refusal = current.refusal
        assert refusal is not None
        raise BoardRefusal(
            "FOLD_REFUSED",
            f"the log does not fold before the attachment: event "
            f"{refusal.event_id} at index {refusal.index}: {refusal.reason}",
        )
    row = current.state["rows"].get(event.get("row_id") or "")
    claim_ids = tuple(row.get("claim_ids") or []) if row else ()
    work_product: list[str] = []
    for past in events:
        if past.get("kind") != "row_update" or past.get("row_id") != event.get("row_id"):
            continue
        payload = past.get("payload") or {}
        if (payload.get("changes") or {}).get("status") == "in_review":
            recorded = payload.get("work_product")
            if isinstance(recorded, list):
                work_product = [str(item) for item in recorded]
    queue_dir = verdict_context.get("gatekeeper_queue_dir")
    ci_dir = verdict_context.get("ci_records_dir")
    check = verdicts.evaluate_verdict(
        event["payload"]["verdict_ref"],
        claim_ids=claim_ids,
        work_product=tuple(work_product),
        board_dir=board_dir,
        gatekeeper_queue_dir=Path(queue_dir) if queue_dir else None,
        ci_records_dir=Path(ci_dir) if ci_dir else None,
    )
    payload = dict(event["payload"])
    payload["verdict_evaluation"] = {
        "outcome": check.outcome,
        "detail": check.detail,
        "record_hash": check.record_hash,
    }
    return payload


def _wait_registration(event: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The (row_id, wait) a caller event registers, or None.

    A wait is registered by a row creation carrying one, by a block
    transition's changes, or by an amendment's changes. Consuming a
    wait (changes setting it to null) is not a registration.
    """
    payload = event.get("payload") or {}
    kind = event.get("kind")
    if kind == "row_created":
        wait = payload.get("wait")
        if isinstance(wait, dict):
            return str(payload.get("row_id")), wait
    elif kind in ("row_update", "amendment"):
        changes = payload.get("changes") or {}
        wait = changes.get("wait")
        if isinstance(wait, dict):
            return str(event.get("row_id")), wait
    return None


def find_registration(
    events: list[dict[str, Any]], row_id: str, wait: dict[str, Any]
) -> str | None:
    """The event_id that registered a row's current wait, or None.

    Scans for the latest event whose registered wait equals the
    row's current wait object; the keeper and the sweep cite waits
    by their registration event.
    """
    found: str | None = None
    for event in events:
        registration = _wait_registration(event)
        if registration is not None and registration[0] == row_id and registration[1] == wait:
            found = event["event_id"]
    return found


def find_wake(
    events: list[dict[str, Any]], registration_id: str | None, row_id: str
) -> dict[str, Any] | None:
    """The wake event that fired for a registration, or None."""
    if registration_id is None:
        return None
    for event in events:
        if event.get("kind") != "wake":
            continue
        payload = event.get("payload") or {}
        if payload.get("wait_event") == registration_id and payload.get("row") == row_id:
            return event
    return None


def _record_locations(context: dict[str, Any]) -> dict[str, Any]:
    """Record-source locations from a verdict/keeper context dict."""
    locations: dict[str, Any] = {}
    queue_dir = context.get("gatekeeper_queue_dir")
    if queue_dir:
        locations["gatekeeper_queue_dir"] = Path(queue_dir)
    ledger = context.get("gatekeeper_ledger")
    if ledger:
        locations["gatekeeper_ledger"] = Path(ledger)
    ci_dir = context.get("ci_records_dir")
    if ci_dir:
        locations["ci_records_dir"] = Path(ci_dir)
    return locations


def _dependency_satisfied(
    board_state: dict[str, Any], row: dict[str, Any] | None, wait: dict[str, Any]
) -> tuple[bool, str] | None:
    """Whether a dependency wait stands satisfied, and why.

    The one satisfaction rule, used at registration (FR-P3) and at
    the done transition (A5.1.3) alike: a wait whose ``match`` names
    a row is satisfied by that row standing done; otherwise a wait
    on a row with dependencies is satisfied when every dependency
    stands done. A wait with neither a named match nor dependencies
    has no mechanical rule here and returns None — its falsifier
    decides.
    """
    rows = board_state.get("rows", {})
    match = wait.get("match") or {}
    named = match.get("row_id") or match.get("row")
    if named is not None:
        status = (rows.get(named) or {}).get("status")
        return (
            status == "done",
            f"dependency {named!r} named by the wait's match stands {status!r}",
        )
    depends_on = (row or {}).get("depends_on") or []
    if depends_on:
        outstanding = [dep for dep in depends_on if (rows.get(dep) or {}).get("status") != "done"]
        if outstanding:
            return False, f"dependencies not yet done: {outstanding}"
        return True, "every dependency of the row stands done"
    return None


def _evaluate_registration(
    events: list[dict[str, Any]],
    stored: dict[str, Any],
    row_id: str,
    wait: dict[str, Any],
    context: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """The append path's wake-on-watch evaluation (FR-P3).

    Returns the ``wake_check`` stamp for the registration event. A
    ``dependency`` wait is judged by the satisfaction rule
    (``_dependency_satisfied``), falling back to its wake falsifier
    when the rule does not reach it; every other kind is evaluated
    against its wake falsifier's record. The result is stamped into
    the event before it is hashed, so the check is part of the chain
    (the ``verdict_evaluation`` precedent of FR-K1a).
    """
    # The state is the fold of the existing log: the registration
    # event is not yet stamped (writer, hashes), so it cannot fold,
    # and it does not change any other row. A row created by the
    # registration itself takes its depends_on from its payload.
    folded = fold.fold_events(events, fold.default_board_checker())
    board_state = folded.state if folded.ok else {}
    if wait.get("wait_kind") == "dependency":
        row = board_state.get("rows", {}).get(row_id)
        if row is None:
            row = {"depends_on": (stored.get("payload") or {}).get("depends_on") or []}
        satisfied = _dependency_satisfied(board_state, row, wait)
        if satisfied is not None:
            holds, detail = satisfied
            return {
                "outcome": "holds" if holds else "not_yet",
                "detail": detail,
                "evaluated_at": records.format_timestamp(now),
                "evaluator": "append-path",
            }
    outcome = records.evaluate_falsifier(
        wait,
        board_state=board_state,
        now=now,
        **_record_locations(context),
    )
    return {
        "outcome": outcome.outcome,
        "detail": outcome.detail,
        "evaluated_at": records.format_timestamp(now),
        "evaluator": "append-path",
        "citation": outcome.citation,
    }


def _refuse_short_deadline(
    events: list[dict[str, Any]], event: dict[str, Any], wait: dict[str, Any], now: datetime
) -> None:
    """FR-P4's registration guard: the sweep deadline must leave the
    keeper at least two cadence intervals to observe the wait.

    A registration re-appended by fork recovery (its payload carries
    ``recovered_from``) is a restoration, not a new registration:
    the refusal does not apply, and the keeper's first sweep bounds
    the wait instead. The exemption is recorded in the event's
    wake_check detail by the caller.
    """
    payload = event.get("payload") or {}
    if "recovered_from" in payload:
        return
    folded = fold.fold_events(events, fold.default_board_checker())
    genesis = (folded.state.get("genesis") or {}) if folded.ok else {}
    cadence = records.parse_cadence(genesis.get("keeper_cadence"))
    if cadence is None:
        raise BoardRefusal(
            "SCHEMA",
            "the board's genesis keeper_cadence does not parse; "
            "a wait cannot be registered against an unknown cadence",
        )
    deadline = records.parse_timestamp(wait.get("sweep_deadline"))
    if deadline is None:
        raise BoardRefusal(
            "SCHEMA",
            f"the wait's sweep_deadline {wait.get('sweep_deadline')!r} is not an ISO timestamp",
        )
    minimum = now + 2 * cadence
    if deadline < minimum:
        raise BoardRefusal(
            "SWEEP_DEADLINE",
            f"the wait's sweep_deadline {records.format_timestamp(deadline)} is less "
            f"than two keeper-cadence intervals ({genesis.get('keeper_cadence')}) after "
            f"registration ({records.format_timestamp(minimum)} at the earliest); "
            "FR-P4 refuses the registration",
        )


def _derive_system_events(
    events: list[dict[str, Any]],
    primary: dict[str, Any],
    context: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    """System wake events the append operation owes for ``primary``.

    Two duties, both the append path's (spec 5.1 as amended):

    - Wake-on-watch (FR-P3): if ``primary`` registered a wait whose
      ending condition already holds, a wake fires in the same
      operation.
    - Dependency wakes (A5.1.3): if ``primary`` is a ``done``
      transition, every dependent whose ``dependency`` wait that
      transition satisfies gets a wake in the same operation. A wait
      whose ``match`` names a row is satisfied by that row's
      completion; an unnamed dependency wait is satisfied when every
      dependency of the waiting row stands done.

    ``events`` includes ``primary``. Wake event ids are derived
    deterministically from the primary's id, so an idempotent retry
    of the primary re-derives exactly the wakes that never landed
    and no others. A wake whose registration already has one is
    never derived twice.
    """
    events = list(events)
    folded = fold.fold_events(events, fold.default_board_checker())
    if not folded.ok:
        return []
    board_state = folded.state
    rows = board_state.get("rows", {})
    derived: list[dict[str, Any]] = []
    head = primary["event_hash"]

    def add_wake(row_id: str, registration_id: str, via: str, detail: str) -> None:
        nonlocal head
        wake_id = f"wake:{primary['event_id']}:{row_id}"
        if any(existing["event_id"] == wake_id for existing in events):
            return
        if find_wake(events, registration_id, row_id) is not None:
            return
        wake = {
            "event_id": wake_id,
            "board_id": primary["board_id"],
            "row_id": row_id,
            "actor": "system",
            "kind": "wake",
            "payload": {
                "row": row_id,
                "wait_event": registration_id,
                "via": via,
                "detail": detail,
            },
        }
        wake["writer"] = writer_stamp(primary["board_id"])
        wake["prev_hash"] = head
        wake["event_hash"] = canonical.event_hash(wake)
        head = wake["event_hash"]
        derived.append(wake)
        events.append(wake)

    registration = _wait_registration(primary)
    if registration is not None:
        row_id, wait = registration
        stamp = (primary.get("payload") or {}).get("wake_check") or {}
        if stamp.get("outcome") == "holds":
            add_wake(
                row_id,
                primary["event_id"],
                "wake_on_watch",
                f"the wait's ending condition already held at registration: {stamp.get('detail')}",
            )
    payload = primary.get("payload") or {}
    changes = payload.get("changes") or {}
    if primary.get("kind") == "row_update" and changes.get("status") == "done":
        done_row = primary.get("row_id")
        for row_id, row in rows.items():
            if row_id == done_row:
                continue
            wait = row.get("wait")
            if not isinstance(wait, dict) or wait.get("wait_kind") != "dependency":
                continue
            registration_id = find_registration(events, row_id, wait)
            if registration_id is None:
                continue
            satisfied = _dependency_satisfied(board_state, row, wait)
            if satisfied is not None and satisfied[0]:
                add_wake(row_id, registration_id, "dependency", satisfied[1])
    return derived


def _commit_batch(
    board_dir: Path, events: list[dict[str, Any]], batch: list[dict[str, Any]]
) -> None:
    """Fold-check a batch incrementally, write it, refold, write state.

    Every fold check runs BEFORE any write: an event the fold
    refuses must never enter the log. (Phase 1 wrote first and
    checked after; a refused event then stood in the log and every
    later append re-refused at the same event, bricking the board.
    The pre-write check is the fix; the post-write fold remains as
    the state-writing step and a safety net.)
    """
    sequence = list(events)
    for stored in batch:
        check = fold.fold_events([*sequence, stored], fold.default_board_checker())
        if not check.ok:
            refusal = check.refusal
            assert refusal is not None
            raise BoardRefusal(
                "FOLD_REFUSED",
                f"the event does not fold: event {refusal.event_id} "
                f"at index {refusal.index}: {refusal.reason}",
            )
        sequence.append(stored)
    log_path = board_dir / fold.EVENTS_FILE
    for stored in batch:
        if not _append_verified(log_path, canonical.canonical_line(stored)):
            raise BoardRefusal(
                "APPEND_UNVERIFIED", "the append could not be verified after retries"
            )
    result = fold.fold_board(board_dir)
    if not result.ok:
        refusal = result.refusal
        assert refusal is not None
        raise BoardRefusal(
            "FOLD_REFUSED",
            f"the appended event does not fold: event {refusal.event_id} "
            f"at index {refusal.index}: {refusal.reason}",
        )
    state.write_state(board_dir, result.state)


def append_event(
    board_dir: Path,
    event: dict[str, Any],
    expected_prev_hash: str,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
    verdict_context: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append one caller event; returns the stored event.

    Raises BoardRefusal with a named code on any refusal. On an
    idempotent retry (event_id already present) returns the existing
    stored event; any system wakes the original append owed that
    never landed (a crash between the primary write and its derived
    wakes) are derived and appended first, so a retry completes the
    operation rather than merely repeating it. ``verdict_context``
    supplies the record locations verdict attachments and wait
    falsifiers resolve against: ``gatekeeper_queue_dir``,
    ``gatekeeper_ledger`` and ``ci_records_dir``. ``now`` is the
    append's clock for the FR-P3 evaluation and the FR-P4 deadline
    refusal; it defaults to the real clock and exists so drills run
    on stated times.
    """
    board_dir = Path(board_dir)
    problems = validate.validate_caller_event(event)
    if problems:
        raise BoardRefusal("SCHEMA", "; ".join(problems))
    moment = now or records.utcnow()
    context = verdict_context or {}
    with _AppendLock(board_dir, lock_timeout):
        events = _read_events(board_dir)
        for existing in events:
            if existing["event_id"] == event["event_id"]:
                derived = _derive_system_events(events, existing, context, moment)
                if derived:
                    _commit_batch(board_dir, events, derived)
                return existing
        head = events[-1]["event_hash"] if events else canonical.GENESIS_PREV_HASH
        if expected_prev_hash != head:
            raise BoardRefusal(
                "HEAD_MOVED",
                f"expected prev_hash {expected_prev_hash} but the log head "
                f"is {head}; re-read and retry",
            )
        stored = dict(event)
        if event["kind"] == "verdict_attached":
            stored["payload"] = _stamped_attachment_payload(board_dir, events, event, context)
        registration = _wait_registration(stored)
        if registration is not None:
            row_id, wait = registration
            _refuse_short_deadline(events, stored, wait, moment)
            stamp = _evaluate_registration(events, stored, row_id, wait, context, moment)
            if "recovered_from" in (stored.get("payload") or {}):
                stamp["detail"] = (
                    f"{stamp['detail']} (re-registered by fork recovery; "
                    "the FR-P4 deadline refusal does not apply to a restoration)"
                )
            payload = dict(stored["payload"])
            payload["wake_check"] = stamp
            stored["payload"] = payload
        stored["writer"] = writer_stamp(event["board_id"])
        stored["prev_hash"] = head
        stored["event_hash"] = canonical.event_hash(stored)
        batch = [stored]
        check = fold.fold_events([*events, stored], fold.default_board_checker())
        if not check.ok:
            refusal = check.refusal
            assert refusal is not None
            raise BoardRefusal(
                "FOLD_REFUSED",
                f"the event does not fold: event {refusal.event_id} "
                f"at index {refusal.index}: {refusal.reason}",
            )
        derived = _derive_system_events([*events, stored], stored, context, moment)
        batch.extend(derived)
        _commit_batch(board_dir, events, batch)
        return stored


def create_board(board_dir: Path, genesis_payload: dict[str, Any], actor: str) -> dict[str, Any]:
    """Create a board directory and append its genesis event.

    Writes the .gitattributes eol=lf lines (the genesis checklist item
    of FR-S1), an empty log, and the genesis event through the append
    path itself.
    """
    board_dir = Path(board_dir)
    board_dir.mkdir(parents=True, exist_ok=True)
    (board_dir / ".gitattributes").write_text(
        "*.jsonl text eol=lf\nstate.json text eol=lf\n", encoding="utf-8"
    )
    log_path = board_dir / fold.EVENTS_FILE
    if not log_path.exists():
        log_path.write_bytes(b"")
    genesis = {
        "event_id": f"genesis-{genesis_payload['board_id']}",
        "board_id": genesis_payload["board_id"],
        "row_id": None,
        "actor": actor,
        "kind": "genesis",
        "payload": genesis_payload,
    }
    return append_event(board_dir, genesis, canonical.GENESIS_PREV_HASH)


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in ("create", "append"):
        print(__doc__)
        return 2
    command, board_dir = argv[0], Path(argv[1])
    request = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    try:
        if command == "create":
            stored = create_board(board_dir, request["payload"], request["actor"])
        else:
            stored = append_event(
                board_dir,
                request["event"],
                request["expected_prev_hash"],
                verdict_context=request.get("verdict_context"),
            )
    except BoardRefusal as refusal:
        print(f"REFUSED {refusal.code}: {refusal.message}")
        return 1
    print(json.dumps(stored, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
