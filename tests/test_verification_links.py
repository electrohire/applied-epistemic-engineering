"""Real receipt-backed discovery, membership invalidation and strict links."""

import sys
from pathlib import Path

import pytest

from aee.verification_links import (
    TestDiscovery as Discovery,
)
from aee.verification_links import (
    capture_test_discovery,
    check_verification_links,
    verify_test_discovery,
)


@pytest.fixture
def collected(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_one.py").write_text("def test_one(): pass\n")
    (tmp_path / "collector.py").write_text(
        "import json\nfrom pathlib import Path\n"
        "tests = [{'id': 'tests.test_one::test_one', 'path': 'tests/test_one.py'}]\n"
        "Path('inventory.json').write_text(json.dumps({'schema_version':'1.0','tests':tests}))\n"
    )
    record = capture_test_discovery(
        [sys.executable, "collector.py"],
        tmp_path,
        repository_id="example",
        managed_roots=["tests"],
        suffixes=[".py"],
        paths=["collector.py"],
        requirement_ids=["FR-1"],
        report_path="inventory.json",
    )
    return tmp_path, record


def verify(collected, **kwargs):
    root, record = collected
    return verify_test_discovery(
        record, root, repository_id="example", trusted_discovery_digests=[record.digest], **kwargs
    )


def test_receipt_round_trip_and_no_implicit_producer_trust(collected, monkeypatch):
    root, record = collected
    assert Discovery.from_dict(record.to_dict()) == Discovery.from_bytes(record.canonical)
    assert verify(collected)["outcome"] == "pass"
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("ingest executed command"))
    unknown = verify_test_discovery(record, root, repository_id="example")
    assert unknown["outcome"] == "gather_evidence"
    assert unknown["findings"] == ["collection_producer_unverified"]
    assert verify(collected)["outcome"] == "pass"
    assert verify_test_discovery(record, root, repository_id="other")["outcome"] != "pass"
    copied = record.to_dict()
    copied["suffixes"].append(".js")
    assert ".js" not in record.to_dict()["suffixes"]


@pytest.mark.parametrize(
    "mutation", ["added", "changed", "removed", "renamed", "config", "report", "missing", "empty"]
)
def test_inventory_cannot_stay_fresh_after_changes(collected, mutation):
    root, _ = collected
    source = root / "tests/test_one.py"
    if mutation == "added":
        (root / "tests/test_new.py").write_text("def test_new(): pass")
    elif mutation == "changed":
        source.write_text("def test_one(): assert False")
    elif mutation == "removed":
        source.unlink()
    elif mutation == "renamed":
        source.rename(root / "tests/test_renamed.py")
    elif mutation == "config":
        (root / "collector.py").write_text("changed configuration")
    elif mutation == "report":
        (root / "inventory.json").write_text("{}")
    elif mutation == "missing":
        (root / "inventory.json").unlink()
    else:
        source.unlink()
        (root / "tests").rmdir()
    assert verify(collected)["outcome"] == "gather_evidence"


def test_suffix_scope_is_explicit_not_entire_environment(collected):
    root, _ = collected
    (root / "tests/notes.txt").write_text("outside declared suffix policy")
    (root / "unscoped.py").write_text("outside declared managed roots")
    assert verify(collected)["outcome"] == "pass"


@pytest.mark.parametrize(
    "links,missing,broken,orphans,unknown",
    [
        (
            {"FR-1": ["tests.test_one::test_one"], "FR-2": ["tests.test_one::test_one"]},
            [],
            [],
            [],
            [],
        ),
        ({}, ["FR-1", "FR-2"], [], ["tests.test_one::test_one"], []),
        ({"FR-1": ["missing"]}, ["FR-2"], ["missing"], ["tests.test_one::test_one"], []),
        ({"FR-X": ["tests.test_one::test_one"]}, ["FR-1", "FR-2"], [], [], ["FR-X"]),
    ],
)
def test_many_to_many_links_and_explicit_findings(
    collected, links, missing, broken, orphans, unknown
):
    root, record = collected
    result = check_verification_links(
        record,
        root,
        repository_id="example",
        accepted_requirement_ids=["FR-1", "FR-2"],
        links=links,
        trusted_discovery_digests=[record.digest],
    )
    assert result["missing_requirements"] == missing
    assert result["broken_test_ids"] == broken
    assert result["orphan_test_ids"] == orphans
    assert result["unknown_requirements"] == unknown
    assert result["outcome"] == (
        "gather_evidence" if any([missing, broken, orphans, unknown]) else "pass"
    )


