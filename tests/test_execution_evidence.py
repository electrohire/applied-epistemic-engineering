"""Actual capture, bounded failures and strict non-executing record ingestion."""

from __future__ import annotations

import base64
import json
import os
import sys
from types import SimpleNamespace

import pytest

import aee.execution_evidence as execution


def capture(tmp_path, code="print('observed')", **options):
    source = tmp_path / "source.py"
    if not source.exists():
        source.write_text("answer = 42\n")
    return execution.capture_execution(
        [sys.executable, "-c", code],
        tmp_path,
        ["source.py"],
        repository_id="project",
        requirement_ids=["r01"],
        test_ids=["tests::test_answer"],
        **options,
    )


def test_actual_capture_roundtrip_scope_output_and_no_implicit_trust(tmp_path):
    record = capture(tmp_path)
    data = record.to_dict()
    assert data["termination"] == "exited" and data["exit_code"] == 0
    assert data["producer"] == "local-process-capture"
    assert data["requirement_ids"] == ["R01"]
    assert data["scope_before"] == data["scope_after"]
    assert base64.b64decode(data["stdout"]["retained_base64"]).strip() == b"observed"
    assert data["stderr"]["byte_count"] == 0 and data["stderr"]["complete"]
    assert data["duration_seconds"] >= 0
    assert execution.ExecutionRecord.from_dict(data) == record
    assert execution.ExecutionRecord.from_bytes(json.dumps(data).encode()) == record
    assert len(record.digest) == 64
    assert (
        execution.check_execution_applicability(record, tmp_path, repository_id="project")[
            "producer_trust"
        ]
        == "unverified"
    )
    data["argv"].clear()
    assert record.to_dict()["argv"]


def test_exit_code_and_binary_output_are_observed_not_reinterpreted(tmp_path):
    record = capture(
        tmp_path,
        "import sys;sys.stdout.buffer.write(b'\\xff\\x00');sys.stderr.write('failure');sys.exit(7)",
    )
    data = record.to_dict()
    assert data["exit_code"] == 7 and data["termination"] == "exited"
    assert base64.b64decode(data["stdout"]["retained_base64"]) == b"\xff\x00"
    assert (
        execution.check_execution_applicability(record, tmp_path, repository_id="project")[
            "execution_status"
        ]
        == "failed"
    )


def test_timeout_and_output_overflow_stop_without_pass(tmp_path):
    timed = capture(tmp_path, "import time;time.sleep(10)", timeout=0.15)
    assert timed.to_dict()["termination"] == "timeout"
    overflowing = capture(
        tmp_path, "import sys;sys.stdout.write('x'*200000);sys.stdout.flush()", max_output_bytes=64
    )
    data = overflowing.to_dict()
    assert data["termination"] == "output_limit"
    assert len(base64.b64decode(data["stdout"]["retained_base64"])) <= 64
    assert (
        execution.check_execution_applicability(overflowing, tmp_path, repository_id="project")[
            "execution_status"
        ]
        == "unknown"
    )


def test_changed_or_missing_scope_during_capture_cannot_be_applicable(tmp_path):
    changed = capture(tmp_path, "from pathlib import Path;Path('source.py').write_text('changed')")
    assert (
        execution.check_execution_applicability(changed, tmp_path, repository_id="project")[
            "freshness"
        ]
        == "stale"
    )
    missing = capture(tmp_path, "from pathlib import Path;Path('source.py').unlink()")
    assert missing.to_dict()["scope_after"] is None
    assert missing.to_dict()["scope_error"] == "FileNotFoundError"
    assert (
        execution.check_execution_applicability(missing, tmp_path, repository_id="project")[
            "freshness"
        ]
        == "unknown"
    )


def test_gate_recomputes_current_bytes_and_identity(tmp_path):
    record = capture(tmp_path)
    (tmp_path / "source.py").write_text("later edit")
    assert (
        execution.check_execution_applicability(record, tmp_path, repository_id="project")[
            "freshness"
        ]
        == "stale"
    )
    assert (
        execution.check_execution_applicability(record, tmp_path, repository_id="another")[
            "freshness"
        ]
        == "unknown"
    )


