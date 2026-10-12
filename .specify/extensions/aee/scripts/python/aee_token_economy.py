#!/usr/bin/env python3
"""Thin AEE policy layer over optional token-economy tools.

Tools compress or route context; they never originate evidence. Token savings
are measured, never estimated. Every subcommand degrades gracefully when the
optional tool it wraps is absent: rtk, headroom, token-router, ollama.

The three wrapped tools are external runtimes with their own upstreams:
- rtk: https://github.com/rtk-ai/rtk (Apache-2.0) - shell-output compression.
- headroom: https://github.com/headroomlabs-ai/headroom (Apache-2.0).
- token-router: https://github.com/sleeplesshan/token-router (MIT) - local
  line router over logs and source files.

Path-safety helpers mirror scripts/python/run_aee.py so this adapter stays
runnable standalone.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_MAX_DIRECT_LINES = 300
DEFAULT_WINDOW = 8
DEFAULT_MAX_OUTPUT_LINES = 160
DEFAULT_HEADROOM_HOURS = 168
ROUTER_TIMEOUT_SECONDS = 300

EVIDENCE_POLICY = (
    "Router output is not evidence. The local router selects lines; it never "
    "analyzes. Cite the original file and line ranges; treat router prose as "
    "unsupported unless grounded in verbatim slices."
)

SAVINGS_POLICY = (
    "Measured only. RTK and Headroom are separate savings channels; "
    "token-router and Ollama are workflow tools, not savings. Never estimate; "
    "never double-count; report n/a with a reason when a measurement is "
    "unavailable."
)

# Basename fragments that fail closed: routing secrets would put them in
# model context. This list is intentionally conservative.
_SECRET_FRAGMENTS = (
    ".env",
    ".pem",
    ".key",
    "id_rsa",
    "id_ed25519",
    "credentials",
    "secret",
    "service-account",
    "private-key",
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--project-root", type=Path, default=Path.cwd())
    sub = root.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Report optional tool availability.")
    status.add_argument("--format", choices=("json", "text"), default="json")

    route = sub.add_parser("route", help="Route a large file to raw slices.")
    route.add_argument("--file", type=Path, required=True)
    route.add_argument(
        "--mode",
        choices=("error_log", "heavy_code", "agent_context"),
        default="error_log",
    )
    route.add_argument("--query", default="")
    route.add_argument("--max-direct-lines", type=int, default=DEFAULT_MAX_DIRECT_LINES)
    route.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    route.add_argument("--max-output-lines", type=int, default=DEFAULT_MAX_OUTPUT_LINES)

    report = sub.add_parser("report", help="Measured-only savings report.")
    report.add_argument("--hours", type=int, default=DEFAULT_HEADROOM_HOURS)

    shell = sub.add_parser(
        "shell", help="Run a shell command with token-economy telemetry."
    )
    shell.add_argument(
        "--telemetry",
        type=Path,
        default=Path(".specify/extensions/aee/telemetry/shell-calls.jsonl"),
    )
    shell.add_argument("argv", nargs=argparse.REMAINDER)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = args.project_root.resolve(strict=True)
    _reject_symlink_chain(root, root)
    if args.command == "status":
        return _status(root, args)
    if args.command == "route":
        return _route(root, args)
    if args.command == "report":
        return _report(args)
    if args.command == "shell":
        return _shell(root, args)
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def _find_token_router(root: Path) -> Path | None:
    """Locate the optional token-router backend without vendoring it.

    Discovery anchors on the project root (and its parent, for a
    sibling checkout), never on the caller's working directory — the
    tool accepts --project-root, so results must not depend on where
    the agent happens to invoke it from.
    """
    env_home = os.environ.get("TOKEN_ROUTER_HOME")
    candidates: list[Path] = []
    if env_home:
        candidates.append(Path(env_home) / "scripts" / "router.py")
    candidates.append(root / "token-router" / "scripts" / "router.py")
    candidates.append(root.parent / "token-router" / "scripts" / "router.py")
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def tool_status(root: Path) -> dict:
    """Availability of each optional tool. Never raises when tools are absent."""
    status: dict = {}
    for name in ("rtk", "headroom", "ollama"):
        path = shutil.which(name)
        status[name] = {"available": path is not None, "path": path}
    router = _find_token_router(root)
    status["token-router"] = {
        "available": router is not None,
        "path": str(router) if router else None,
    }
    return status


def _status(root: Path, args: argparse.Namespace) -> int:
    status = tool_status(root)
    if args.format == "text":
        for name, info in status.items():
            state = info["path"] if info["available"] else "unavailable"
            print(f"- {name}: {state}")
    else:
        print(json.dumps(status, indent=2))
    return 0


# ---------------------------------------------------------------------------
# route
# ---------------------------------------------------------------------------


def _looks_like_secret(path: Path) -> bool:
    lowered = path.name.lower()
    return any(fragment in lowered for fragment in _SECRET_FRAGMENTS)


def _route(root: Path, args: argparse.Namespace) -> int:
    if _looks_like_secret(args.file):
        print(
            f"refused: {args.file} looks like a secret-bearing file; "
            "token routing must never move secrets into model context.",
            file=sys.stderr,
        )
        return 2
    try:
        source = _safe_existing(root, args.file)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    record: dict = {
        "file": source.relative_to(root).as_posix(),
        "mode": args.mode,
        "query": args.query,
        "total_lines": total,
        "policy": EVIDENCE_POLICY,
    }
    if total <= args.max_direct_lines:
        record["action"] = "read_directly"
        record["reason"] = (
            f"{total} lines is at or below max_direct_lines "
            f"({args.max_direct_lines}); read the file directly."
        )
        print(json.dumps(record, indent=2))
        return 0
    status = tool_status(root)
    router = _find_token_router(root) if status["token-router"]["available"] else None
    ollama = status["ollama"]["available"]
    if router is not None and ollama:
        ranges = _router_backend(router, source, args)
        backend = "token-router"
    else:
        ranges = _deterministic_ranges(lines, args.query, args.window)
        backend = "deterministic"
        record["fallback_reason"] = (
            "token-router backend unavailable"
            if router is None
            else "ollama unavailable for the token-router backend"
        )
    ranges = _clamp_ranges(ranges, total, args.max_output_lines)
    if not ranges:
        record["action"] = "no_matches"
        record["backend"] = backend
        record["reason"] = (
            "No line ranges matched; refusing to invent ranges. Sharpen the "
            "query or widen the window."
        )
        print(json.dumps(record, indent=2))
        return 0
    record.update(
        {
            "action": "routed",
            "backend": backend,
            "ranges": ranges,
            "slices": [
                {
                    "start": start,
                    "end": end,
                    "text": "\n".join(lines[start - 1 : end]),
                }
                for start, end in ranges
            ],
        }
    )
    print(json.dumps(record, indent=2))
    return 0


def _router_backend(
    router: Path, source: Path, args: argparse.Namespace
) -> list[tuple[int, int]]:
    """Ask the upstream token-router for line ranges; never trust prose."""
    env = dict(os.environ)
    env["OLLAMA_NUM_CTX"] = "8192"
    env["OLLAMA_KEEP_ALIVE"] = "0s"
    command = [
        sys.executable,
        str(router),
        args.mode,
        str(source),
        "--query",
        args.query,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=ROUTER_TIMEOUT_SECONDS,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    raw_ranges = payload.get("ranges", payload.get("line_ranges", []))
    ranges: list[tuple[int, int]] = []
    if isinstance(raw_ranges, list):
        for item in raw_ranges:
            if (
                isinstance(item, (list, tuple))
                and len(item) == 2
                and all(isinstance(v, int) for v in item)
            ):
                ranges.append((item[0], item[1]))
    return ranges


def _deterministic_ranges(
    lines: list[str], query: str, window: int
) -> list[tuple[int, int]]:
    """Literal case-insensitive match windows. No model involved."""
    if not query.strip():
        return []
    needle = query.lower()
    hits = [i + 1 for i, line in enumerate(lines) if needle in line.lower()]
    if not hits:
        return []
    merged: list[tuple[int, int]] = []
    for hit in hits:
        start = max(1, hit - window)
        end = min(len(lines), hit + window)
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _clamp_ranges(
    ranges: list[tuple[int, int]], total: int, max_output_lines: int
) -> list[tuple[int, int]]:
    clamped: list[tuple[int, int]] = []
    budget = max_output_lines
    for start, end in ranges:
        start = max(1, start)
        end = min(total, end)
        if end < start or budget <= 0:
            continue
        width = min(end - start + 1, budget)
        clamped.append((start, start + width - 1))
        budget -= width
    return clamped


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def _walk_number(payload: object, keys: tuple[str, ...]) -> int | float | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and isinstance(value, (int, float)) and not isinstance(
                value, bool
            ):
                return value
        for value in payload.values():
            found = _walk_number(value, keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _walk_number(item, keys)
            if found is not None:
                return found
    return None


def _measure_rtk() -> dict:
    if shutil.which("rtk") is None:
        return {
            "used": False,
            "saved_tokens": "n/a",
            "reason": "rtk not installed",
        }
    try:
        completed = subprocess.run(
            ["rtk", "gain", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "used": True,
            "saved_tokens": "n/a",
            "reason": "`rtk gain --format json` did not complete",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "used": True,
            "saved_tokens": "n/a",
            "reason": "no parseable JSON from `rtk gain --format json`",
        }
    saved = _walk_number(payload, ("saved_tokens", "total_saved", "tokens_saved"))
    if saved is None:
        return {
            "used": True,
            "saved_tokens": "n/a",
            "reason": "no parseable savings field in `rtk gain --format json` output",
        }
    return {
        "used": True,
        "saved_tokens": saved,
        "source": "rtk gain --format json",
    }


def _measure_headroom(hours: int) -> dict:
    if shutil.which("headroom") is None:
        return {
            "used": False,
            "saved_tokens": "n/a",
            "reason": "headroom not installed",
        }
    try:
        completed = subprocess.run(
            ["headroom", "perf", "--hours", str(hours)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "used": True,
            "saved_tokens": "n/a",
            "reason": f"`headroom perf --hours {hours}` did not complete",
        }
    saved: int | float | str = "n/a"
    reason = (
        "headroom perf output has no parseable token field; "
        "see output_excerpt"
    )
    try:
        payload = json.loads(completed.stdout)
        found = _walk_number(payload, ("saved_tokens", "total_saved", "tokens_saved"))
        if found is not None:
            saved = found
            reason = ""
    except json.JSONDecodeError:
        pass
    record: dict = {
        "used": True,
        "saved_tokens": saved,
        "source": f"headroom perf --hours {hours}",
        "output_excerpt": completed.stdout[:500],
    }
    if reason:
        record["reason"] = reason
    return record


def _report(args: argparse.Namespace) -> int:
    rtk = _measure_rtk()
    headroom = _measure_headroom(args.hours)
    combined: int | float | str = "n/a"
    if isinstance(rtk["saved_tokens"], (int, float)) and isinstance(
        headroom["saved_tokens"], (int, float)
    ):
        combined = rtk["saved_tokens"] + headroom["saved_tokens"]
    print(
        json.dumps(
            {
                "rtk": rtk,
                "headroom": headroom,
                "combined_saved_tokens": combined,
                "policy": SAVINGS_POLICY,
            },
            indent=2,
        )
    )
    return 0


# ---------------------------------------------------------------------------
# shell
# ---------------------------------------------------------------------------


def _shell(root: Path, args: argparse.Namespace) -> int:
    command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    if not command:
        print("refused: no command supplied after `shell`", file=sys.stderr)
        return 2
    rtk_available = shutil.which("rtk") is not None
    # Validate the telemetry destination BEFORE running the wrapped
    # command: an invalid --telemetry path must refuse up front, not
    # raise after the command's side effects have already happened.
    try:
        telemetry = _safe_output(root, args.telemetry)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    try:
        completed = subprocess.run(command, capture_output=True, check=False)
    except OSError as exc:
        print(f"refused: cannot execute {command[0]!r}: {exc}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(completed.stdout)
    sys.stderr.buffer.write(completed.stderr)
    record = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "command": command,
        "rtk_available": rtk_available,
        "stdout_bytes": len(completed.stdout),
        "stderr_bytes": len(completed.stderr),
        "exit_code": completed.returncode,
        "note": (
            "Shell-output filtering is handled by rtk tool hooks "
            "(`rtk init -g`) when installed; this wrapper records telemetry "
            "only. Savings remain measured via `rtk gain`."
        ),
    }
    with telemetry.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return completed.returncode


# ---------------------------------------------------------------------------
# path safety (mirrors run_aee.py adapter policy)
# ---------------------------------------------------------------------------


def _safe_existing(root: Path, value: Path) -> Path:
    candidate = value if value.is_absolute() else root / value
    _reject_symlink_chain(root, candidate)
    resolved = candidate.resolve(strict=True)
    _require_inside(root, resolved)
    if not resolved.is_file():
        raise ValueError(f"not a regular file: {value}")
    return resolved


def _safe_output(root: Path, value: Path) -> Path:
    candidate = value if value.is_absolute() else root / value
    _require_inside(root, candidate.resolve(strict=False))
    _reject_symlink_chain(root, candidate)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_chain(root, candidate)
    return candidate


def _require_inside(root: Path, candidate: Path) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {candidate}") from exc


def _reject_symlink_chain(root: Path, candidate: Path) -> None:
    absolute = candidate if candidate.is_absolute() else root / candidate
    _require_inside(root, absolute.resolve(strict=False))
    current = root
    try:
        parts = absolute.relative_to(root).parts
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {absolute}") from exc
    for part in parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError(f"symlinked path component refused: {current}")


if __name__ == "__main__":
    sys.exit(main())
