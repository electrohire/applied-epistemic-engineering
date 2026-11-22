#!/usr/bin/env python3
"""The kernel: the canonical transition table and its guards.

Spec AB-001 Section 4 (as amended), tasks T008 (transition table),
T009 (resumption notes, FR-K3), T011 (amendment mechanics, FR-K4),
T012 (assignment rules, FR-K5). Section 4.7: this module is the one
canonical machine form of the kernel; the extension's shipped
definitions are pinned to it by hash until generation replaces pinning.

The kernel plugs into the fold through the substrate's seam
(``board.fold``): ``kernel_checker`` first applies the substrate's
structural rules, then the kernel's. The append path and
``fold.fold_board`` enforce this checker, so a transition not in the
table, or failing its guard, is refused before it can stand in a log.

What an event looks like, on top of the substrate's kinds:

- A status transition is a ``row_update`` event whose payload
  ``changes`` carry ``status``; transition-specific data rides in the
  payload beside ``changes`` (``work_product``, ``wake_ref``,
  ``override_reason``, ``comment_ref``, ``verdict_ref``, ``reason``,
  ``replaced_by``, and ``resumption_note`` for a block). A block's
  ``resumption_note`` is payload-level; the fold copies it onto the
  row. A ``row_update`` may otherwise change only ``execution_state``
  and ``blocker_note`` (transport fact and annotation); every other
  field has its own path (amendment, attachment) or is immutable.
- A verdict attachment is a ``verdict_attached`` event (FR-K1a). Its
  payload carries ``verdict_ref`` and the append service's stamped
  ``verdict_evaluation`` (see ``board.verdicts``); an attachment
  without the stamp does not fold, so a hand-written log cannot
  manufacture a favorable verdict.
- An amendment is an ``amendment`` event whose payload carries
  ``changes`` plus ``reason`` and ``authority`` (FR-K4).

Honesty note (spec 4.2, Amendment 1): the table's actor column names
roles, and in the pilot those roles are accountability controls, not
authentication. This checker mechanically enforces everything that
does not depend on who is speaking — legal transitions, guards over
board state, the favorable-verdict requirement, WIP counts, cycle
refusal — and one comparison that is state-based rather than
role-based: the row's named holder (``assignee_instance``) may not
attach the row's own verdict (FR-K1a). Actor-based rules beyond that
(planner-only promotion, reviewer-only ``done``) are recorded in the
log and detectable after the fact; they are not structurally
prevented, and no surface may claim otherwise.

This does not establish that actors will not collude outside the
board; the board records what it is told, and the verdict rules
limit what that can buy.
"""

from __future__ import annotations

import re
from typing import Any

from . import fold, validate

STATUSES = (
    "proposed",
    "planned",
    "ready",
    "in_progress",
    "blocked",
    "in_review",
    "done",
    "withdrawn",
    "superseded",
)
TERMINAL_STATUSES = frozenset({"done", "withdrawn", "superseded"})
NON_TERMINAL_STATUSES = tuple(s for s in STATUSES if s not in TERMINAL_STATUSES)
CREATION_STATUSES = ("proposed", "planned")