@pytest.mark.parametrize(
    "links", [None, {"FR-1": "test"}, {"FR-1": []}, {"": ["test"]}, {"FR-1": ["x", "x"]}]
)
def test_malformed_links_refused(collected, links):
    root, record = collected
    with pytest.raises(ValueError):
        check_verification_links(
            record, root, repository_id="example", accepted_requirement_ids=["FR-1"], links=links
        )


def report_record(collected, data):
    """Rebind synthetic report bytes as a trusted-host fixture, not actual discovery."""
    import hashlib

    root, record = collected
    (root / "inventory.json").write_bytes(data)
    value = record.to_dict()
    receipt = value["execution"]["reports"][0]
    receipt.update(sha256=hashlib.sha256(data).hexdigest(), byte_count=len(data))
    return root, Discovery.from_dict(value)


@pytest.mark.parametrize(
    "report",
    [
        b"not json",
        b"[]",
        b'{"schema_version":"2.0","tests":[]}',
        b'{"schema_version":"1.0","tests":[],"collected":true}',
        b'{"schema_version":"1.0","tests":[]}',
        b'{"schema_version":"1.0","tests":null}',
        b'{"schema_version":"1.0","tests":[{}]}',
        b'{"schema_version":"1.0","tests":[{"id":"x","path":"../out.py"}]}',
        b'{"schema_version":"1.0","tests":[{"id":"x","path":"collector.py"}]}',
        b'{"schema_version":"1.0","tests":[{"id":"","path":"tests/test_one.py"}]}',
        b'{"schema_version":"1.0","tests":[{"id":"x","path":"tests/test_one.py"},{"id":"x","path":"tests/test_one.py"}]}',
        b'{"schema_version":"1.0","schema_version":"1.0","tests":[]}',
    ],
)
def test_bad_collection_reports_never_pass(collected, report):
    assert verify(report_record(collected, report))["outcome"] == "gather_evidence"


@pytest.mark.parametrize(
    "change", ["version", "extra", "roots", "overlap", "suffixes", "error", "member", "path"]
)
def test_strict_discovery_schema(collected, change):
    _, record = collected
    value = record.to_dict()
    if change == "version":
        value["schema_version"] = "future"
    elif change == "extra":
        value["trusted"] = True
    elif change == "roots":
        value["managed_roots"] = ["../tests"]
    elif change == "overlap":
        value["managed_roots"] = ["tests", "tests/sub"]
    elif change == "suffixes":
        value["suffixes"] = [".*"]
    elif change == "error":
        value["membership_error"] = "error with a post snapshot"
    elif change == "member":
        value["managed_roots"] = ["other"]
    else:
        value["report_path"] = "./inventory.json"
    with pytest.raises(ValueError):
        Discovery.from_dict(value)


def test_inner_execution_pin_does_not_authenticate_membership(collected):
    from aee.execution_evidence import ExecutionRecord

    root, record = collected
    inner = ExecutionRecord.from_dict(record.to_dict()["execution"])
    result = verify_test_discovery(
        record, root, repository_id="example", trusted_discovery_digests=[inner.digest]
    )
    assert result["outcome"] == "gather_evidence"
    with pytest.raises(ValueError):
        verify_test_discovery(
            record, root, repository_id="example", trusted_discovery_digests=record.digest
        )


