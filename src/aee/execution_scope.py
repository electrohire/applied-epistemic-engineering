"""Versioned, confined input snapshots for execution-evidence applicability.

A fresh snapshot establishes that the explicitly scoped bytes are unchanged.
It is not proof of execution, producer identity, test completeness or correctness.
Git metadata is deliberately not executed or trusted while ingesting evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

SCOPE_VERSION = "1.0"
MAX_SCOPE_FILES = 10_000
MAX_INPUT_BYTES = 16 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _repository(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError("repository_id must be a nonempty string of at most 1024 characters")
    return value


def scope_path(value: object) -> str:
    """Normalize a portable relative file name; refuse traversal, ADS and globs."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError("scope path must be a nonempty string of at most 4096 characters")
    name = value.replace("\\", "/")
    if (
        PurePosixPath(name).is_absolute()
        or PureWindowsPath(value).drive
        or ".." in PurePosixPath(name).parts
        or any(c in name for c in (":", "*", "?", "\x00"))
    ):
        raise ValueError("scope paths must be explicit relative files without traversal or globs")
    normalized = PurePosixPath(name).as_posix()
    if normalized == ".":
        raise ValueError("a scope entry must name a file")
    return normalized


def _file(root: Path, name: str) -> Path:
    current = root
    for part in PurePosixPath(name).parts:
        current = current / part
        if current.is_symlink() or (
            current.exists() and getattr(current.lstat(), "st_file_attributes", 0) & 0x400
        ):
            raise ValueError("symlinked/reparse scope components are refused")
    resolved = current.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError("scope file escapes the project root")
    return resolved


def _digest(path: Path) -> str:
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("scope input must be a regular file")
    with path.open("rb") as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("scope input exceeds the size limit")
    return hashlib.sha256(data).hexdigest()


def _tree(repository_id: str, files: tuple[tuple[str, str], ...]) -> str:
    value = {"schema_version": SCOPE_VERSION, "repository_id": repository_id, "files": dict(files)}
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ScopeSnapshot:
    """Immutable in-memory scope; input records must use :meth:`from_dict`."""

    repository_id: str
    files: tuple[tuple[str, str], ...]
    tree_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCOPE_VERSION,
            "repository_id": self.repository_id,
            "files": dict(self.files),
            "tree_hash": self.tree_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ScopeSnapshot:
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "repository_id",
            "files",
            "tree_hash",
        }:
            raise ValueError("invalid scope snapshot fields")
        if value["schema_version"] != SCOPE_VERSION:
            raise ValueError("unsupported scope snapshot version")
        repository_id = _repository(value["repository_id"])
        raw = value["files"]
        if not isinstance(raw, dict) or not 1 <= len(raw) <= MAX_SCOPE_FILES:
            raise ValueError("scope must contain a bounded nonempty file mapping")
        files: list[tuple[str, str]] = []
        for name, digest in raw.items():
            if scope_path(name) != name:
                raise ValueError("stored scope paths must use canonical portable names")
            if not isinstance(digest, str) or not _HASH.fullmatch(digest):
                raise ValueError("scope content hashes must be SHA256 hex strings")
            files.append((name, digest))
        ordered = tuple(sorted(files))
        if value["tree_hash"] != _tree(repository_id, ordered):
            raise ValueError("scope tree hash mismatch")
        return cls(repository_id, ordered, value["tree_hash"])


def snapshot_scope(root: str | Path, paths: Sequence[str], *, repository_id: str) -> ScopeSnapshot:
    """Hash explicit code, test and configuration inputs without executing them."""
    repository_id = _repository(repository_id)
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("project root must be a directory")
    if (
        not isinstance(paths, Sequence)
        or isinstance(paths, (str, bytes))
        or not 1 <= len(paths) <= MAX_SCOPE_FILES
    ):
        raise ValueError("scope must be a bounded nonempty sequence of file paths")
    names = [scope_path(name) for name in paths]
    if len(set(names)) != len(names):
        raise ValueError("duplicate scope path")
    files = tuple((name, _digest(_file(root, name))) for name in sorted(names))
    return ScopeSnapshot(repository_id, files, _tree(repository_id, files))


@dataclass(frozen=True, slots=True)
class FreshnessReport:
    status: Literal["fresh", "stale", "unknown"]
    changed: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "changed": list(self.changed),
            "missing": list(self.missing),
            "unreadable": list(self.unreadable),
            "reason": self.reason,
        }


def check_freshness(
    snapshot: ScopeSnapshot, root: str | Path, *, repository_id: str
) -> FreshnessReport:
    """Compare current scoped bytes; unsafe/unreadable inputs can never be fresh."""
    # Validate even directly constructed objects rather than trusting Python callers.
    if len(snapshot.files) != len(dict(snapshot.files)):
        raise ValueError("duplicate scope path in snapshot")
    snapshot = ScopeSnapshot.from_dict(snapshot.to_dict())
    if _repository(repository_id) != snapshot.repository_id:
        return FreshnessReport("unknown", reason="repository_identity_mismatch")
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("project root must be a directory")
    changed: list[str] = []
    missing: list[str] = []
    unreadable: list[str] = []
    for name, expected in snapshot.files:
        try:
            actual = _digest(_file(root, name))
        except FileNotFoundError:
            missing.append(name)
        except (OSError, ValueError):
            unreadable.append(name)
        else:
            if actual != expected:
                changed.append(name)
    status: Literal["fresh", "stale", "unknown"] = (
        "unknown" if unreadable else "stale" if changed or missing else "fresh"
    )
    return FreshnessReport(status, tuple(changed), tuple(missing), tuple(unreadable))