# The pinned transition table (spec 4.2). Keys are (from, to); a
# from-status of None is row creation. The actor column is recorded
# for the canonical form; per the honesty note it is accountability,
# not enforcement, except where a guard below says otherwise.
TRANSITIONS: dict[tuple[str | None, str], dict[str, str]] = {
    (None, "proposed"): {
        "actor": "planner",
        "guard": "via spec draft or amendment event with reason",
    },
    (None, "planned"): {
        "actor": "generator (planner-authorized)",
        "guard": "genesis records spec_hash; the row traces to a line "
        "of the frozen artifact",
    },
    ("proposed", "planned"): {
        "actor": "planner",
        "guard": "the row's spec artifact is frozen (genesis spec_hash)",
    },
    ("planned", "ready"): {
        "actor": "planner only",
        "guard": "all depends_on rows are done",
    },
    ("ready", "in_progress"): {
        "actor": "assignee (kind holder or named instance)",
        "guard": "single holder; the board's wip_limit is not exceeded",
    },
    ("in_progress", "blocked"): {
        "actor": "holder",
        "guard": "a structured wait is registered and the resumption "
        "note carries its four parts (FR-K3)",
    },
    ("blocked", "in_progress"): {
        "actor": "holder (same or reassigned by planner)",
        "guard": "a wake event exists for the registered wait, or the "
        "planner overrides with a recorded reason; the wait is consumed",
    },
    ("in_progress", "in_review"): {
        "actor": "holder",
        "guard": "work product references recorded in the transition event",
    },
    ("in_review", "in_progress"): {
        "actor": "reviewer",
        "guard": "comment event with a record reference, or a "
        "verdict-driven return recording the verdict_ref",
    },
    ("in_review", "done"): {
        "actor": "reviewer or planner",
        "guard": "verdict_ref attached by a verdict-attachment event "
        "and favorable for its class (FR-K1); the transition event "
        "carries the full verdict_ref",
    },
}
for _from in NON_TERMINAL_STATUSES:
    TRANSITIONS[(_from, "withdrawn")] = {
        "actor": "planner",
        "guard": "reason recorded",
    }
    TRANSITIONS[(_from, "superseded")] = {
        "actor": "planner",
        "guard": "pointer to the replacing row recorded",
    }
del _from

# Fields a row_update's changes may carry. Status changes are
# transitions (table above); wait rides only with a block or unblock
# transition; verdict_ref, depends_on, assignees and body have their
# own paths and are refused here.
ROW_UPDATE_CHANGE_FIELDS = frozenset({"status", "execution_state", "blocker_note", "wait"})

# FR-K4: the amendable fields are exactly these (pinned in
# board/schema.json, read via board.validate). verdict_ref changes
# only by superseding attachment (FR-K1a); anything else is a
# supersede-and-replace of the row.
AMENDABLE_FIELDS = validate.AMENDABLE_FIELDS

# FR-K3: the resumption note's four labeled parts.
NOTE_PARTS = (
    "Current position",
    "Next action",
    "Records that matter",
    "What would change the plan",
)

# The verdict_ref format (spec 4.3): class, identifier, and the
# content hash (engine, gatekeeper, gate) or head SHA (ci) captured
# at citation time. board.verdicts owns resolution and favorability;
# this pattern is the fold's structural check on the reference.
_VERDICT_REF = re.compile(
    r"^(?P<cls>engine|gatekeeper|ci|gate):(?P<identifier>.+)#(?P<digest>[0-9a-f]{40,64})$"
)


def parse_verdict_ref_shape(verdict_ref: Any) -> dict[str, str] | None:
    """The ref's parts if it matches the pinned format, else None."""
    if not isinstance(verdict_ref, str):
        return None
    match = _VERDICT_REF.match(verdict_ref)
    if match is None:
        return None
    parts = match.groupdict()
    expected = 40 if parts["cls"] == "ci" else 64
    if len(parts["digest"]) != expected:
        return None
    return parts


def validate_resumption_note(note: Any) -> list[str]:
    """Problems with a resumption note ([] means acceptable).

    FR-K3: the note must carry the four labeled parts, checked for
    presence as labeled sections — a line beginning with the label,
    a colon, and non-empty content. Quality is not judged; KB-3
    measures whether the notes pay.
    """
    if not isinstance(note, str) or not note.strip():
        return ["resumption_note is missing or empty"]
    problems: list[str] = []
    lines = note.splitlines()
    for part in NOTE_PARTS:
        found = False
        for line in lines:
            head, sep, tail = line.partition(":")
            if sep and head.strip().lower() == part.lower() and tail.strip():
                found = True
                break
        if not found:
            problems.append(f"resumption_note lacks a labeled part: {part!r}")
    return problems


def _depends_map(state: dict[str, Any]) -> dict[str, list[str]]:
    return {row_id: list(row.get("depends_on", [])) for row_id, row in state["rows"].items()}


def _reaches(deps: dict[str, list[str]], start: str, target: str) -> bool:
    stack = [start]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(deps.get(node, []))
    return False


