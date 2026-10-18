"""Confined, content-bound applicability; freshness is not execution proof."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

import aee.execution_scope as scope


def example(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/code.py").write_text("answer = 42\n")
    (tmp_path / "test.py").write_text("assert True\n")
    return scope.snapshot_scope(tmp_path, ["test.py", "src/code.py"], repository_id="project")


def test_scope_roundtrip_is_order_independent_and_defensively_copied(tmp_path):
    first = example(tmp_path)
    second = scope.snapshot_scope(tmp_path, ["src/code.py", "test.py"], repository_id="project")
    assert first == second == scope.ScopeSnapshot.from_dict(first.to_dict())
    value = first.to_dict()
    value["files"].clear()
    assert len(first.files) == 2
    assert scope.check_freshness(first, tmp_path, repository_id="project").to_dict() == {
        "status": "fresh",
        "changed": [],
        "missing": [],
        "unreadable": [],
        "reason": "",
    }


def test_scoped_changes_stale_and_unrelated_changes_do_not_invalidate(tmp_path):
    snapshot = example(tmp_path)
    (tmp_path / "unrelated.txt").write_text("not in explicitly declared scope")
    assert scope.check_freshness(snapshot, tmp_path, repository_id="project").status == "fresh"
    (tmp_path / "src/code.py").write_text("answer = 43\n")
    (tmp_path / "test.py").unlink()
    value = scope.check_freshness(snapshot, tmp_path, repository_id="project")
    assert value.status == "stale" and value.changed == ("src/code.py",)
    assert value.missing == ("test.py",)


def test_wrong_repository_stays_unknown_without_reading_inputs(tmp_path, monkeypatch):
    snapshot = example(tmp_path)
    monkeypatch.setattr(scope, "_digest", lambda p: pytest.fail("must not read another project"))
    value = scope.check_freshness(snapshot, tmp_path, repository_id="other")
    assert value.status == "unknown" and value.reason == "repository_identity_mismatch"


@pytest.mark.parametrize("error", [PermissionError("fixture"), ValueError("unsafe input")])
def test_unreadable_input_is_unknown_not_fresh(tmp_path, monkeypatch, error):
    snapshot = example(tmp_path)

    def fail(path):
        raise error

    monkeypatch.setattr(scope, "_digest", fail)
    value = scope.check_freshness(snapshot, tmp_path, repository_id="project")
    assert value.status == "unknown" and len(value.unreadable) == 2


@pytest.mark.parametrize(
    "value",
    [
        None,
        42,
        "",
        "x" * 4097,
        "../secret",
        "a/../b",
        "/abs",
        "C:rel",
        "C:\\abs",
        "//server/share",
        "a:stream",
        "a*",
        "a?",
        "a\x00b",
        ".",
    ],
)
def test_bad_path_refused(value):
    with pytest.raises(ValueError):
        scope.scope_path(value)


def test_portable_path_normalization():
    assert scope.scope_path("./src\\code.py") == "src/code.py"


@pytest.mark.parametrize("value", [None, 4, "", " ", "x" * 1025])
def test_bad_repository_id_rejected(tmp_path, value):
    with pytest.raises(ValueError, match="repository_id"):
        scope.snapshot_scope(tmp_path, ["file"], repository_id=value)


@pytest.mark.parametrize("value", [None, [], "file", b"file", ["a"] * 10001])
def test_scope_shape_bounded(tmp_path, value):
    with pytest.raises(ValueError, match="bounded"):
        scope.snapshot_scope(tmp_path, value, repository_id="project")


def test_duplicate_normalized_scope_and_non_directory_root(tmp_path):
    (tmp_path / "file").write_text("x")
    with pytest.raises(ValueError, match="duplicate"):
        scope.snapshot_scope(tmp_path, ["file", "./file"], repository_id="project")
    with pytest.raises(ValueError, match="root must be a directory"):
        scope.snapshot_scope(tmp_path / "file", ["file"], repository_id="project")
    snapshot = scope.snapshot_scope(tmp_path, ["file"], repository_id="project")
    with pytest.raises(ValueError, match="root must be a directory"):
        scope.check_freshness(snapshot, tmp_path / "file", repository_id="project")


def test_oversized_and_non_regular_input_refused(tmp_path, monkeypatch):
    (tmp_path / "file").write_text("xx")
    monkeypatch.setattr(scope, "MAX_INPUT_BYTES", 1)
    with pytest.raises(ValueError, match="size limit"):
        scope.snapshot_scope(tmp_path, ["file"], repository_id="project")
    (tmp_path / "directory").mkdir()
    with pytest.raises(ValueError, match="regular file"):
        scope.snapshot_scope(tmp_path, ["directory"], repository_id="project")


def test_symlink_refused_before_any_content_read(tmp_path, monkeypatch):
    (tmp_path / "file").write_text("inside")
    monkeypatch.setattr(Path, "is_symlink", lambda p: p.name == "file")
    monkeypatch.setattr(scope, "_digest", lambda p: pytest.fail("unsafe input was read"))
    with pytest.raises(ValueError, match="symlink"):
        scope.snapshot_scope(tmp_path, ["file"], repository_id="project")


def test_resolver_escape_refused(tmp_path, monkeypatch):
    (tmp_path / "file").write_text("inside")
    original = Path.resolve

    def changed(path, *args, **kwargs):
        return (
            tmp_path.parent / "outside" if path.name == "file" else original(path, *args, **kwargs)
        )

    monkeypatch.setattr(Path, "resolve", changed)
    with pytest.raises(ValueError, match="escapes"):
        scope.snapshot_scope(tmp_path, ["file"], repository_id="project")


@pytest.mark.parametrize(
    "change",
    ["fields", "version", "files_type", "files_empty", "path", "digest_type", "digest_hex", "tree"],
)
def test_malformed_or_tampered_snapshot_refused(tmp_path, change):
    value = copy.deepcopy(example(tmp_path).to_dict())
    if change == "fields":
        value["extra"] = True
    if change == "version":
        value["schema_version"] = "999"
    if change == "files_type":
        value["files"] = []
    if change == "files_empty":
        value["files"] = {}
    if change == "path":
        value["files"] = {"./file": "0" * 64}
    if change == "digest_type":
        value["files"]["test.py"] = 4
    if change == "digest_hex":
        value["files"]["test.py"] = "not a digest"
    if change == "tree":
        value["tree_hash"] = "0" * 64
    with pytest.raises(ValueError):
        scope.ScopeSnapshot.from_dict(value)


def test_snapshot_input_must_be_mapping():
    with pytest.raises(ValueError, match="fields"):
        scope.ScopeSnapshot.from_dict([])


def test_python_constructed_snapshot_cannot_hide_duplicate_paths(tmp_path):
    first = example(tmp_path)
    forged = scope.ScopeSnapshot(first.repository_id, first.files + first.files, first.tree_hash)
    with pytest.raises(ValueError, match="duplicate"):
        scope.check_freshness(forged, tmp_path, repository_id="project")
