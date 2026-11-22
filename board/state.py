#!/usr/bin/env python3
"""State snapshots (spec AB-001 3.3, FR-S4; task T005).

The state file is written only by the append holder, inside the append
lock, by verified write with read-back hash, and carries the head
``event_hash`` it folded. Whenever no append is in flight the served
state's head hash equals the log head; a state file whose head differs
is labeled stale wherever surfaced, with both hashes shown.

This does not establish that the folded state is correct; that is the
KB-6 audit's question.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from . import canonical, fold

STATE_FILE = "state.json"


def _write_verified(path: Path, data: bytes, attempts: int = 8) -> bool:
    """Write via a same-directory temp file, fsync, atomic replace, and
    a read-back size check; the gatekeeper's verified-write discipline."""
    tmp = path.with_name(path.name + ".tmp")
    for i in range(attempts):
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            try:
                view = memoryview(data)
                while view:
                    n = os.write(fd, view)
                    view = view[n:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, path)
            if path.read_bytes() == data:
                return True
        except OSError:
            pass
        if i + 1 < attempts:
            time.sleep(min(0.25 * (2**i), 8.0))
    return False


def write_state(board_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Write the folded state by verified write; returns the stored object.

    The stored object is the state plus its canonical ``state_hash`` for
    read-back verification. Raises OSError if the write cannot be
    verified; a failed state write fails the append closed.
    """
    stored = dict(state)
    stored["state_hash"] = canonical.state_hash(state)
    data = canonical.canonical_line(stored)
    if not _write_verified(Path(board_dir) / STATE_FILE, data):
        raise OSError(f"state write could not be verified: {board_dir / STATE_FILE}")
    return stored


def read_state(board_dir: Path) -> dict[str, Any] | None:
    """The stored state object, or None if no state file exists.

    Raises ValueError if the file's read-back hash does not verify.
    """
    path = Path(board_dir) / STATE_FILE
    if not path.exists():
        return None
    import json

    stored = json.loads(path.read_bytes().decode("utf-8"))
    body = {k: v for k, v in stored.items() if k != "state_hash"}
    if stored.get("state_hash") != canonical.state_hash(body):
        raise ValueError(f"state file read-back hash does not verify: {path}")
    return stored


def freshness(board_dir: Path) -> dict[str, Any]:
    """Freshness of the served state against the log head.

    Returns {"status": "current" | "stale" | "missing", "state_head": ...,
    "log_head": ...}. A stale state is labeled, never silently served:
    both hashes are always shown.
    """
    log_head = fold.log_head_hash(board_dir)
    stored = read_state(board_dir)
    if stored is None:
        return {"status": "missing", "state_head": None, "log_head": log_head}
    state_head = stored.get("head_hash")
    return {
        "status": "current" if state_head == log_head else "stale",
        "state_head": state_head,
        "log_head": log_head,
    }