def creates_cycle(state: dict[str, Any], row_id: str, depends_on: list[str]) -> bool:
    """True if giving ``row_id`` these dependencies closes a cycle.

    Checked over the full graph as amended: the pre-existing graph is
    acyclic by induction (every edge addition is checked here), so it
    suffices to ask whether the row can reach itself through the
    amended graph. Dependencies on rows not yet created are forward
    references; the cycle, if any, is refused when the closing row or
    amendment lands.
    """
    deps = _depends_map(state)
    deps[row_id] = list(depends_on)
    return any(dep == row_id or _reaches(deps, dep, row_id) for dep in depends_on)


def _row(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any] | None:
    row_id = event.get("row_id")
    if row_id is None:
        payload = event.get("payload") or {}
        row_id = payload.get("row_id")
    return state["rows"].get(row_id) if row_id else None


def _check_creation(event: dict[str, Any], state: dict[str, Any]) -> str | None:
    payload = event.get("payload") or {}
    row_id = payload.get("row_id")
    status = payload.get("status", "proposed")
    if (None, status) not in TRANSITIONS:
        return (
            f"kernel table: a row is created as proposed or planned, not {status!r} "
            "(spec 4.2 creation rows)"
        )
    if payload.get("gate_row") is True and payload.get("assignee_kind") is not None:
        return (
            "kernel FR-K5: a gate row takes a named assignee_instance; "
            "a kind assignee is refused"
        )
    depends_on = payload.get("depends_on") or []
    if creates_cycle(state, row_id, list(depends_on)):
        return f"kernel FR-K4: creating row {row_id!r} with these dependencies closes a cycle"
    return None