def test_collection_mutation_retains_actual_execution(collected):
    root, _ = collected
    record = capture_test_discovery(
        [sys.executable, "-c", "from pathlib import Path; Path('tests/new.py').write_text('new')"],
        root,
        repository_id="example",
        managed_roots=["tests"],
        suffixes=[".py"],
        paths=[],
        requirement_ids=["FR-1"],
        report_path="new-inventory.json",
    )
    assert record.to_dict()["execution"]["exit_code"] == 0
    assert record.to_dict()["members_after"] is None
    assert verify((root, record))["outcome"] == "gather_evidence"


def test_actual_pytest_collection(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_example.py").write_text("def test_example(): assert True\n")
    # The plugin writes only the items observed by actual pytest collection.
    (tmp_path / "collector.py").write_text(
        "import json, pytest\nfrom pathlib import Path\n"
        "class Plugin:\n"
        " def pytest_collection_finish(self, session):\n"
        "  tests=[{'id':i.nodeid,'path':Path(i.path).relative_to(Path.cwd()).as_posix()}"
        " for i in session.items]\n"
        "  Path('inventory.json').write_text(json.dumps({'schema_version':'1.0','tests':tests}))\n"
        "raise SystemExit(pytest.main(['--collect-only','-q','tests'],plugins=[Plugin()]))\n"
    )
    record = capture_test_discovery(
        [sys.executable, "collector.py"],
        tmp_path,
        repository_id="real",
        managed_roots=["tests"],
        suffixes=[".py"],
        paths=["collector.py"],
        requirement_ids=["FR-1"],
        report_path="inventory.json",
    )
    result = check_verification_links(
        record,
        tmp_path,
        repository_id="real",
        accepted_requirement_ids=["FR-1"],
        links={"FR-1": ["tests/test_example.py::test_example"]},
        trusted_discovery_digests=[record.digest],
    )
    assert result["outcome"] == "pass"
    assert len(result["tests"]) == 1


def test_managed_tree_limits_and_read_errors(collected, monkeypatch):
    from aee import verification_links as module

    root, _ = collected
    monkeypatch.setattr(module, "MAX_DISCOVERY_ENTRIES", 1)
    (root / "tests/extra.txt").write_text("bounded enumeration includes ignored entries")
    assert "collection_inventory_unverifiable" in verify(collected)["findings"]
    monkeypatch.setattr(module, "MAX_DISCOVERY_ENTRIES", 10000)

    def unreadable(directory, *, onerror, followlinks):
        onerror(PermissionError("unreadable managed tree"))

    monkeypatch.setattr(module.os, "walk", unreadable)
    assert verify(collected)["outcome"] == "gather_evidence"
    with pytest.raises(PermissionError):
        capture_test_discovery(
            [sys.executable, "-c", "pass"],
            root,
            repository_id="example",
            managed_roots=["tests"],
            suffixes=[".py"],
            paths=[],
            requirement_ids=["FR-1"],
            report_path="new.json",
        )


def test_links_and_reparse_points_refused(collected, monkeypatch):
    from types import SimpleNamespace

    root, _ = collected
    original = Path.lstat

    def reparse(path, *args, **kwargs):
        if path.name == "test_one.py":
            return SimpleNamespace(st_mode=original(path).st_mode, st_file_attributes=0x400)
        return original(path, *args, **kwargs)

    # Test both the managed directory walker and the generic scoped-file gate.
    from aee.verification_links import _members

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ValueError):
        _members(root, ["tests"], [".py"])
    assert verify(collected)["outcome"] == "gather_evidence"
    monkeypatch.setattr(Path, "lstat", original)
    target = root / "tests/linked.py"
    try:
        target.symlink_to(root / "tests/test_one.py")
    except OSError:
        pytest.skip("host has no symlink creation privilege")
    assert verify(collected)["outcome"] == "gather_evidence"


@pytest.mark.parametrize(
    "roots,suffixes",
    [
        (["./tests"], [".py"]),
        ([f"test{i}" for i in range(33)], [".py"]),
        (["tests"], [f".ext{i}" for i in range(33)]),
        (["tests"], ["py"]),
        (["tests"], ["."]),
    ],
)
def test_invalid_directory_policy(collected, roots, suffixes):
    _, record = collected
    value = record.to_dict()
    value.update(managed_roots=roots, suffixes=suffixes)
    with pytest.raises(ValueError):
        Discovery.from_dict(value)


