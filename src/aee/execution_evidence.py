"""Bounded explicit local execution and strict, non-executing evidence ingestion.

Capture is an authorized action, not an OS sandbox. Callers supply trusted argv
and OS permissions/isolation. Imported records are unverified regardless of their
producer label; hash-pinned records require an independently established policy.
A process exit alone never establishes test completeness or correctness.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Collection, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import IO, Any

from aee.execution_scope import ScopeSnapshot, _file, check_freshness, scope_path, snapshot_scope
from aee.extract import duplicate_key_hook
from aee.ledger import HashChainLedger
from aee.model import normalize_claim_id

MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_REPORT_BYTES = 4 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {
    "schema_version",
    "producer",
    "argv",
    "executable",
    "requirement_ids",
    "test_ids",
    "started_at",
    "ended_at",
    "duration_seconds",
    "exit_code",
    "termination",
    "scope_before",
    "scope_after",
    "scope_error",
    "stdout",
    "stderr",
    "cleanup_complete",
    "reports",
}


def report_bytes(root: str | Path, name: str) -> bytes:
    """Read a bounded regular report under the root without following symlinks."""
    path = _file(Path(root).resolve(strict=True), scope_path(name))
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("report must be a regular file")
    with path.open("rb") as handle:
        data = handle.read(MAX_REPORT_BYTES + 1)
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("report exceeds its size limit")
    return data


def _reports(value: Any) -> None:
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError("invalid report receipts")
    names = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "byte_count", "error"}:
            raise ValueError("invalid report receipt fields")
        if scope_path(item["path"]) != item["path"]:
            raise ValueError("report path must be canonical")
        names.append(item["path"])
        if not isinstance(item["error"], str) or len(item["error"]) > 256:
            raise ValueError("invalid report error")
        if item["error"]:
            if item["sha256"] is not None or item["byte_count"] is not None:
                raise ValueError("unavailable report cannot claim bytes/hash")
        elif (
            not isinstance(item["sha256"], str)
            or not _HASH.fullmatch(item["sha256"])
            or type(item["byte_count"]) is not int
            or not 0 <= item["byte_count"] <= MAX_REPORT_BYTES
        ):
            raise ValueError("invalid report hash/length")
    if len(set(names)) != len(names):
        raise ValueError("duplicate report paths")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("invalid execution record JSON") from exc


def _strings(value: object, name: str, *, minimum: int = 0) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not minimum <= len(value) <= 10_000
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > 8192 or "\0" in item
            for item in value
        )
    ):
        raise ValueError(f"invalid {name} sequence")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise ValueError(f"duplicate {name}")
    return result


def _argv(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not 1 <= len(value) <= 256
        or any(not isinstance(item, str) or len(item) > 8192 or "\0" in item for item in value)
        or not value[0].strip()
    ):
        raise ValueError("argv must be a bounded explicit nonempty argument sequence")
    return tuple(value)


def _date(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("invalid execution timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("execution timestamps require an explicit timezone")
    return parsed


def _output(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {
        "sha256",
        "byte_count",
        "retained_base64",
        "complete",
    }:
        raise ValueError("invalid captured output fields")
    count = value["byte_count"]
    if type(count) is not int or count < 0 or type(value["complete"]) is not bool:
        raise ValueError("invalid captured output count/completeness")
    if not isinstance(value["retained_base64"], str):
        raise ValueError("invalid captured output encoding")
    try:
        data = base64.b64decode(value["retained_base64"], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid captured output encoding") from exc
    if len(data) > MAX_OUTPUT_BYTES or len(data) > count:
        raise ValueError("invalid captured output length")
    if not isinstance(value["sha256"], str) or not _HASH.fullmatch(value["sha256"]):
        raise ValueError("invalid captured output SHA256")
    if value["complete"] and (
        len(data) != count or hashlib.sha256(data).hexdigest() != value["sha256"]
    ):
        raise ValueError("captured output hash/length mismatch")


def _validate(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("invalid execution record fields")
    if value["schema_version"] != "1.0" or value["producer"] != "local-process-capture":
        raise ValueError("unsupported execution record version/producer mechanism")
    _argv(value["argv"])
    executable = value["executable"]
    if (
        not isinstance(executable, str)
        or not 1 <= len(executable) <= 8192
        or "\0" in executable
        or not (
            PurePosixPath(executable).is_absolute() or PureWindowsPath(executable).is_absolute()
        )
    ):
        raise ValueError("execution record needs an explicit absolute executable")
    ids = _strings(value["requirement_ids"], "requirement_ids", minimum=1)
    if any(normalize_claim_id(identity) != identity for identity in ids):
        raise ValueError("execution requirement IDs must be canonical")
    _strings(value["test_ids"], "test_ids")
    if _date(value["ended_at"]) < _date(value["started_at"]):
        raise ValueError("execution ends before it starts")
    duration = value["duration_seconds"]
    if (
        type(duration) not in (int, float)
        or not math.isfinite(duration)
        or not 0 <= duration <= 86400
    ):
        raise ValueError("invalid execution duration")
    if not isinstance(value["termination"], str) or value["termination"] not in {
        "exited",
        "timeout",
        "output_limit",
        "io_error",
    }:
        raise ValueError("invalid execution termination")
    if value["exit_code"] is not None and type(value["exit_code"]) is not int:
        raise ValueError("invalid execution exit code")
    if value["termination"] == "exited" and value["exit_code"] is None:
        raise ValueError("normal execution requires its actual exit code")
    before = ScopeSnapshot.from_dict(value["scope_before"])
    error = value["scope_error"]
    if not isinstance(error, str) or len(error) > 256:
        raise ValueError("invalid execution scope error")
    if value["scope_after"] is None:
        if not error:
            raise ValueError("missing post-execution scope needs an explicit error")
    else:
        after = ScopeSnapshot.from_dict(value["scope_after"])
        if (
            error
            or after.repository_id != before.repository_id
            or dict(after.files).keys() != dict(before.files).keys()
        ):
            raise ValueError("post-execution scope identity/paths differ")
    if type(value["cleanup_complete"]) is not bool:
        raise ValueError("invalid cleanup completeness")
    _output(value["stdout"])
    _output(value["stderr"])
    _reports(value["reports"])


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """Immutable validated canonical JSON. Importing it does not authenticate it."""

    payload: str

    def __post_init__(self) -> None:
        if not isinstance(self.payload, str) or len(self.payload.encode()) > MAX_RECORD_BYTES:
            raise ValueError("execution record exceeds its size limit")
        try:
            value = json.loads(
                self.payload, object_pairs_hook=duplicate_key_hook("execution record")
            )
        except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("invalid execution record JSON") from exc
        _validate(value)
        canonical = _canonical(value)
        if len(canonical.encode()) > MAX_RECORD_BYTES:
            raise ValueError("execution record exceeds its size limit")
        object.__setattr__(self, "payload", canonical)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ExecutionRecord:
        if not isinstance(value, Mapping):
            raise ValueError("execution record must be a mapping")
        return cls(_canonical(dict(value)))

    @classmethod
    def from_bytes(cls, data: bytes) -> ExecutionRecord:
        if not isinstance(data, bytes) or len(data) > MAX_RECORD_BYTES:
            raise ValueError("execution record exceeds its size limit")
        try:
            return cls(data.decode("utf-8"))
        except UnicodeError as exc:
            raise ValueError("execution record must be UTF-8") from exc

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.payload)  # type: ignore[no-any-return]

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.payload.encode()).hexdigest()


class _OutputReader:
    def __init__(self, stream: IO[bytes], limit: int, overflow: threading.Event) -> None:
        self.stream, self.limit, self.overflow = stream, limit, overflow
        self.data = bytearray()
        self.count = 0
        self.hash = hashlib.sha256()
        self.eof = False
        self.error = False

    def read(self) -> None:
        try:
            while chunk := self.stream.read(8192):
                self.count += len(chunk)
                self.hash.update(chunk)
                self.data.extend(chunk[: max(0, self.limit - len(self.data))])
                if self.count > self.limit:
                    self.overflow.set()
            self.eof = True
        except (OSError, ValueError):
            self.error = True

    def result(self) -> dict[str, Any]:
        return dict(
            sha256=self.hash.hexdigest(),
            byte_count=self.count,
            retained_base64=base64.b64encode(self.data).decode("ascii"),
            complete=self.eof and not self.error and self.count == len(self.data),
        )


def _terminate(process: subprocess.Popen[bytes]) -> None:
    """Best-effort process-tree cleanup; capture does not provide OS isolation."""
    if sys.platform == "win32":
        taskkill = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32/taskkill.exe"
        try:
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            with suppress(ProcessLookupError):
                process.kill()
    else:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        with suppress(ProcessLookupError):
            process.kill()
    process.wait(timeout=5)


def capture_execution(
    argv: Sequence[str],
    root: str | Path,
    paths: Sequence[str],
    *,
    repository_id: str,
    requirement_ids: Sequence[str],
    test_ids: Sequence[str] = (),
    timeout: float = 600,
    max_output_bytes: int = 128 * 1024,
    report_paths: Sequence[str] = (),
) -> ExecutionRecord:
    """Explicitly execute caller-authorized argv; retain bounded binary observations.

    No shell is implicitly used. Batch scripts are refused because Windows may
    invoke a shell for them despite shell=False. Commands can still explicitly
    invoke interpreters and have the caller's OS privileges. Logs are bounded;
    output overflow, failed drainage or timeout cannot become a successful run.
    """
    command = _argv(argv)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError("timeout must be finite, positive and at most3600seconds")
    if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= MAX_OUTPUT_BYTES:
        raise ValueError("invalid max_output_bytes")
    ids = tuple(
        normalize_claim_id(identity)
        for identity in _strings(requirement_ids, "requirement_ids", minimum=1)
    )
    _strings(ids, "requirement_ids", minimum=1)
    tests = _strings(test_ids, "test_ids")
    root = Path(root).resolve(strict=True)
    before = snapshot_scope(root, paths, repository_id=repository_id)
    scoped_names = tuple(name for name, _ in before.files)
    names = tuple(scope_path(name) for name in _strings(report_paths, "report_paths"))
    if len(names) > 32 or len(set(names)) != len(names):
        raise ValueError("invalid/duplicate report paths")
    for name in names:
        if _file(root, name).exists():
            raise ValueError("report output must not already exist")
    if (
        len(
            _canonical(
                dict(
                    argv=command,
                    scope=before.to_dict(),
                    requirements=ids,
                    tests=tests,
                    reports=names,
                )
            ).encode()
        )
        > MAX_RECORD_BYTES // 8
    ):
        raise ValueError("execution inputs exceed record size reservation")
    if Path(command[0]).is_absolute():
        executable = Path(command[0])
    elif "/" in command[0] or "\\" in command[0]:
        executable = root / command[0]
    else:
        resolved = shutil.which(command[0])
        if resolved is None:
            raise FileNotFoundError("requested executable was not found")
        executable = Path(resolved)
    if executable.suffix.lower() in {".bat", ".cmd"}:
        raise ValueError("implicit batch-script shell execution is refused")
    executable = executable.resolve(strict=True)
    started = datetime.now(UTC).isoformat()
    begin = time.monotonic()
    overflow = threading.Event()
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        creation_flags = 0
    process = subprocess.Popen(
        command,
        executable=str(executable),
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        shell=False,
        start_new_session=os.name != "nt",
        creationflags=creation_flags,
    )
    assert process.stdout is not None and process.stderr is not None
    readers = [
        _OutputReader(process.stdout, max_output_bytes, overflow),
        _OutputReader(process.stderr, max_output_bytes, overflow),
    ]
    threads = [threading.Thread(target=reader.read, daemon=True) for reader in readers]
    termination = "exited"
    try:
        for thread in threads:
            thread.start()
        while process.poll() is None:
            if overflow.wait(0.01):
                termination = "output_limit"
                break
            if time.monotonic() - begin >= timeout:
                termination = "timeout"
                break
        if termination != "exited":
            _terminate(process)
        for thread in threads:
            thread.join(timeout=1)
        if overflow.is_set():
            termination = "output_limit"
        if any(reader.error or not reader.eof for reader in readers):
            termination = "io_error"
    finally:
        if process.poll() is None:
            _terminate(process)
        for reader in readers:
            reader.stream.close()
    cleanup = all(not thread.is_alive() for thread in threads)
    scope_error = ""
    try:
        after = snapshot_scope(root, scoped_names, repository_id=repository_id).to_dict()
    except (OSError, ValueError) as exc:
        after = None
        scope_error = type(exc).__name__
    receipts = []
    for name in names:
        try:
            data = report_bytes(root, name)
            receipt = dict(
                path=name, sha256=hashlib.sha256(data).hexdigest(), byte_count=len(data), error=""
            )
        except (OSError, ValueError) as exc:
            receipt = dict(path=name, sha256=None, byte_count=None, error=type(exc).__name__)
        receipts.append(receipt)
    return ExecutionRecord.from_dict(
        dict(
            schema_version="1.0",
            producer="local-process-capture",
            argv=list(command),
            executable=str(executable),
            requirement_ids=list(ids),
            test_ids=list(tests),
            started_at=started,
            ended_at=datetime.now(UTC).isoformat(),
            duration_seconds=time.monotonic() - begin,
            exit_code=process.returncode,
            termination=termination,
            scope_before=before.to_dict(),
            scope_after=after,
            scope_error=scope_error,
            stdout=readers[0].result(),
            stderr=readers[1].result(),
            cleanup_complete=cleanup,
            reports=receipts,
        )
    )


def check_execution_applicability(
    record: ExecutionRecord,
    root: str | Path,
    *,
    repository_id: str,
    trusted_record_digests: Collection[str] = (),
) -> dict[str, Any]:
    """Recompute applicability without executing the recorded command.

    Pins are supplied by an independently established host/CI policy, never read
    from the record. Even a pinned, fresh zero exit is not complete test evidence;
    report/inventory/link verification is a separate step.
    """
    record = ExecutionRecord(record.payload)
    if (
        not isinstance(trusted_record_digests, Collection)
        or isinstance(trusted_record_digests, (str, bytes))
        or any(
            not isinstance(pin, str) or not _HASH.fullmatch(pin) for pin in trusted_record_digests
        )
    ):
        raise ValueError("invalid trusted record digest policy")
    value = record.to_dict()
    before = ScopeSnapshot.from_dict(value["scope_before"])
    if value["scope_after"] is None:
        freshness = "unknown"
    elif value["scope_after"]["tree_hash"] != before.tree_hash:
        freshness = "stale"
    else:
        try:
            freshness = check_freshness(before, root, repository_id=repository_id).status
        except (OSError, ValueError):
            freshness = "unknown"
    complete = value["cleanup_complete"] and all(
        value[key]["complete"] for key in ("stdout", "stderr")
    )
    status = (
        ("succeeded" if value["exit_code"] == 0 else "failed")
        if value["termination"] == "exited" and complete
        else "unknown"
    )
    return dict(
        record_sha256=record.digest,
        execution_status=status,
        freshness=freshness,
        producer_trust="pinned-record" if record.digest in trusted_record_digests else "unverified",
        test_verification="unassessed",
    )


def append_execution_record(
    record: ExecutionRecord, ledger: HashChainLedger, *, actor: str = "aee-local-capture"
) -> dict[str, Any]:
    """Retain a validated observation in the existing anchored ledger.

    Appending does not authenticate the actor/producer or promote trust. Repeated
    receipts retain the same record digest and are not independent observations.
    """
    record = ExecutionRecord(record.payload)
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 256:
        raise ValueError("execution actor must be a bounded nonempty label")
    return ledger.append(
        "execution_observation",
        dict(record_sha256=record.digest, record=record.to_dict(), producer_trust="unverified"),
        actor=actor,
    )