def _check_transition(
    event: dict[str, Any], state: dict[str, Any], row: dict[str, Any]
) -> str | None:
    payload = event.get("payload") or {}
    changes = payload.get("changes") or {}
    unknown = set(changes) - ROW_UPDATE_CHANGE_FIELDS
    if unknown:
        return (
            "kernel: row_update changes may carry only "
            f"{sorted(ROW_UPDATE_CHANGE_FIELDS)}; refused fields: {sorted(unknown)} "
            "(other fields move by amendment or verdict attachment)"
        )
    if "wait" in changes and "status" not in changes:
        return "kernel: a wait change rides a block or unblock transition, not a bare update"
    if "status" not in changes:
        return None  # execution_state / blocker_note annotation only
    from_status = row["status"]
    to_status = changes["status"]
    if (from_status, to_status) not in TRANSITIONS:
        return f"kernel table: no transition {from_status!r} -> {to_status!r} (spec 4.2)"
    genesis = state.get("genesis") or {}
    if to_status == "ready":
        for dep in row.get("depends_on", []):
            dep_row = state["rows"].get(dep)
            if dep_row is None:
                return f"kernel guard: dependency {dep!r} does not exist; it cannot be done"
            if dep_row["status"] != "done":
                return (
                    f"kernel guard: dependency {dep!r} is {dep_row['status']!r}, "
                    "not done; the row cannot be promoted to ready"
                )
    elif (from_status, to_status) == ("ready", "in_progress"):
        if row.get("assignee_kind") is None and row.get("assignee_instance") is None:
            return "kernel guard: taking a row requires a recorded holder (assignee)"
        wip_limit = genesis.get("wip_limit")
        in_progress = sum(1 for r in state["rows"].values() if r["status"] == "in_progress")
        if isinstance(wip_limit, int) and in_progress >= wip_limit:
            return (
                f"kernel guard: the board's wip_limit {wip_limit} is reached "
                f"({in_progress} rows in progress)"
            )
    elif (from_status, to_status) == ("in_progress", "blocked"):
        wait = changes.get("wait", row.get("wait"))
        if wait is None:
            return "kernel guard: blocking requires a registered structured wait"
        problems = validate.validate_wait(wait, "block wait")
        if problems:
            return "kernel guard: " + "; ".join(problems)
        problems = validate_resumption_note(payload.get("resumption_note"))
        if problems:
            return "kernel FR-K3: " + "; ".join(problems)
    elif (from_status, to_status) == ("blocked", "in_progress"):
        if changes.get("wait") is not None or "wait" not in changes:
            return (
                "kernel guard: unblocking consumes the registered wait "
                "(changes set wait to null)"
            )
        wake_ref = payload.get("wake_ref")
        override = payload.get("override_reason")
        if not (isinstance(wake_ref, str) and wake_ref.strip()) and not (
            isinstance(override, str) and override.strip()
        ):
            return (
                "kernel guard: unblocking requires a wake reference or a "
                "planner override with a recorded reason"
            )
    elif (from_status, to_status) == ("in_progress", "in_review"):
        work = payload.get("work_product")
        if (
            not isinstance(work, list)
            or not work
            or not all(isinstance(item, str) and item.strip() for item in work)
        ):
            return (
                "kernel guard: entering review requires work product "
                "references recorded in the transition event"
            )
    elif (from_status, to_status) == ("in_review", "in_progress"):
        comment_ref = payload.get("comment_ref")
        verdict_ref = payload.get("verdict_ref")
        if isinstance(verdict_ref, str) and verdict_ref:
            if verdict_ref != row.get("verdict_ref"):
                return (
                    "kernel guard: a verdict-driven return records the row's "
                    "attached verdict_ref, not a different reference"
                )
        elif not (isinstance(comment_ref, str) and comment_ref.strip()):
            return (
                "kernel guard: the rework path requires a comment event "
                "with a record reference, or a verdict-driven return"
            )
    elif (from_status, to_status) == ("in_review", "done"):
        verdict_ref = row.get("verdict_ref")
        if not verdict_ref:
            return "kernel FR-K1: done requires an attached verdict_ref"
        attachment = (state.get("attachments") or {}).get(row["row_id"])
        if attachment is None or attachment.get("verdict_ref") != verdict_ref:
            return "kernel FR-K1a: the row's verdict_ref was not set by a verdict-attachment event"
        evaluation = attachment.get("evaluation") or {}
        if evaluation.get("outcome") != "favorable":
            return (
                "kernel FR-K1: the attached verdict is "
                f"{evaluation.get('outcome', 'unevaluated')}, not favorable; the row "
                "routes only to in_progress or withdrawn"
            )
        if payload.get("verdict_ref") != verdict_ref:
            return (
                "kernel FR-K1: the done transition event carries the full "
                "verdict_ref including its hash"
            )
    elif to_status == "withdrawn":
        reason = payload.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            return "kernel guard: withdrawal records a reason"
    elif to_status == "superseded":
        replaced_by = payload.get("replaced_by")
        if not (isinstance(replaced_by, str) and replaced_by.strip()):
            return "kernel guard: superseding records the replacing row"
        if replaced_by == row["row_id"]:
            return "kernel guard: a row cannot supersede itself"
        if replaced_by not in state["rows"]:
            return f"kernel guard: the replacing row {replaced_by!r} does not exist"
    return None


def _check_amendment(
    event: dict[str, Any], state: dict[str, Any], row: dict[str, Any]
) -> str | None:
    payload = event.get("payload") or {}
    reason = payload.get("reason")
    if not (isinstance(reason, str) and reason.strip()):
        return "kernel FR-K4: an amendment records its reason"
    authority = payload.get("authority")
    if not (isinstance(authority, str) and authority.strip()):
        return "kernel FR-K4: an amendment records its authority"
    changes = payload.get("changes") or {}
    if not changes:
        return "kernel FR-K4: an amendment carries changes"
    refused = set(changes) - AMENDABLE_FIELDS
    if refused:
        named = sorted(refused)
        if "verdict_ref" in refused:
            return (
                "kernel FR-K1a/FR-K4: verdict_ref changes only by superseding "
                f"attachment, never by amendment (refused fields: {named})"
            )
        return (
            "kernel FR-K4: the amendable fields are exactly "
            f"{sorted(AMENDABLE_FIELDS)}; refused fields: {named} "
            "(any other change is a supersede-and-replace of the row)"
        )
    if (
        "assignee_kind" in changes
        and changes["assignee_kind"] is not None
        and row["row_id"] in (state.get("gate_rows") or [])
    ):
        return (
            "kernel FR-K5: a gate row takes a named assignee_instance; "
            "a kind assignee is refused"
        )
    if ("assignee_kind" in changes or "assignee_instance" in changes) and row["status"] in (
        "in_progress",
        "blocked",
    ):
        problems = validate_resumption_note(payload.get("resumption_note"))
        if problems:
            return "kernel FR-K3 (handoff): " + "; ".join(problems)
    if "wait" in changes and changes["wait"] is not None:
        problems = validate.validate_wait(changes["wait"], "amendment wait")
        if problems:
            return "kernel FR-K4: " + "; ".join(problems)
    if "depends_on" in changes and creates_cycle(
        state, row["row_id"], list(changes["depends_on"] or [])
    ):
        return "kernel FR-K4: this amendment closes a cycle in the depends_on graph"
    return None


