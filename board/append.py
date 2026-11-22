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
from pathlib import Path
from typing import Any

from . import canonical, fold, state, validate

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


def append_event(
    board_dir: Path,
    event: dict[str, Any],
    expected_prev_hash: str,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> dict[str, Any]:
    """Append one caller event; returns the stored event.

    Raises BoardRefusal with a named code on any refusal. On an
    idempotent retry (event_id already present) returns the existing
    stored event and writes nothing.
    """
    board_dir = Path(board_dir)
    problems = validate.validate_caller_event(event)
    if problems:
        raise BoardRefusal("SCHEMA", "; ".join(problems))
    with _AppendLock(board_dir, lock_timeout):
        events = _read_events(board_dir)
        for existing in events:
            if existing["event_id"] == event["event_id"]:
                return existing
        head = events[-1]["event_hash"] if events else canonical.GENESIS_PREV_HASH
        if expected_prev_hash != head:
            raise BoardRefusal(
                "HEAD_MOVED",
                f"expected prev_hash {expected_prev_hash} but the log head "
                f"is {head}; re-read and retry",
            )
        stored = dict(event)
        stored["writer"] = writer_stamp(event["board_id"])
        stored["prev_hash"] = head
        stored["event_hash"] = canonical.event_hash(stored)
        line = canonical.canonical_line(stored)
        log_path = board_dir / fold.EVENTS_FILE
        if not _append_verified(log_path, line):
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
            stored = append_event(board_dir, request["event"], request["expected_prev_hash"])
    except BoardRefusal as refusal:
        print(f"REFUSED {refusal.code}: {refusal.message}")
        return 1
    print(json.dumps(stored, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
