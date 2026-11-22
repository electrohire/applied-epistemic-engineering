#!/usr/bin/env python3
"""The generated tasks view (spec AB-001 3.3, FR-S5; 4.3, FR-K2; task T007).

The human tasks rendering is generated from board state by script,
carries a generated-file header and the head hash it was generated
from, and is never hand-edited. Freshness is labeled: a view generated
from a stale state says so, with both hashes.

FR-K2 rendering constraint: any surface showing a row's state shows
``status`` and ``execution_state`` together or neither, and
``execution_state`` is never rendered as completion. In this view a
row line always carries both fields, in that order, and the word for
completion appears only as a status value from the kernel's enum.

This does not establish that board state is correct, only that the
two surfaces never disagree silently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import fold, state

VIEW_FILE = "tasks.md"
GENERATED_HEADER = "<!-- GENERATED from board state by board/view.py - do not edit by hand. -->"


def render_view(state_obj: dict[str, Any], freshness_info: dict[str, Any]) -> str:
    lines = [GENERATED_HEADER]
    lines.append(f"# Board: {state_obj.get('board_id', '')}")
    lines.append(f"Generated from head: {state_obj.get('head_hash', '')}")
    if freshness_info.get("status") == "stale":
        lines.append(
            "STALE: state head "
            f"{freshness_info.get('state_head')} != log head "
            f"{freshness_info.get('log_head')}"
        )
    if state_obj.get("halted"):
        lines.append(f"HALTED at event {state_obj.get('halt_event')}")
    lines.append("")
    rows = state_obj.get("rows", {})
    if not rows:
        lines.append("No rows.")
    for row_id in sorted(rows):
        row = rows[row_id]
        lines.append(
            f"- [{row['status']}] {row_id} - {row['task_ref']} "
            f"(execution_state: {row['execution_state']})"
        )
        details = []
        if row.get("depends_on"):
            details.append(f"depends_on: {', '.join(row['depends_on'])}")
        if row.get("verdict_ref"):
            details.append(f"verdict_ref: {row['verdict_ref']}")
        if row.get("wait"):
            details.append(f"wait: {row['wait'].get('wait_kind')}")
        if details:
            lines.append(f"  - {'; '.join(details)}")
    lines.append("")
    return "\n".join(lines)


def generate_view(board_dir: Path) -> Path:
    """Generate tasks.md in the board directory from the served state."""
    board_dir = Path(board_dir)
    stored = state.read_state(board_dir)
    if stored is None:
        result = fold.fold_board(board_dir)
        if not result.ok:
            refusal = result.refusal
            assert refusal is not None
            raise ValueError(
                f"cannot generate a view: the fold refuses at event "
                f"{refusal.event_id}: {refusal.reason}"
            )
        stored = result.state
    info = state.freshness(board_dir)
    text = render_view(stored, info)
    out = board_dir / VIEW_FILE
    if not state._write_verified(out, text.encode("utf-8")):
        raise OSError(f"view write could not be verified: {out}")
    return out