def test_record_size_bounds_and_strict_json(collected, monkeypatch):
    from aee import verification_links as module

    _, record = collected
    for data in ["string", b"[]", b'{"x":1,"x":2}', b"[" * 2000 + b"0" + b"]" * 2000]:
        with pytest.raises(ValueError):
            Discovery.from_bytes(data)
    monkeypatch.setattr(module, "MAX_DISCOVERY_BYTES", 1)
    with pytest.raises(ValueError):
        Discovery.from_bytes(record.canonical)
    with pytest.raises(ValueError):
        Discovery.from_dict(record.to_dict())


@pytest.mark.parametrize(
    "change",
    [
        "receipt",
        "missing_byte_scope",
        "wrong_scope",
        "failed",
        "empty_report",
        "noncanonical_source",
    ],
)
def test_receipt_binding_and_failed_collection(collected, change):
    from aee.execution_scope import snapshot_scope

    root, record = collected
    value = record.to_dict()
    if change == "receipt":
        value["execution"]["reports"] = []
    elif change == "missing_byte_scope":
        value["execution"]["scope_before"] = snapshot_scope(
            root, ["collector.py"], repository_id="example"
        ).to_dict()
        value["execution"]["scope_after"] = value["execution"]["scope_before"]
    elif change == "wrong_scope":
        value["execution"]["scope_before"] = snapshot_scope(
            root, ["collector.py"], repository_id="wrong"
        ).to_dict()
        value["execution"]["scope_after"] = value["execution"]["scope_before"]
    elif change == "failed":
        value["execution"]["exit_code"] = 5
    elif change == "empty_report":
        return_value = report_record(collected, b'{"schema_version":"1.0","tests":[null]}')
        assert verify(return_value)["outcome"] == "gather_evidence"
        return
    else:
        return_value = report_record(
            collected, b'{"schema_version":"1.0","tests":[{"id":"x","path":"./tests/test_one.py"}]}'
        )
        assert verify(return_value)["outcome"] == "gather_evidence"
        return
    mutated = Discovery.from_dict(value)
    assert verify((root, mutated))["outcome"] == "gather_evidence"


def test_scope_sequence_is_not_a_string(collected):
    root, _ = collected
    with pytest.raises(ValueError):
        capture_test_discovery(
            [sys.executable, "-c", "pass"],
            root,
            repository_id="example",
            managed_roots=["tests"],
            suffixes=[".py"],
            paths="collector.py",
            requirement_ids=["FR-1"],
            report_path="new.json",
        )
    with pytest.raises(ValueError):
        check_verification_links(
            collected[1], root, repository_id="example", accepted_requirement_ids="FR-1", links={}
        )
    with pytest.raises(ValueError, match="duplicate"):
        capture_test_discovery(
            [sys.executable, "-c", "pass"],
            root,
            repository_id="example",
            managed_roots=["tests"],
            suffixes=[".py"],
            paths=["collector.py", "collector.py"],
            requirement_ids=["FR-1"],
            report_path="unused.json",
        )


@pytest.mark.parametrize(
    "length,expected", [(4151, "pass"), (8192, "pass"), (8193, "gather_evidence")]
)
def test_long_parameterized_test_identity(collected, length, expected):
    import json

    report = json.dumps(
        {"schema_version": "1.0", "tests": [{"id": "x" * length, "path": "tests/test_one.py"}]}
    ).encode()
    assert verify(report_record(collected, report))["outcome"] == expected