def test_ingestion_never_spawns_and_rejects_duplicate_json_keys(tmp_path, monkeypatch):
    record = capture(tmp_path)
    monkeypatch.setattr(
        execution.subprocess, "Popen", lambda *a, **k: pytest.fail("ingestion executed a command")
    )
    assert execution.ExecutionRecord.from_dict(record.to_dict()) == record
    data = json.dumps(record.to_dict()).replace(
        '"schema_version": "1.0"', '"schema_version":"1.0","schema_version":"9"', 1
    )
    with pytest.raises(ValueError, match="duplicate"):
        execution.ExecutionRecord.from_bytes(data.encode())


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "9"),
        ("extra", True),
        ("producer", "trusted-ci"),
        ("argv", []),
        ("argv", "echo"),
        ("argv", [""]),
        ("argv", ["x", "\x00"]),
        ("requirement_ids", []),
        ("requirement_ids", ["R01", "R01"]),
        ("requirement_ids", ["r01"]),
        ("test_ids", ["x", "x"]),
        ("duration_seconds", float("nan")),
        ("duration_seconds", True),
        ("duration_seconds", -1),
        ("started_at", "yesterday"),
        ("started_at", "2026-10-18T00:00:00"),
        ("ended_at", "2000-01-01T00:00:00Z"),
        ("exit_code", True),
        ("exit_code", None),
        ("termination", "passed"),
        ("scope_after", None),
    ],
)
def test_malformed_records_refused(tmp_path, field, value):
    data = capture(tmp_path).to_dict()
    data[field] = value
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_dict(data)


@pytest.mark.parametrize(
    "change", ["fields", "bytes", "boolean", "base64", "hash", "length", "complete"]
)
def test_log_tampering_refused(tmp_path, change):
    data = capture(tmp_path).to_dict()
    output = data["stdout"]
    if change == "fields":
        output["extra"] = 0
    if change == "bytes":
        output["byte_count"] = -1
    if change == "boolean":
        output["byte_count"] = True
    if change == "base64":
        output["retained_base64"] = "!!!"
    if change == "hash":
        output["sha256"] = "0" * 64
    if change == "length":
        output["byte_count"] += 1
    if change == "complete":
        output["complete"] = "yes"
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_dict(data)


@pytest.mark.parametrize(
    "options",
    [
        dict(timeout=0),
        dict(timeout=True),
        dict(timeout=float("inf")),
        dict(max_output_bytes=0),
        dict(max_output_bytes=True),
        dict(max_output_bytes=2_000_000),
    ],
)
def test_invalid_limits_refused_before_execution(tmp_path, options, monkeypatch):
    monkeypatch.setattr(
        execution.subprocess, "Popen", lambda *a, **k: pytest.fail("bad limits executed")
    )
    with pytest.raises(ValueError):
        capture(tmp_path, **options)


def test_input_snapshot_and_record_size_limits(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_bytes(b"[]")
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_bytes(b"not json")
    monkeypatch.setattr(execution, "MAX_RECORD_BYTES", 10)
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_bytes(b" " * 11)
    monkeypatch.setattr(
        execution.subprocess, "Popen", lambda *a, **k: pytest.fail("oversize scope executed")
    )
    with pytest.raises(ValueError):
        capture(tmp_path)


def test_shell_metacharacters_are_literal_arguments(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("bounded")
    value = "x; echo injected & $(never)"
    record = execution.capture_execution(
        [sys.executable, "-c", "import sys;print(sys.argv[1])", value],
        tmp_path,
        ["source.py"],
        repository_id="project",
        requirement_ids=["R01"],
    )
    assert base64.b64decode(record.to_dict()["stdout"]["retained_base64"]).decode().strip() == value
    assert not (tmp_path / "injected").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("started_at", None),
        ("started_at", "x" * 65),
        ("executable", "relative/python"),
        ("scope_error", 3),
        ("scope_error", "x" * 257),
        ("cleanup_complete", "yes"),
        ("requirement_ids", [3]),
        ("requirement_ids", "R01"),
        ("test_ids", [""]),
        ("argv", [3]),
        ("argv", ["x" * 8193]),
        ("argv", [" "]),
    ],
)
def test_additional_shape_errors(tmp_path, field, value):
    data = capture(tmp_path).to_dict()
    data[field] = value
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_dict(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("retained_base64", 3),
        ("retained_base64", base64.b64encode(b"x" * 200).decode()),
        ("sha256", "bad"),
        ("sha256", None),
    ],
)
def test_output_shape_errors(tmp_path, field, value):
    data = capture(tmp_path).to_dict()
    data["stdout"][field] = value
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_dict(data)


