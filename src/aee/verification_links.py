"""Receipt-backed discovery and requirement links, without a second score layer.

Collection is an explicit authorized command. Ingestion never executes commands.
Directory membership is checked separately from declared-byte scope freshness.
Neither proves test adequacy, runtime environment immutability or CI identity.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from aee.execution_evidence import (
    ExecutionRecord,
    capture_execution,
    check_execution_applicability,
    report_bytes,
)
from aee.execution_scope import ScopeSnapshot, _file, scope_path, snapshot_scope
from aee.extract import duplicate_key_hook

MAX_DISCOVERY_ENTRIES = 10_000
MAX_DISCOVERY_BYTES = 8 * 1024 * 1024


def _names(values: object) -> list[str]:
    if (
        not isinstance(values, (list, tuple))
        or not 1 <= len(values) <= MAX_DISCOVERY_ENTRIES
        or any(not isinstance(v, str) or not v.strip() or len(v) > 8192 for v in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("identities must be bounded, nonempty and unique")
    return sorted(values)


def _policy(roots: object, suffixes: object) -> tuple[list[str], list[str]]:
    roots = _names(roots)
    if len(roots) > 32:
        raise ValueError("at most 32 managed roots are supported")
    if any(scope_path(name) != name for name in roots):
        raise ValueError("managed roots must be canonical relative directories")
    if any(a != b and b.startswith(a + "/") for a in roots for b in roots):
        raise ValueError("managed roots must not overlap")
    suffixes = _names(suffixes)
    if len(suffixes) > 32:
        raise ValueError("at most 32 suffixes are supported")
    if any(
        not suffix.startswith(".") or len(suffix) < 2 or any(c in suffix for c in "/\\:*?\x00")
        for suffix in suffixes
    ):
        raise ValueError("suffix policy must contain literal file suffixes")
    return roots, suffixes


def _members(root: Path, roots: Sequence[str], suffixes: Sequence[str]) -> list[str]:
    """Walk a bounded managed tree, refusing links and unreadable directories."""
    names = []
    count = 0

    def failed(error: OSError) -> None:
        raise error

    for name in roots:
        directory = _file(root, name)
        if not directory.is_dir():
            raise ValueError("managed test root must exist as a directory")
        for current, directories, files in os.walk(directory, onerror=failed, followlinks=False):
            for leaf in [*directories, *files]:
                count += 1
                if count > MAX_DISCOVERY_ENTRIES:
                    raise ValueError("managed directory entry limit exceeded")
                path = Path(current) / leaf
                if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                    raise ValueError("managed test trees cannot contain links/reparse points")
            for leaf in files:
                if any(leaf.endswith(suffix) for suffix in suffixes):
                    names.append((Path(current) / leaf).relative_to(root).as_posix())
    if not names:
        raise ValueError("managed test inventory is empty")
    return sorted(names)


@dataclass(frozen=True, slots=True)
class TestDiscovery:
    """Immutable collection transaction. Trust is supplied outside this record."""

    canonical: bytes

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TestDiscovery:
        if (
            not isinstance(value, Mapping)
            or set(value)
            != {
                "schema_version",
                "managed_roots",
                "suffixes",
                "members_before",
                "members_after",
                "membership_error",
                "report_path",
                "execution",
            }
            or value["schema_version"] != "1.0"
        ):
            raise ValueError("invalid discovery fields or version")
        roots, suffixes = _policy(value["managed_roots"], value["suffixes"])
        before = ScopeSnapshot.from_dict(value["members_before"])
        after = value["members_after"]
        error = value["membership_error"]
        if not isinstance(error, str) or len(error) > 256 or (after is None) != bool(error):
            raise ValueError("membership error must explain an unavailable post snapshot")
        record = ExecutionRecord.from_dict(value["execution"])
        for snapshot in [before, *([] if after is None else [ScopeSnapshot.from_dict(after)])]:
            if snapshot.repository_id != before.repository_id or any(
                not any(path.startswith(directory + "/") for directory in roots)
                or not any(path.endswith(suffix) for suffix in suffixes)
                for path, digest in snapshot.files
            ):
                raise ValueError("managed members must match the declared directory policy")
        name = scope_path(value["report_path"])
        if name != value["report_path"]:
            raise ValueError("discovery report path must be canonical")
        canonical = json.dumps(
            dict(
                value,
                managed_roots=roots,
                suffixes=suffixes,
                members_before=before.to_dict(),
                members_after=None if after is None else ScopeSnapshot.from_dict(after).to_dict(),
                execution=record.to_dict(),
            ),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
        if len(canonical) > MAX_DISCOVERY_BYTES:
            raise ValueError("discovery record too large")
        return cls(canonical)

    @classmethod
    def from_bytes(cls, data: bytes) -> TestDiscovery:
        if not isinstance(data, bytes) or len(data) > MAX_DISCOVERY_BYTES:
            raise ValueError("discovery input must be bounded bytes")
        return cls.from_dict(
            json.loads(data.decode("utf-8"), object_pairs_hook=duplicate_key_hook("test discovery"))
        )

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.canonical))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical).hexdigest()


def capture_test_discovery(
    argv: Sequence[str],
    root: str | Path,
    *,
    repository_id: str,
    managed_roots: Sequence[str],
    suffixes: Sequence[str],
    paths: Sequence[str],
    requirement_ids: Sequence[str],
    report_path: str,
    timeout: float = 600,
) -> TestDiscovery:
    """Explicitly collect a project inventory with pre/post membership receipts.

    The caller chooses the collection command and literal source suffix policy.
    The command writes a new JSON report: schema_version1.0 and tests[{id,path}].
    It must actually discover tests; an agent-authored manifest has no authority.
    Caller trust/isolation policy must authenticate this collection transaction.
    """
    roots, suffixes = _policy(managed_roots, suffixes)
    if not isinstance(paths, (list, tuple)):
        raise ValueError("additional scope must be an explicit path sequence")
    paths = [scope_path(name) for name in paths]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate additional scope path")
    root = Path(root).resolve(strict=True)
    before = snapshot_scope(root, _members(root, roots, suffixes), repository_id=repository_id)
    record = capture_execution(
        argv,
        root,
        sorted(set(paths) | dict(before.files).keys()),
        repository_id=repository_id,
        requirement_ids=requirement_ids,
        report_paths=[report_path],
        timeout=timeout,
    )
    error = ""
    try:
        after = snapshot_scope(root, _members(root, roots, suffixes), repository_id=repository_id)
        # New files have no pre-execution byte receipt, so retain the mismatch as
        # an unavailable post snapshot rather than legitimizing new inventory.
        if after != before:
            raise ValueError("managed test inputs changed during collection")
        post = after.to_dict()
    except (OSError, ValueError) as exc:
        post = None
        error = type(exc).__name__
    return TestDiscovery.from_dict(
        dict(
            schema_version="1.0",
            managed_roots=roots,
            suffixes=suffixes,
            members_before=before.to_dict(),
            members_after=post,
            membership_error=error,
            report_path=scope_path(report_path),
            execution=record.to_dict(),
        )
    )


def verify_test_discovery(
    discovery: TestDiscovery,
    root: str | Path,
    *,
    repository_id: str,
    trusted_discovery_digests: Collection[str] = (),
) -> dict[str, Any]:
    """Revalidate receipt, command, membership and bytes without running anything."""
    discovery = TestDiscovery.from_bytes(discovery.canonical)
    value = discovery.to_dict()
    record = ExecutionRecord.from_dict(value["execution"])
    # Reuse the strict external digest-policy validator, pinning the transaction
    # (not only its inner command record, which would omit membership policy).
    check_execution_applicability(
        record, root, repository_id=repository_id, trusted_record_digests=trusted_discovery_digests
    )
    trusted = discovery.digest in trusted_discovery_digests
    result = check_execution_applicability(
        record,
        root,
        repository_id=repository_id,
        trusted_record_digests=[record.digest] if trusted else [],
    )
    result.update(
        discovery_sha256=discovery.digest, outcome="gather_evidence", tests=[], findings=[]
    )
    if not trusted:
        result["findings"].append("collection_producer_unverified")
    if result["execution_status"] != "succeeded" or result["freshness"] != "fresh":
        result["findings"].append("collection_execution_not_applicable")
    try:
        current = snapshot_scope(
            Path(root).resolve(strict=True),
            _members(Path(root).resolve(strict=True), value["managed_roots"], value["suffixes"]),
            repository_id=repository_id,
        )
        if value["members_after"] is None or current.to_dict() != value["members_before"]:
            raise ValueError("membership/bytes changed or unavailable")
        for field, scoped in [("members_before", "scope_before"), ("members_after", "scope_after")]:
            captured = record.to_dict()[scoped]
            if (
                captured is None
                or captured["repository_id"] != repository_id
                or any(
                    captured["files"].get(path) != digest
                    for path, digest in value[field]["files"].items()
                )
            ):
                raise ValueError("membership differs from actual collection scope")
        name = value["report_path"]
        data = report_bytes(root, name)
        receipt = next((r for r in record.to_dict()["reports"] if r["path"] == name), None)
        if (
            receipt is None
            or receipt["error"]
            or receipt["sha256"] != hashlib.sha256(data).hexdigest()
            or receipt["byte_count"] != len(data)
        ):
            raise ValueError("discovery receipt missing or changed")
        report = json.loads(
            data.decode("utf-8"), object_pairs_hook=duplicate_key_hook("test inventory")
        )
        if (
            not isinstance(report, dict)
            or set(report) != {"schema_version", "tests"}
            or report["schema_version"] != "1.0"
        ):
            raise ValueError("unsupported collection report")
        tests = report["tests"]
        if not isinstance(tests, list) or not 1 <= len(tests) <= MAX_DISCOVERY_ENTRIES:
            raise ValueError("empty or oversized collection")
        ids = []
        for test in tests:
            if not isinstance(test, dict) or set(test) != {"id", "path"}:
                raise ValueError("invalid collected identity")
            ids.append(test["id"])
            if scope_path(test["path"]) != test["path"] or test["path"] not in dict(current.files):
                raise ValueError("collected source outside managed inventory")
        _names(ids)
        result["tests"] = tests
    except (OSError, ValueError, RecursionError) as exc:
        result["findings"].append("collection_inventory_unverifiable")
        result["inventory_error"] = type(exc).__name__ + ":" + str(exc)[:512]
    if not result["findings"]:
        result["outcome"] = "pass"
    return result


def check_verification_links(
    discovery: TestDiscovery,
    root: str | Path,
    *,
    repository_id: str,
    accepted_requirement_ids: Sequence[str],
    links: Mapping[str, Sequence[str]],
    trusted_discovery_digests: Collection[str] = (),
) -> dict[str, Any]:
    """Check many-to-many requirement links against actual collected identities.

    Shared tests are allowed; every managed test must be linked. This initial
    test-only route cannot grant a human verification exemption from a name or
    checkbox. Approved non-test methods require a separate trusted policy.
    """
    requirements = _names(accepted_requirement_ids)
    if not isinstance(links, Mapping):
        raise ValueError("links must be a requirement-to-test mapping")
    if any(not isinstance(tests, (list, tuple)) for tests in links.values()):
        raise ValueError("linked tests must be explicit identity sequences")
    if links:
        _names(list(links))
    checked = {key: _names(tests) for key, tests in links.items()}
    result = verify_test_discovery(
        discovery,
        root,
        repository_id=repository_id,
        trusted_discovery_digests=trusted_discovery_digests,
    )
    result["scope"] = (
        "Requirement/test link integrity only; not test execution, verification adequacy "
        "or acceptance of requirements."
    )
    actual = {test["id"] for test in result["tests"]}
    linked = {test for tests in checked.values() for test in tests}
    result.update(
        missing_requirements=sorted(set(requirements) - set(checked)),
        unknown_requirements=sorted(set(checked) - set(requirements)),
        broken_test_ids=sorted(linked - actual),
        orphan_test_ids=sorted(actual - linked),
    )
    for key in (
        "missing_requirements",
        "unknown_requirements",
        "broken_test_ids",
        "orphan_test_ids",
    ):
        if result[key]:
            result["findings"].append(key)
    if result["findings"]:
        result["outcome"] = "gather_evidence"
    return result