def method_fixture(root, requirement_ids=("R02",)):
    from aee import VerificationMethodApproval, snapshot_scope

    (root / "manual-requirement.md").write_text("Synthetic non-test requirement fixture")
    (root / "approval-receipt.txt").write_text(
        "Synthetic external-host receipt fixture; not real human approval"
    )
    return VerificationMethodApproval.from_dict(
        dict(
            schema_version="1.0",
            decision="approve_method",
            method_id="MANUAL-01",
            method_description="Inspect the bounded fixture",
            requirement_ids=list(requirement_ids),
            approver_label="synthetic human label",
            approved_at="2026-10-18T00:00:00+00:00",
            receipt_path="approval-receipt.txt",
            scope=snapshot_scope(
                root, ["manual-requirement.md", "approval-receipt.txt"], repository_id="example"
            ).to_dict(),
        )
    )


@pytest.mark.parametrize("trusted", [False, True])
def test_non_test_method_needs_separate_host_approval_and_is_not_execution(collected, trusted):
    root, discovery = collected
    method = method_fixture(root)
    result = check_verification_links(
        discovery,
        root,
        repository_id="example",
        accepted_requirement_ids=["FR-1", "R02"],
        links={"FR-1": ["tests.test_one::test_one"]},
        trusted_discovery_digests=[discovery.digest],
        approved_methods=[method],
        trusted_human_approval_digests=[method.digest] if trusted else [],
    )
    assert result["outcome"] == ("pass" if trusted else "gather_evidence")
    assert result["method_approvals"][0]["verification_status"] == "unassessed"
    if not trusted:
        assert result["missing_requirements"] == ["R02"]
        assert "method_approval_not_applicable" in result["findings"]


def test_stale_method_and_orphan_tests_remain_blockers(collected):
    root, discovery = collected
    method = method_fixture(root, ["FR-1", "R02"])
    result = check_verification_links(
        discovery,
        root,
        repository_id="example",
        accepted_requirement_ids=["FR-1", "R02"],
        links={},
        trusted_discovery_digests=[discovery.digest],
        approved_methods=[method],
        trusted_human_approval_digests=[method.digest],
    )
    assert result["orphan_test_ids"] == ["tests.test_one::test_one"]
    assert result["outcome"] == "gather_evidence"
    (root / "approval-receipt.txt").write_text("changed permission")
    result = check_verification_links(
        discovery,
        root,
        repository_id="example",
        accepted_requirement_ids=["FR-1", "R02"],
        links={"FR-1": ["tests.test_one::test_one"]},
        trusted_discovery_digests=[discovery.digest],
        approved_methods=[method],
        trusted_human_approval_digests=[method.digest],
    )
    assert "method_approval_not_applicable" in result["findings"]


def test_duplicate_or_malformed_methods_are_refused(collected, monkeypatch):
    root, discovery = collected
    method = method_fixture(root)
    for methods in ("method", [True], [method, method]):
        with pytest.raises(ValueError):
            check_verification_links(
                discovery,
                root,
                repository_id="example",
                accepted_requirement_ids=["FR-1"],
                links={},
                approved_methods=methods,
            )
    from aee import VerificationMethodApproval

    oversized = VerificationMethodApproval(b" " * (2 * 1024 * 1024 + 1))
    for methods in ([method] * 10001, [oversized]):
        with pytest.raises(ValueError):
            check_verification_links(
                discovery,
                root,
                repository_id="example",
                accepted_requirement_ids=["FR-1"],
                links={},
                approved_methods=methods,
            )


def test_method_cannot_introduce_an_unaccepted_requirement(collected):
    root, discovery = collected
    method = method_fixture(root)
    result = check_verification_links(
        discovery,
        root,
        repository_id="example",
        accepted_requirement_ids=["FR-1"],
        links={"FR-1": ["tests.test_one::test_one"]},
        trusted_discovery_digests=[discovery.digest],
        approved_methods=[method],
        trusted_human_approval_digests=[method.digest],
    )
    assert result["unknown_requirements"] == ["R02"]
    assert result["outcome"] == "gather_evidence"


def test_excessive_discovery_nesting_is_a_typed_input_error():
    depth = max(10000, sys.getrecursionlimit() * 4)
    with pytest.raises(ValueError, match="nesting"):
        Discovery.from_bytes(b"[" * depth + b"0" + b"]" * depth)