def test_mismatched_post_scope_and_error_state(tmp_path):
    from aee.execution_scope import snapshot_scope

    data = capture(tmp_path).to_dict()
    bad = dict(data, scope_error="unexpected")
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_dict(bad)
    bad = dict(
        data, scope_after=snapshot_scope(tmp_path, ["source.py"], repository_id="another").to_dict()
    )
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_dict(bad)
    (tmp_path / "other.py").write_text("another")
    bad = dict(
        data, scope_after=snapshot_scope(tmp_path, ["other.py"], repository_id="project").to_dict()
    )
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_dict(bad)


def test_canonical_size_is_bounded_after_unicode_expansion(tmp_path, monkeypatch):
    data = capture(tmp_path).to_dict()
    data["argv"].append("é" * 1000)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    canonical = json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode()
    monkeypatch.setattr(execution, "MAX_RECORD_BYTES", (len(raw) + len(canonical)) // 2)
    with pytest.raises(ValueError, match="size limit"):
        execution.ExecutionRecord.from_bytes(raw)


def test_invalid_constructor_encoding_and_json_serialization():
    with pytest.raises(ValueError):
        execution.ExecutionRecord(None)
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_bytes(b"\xff")
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_dict({"bad": object()})


def test_closed_output_stream_is_incomplete():
    import io

    stream = io.BytesIO()
    stream.close()
    reader = execution._OutputReader(stream, 64, execution.threading.Event())
    reader.read()
    assert reader.error and not reader.result()["complete"]


def test_capture_io_error_never_succeeds(tmp_path, monkeypatch):
    def unreadable(reader):
        reader.error = True

    monkeypatch.setattr(execution._OutputReader, "read", unreadable)
    record = capture(tmp_path)
    assert record.to_dict()["termination"] == "io_error"
    assert (
        execution.check_execution_applicability(record, tmp_path, repository_id="project")[
            "execution_status"
        ]
        == "unknown"
    )


def test_start_failure_cleans_up_the_real_process(tmp_path, monkeypatch):
    processes = []
    original = execution.subprocess.Popen

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    def fail_start(thread):
        raise RuntimeError("injected thread resource failure")

    monkeypatch.setattr(execution.subprocess, "Popen", spawn)
    monkeypatch.setattr(execution.threading.Thread, "start", fail_start)
    with pytest.raises(RuntimeError, match="thread resource"):
        capture(tmp_path, "import time;time.sleep(10)")
    assert processes and all(process.poll() is not None for process in processes)


@pytest.mark.parametrize(
    "platform,missing,already_exited",
    [
        ("win32", True, False),
        ("win32", False, False),
        ("linux", False, False),
        ("linux", True, True),
    ],
)
def test_native_tree_cleanup_fallback_contract(monkeypatch, platform, missing, already_exited):
    calls = []

    class Process:
        pid = 123
        returncode = 0 if already_exited else None

        def poll(self):
            return self.returncode

        def kill(self):
            calls.append("kill")
            self.returncode = -9

        def wait(self, timeout):
            calls.append("wait")
            return self.returncode

    def run(*args, **kwargs):
        calls.append("taskkill")
        if missing:
            raise FileNotFoundError("no taskkill")

    def killpg(*args):
        calls.append("killpg")
        if missing:
            raise ProcessLookupError("already gone")

    monkeypatch.setattr(execution, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(execution, "os", SimpleNamespace(environ={}, killpg=killpg))
    monkeypatch.setattr(execution, "signal", SimpleNamespace(SIGKILL=9))
    monkeypatch.setattr(execution.subprocess, "run", run)
    execution._terminate(Process())
    assert calls[-1] == "wait"
    assert ("taskkill" if platform == "win32" else "killpg") in calls


def test_explicit_relative_and_path_resolved_executables(tmp_path, monkeypatch):
    source = tmp_path / "source.py"
    source.write_text("bounded")
    relative = os.path.relpath(sys.executable, tmp_path)
    record = execution.capture_execution(
        [relative, "-c", "pass"],
        tmp_path,
        ["source.py"],
        repository_id="project",
        requirement_ids=["R01"],
    )
    assert record.to_dict()["exit_code"] == 0
    monkeypatch.setattr(execution.shutil, "which", lambda name: sys.executable)
    record = execution.capture_execution(
        ["python-probe", "-c", "pass"],
        tmp_path,
        ["source.py"],
        repository_id="project",
        requirement_ids=["R01"],
    )
    assert record.to_dict()["executable"] != record.to_dict()["argv"][0]
    monkeypatch.setattr(execution.shutil, "which", lambda name: None)
    with pytest.raises(FileNotFoundError):
        execution.capture_execution(
            ["missing"], tmp_path, ["source.py"], repository_id="project", requirement_ids=["R01"]
        )
    with pytest.raises(ValueError, match="batch-script"):
        execution.capture_execution(
            [str(tmp_path / "x.cmd")],
            tmp_path,
            ["source.py"],
            repository_id="project",
            requirement_ids=["R01"],
        )


def test_explicit_pin_and_missing_current_root(tmp_path):
    record = capture(tmp_path)
    pinned = execution.check_execution_applicability(
        record, tmp_path, repository_id="project", trusted_record_digests={record.digest}
    )
    assert (
        pinned["producer_trust"] == "pinned-record" and pinned["test_verification"] == "unassessed"
    )
    assert (
        execution.check_execution_applicability(
            record, tmp_path / "missing", repository_id="project"
        )["freshness"]
        == "unknown"
    )
    for pins in (None, "bad", ["bad"], [3]):
        with pytest.raises(ValueError):
            execution.check_execution_applicability(
                record, tmp_path, repository_id="project", trusted_record_digests=pins
            )


def test_capture_without_windows_creation_flags(tmp_path, monkeypatch):
    # Exercise the no-flags branch with a real process. Native POSIX tree cleanup
    # is still exercised by the Linux/macOS CI legs, not claimed by this test.
    monkeypatch.setattr(execution, "sys", SimpleNamespace(platform="linux"))
    assert capture(tmp_path).to_dict()["exit_code"] == 0


def test_report_creation_binding_and_missing_output(tmp_path):
    record = capture(
        tmp_path,
        "from pathlib import Path;Path('junit.xml').write_text('<testsuite/>')",
        report_paths=["junit.xml", "missing.xml"],
    )
    assert record.to_dict()["reports"][0]["byte_count"] == len(b"<testsuite/>")
    assert record.to_dict()["reports"][1]["error"] == "FileNotFoundError"
    with pytest.raises(ValueError, match="already exist"):
        capture(tmp_path, report_paths=["junit.xml"])
    with pytest.raises(ValueError):
        capture(tmp_path, report_paths=["x.xml", "./x.xml"])
    with pytest.raises(ValueError):
        capture(tmp_path, report_paths=[f"x{i}.xml" for i in range(33)])
    with pytest.raises(ValueError):
        capture(tmp_path, report_paths=["../escape.xml"])


def test_unreadable_and_oversize_reports_record_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(execution, "MAX_REPORT_BYTES", 2)
    record = capture(
        tmp_path,
        "from pathlib import Path;Path('large.xml').write_text('large');Path('dir').mkdir()",
        report_paths=["large.xml", "dir"],
    )
    assert all(item["error"] == "ValueError" for item in record.to_dict()["reports"])


@pytest.mark.parametrize(
    "change",
    [
        "type",
        "too_many",
        "fields",
        "path",
        "error_type",
        "error_long",
        "unavailable_hash",
        "sha",
        "sha_type",
        "count",
        "duplicate",
    ],
)
def test_strict_receipt_ingestion(tmp_path, change):
    data = capture(tmp_path).to_dict()
    item = dict(path="junit.xml", sha256="a" * 64, byte_count=1, error="")
    data["reports"] = [item]
    if change == "type":
        data["reports"] = {}
    if change == "too_many":
        data["reports"] = [dict(item) for _ in range(33)]
    if change == "fields":
        item["extra"] = True
    if change == "path":
        item["path"] = "./junit.xml"
    if change == "error_type":
        item["error"] = None
    if change == "error_long":
        item["error"] = "x" * 257
    if change == "unavailable_hash":
        item["error"] = "missing"
    if change == "sha":
        item["sha256"] = "bad"
    if change == "sha_type":
        item["sha256"] = None
    if change == "count":
        item["byte_count"] = True
    if change == "duplicate":
        data["reports"].append(dict(item))
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_dict(data)


def test_unhashable_termination_is_clean_validation_error(tmp_path):
    data = capture(tmp_path).to_dict()
    data["termination"] = []
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_dict(data)


def test_actual_anchored_ledger_retains_observation_without_promoting_trust(tmp_path):
    from aee.ledger import HashChainLedger

    record = capture(tmp_path)
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    first = execution.append_execution_record(record, ledger, actor="test-runner-label")
    assert first["payload"]["producer_trust"] == "unverified"
    assert first["payload"]["record_sha256"] == record.digest
    assert ledger.verify(require_anchor=True).valid
    second = execution.append_execution_record(record, ledger)
    assert second["payload"]["record_sha256"] == first["payload"]["record_sha256"]
    assert second["previous_hash"] == first["entry_hash"]
    lines = ledger.path.read_text().splitlines()
    bad = json.loads(lines[0])
    bad["payload"]["record"]["exit_code"] = 7
    ledger.path.write_text(json.dumps(bad) + "\n" + lines[1] + "\n")
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="invalid ledger"):
        execution.append_execution_record(record, ledger)
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("actor", [None, "", " ", "x" * 257])
def test_bad_actor_label_does_not_append(tmp_path, actor):
    from aee.ledger import HashChainLedger

    record = capture(tmp_path)
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    with pytest.raises(ValueError):
        execution.append_execution_record(record, ledger, actor=actor)
    assert not ledger.path.exists()


def test_readonly_mapping_and_non_mapping_ingestion(tmp_path):
    from types import MappingProxyType

    record = capture(tmp_path)
    assert execution.ExecutionRecord.from_dict(MappingProxyType(record.to_dict())) == record
    with pytest.raises(ValueError):
        execution.ExecutionRecord.from_dict([])


def test_scope_list_is_frozen_before_process_start(tmp_path, monkeypatch):
    (tmp_path / "source.py").write_text("bounded")
    (tmp_path / "other.py").write_text("other")
    paths = ["source.py"]
    original = execution.subprocess.Popen

    def spawn(*args, **kwargs):
        paths.append("other.py")
        return original(*args, **kwargs)

    monkeypatch.setattr(execution.subprocess, "Popen", spawn)
    record = execution.capture_execution(
        [sys.executable, "-c", "pass"],
        tmp_path,
        paths,
        repository_id="project",
        requirement_ids=["R01"],
    )
    data = record.to_dict()
    assert data["scope_before"] == data["scope_after"]
    assert set(data["scope_after"]["files"]) == {"source.py"}
