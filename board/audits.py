#!/usr/bin/env python3
"""The weekly audits: spec AB-001 Section 6, tasks T018-T023.

Six scripted checks, run in the pilot's weekly rhythm (T031). Each
takes a board directory (plus its check's own inputs), reads the
board through the real fold, and returns a report dict: ``ok`` is
True only when the check ran to completion and found nothing. Every
audit fails closed: a board that cannot be read, a log that does not
fold, or a cited input that cannot be loaded is a failed report with
a finding, never a pass. Findings are the pilot's tripwire input
(Section 7.5); the weekly rhythm, not this module, decides what a
finding halts.

- ``audit_kb2`` (T018): every row that entered ``done`` since the
  last audit is re-verified against the record its ``verdict_ref``
  cites — the record is resolved now, its current content hash is
  compared against the hash captured at citation time, and its
  outcome must be favorable under Section 4.3's table (the resolver
  is ``board.verdicts``, the same one the fold's gate uses). The
  report carries ``audited_through_index`` / ``audited_through_head``
  for the next run's ``since_index``.
- ``audit_kb5`` (T019): the published tasks view is regenerated
  from the log and byte-compared. The comparison is made at the
  head the view names in its own header, so events appended after
  the view was generated (in-flight events) explain themselves; a
  view whose named head is not in the log, or whose bytes differ
  at that head, is a finding.
- ``audit_kb6`` (T020): the log is folded from genesis into a fresh
  state and byte-compared against the served state file. Any
  difference is a finding of the highest severity this spec
  defines. A log over the plan's 10,000-event pilot bound raises
  the archival question as a note.
- ``audit_trace`` (T021): every row traces to a line of the
  genesis artifact (the file whose SHA-256 is the genesis
  ``spec_hash`` and whose lines carry the row's ``task_ref``), or
  through a supersede chain or a recovery citation to a row that
  does. This is the only audit that compares the board against
  something outside itself.
- ``audit_boundary`` (T022): no row's ``spec_ref`` or ``task_ref``
  (and no board's genesis) resolves into a registered study-arm
  artifact of the ninety-day program. A hit is the Section 7.5
  tripwire firing. The registry is an input: a list of study-arm
  artifact identifiers (paths or ref strings) the program's
  registration names; the CLI reads it from a JSON file of the
  shape ``{"study_arm_artifacts": [...]}``.
- ``audit_kernel_drift`` (T023): the kernel's two homes agree.
  Until the extension ships its pinned definitions (Phase 5,
  T025), the runnable leg is the pre-check: ``board.kernel``'s
  canonical definitions against the pinned enums of
  ``board/schema.json``. When the extension's shipped definitions
  file is supplied, its canonical hash must equal
  ``board.kernel.kernel_definitions_hash()``. The report's
  ``scope`` field states which legs ran, so a schema-only pass is
  never mistaken for the full comparison.

Usage:
    python3 -m board.audits kb2 <board_dir> [--since N]
        [--gatekeeper-queue-dir D] [--ci-records-dir D]
    python3 -m board.audits kb5 <board_dir>
    python3 -m board.audits kb6 <board_dir>
    python3 -m board.audits trace <board_dir> <artifact_path>
    python3 -m board.audits boundary <registry.json> <board_dir>...
    python3 -m board.audits drift [--extension-definitions PATH]

Exit status is 0 when the report is ok, 1 otherwise.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from . import canonical, fold, kernel, state, verdicts, view

# The plan's pilot bound (plan.md, Performance Goals): a log over
# this many events raises archival at its weekly audit.
ARCHIVAL_EVENT_BOUND = 10_000


class _AuditInputError(Exception):
    """An input the audit needs cannot be read; the audit fails closed."""


def _base_report(audit: str, board_dir: Path) -> dict[str, Any]:
    return {
        "audit": audit,
        "board_dir": str(board_dir),
        "board_id": None,
        "ok": False,
        "findings": [],
        "notes": [],
    }


def _failed(report: dict[str, Any], kind: str, detail: str) -> dict[str, Any]:
    report["findings"].append({"kind": kind, "detail": detail})
    report["ok"] = False
    return report


def _read_log_lines(board_dir: Path) -> list[bytes]:
    path = Path(board_dir) / fold.EVENTS_FILE
    if not path.exists():
        raise _AuditInputError(f"the board has no log file: {path}")
    try:
        return [raw for raw in path.read_bytes().splitlines() if raw.strip()]
    except OSError as exc:
        raise _AuditInputError(f"the board's log cannot be read: {exc}") from exc


def _parse_events(lines: list[bytes]) -> list[dict[str, Any]]:
    events = []
    for index, raw in enumerate(lines):
        try:
            events.append(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _AuditInputError(f"log line {index} does not parse: {exc}") from exc
    return events


def _fold_or_fail(report: dict[str, Any], board_dir: Path) -> fold.FoldResult | None:
    """Fold the board; on any input failure record it and return None."""
    try:
        lines = _read_log_lines(board_dir)
    except _AuditInputError as exc:
        _failed(report, "board_unreadable", str(exc))
        return None
    result = fold.fold_lines(lines, fold.default_board_checker())
    if not result.ok:
        refusal = result.refusal
        assert refusal is not None
        _failed(
            report,
            "fold_refusal",
            f"the log does not fold: event {refusal.event_id} at index "
            f"{refusal.index}: {refusal.reason}",
        )
        return None
    report["board_id"] = result.state.get("board_id")
    return result


# ---------------------------------------------------------------- KB-2


def audit_kb2(
    board_dir: Path,
    *,
    since_index: int = 0,
    gatekeeper_queue_dir: Path | None = None,
    ci_records_dir: Path | None = None,
) -> dict[str, Any]:
    """KB-2 (T018): every completion since the last audit re-verified.

    ``since_index`` is the event index the previous audit reported
    as ``audited_through_index``; done entries before it are not
    rechecked (the weekly rhythm owns the cadence). Resolution is
    the fold's own resolver, ``board.verdicts.evaluate_verdict``,
    run against the records as they stand now: a record swapped
    after citation fails its citation hash, and a record whose
    outcome is not favorable fails the favorable check.
    """
    board_dir = Path(board_dir)
    report = _base_report("kb2", board_dir)
    report["since_index"] = since_index
    report["checked"] = []
    folded = _fold_or_fail(report, board_dir)
    if folded is None:
        return report
    try:
        events = _parse_events(_read_log_lines(board_dir))
    except _AuditInputError as exc:
        return _failed(report, "board_unreadable", str(exc))
    board_state = folded.state
    for index, event in enumerate(events):
        if index < since_index:
            continue
        payload = event.get("payload") or {}
        changes = payload.get("changes") or {}
        if event.get("kind") != "row_update" or changes.get("status") != "done":
            continue
        row_id = event.get("row_id")
        row = board_state.get("rows", {}).get(row_id)
        verdict_ref = payload.get("verdict_ref") or (row or {}).get("verdict_ref")
        work_product: list[str] = []
        for past in events[: index + 1]:
            if past.get("kind") != "row_update" or past.get("row_id") != row_id:
                continue
            past_payload = past.get("payload") or {}
            if (past_payload.get("changes") or {}).get("status") == "in_review":
                recorded = past_payload.get("work_product")
                if isinstance(recorded, list):
                    work_product = [str(item) for item in recorded]
        check = verdicts.evaluate_verdict(
            verdict_ref,
            claim_ids=tuple((row or {}).get("claim_ids") or []),
            work_product=tuple(work_product),
            board_dir=board_dir,
            gatekeeper_queue_dir=gatekeeper_queue_dir,
            ci_records_dir=ci_records_dir,
        )
        entry = {
            "row": row_id,
            "event_id": event.get("event_id"),
            "verdict_ref": verdict_ref,
            "outcome": check.outcome,
            "detail": check.detail,
        }
        report["checked"].append(entry)
        if check.outcome != "favorable":
            report["findings"].append(
                {
                    "kind": "done_without_favorable_record",
                    "severity": "tripwire",
                    **entry,
                }
            )
    report["audited_through_index"] = len(events)
    report["audited_through_head"] = board_state.get("head_hash")
    report["ok"] = not report["findings"]
    return report


# ---------------------------------------------------------------- KB-5


def audit_kb5(board_dir: Path) -> dict[str, Any]:
    """KB-5 (T019): the published view agrees with the log.

    The view is regenerated from the fold of the log prefix ending
    at the head the view's own header names, and byte-compared
    with the published file. Divergence at that head is a finding;
    events appended after that head are in-flight and explain
    themselves (their count is reported).
    """
    board_dir = Path(board_dir)
    report = _base_report("kb5", board_dir)
    view_path = board_dir / view.VIEW_FILE
    if not view_path.exists():
        return _failed(report, "view_missing", f"the board has no published view: {view_path}")
    try:
        published = view_path.read_bytes()
        published_text = published.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _failed(report, "view_unreadable", f"the published view cannot be read: {exc}")
    named_head = None
    freshness: dict[str, Any] = {"status": "current"}
    for line in published_text.splitlines():
        if line.startswith("Generated from head: "):
            named_head = line.partition(": ")[2].strip()
        elif line.startswith("STALE: state head "):
            match = re.match(r"STALE: state head (\S+) != log head (\S+)", line)
            if match:
                freshness = {
                    "status": "stale",
                    "state_head": match.group(1),
                    "log_head": match.group(2),
                }
    if named_head is None:
        return _failed(
            report, "view_head_missing", "the published view names no head hash in its header"
        )
    report["view_head"] = named_head
    try:
        lines = _read_log_lines(board_dir)
        events = _parse_events(lines)
    except _AuditInputError as exc:
        return _failed(report, "board_unreadable", str(exc))
    if named_head == canonical.GENESIS_PREV_HASH:
        prefix: list[dict[str, Any]] = []
    else:
        cut = next(
            (i for i, event in enumerate(events) if event.get("event_hash") == named_head), None
        )
        if cut is None:
            return _failed(
                report,
                "view_head_not_in_log",
                f"the view's named head {named_head} is not an event in the log; "
                "the view was not generated from this log",
            )
        prefix = events[: cut + 1]
    folded = fold.fold_events(prefix, fold.default_board_checker())
    if not folded.ok:
        refusal = folded.refusal
        assert refusal is not None
        return _failed(
            report,
            "fold_refusal",
            f"the log prefix to the view's head does not fold: event "
            f"{refusal.event_id} at index {refusal.index}: {refusal.reason}",
        )
    report["board_id"] = folded.state.get("board_id")
    report["in_flight_events"] = len(events) - len(prefix)
    rendered = view.render_view(folded.state, freshness)
    if rendered.encode("utf-8") != published:
        detail = "the published view differs from a regeneration at its named head"
        for number, (mine, theirs) in enumerate(
            zip(rendered.splitlines(), published_text.splitlines(), strict=False)
        ):
            if mine != theirs:
                detail += (
                    f"; first difference at line {number + 1}: "
                    f"published {theirs!r}, regenerated {mine!r}"
                )
                break
        else:
            detail += (
                f"; line counts differ (published {len(published_text.splitlines())}, "
                f"regenerated {len(rendered.splitlines())})"
            )
        return _failed(report, "view_divergence", detail)
    report["ok"] = True
    return report


# ---------------------------------------------------------------- KB-6


def audit_kb6(board_dir: Path) -> dict[str, Any]:
    """KB-6 (T020): the served state is the fold of the log.

    The log is folded from genesis into a fresh state and the
    canonical bytes of that state (with its read-back hash, exactly
    as ``board.state.write_state`` stores it) are byte-compared
    against the served state file. Any difference, any fold
    refusal, and any fold finding (a torn tail, a repeated event
    id) is a finding of the highest severity this spec defines.
    """
    board_dir = Path(board_dir)
    report = _base_report("kb6", board_dir)
    try:
        lines = _read_log_lines(board_dir)
    except _AuditInputError as exc:
        return _failed(report, "board_unreadable", str(exc))
    folded = fold.fold_lines(lines, fold.default_board_checker())
    if not folded.ok:
        refusal = folded.refusal
        assert refusal is not None
        return _failed(
            report,
            "fold_refusal",
            f"the log does not fold: event {refusal.event_id} at index "
            f"{refusal.index}: {refusal.reason}",
        )
    report["board_id"] = folded.state.get("board_id")
    for finding in folded.findings:
        report["findings"].append(
            {"kind": finding.get("kind", "fold_finding"), "severity": "highest", **finding}
        )
    fresh = folded.state
    report["fold_head"] = fresh.get("head_hash")
    report["event_count"] = fresh.get("event_count")
    if isinstance(fresh.get("event_count"), int) and fresh["event_count"] > ARCHIVAL_EVENT_BOUND:
        report["notes"].append(
            f"the log holds {fresh['event_count']} events, over the "
            f"{ARCHIVAL_EVENT_BOUND}-event pilot bound; archival is raised"
        )
    state_path = board_dir / state.STATE_FILE
    if not state_path.exists():
        report["findings"].append(
            {"kind": "state_missing", "severity": "highest", "detail": "no served state file"}
        )
        report["ok"] = False
        return report
    try:
        served_bytes = state_path.read_bytes()
    except OSError as exc:
        report["findings"].append(
            {"kind": "state_unreadable", "severity": "highest", "detail": str(exc)}
        )
        report["ok"] = False
        return report
    try:
        served = json.loads(served_bytes.decode("utf-8"))
        report["served_head"] = served.get("head_hash") if isinstance(served, dict) else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        report["served_head"] = None
    stored = dict(fresh)
    stored["state_hash"] = canonical.state_hash(fresh)
    expected = canonical.canonical_line(stored)
    if served_bytes != expected:
        report["findings"].append(
            {
                "kind": "state_divergence",
                "severity": "highest",
                "detail": "the served state file differs from a fresh fold of the log "
                f"(fold head {report['fold_head']}, served head {report.get('served_head')})",
            }
        )
    report["ok"] = not report["findings"]
    return report


# ------------------------------------------------------- artifact trace


def _task_ref_in_artifact(task_ref: str, artifact_lines: list[str]) -> bool:
    """A task identifier traces to a line carrying it as a token."""
    pattern = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(task_ref) + r"(?![A-Za-z0-9_-])")
    return any(pattern.search(line) for line in artifact_lines)


def audit_trace(board_dir: Path, artifact_path: Path) -> dict[str, Any]:
    """Artifact-trace audit (T021): the board is still its artifact.

    The artifact is identified by hash: the file's SHA-256 must
    equal the genesis ``spec_hash`` (a different file is not the
    frozen artifact, and tracing against it would prove nothing —
    the audit fails closed). A row traces when its ``task_ref``
    appears on a line of the artifact, or when its lineage reaches
    a tracing row: a row created as the replacement of a superseded
    row traces through the row it replaced, and a row re-appended
    by fork recovery traces through the original event it cites.
    """
    board_dir = Path(board_dir)
    report = _base_report("trace", board_dir)
    report["artifact"] = str(artifact_path)
    folded = _fold_or_fail(report, board_dir)
    if folded is None:
        return report
    board_state = folded.state
    genesis = board_state.get("genesis") or {}
    spec_hash = genesis.get("spec_hash")
    report["spec_hash"] = spec_hash
    try:
        raw = Path(artifact_path).read_bytes()
    except OSError as exc:
        return _failed(report, "artifact_unreadable", f"the genesis artifact cannot be read: {exc}")
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != spec_hash:
        return _failed(
            report,
            "artifact_hash_mismatch",
            f"the artifact's SHA-256 is {actual_hash}, not the genesis "
            f"spec_hash {spec_hash}; this is not the frozen artifact",
        )
    try:
        artifact_lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        return _failed(report, "artifact_unreadable", f"the artifact is not UTF-8 text: {exc}")
    try:
        events = _parse_events(_read_log_lines(board_dir))
    except _AuditInputError as exc:
        return _failed(report, "board_unreadable", str(exc))
    replaced_by: dict[str, str] = {}
    recovered_task_ref: dict[str, str] = {}
    events_by_id = {event.get("event_id"): event for event in events}
    for event in events:
        payload = event.get("payload") or {}
        changes = payload.get("changes") or {}
        if event.get("kind") == "row_update" and changes.get("status") == "superseded":
            target = payload.get("replaced_by")
            if isinstance(target, str) and event.get("row_id"):
                replaced_by[target] = str(event["row_id"])
        if event.get("kind") == "row_created" and payload.get("recovered_from"):
            original = events_by_id.get(payload["recovered_from"])
            if original is not None and original.get("kind") == "row_created":
                original_ref = (original.get("payload") or {}).get("task_ref")
                if isinstance(original_ref, str):
                    recovered_task_ref[str(payload.get("row_id"))] = original_ref

    rows = board_state.get("rows", {})
    memo: dict[str, bool] = {}

    def traces(row_id: str, seen: frozenset[str]) -> bool:
        if row_id in memo:
            return memo[row_id]
        if row_id in seen:
            return False
        row = rows.get(row_id)
        if row is None:
            return False
        refs = [row.get("task_ref")]
        if row_id in recovered_task_ref:
            refs.append(recovered_task_ref[row_id])
        result = any(
            isinstance(ref, str) and ref and _task_ref_in_artifact(ref, artifact_lines)
            for ref in refs
        )
        if not result and row_id in replaced_by:
            result = traces(replaced_by[row_id], seen | {row_id})
        memo[row_id] = result
        return result

    report["rows_checked"] = len(rows)
    for row_id in sorted(rows):
        if not traces(row_id, frozenset()):
            report["findings"].append(
                {
                    "kind": "row_untraceable",
                    "row": row_id,
                    "task_ref": rows[row_id].get("task_ref"),
                    "detail": "the row traces neither to a line of the genesis "
                    "artifact nor through a supersede chain or recovery "
                    "citation to a row that does",
                }
            )
    report["ok"] = not report["findings"]
    return report


# ------------------------------------------------------------- boundary


def _resolves_into(ref: Any, artifact: str) -> bool:
    """A ref resolves into a registered artifact: equal to it,
    a path under it, or carrying it as a delimited token."""
    if not isinstance(ref, str) or not ref or not artifact:
        return False
    if ref == artifact:
        return True
    if ref.startswith(artifact.rstrip("/") + "/"):
        return True
    pattern = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(artifact) + r"(?![A-Za-z0-9_-])")
    return pattern.search(ref) is not None


def audit_boundary(board_dirs: list[Path], study_arm_artifacts: list[str]) -> dict[str, Any]:
    """Boundary audit (T022): the contamination detector.

    Every board in ``board_dirs`` is folded and checked: no row's
    ``spec_ref`` or ``task_ref``, and no board's genesis ``spec_ref``
    or ``program``, resolves into any registered study-arm artifact.
    A hit is the Section 7.5 tripwire firing (``tripwire`` in the
    report), not a lesser finding.
    """
    report: dict[str, Any] = {
        "audit": "boundary",
        "board_dirs": [str(d) for d in board_dirs],
        "study_arm_artifacts": list(study_arm_artifacts),
        "ok": False,
        "tripwire": False,
        "findings": [],
        "notes": [],
    }
    if not study_arm_artifacts:
        report["findings"].append(
            {
                "kind": "registry_empty",
                "detail": "no study-arm artifacts were supplied; the boundary "
                "cannot be checked and is not reported as held",
            }
        )
        return report
    for board_dir in board_dirs:
        board_dir = Path(board_dir)
        sub = _base_report("boundary", board_dir)
        folded = _fold_or_fail(sub, board_dir)
        if folded is None:
            for finding in sub["findings"]:
                report["findings"].append({"board_dir": str(board_dir), **finding})
            continue
        board_state = folded.state
        genesis = board_state.get("genesis") or {}
        for field in ("spec_ref", "program"):
            value = genesis.get(field)
            for artifact in study_arm_artifacts:
                if _resolves_into(value, artifact):
                    report["findings"].append(
                        {
                            "kind": "board_belongs_to_study_arm",
                            "board_dir": str(board_dir),
                            "board_id": board_state.get("board_id"),
                            "field": f"genesis.{field}",
                            "ref": value,
                            "artifact": artifact,
                        }
                    )
        for row_id, row in sorted(board_state.get("rows", {}).items()):
            for field in ("spec_ref", "task_ref"):
                value = row.get(field)
                for artifact in study_arm_artifacts:
                    if _resolves_into(value, artifact):
                        report["findings"].append(
                            {
                                "kind": "row_ref_in_study_arm",
                                "board_dir": str(board_dir),
                                "board_id": board_state.get("board_id"),
                                "row": row_id,
                                "field": field,
                                "ref": value,
                                "artifact": artifact,
                            }
                        )
    report["tripwire"] = bool(report["findings"])
    report["ok"] = not report["findings"]
    return report


# --------------------------------------------------------- kernel drift


def audit_kernel_drift(extension_definitions_path: Path | None = None) -> dict[str, Any]:
    """Kernel drift check (T023): the two kernel homes agree.

    Leg A (always run): the canonical definitions in
    ``board.kernel`` against the pinned enums of
    ``board/schema.json`` — the spec's pinned kernel definition in
    the schema. Leg B (when ``extension_definitions_path`` is
    supplied): the extension's shipped definitions file (the JSON
    object Phase 5 pins) must hash, in canonical form, to
    ``kernel_definitions_hash()``. A supplied file that cannot be
    read fails the check closed.
    """
    report: dict[str, Any] = {
        "audit": "kernel_drift",
        "ok": False,
        "scope": "schema_only",
        "canonical_hash": kernel.kernel_definitions_hash(),
        "findings": [],
        "notes": [],
    }
    definitions = kernel.kernel_definitions()
    schema_path = Path(__file__).parent / "schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        report["findings"].append(
            {"kind": "schema_unreadable", "detail": f"board/schema.json cannot be read: {exc}"}
        )
        return report
    if list(schema.get("status_enum") or []) != definitions["statuses"]:
        report["findings"].append(
            {
                "kind": "kernel_schema_divergence",
                "field": "status_enum",
                "detail": "board/schema.json's status_enum differs from the "
                "kernel's canonical statuses",
            }
        )
    if (
        sorted(schema.get("amendable_fields", {}).get("fields") or [])
        != definitions["amendable_fields"]
    ):
        report["findings"].append(
            {
                "kind": "kernel_schema_divergence",
                "field": "amendable_fields",
                "detail": "board/schema.json's amendable fields differ from the kernel's",
            }
        )
    for transition in definitions["transitions"]:
        for endpoint in (transition["from"], transition["to"]):
            if endpoint is not None and endpoint not in definitions["statuses"]:
                report["findings"].append(
                    {
                        "kind": "kernel_schema_divergence",
                        "field": "transitions",
                        "detail": f"transition endpoint {endpoint!r} is not a kernel status",
                    }
                )
    if extension_definitions_path is None:
        report["notes"].append(
            "no extension definitions file was supplied; the cross-repo leg "
            "arms when Phase 5 (T025) ships the pinned definitions and the "
            "weekly rhythm passes the file. This pass covers the schema "
            "pre-check only."
        )
    else:
        report["scope"] = "full"
        try:
            shipped = json.loads(Path(extension_definitions_path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            report["findings"].append(
                {
                    "kind": "extension_definitions_unreadable",
                    "detail": f"the shipped kernel definitions cannot be read: {exc}",
                }
            )
            report["ok"] = False
            return report
        shipped_hash = hashlib.sha256(canonical.canonical_bytes(shipped)).hexdigest()
        report["extension_hash"] = shipped_hash
        if shipped_hash != report["canonical_hash"]:
            report["findings"].append(
                {
                    "kind": "kernel_drift",
                    "detail": "the extension's shipped kernel definitions hash "
                    f"({shipped_hash}) differs from the canonical table's hash "
                    f"({report['canonical_hash']})",
                }
            )
    report["ok"] = not report["findings"]
    return report


# ------------------------------------------------------------------ CLI


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    command, rest = argv[0], argv[1:]
    report: dict[str, Any]
    try:
        if command == "kb2":
            board_dir = Path(rest[0])
            since = 0
            queue_dir = ci_dir = None
            args = rest[1:]
            while args:
                if args[0] == "--since":
                    since = int(args[1])
                    args = args[2:]
                elif args[0] == "--gatekeeper-queue-dir":
                    queue_dir = Path(args[1])
                    args = args[2:]
                elif args[0] == "--ci-records-dir":
                    ci_dir = Path(args[1])
                    args = args[2:]
                else:
                    raise ValueError(f"unknown argument: {args[0]}")
            report = audit_kb2(
                board_dir,
                since_index=since,
                gatekeeper_queue_dir=queue_dir,
                ci_records_dir=ci_dir,
            )
        elif command == "kb5":
            report = audit_kb5(Path(rest[0]))
        elif command == "kb6":
            report = audit_kb6(Path(rest[0]))
        elif command == "trace":
            report = audit_trace(Path(rest[0]), Path(rest[1]))
        elif command == "boundary":
            registry = json.loads(Path(rest[0]).read_text(encoding="utf-8"))
            artifacts = registry.get("study_arm_artifacts")
            if not isinstance(artifacts, list):
                raise ValueError("the registry file must carry a study_arm_artifacts list")
            report = audit_boundary([Path(d) for d in rest[1:]], [str(a) for a in artifacts])
        elif command == "drift":
            path = None
            if rest:
                if rest[0] != "--extension-definitions" or len(rest) != 2:
                    raise ValueError("usage: drift [--extension-definitions PATH]")
                path = Path(rest[1])
            report = audit_kernel_drift(path)
        else:
            print(__doc__)
            return 2
    except (IndexError, ValueError, OSError) as exc:
        print(json.dumps({"audit": command, "ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