def _check_attachment(
    event: dict[str, Any], state: dict[str, Any], row: dict[str, Any]
) -> str | None:
    payload = event.get("payload") or {}
    verdict_ref = payload.get("verdict_ref")
    if parse_verdict_ref_shape(verdict_ref) is None:
        return (
            "kernel FR-K1: a verdict_ref is class:identifier#hash in the "
            "pinned format of spec 4.3"
        )
    current = row.get("verdict_ref")
    if current is None:
        if payload.get("previous_ref") is not None:
            return "kernel FR-K1a: a first attachment records no previous reference"
    else:
        if payload.get("previous_ref") != current:
            return (
                "kernel FR-K1a: a superseding attachment records the previous "
                "reference it replaces"
            )
        reason = payload.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            return "kernel FR-K1a: a superseding attachment records its reason"
    if row.get("assignee_instance") is not None and event.get("actor") == row["assignee_instance"]:
        return (
            "kernel FR-K1a: the row's current holder may not attach the "
            "row's own verdict"
        )
    evaluation = payload.get("verdict_evaluation")
    if not isinstance(evaluation, dict) or evaluation.get("outcome") not in (
        "favorable",
        "unfavorable",
        "unresolvable",
    ):
        return (
            "kernel FR-K1a: a verdict attachment carries the append "
            "service's stamped verdict_evaluation; unstamped attachments "
            "do not fold"
        )
    return None


def kernel_checker(event: dict[str, Any], state: dict[str, Any]) -> str | None:
    """The kernel's transition legality, composed over the substrate's.

    Returns a refusal reason or None. Actor-column rules are
    accountability, not enforcement (see the module docstring), with
    the one state-based exception in FR-K1a.
    """
    reason = fold.structural_checker(event, state)
    if reason is not None:
        return reason
    kind = event["kind"]
    if kind == "genesis" or kind == "recovery":
        return None
    if state.get("genesis") is None:
        return None  # structural checker already refused non-genesis firsts
    if kind == "halt":
        payload = event.get("payload") or {}
        marker = payload.get("reason") or payload.get("tripwire")
        if not (isinstance(marker, str) and marker.strip()):
            return "kernel guard: a halt event records the tripwire class or the planner's reason"
        return None
    if kind == "resume":
        payload = event.get("payload") or {}
        if not state.get("halted"):
            return "kernel guard: a resume event requires a halted board"
        if payload.get("halt_event") != state.get("halt_event"):
            return "kernel guard: a resume event references the halt event it ends"
        reason_text = payload.get("reason")
        if not (isinstance(reason_text, str) and reason_text.strip()):
            return "kernel guard: a resume event records its reason"
        return None
    if kind == "row_created":
        return _check_creation(event, state)
    row = _row(state, event)
    if row is None:
        return None  # structural checker names unknown rows
    if row["status"] in TERMINAL_STATUSES:
        return (
            f"kernel table: row {row['row_id']!r} is {row['status']} "
            "(terminal); no further events"
        )
    if kind == "row_update":
        return _check_transition(event, state, row)
    if kind == "amendment":
        return _check_amendment(event, state, row)
    if kind == "verdict_attached":
        return _check_attachment(event, state, row)
    return None
