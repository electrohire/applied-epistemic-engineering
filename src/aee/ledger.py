"""Append-only, tamper-evident JSONL ledger for epistemic state transitions."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    fcntl = None
else:
    try:
        import fcntl
    except ImportError:  # a non-POSIX Python without fcntl
        fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # non-Windows
    msvcrt = None  # type: ignore[assignment]

GENESIS_HASH = "0" * 64
LEDGER_VERSION = "1.0"
ANCHOR_VERSION = "1.0"

VERIFY_SEMANTICS = (
    "valid means the hash chain is internally self-consistent; completeness is "
    "established only when anchor_status is 'verified' or explicit expected "
    "tip/count assertions pass. Verification does not prove actor identity, "
    "event truth, or a trusted timestamp."
)

# Spec 002 FR-8.1: the documented default assessment-ledger location,
# relative to the project root. The spec-kit-aee runner already ledgers
# to exactly this path by default; the bare engine CLI adopts the same
# default so the two entry points converge (FR-8a ledger parity).
DEFAULT_LEDGER_PATH = Path(".specify/extensions/aee/ledger/epistemic-ledger.jsonl")

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ENTRY_FIELDS = {
    "ledger_version",
    "sequence",
    "timestamp",
    "event_type",
    "actor",
    "previous_hash",
    "payload",
    "entry_hash",
}
_ANCHOR_FIELDS = {"anchor_version", "entry_count", "tip_hash", "ledger_name"}
_FULL_CONTENT_CACHE_LIMIT = 1_048_576
_TIP_CACHE_WINDOW = 65_536


@dataclass(frozen=True, slots=True)
class LedgerAnchor:
    """A portable commitment to one ledger head.

    The anchor deliberately contains only the two values needed to make
    tail truncation detectable by a consumer who retained them:
    ``entry_count`` and ``tip_hash``.  ``ledger_name`` binds the default
    sidecar to its ledger's filename without making the commitment depend
    on a machine-specific absolute path.
    """

    entry_count: int
    tip_hash: str
    anchor_version: str = ANCHOR_VERSION
    ledger_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "anchor_version": self.anchor_version,
            "entry_count": self.entry_count,
            "tip_hash": self.tip_hash,
        }
        if self.ledger_name is not None:
            value["ledger_name"] = self.ledger_name
        return value

    @classmethod
    def from_dict(cls, value: Any) -> LedgerAnchor:
        anchor, errors = _validate_anchor_mapping(value)
        if anchor is None:
            raise ValueError("invalid ledger anchor: " + "; ".join(errors))
        return anchor


@dataclass(frozen=True, slots=True)
class LedgerVerification:
    valid: bool
    entries: int
    errors: tuple[str, ...] = ()
    head_hash: str = GENESIS_HASH
    chain_valid: bool | None = None
    anchor_status: str = "not_checked"
    anchor_entries: int | None = None
    anchor_head_hash: str | None = None
    anchor_path: str | None = None
    anchored: bool = False
    semantics: str = VERIFY_SEMANTICS

    def __post_init__(self) -> None:
        if self.chain_valid is None:
            object.__setattr__(self, "chain_valid", self.valid)

    @property
    def anchor_valid(self) -> bool | None:
        """True only for a matching anchor; None when no anchor verdict exists."""
        if self.anchor_status == "verified":
            return True
        if self.anchor_status in {"mismatch", "invalid"}:
            return False
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "chain_valid": bool(self.chain_valid),
            "entries": self.entries,
            "head_hash": self.head_hash,
            "errors": list(self.errors),
            "anchor_status": self.anchor_status,
            "anchor_entries": self.anchor_entries,
            "anchor_head_hash": self.anchor_head_hash,
            "anchor_path": self.anchor_path,
            "anchored": self.anchored,
            "semantics": self.semantics,
        }


class HashChainLedger:
    """Canonical SHA-256 chain with a local head anchor.

    The chain detects mutation, deletion in the middle, reordering, and
    insertion. A sidecar anchor at ``<ledger>.anchor.json`` is updated on
    every append and commits the resulting entry count and tip hash, so
    deleting the newest entries no longer verifies against that anchor.

    OD-3 remains formally open. This sidecar is the local anchor required
    by Spec 003 FR-4.1; pulling Spec 002 FR-8b's Axiomere anchoring
    forward remains the stronger external-anchor option. A consumer who
    needs truncation evidence against someone able to rewrite both local
    files must retain the anchor values elsewhere (``verify-ledger``
    therefore also accepts explicit expected tip/count assertions).

    Verification is deliberately strict: every physical line must be one
    complete, correctly shaped ledger entry. Malformed content is never
    skipped by ``verify`` or ``entries``.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        # Verified-tip fast path. The legacy (size, mtime_ns) pair is
        # retained only as a cheap pre-check; it is never sufficient for
        # a cache hit. A hit additionally requires the content
        # fingerprint defined in _fingerprint_for_bytes/_current_fingerprint:
        # a SHA-256 of the whole file up to the size bound, and of the
        # tip line beyond it (Spec 003 FR-4.2). Any content change —
        # including a same-size, same-mtime forgery — changes the
        # fingerprint and forces a full verify() before appending.
        self._tip: tuple[int, str] | None = None
        self._tip_stat: tuple[int, int] | None = None
        self._tip_fingerprint: tuple[int, int, str, str] | None = None
        self._tip_anchor_fingerprint: tuple[int, int, str] | None = None
        self._tip_anchor_path: str | None = None

    @property
    def anchor_path(self) -> Path:
        """Default sidecar anchor path: ``<ledger>.anchor.json``."""
        return self.path.with_name(self.path.name + ".anchor.json")

    def _resolve_anchor_path(self, anchor_path: str | Path | None) -> Path:
        return Path(anchor_path) if anchor_path is not None else self.anchor_path

    def _stat_key(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_size, stat.st_mtime_ns)

    @staticmethod
    def _fingerprint_for_bytes(data: bytes, stat_key: tuple[int, int]) -> tuple[int, int, str, str]:
        size, mtime_ns = stat_key
        if size <= _FULL_CONTENT_CACHE_LIMIT:
            return (size, mtime_ns, "full", hashlib.sha256(data).hexdigest())
        lines = data.split(b"\n")
        if lines and lines[-1] == b"":
            lines.pop()
        tip_line = lines[-1] if lines else b""
        if len(tip_line) <= _TIP_CACHE_WINDOW:
            material = tip_line
        else:
            half = _TIP_CACHE_WINDOW // 2
            material = tip_line[:half] + tip_line[-half:]
        return (size, mtime_ns, "tip", hashlib.sha256(material).hexdigest())

    def _current_fingerprint(self) -> tuple[int, int, str, str] | None:
        stat_key = self._stat_key()
        if stat_key is None:
            return None
        size, mtime_ns = stat_key
        if size <= _FULL_CONTENT_CACHE_LIMIT:
            return self._fingerprint_for_bytes(self.path.read_bytes(), stat_key)
        with self.path.open("rb") as handle:
            handle.seek(max(0, size - _TIP_CACHE_WINDOW))
            tail = handle.read()
        segment = tail.rsplit(b"\n", 1)[-1]
        return (size, mtime_ns, "tip", hashlib.sha256(segment).hexdigest())

    def _anchor_fingerprint(self, anchor_path: Path) -> tuple[int, int, str] | None:
        try:
            stat = anchor_path.stat()
            data = anchor_path.read_bytes()
        except FileNotFoundError:
            return None
        return (stat.st_size, stat.st_mtime_ns, hashlib.sha256(data).hexdigest())

    @contextmanager
    def _append_lock(self):  # type: ignore[no-untyped-def]
        """Exclusive advisory lock around verify+append.

        Without it, two concurrent appends can both verify the same
        head and fork the chain (each writing sequence N+1 against
        the same previous_hash). The lock file sits beside the ledger
        and is held only for the append itself. Uses fcntl on POSIX
        and msvcrt byte-range locking on Windows; where neither
        exists the append proceeds unlocked.
        """
        if fcntl is None and msvcrt is None:
            yield
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            else:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write("\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        actor: str = "aee",
        anchor_path: str | Path | None = None,
        allow_duplicate: bool = False,
    ) -> dict[str, Any]:
        with self._append_lock():
            return self._append_locked(
                event_type,
                payload,
                actor=actor,
                anchor_path=anchor_path,
                allow_duplicate=allow_duplicate,
            )

    def _append_locked(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        actor: str = "aee",
        anchor_path: str | Path | None = None,
        assessment_digest: str | None = None,
        allow_duplicate: bool = False,
    ) -> dict[str, Any]:
        resolved_anchor = self._resolve_anchor_path(anchor_path)
        if resolved_anchor == self.path:
            raise ValueError("ledger anchor path must differ from the ledger path")
        anchor, anchor_errors, anchor_fingerprint = self._read_anchor(resolved_anchor)
        if anchor_errors:
            raise ValueError(
                "refusing to append to a ledger with an invalid anchor: " + "; ".join(anchor_errors)
            )

        ledger_fingerprint = self._current_fingerprint()
        cache_hit = (
            self._tip is not None
            and ledger_fingerprint is not None
            and ledger_fingerprint == self._tip_fingerprint
            and anchor_fingerprint == self._tip_anchor_fingerprint
            and str(resolved_anchor) == self._tip_anchor_path
            and (anchor is None or (anchor.entry_count, anchor.tip_hash) == self._tip)
        )
        if cache_hit:
            assert self._tip is not None
            entries, head_hash = self._tip
        else:
            verification = (
                self.verify() if anchor_path is None else self.verify(anchor_path=resolved_anchor)
            )
            if not verification.valid:
                raise ValueError(
                    "refusing to append to an invalid ledger: " + "; ".join(verification.errors)
                )
            entries, head_hash = verification.entries, verification.head_hash

        effective_payload = payload
        recorded_digest = assessment_digest
        if recorded_digest is None and event_type == "assessment":
            candidate = payload.get("assessment_sha256")
            recorded_digest = candidate if isinstance(candidate, str) else None
        if recorded_digest is not None:
            duplicate_sequence = self._find_assessment(recorded_digest, actor)
            if duplicate_sequence is not None:
                if not allow_duplicate:
                    raise ValueError(
                        f"duplicate assessment {recorded_digest} already recorded "
                        f"at sequence {duplicate_sequence} by actor {actor!r}; "
                        "pass allow_duplicate=True to append it again"
                    )
                effective_payload = dict(payload)
                effective_payload["duplicate_of_sequence"] = duplicate_sequence

        entry: dict[str, Any] = {
            "ledger_version": LEDGER_VERSION,
            "sequence": entries + 1,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "event_type": event_type,
            "actor": actor,
            "previous_hash": head_hash,
            "payload": effective_payload,
        }
        entry["entry_hash"] = _entry_hash(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical(entry) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            self._write_anchor_for(entries + 1, str(entry["entry_hash"]), resolved_anchor)
        except Exception:
            # The ledger advanced but its anchor did not; never let a
            # later append trust a tip/anchor pair we know is stale.
            self._tip = None
            self._tip_stat = None
            self._tip_fingerprint = None
            self._tip_anchor_fingerprint = None
            self._tip_anchor_path = None
            raise
        self._remember_tip(entries + 1, str(entry["entry_hash"]), resolved_anchor)
        return entry

    def _find_assessment(self, digest: str, actor: str) -> int | None:
        for entry in self.entries():
            payload = entry.get("payload")
            if (
                entry.get("event_type") == "assessment"
                and entry.get("actor") == actor
                and isinstance(payload, dict)
                and payload.get("assessment_sha256") == digest
            ):
                sequence = entry.get("sequence")
                return sequence if isinstance(sequence, int) else None
        return None

    def _remember_tip(self, entries: int, head_hash: str, anchor_path: Path) -> None:
        self._tip = (entries, head_hash)
        fingerprint = self._current_fingerprint()
        self._tip_fingerprint = fingerprint
        self._tip_stat = (fingerprint[0], fingerprint[1]) if fingerprint else None
        self._tip_anchor_fingerprint = self._anchor_fingerprint(anchor_path)
        self._tip_anchor_path = str(anchor_path)

    def append_assessment(
        self,
        assessment: Any,
        *,
        actor: str = "aee",
        allow_duplicate: bool = False,
        anchor_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Append an assessment, refusing an exact duplicate by default.

        Spec 003 FR-4.6: the same assessment hash recorded by the same
        actor is reported as a duplicate instead of silently chaining a
        second time. ``allow_duplicate=True`` is the explicit opt-in; the
        repeated entry then names the original in
        ``payload.duplicate_of_sequence``.
        """
        value = assessment.to_dict()
        # FR-5.8: the recorded digest is over the assessment CONTENT
        # (created_at excluded — see assessment_content_digest); the
        # run's wall-clock stamp is recorded separately alongside it.
        digest = assessment_content_digest(value)
        payload = {
            "project": value["project"],
            "phase": value["phase"],
            "outcome": value["outcome"],
            "claim_ids": [claim["id"] for claim in value["claims"]],
            "assessment_sha256": digest,
            "assessment_created_at": value.get("created_at"),
        }
        with self._append_lock():
            return self._append_locked(
                "assessment",
                payload,
                actor=actor,
                anchor_path=anchor_path,
                assessment_digest=digest,
                allow_duplicate=allow_duplicate,
            )

    def write_anchor(self, anchor_path: str | Path | None = None) -> LedgerAnchor:
        """Verify the chain and (re)write the sidecar anchor for its head.

        This is the migration/repair path for a pre-FR-4 ledger: the
        existing chain must verify on its own merits before any anchor
        is minted for it. The resulting anchor state is reported as
        ``unverifiable-anchor`` by plain ``verify()`` until this method
        (or the next append) creates the sidecar.
        """
        resolved_anchor = self._resolve_anchor_path(anchor_path)
        if resolved_anchor == self.path:
            raise ValueError("ledger anchor path must differ from the ledger path")
        verification = self._verify_impl(check_anchor=False)
        if not verification.valid:
            raise ValueError(
                "refusing to anchor an invalid ledger: " + "; ".join(verification.errors)
            )
        anchor = self._write_anchor_for(
            verification.entries, verification.head_hash, resolved_anchor
        )
        self._remember_tip(verification.entries, verification.head_hash, resolved_anchor)
        return anchor

    def _write_anchor_for(self, entries: int, head_hash: str, anchor_path: Path) -> LedgerAnchor:
        anchor = LedgerAnchor(
            entry_count=entries,
            tip_hash=head_hash,
            ledger_name=self.path.name,
        )
        content = (
            json.dumps(
                anchor.to_dict(),
                sort_keys=True,
                indent=2,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        )
        anchor_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=anchor_path.parent,
            prefix=anchor_path.name + ".",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, anchor_path)
            _fsync_directory(anchor_path.parent)
        finally:
            if temporary.exists():
                temporary.unlink()
        return anchor

    def _read_anchor(
        self, anchor_path: Path
    ) -> tuple[LedgerAnchor | None, tuple[str, ...], tuple[int, int, str] | None]:
        try:
            data = anchor_path.read_bytes()
        except FileNotFoundError:
            return None, (), None
        except OSError as exc:
            return None, (f"anchor: cannot read {anchor_path}: {exc}",), None
        stat = anchor_path.stat()
        fingerprint = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(data).hexdigest(),
        )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            return None, (f"anchor: invalid UTF-8 ({exc.reason})",), fingerprint
        value, parse_error = _parse_json_strict(text)
        if parse_error is not None:
            return None, (f"anchor: invalid JSON ({parse_error})",), fingerprint
        anchor, errors = _validate_anchor_mapping(value, self.path.name)
        if errors:
            return None, tuple(f"anchor: {error}" for error in errors), fingerprint
        return anchor, (), fingerprint

    def verify(
        self,
        *,
        expected_tip_hash: str | None = None,
        expected_entry_count: int | None = None,
        require_anchor: bool = False,
        anchor_path: str | Path | None = None,
    ) -> LedgerVerification:
        """Strictly verify the chain and, when present, its head anchor.

        A pre-FR-4 ledger without a sidecar still verifies as a chain:
        ``valid`` reflects the chain (plus any explicit assertions), and
        ``anchor_status`` reports ``unverifiable-anchor`` instead of
        silently claiming anchored completeness. Pass
        ``require_anchor=True`` — as ``aee gate`` does — to make the
        absence or mismatch of an anchor a verification failure.
        """
        update_cache = (
            expected_tip_hash is None and expected_entry_count is None and anchor_path is None
        )
        return self._verify_impl(
            expected_tip_hash=expected_tip_hash,
            expected_entry_count=expected_entry_count,
            require_anchor=require_anchor,
            anchor_path=anchor_path,
            check_anchor=True,
            update_cache=update_cache,
        )

    def _verify_impl(
        self,
        *,
        expected_tip_hash: str | None = None,
        expected_entry_count: int | None = None,
        require_anchor: bool = False,
        anchor_path: str | Path | None = None,
        check_anchor: bool = True,
        update_cache: bool = False,
    ) -> LedgerVerification:
        resolved_anchor = self._resolve_anchor_path(anchor_path)
        exists = self.path.exists()
        data = self.path.read_bytes() if exists else b""
        raw_lines = _physical_lines(data) if exists else []

        errors: list[str] = []
        previous = GENESIS_HASH
        entries = 0
        for line_number, raw in enumerate(raw_lines, 1):
            entry, line_errors = _parse_entry_line(raw, line_number)
            errors.extend(line_errors)
            if entry is None:
                continue
            entries += 1
            sequence = entry.get("sequence")
            if (
                isinstance(sequence, int)
                and not isinstance(sequence, bool)
                and sequence != line_number
            ):
                errors.append(f"line {line_number}: expected sequence {line_number}")
            if "previous_hash" in entry and entry.get("previous_hash") != previous:
                errors.append(f"line {line_number}: previous_hash mismatch")
            actual = entry.get("entry_hash")
            if isinstance(actual, str) and not _contains_nonfinite(entry):
                try:
                    expected = _entry_hash(entry)
                except ValueError as exc:
                    errors.append(f"line {line_number}: cannot hash entry ({exc})")
                else:
                    if actual != expected:
                        errors.append(f"line {line_number}: entry_hash mismatch")
            if isinstance(actual, str):
                previous = actual
        head_hash = previous if entries else GENESIS_HASH
        chain_valid = not errors

        anchor_status = "not_checked"
        anchor_entries: int | None = None
        anchor_head_hash: str | None = None
        anchor_fingerprint: tuple[int, int, str] | None = None
        if check_anchor:
            anchor, anchor_errors, anchor_fingerprint = self._read_anchor(resolved_anchor)
            errors.extend(anchor_errors)
            if anchor_errors:
                anchor_status = "invalid"
            elif anchor is not None:
                anchor_entries = anchor.entry_count
                anchor_head_hash = anchor.tip_hash
                mismatches: list[str] = []
                if anchor.entry_count > entries:
                    mismatches.append(
                        f"anchor entry_count {anchor.entry_count} exceeds ledger "
                        f"entries {entries} (tail truncation or a stale anchor)"
                    )
                elif anchor.entry_count < entries:
                    mismatches.append(
                        f"anchor entry_count {anchor.entry_count} is behind ledger "
                        f"entries {entries} (append without an anchor update)"
                    )
                if anchor.tip_hash != head_hash:
                    mismatches.append(
                        f"anchor tip_hash {anchor.tip_hash} does not match ledger head {head_hash}"
                    )
                if mismatches:
                    errors.extend(f"anchor: {item}" for item in mismatches)
                    anchor_status = "mismatch"
                else:
                    anchor_status = "verified"
            else:
                anchor_status = "unverifiable-anchor" if entries else "absent"

        if expected_entry_count is not None:
            if (
                isinstance(expected_entry_count, bool)
                or not isinstance(expected_entry_count, int)
                or expected_entry_count < 0
            ):
                errors.append("expected entry count must be a non-negative integer")
            elif expected_entry_count != entries:
                errors.append(f"expected {expected_entry_count} ledger entries, found {entries}")
        if expected_tip_hash is not None:
            if not isinstance(expected_tip_hash, str) or not _HASH_RE.match(expected_tip_hash):
                errors.append("expected tip hash must be a 64-character hex SHA-256")
            elif expected_tip_hash != head_hash:
                errors.append(f"expected ledger tip {expected_tip_hash}, found {head_hash}")
        if require_anchor and anchor_status != "verified":
            errors.append(
                f"anchor required but anchor status is {anchor_status!r} for {resolved_anchor}"
            )

        result = LedgerVerification(
            valid=not errors,
            entries=entries,
            errors=tuple(errors),
            head_hash=head_hash,
            chain_valid=chain_valid,
            anchor_status=anchor_status,
            anchor_entries=anchor_entries,
            anchor_head_hash=anchor_head_hash,
            anchor_path=str(resolved_anchor),
            anchored=anchor_status == "verified",
        )
        if (
            update_cache
            and chain_valid
            and anchor_status in {"verified", "unverifiable-anchor", "absent"}
        ):
            stat_key = self._stat_key()
            self._tip = (entries, head_hash)
            self._tip_fingerprint = (
                self._fingerprint_for_bytes(data, stat_key) if stat_key else None
            )
            self._tip_stat = stat_key
            self._tip_anchor_fingerprint = anchor_fingerprint
            self._tip_anchor_path = str(resolved_anchor)
        return result

    def entries(self) -> Iterable[dict[str, Any]]:
        """Return the ledger's entries under the same line rules as verify().

        Every physical line must decode as one correctly shaped entry;
        corruption raises a ``ValueError`` naming the line instead of
        being skipped, returned, or surfaced as a bare decode error.
        """
        if not self.path.exists():
            return ()
        parsed: list[dict[str, Any]] = []
        for line_number, raw in enumerate(_physical_lines(self.path.read_bytes()), 1):
            entry, errors = _parse_entry_line(raw, line_number)
            if errors or entry is None:
                detail = "; ".join(errors) if errors else "not a ledger entry"
                raise ValueError(f"corrupt ledger line {line_number} in {self.path}: {detail}")
            sequence = entry.get("sequence")
            if sequence != line_number:
                raise ValueError(
                    f"corrupt ledger line {line_number} in {self.path}: "
                    f"expected sequence {line_number}, found {sequence!r}"
                )
            parsed.append(entry)
        return tuple(parsed)


def _physical_lines(data: bytes) -> list[bytes]:
    """Split ledger bytes on LF only.

    ``str.splitlines()`` also splits on U+2028/U+2029/U+0085 and other
    Unicode boundaries, which is how the pre-FR-4 reader disagreed with
    the file's actual lines. A ledger line is exactly one LF-terminated
    record; the empty segment after a final LF is not a line.
    """
    if not data:
        return []
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    return lines


def _parse_entry_line(raw: bytes, line_number: int) -> tuple[dict[str, Any] | None, list[str]]:
    if not raw.strip():
        return None, [f"line {line_number}: blank line is not a ledger entry"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, [f"line {line_number}: invalid UTF-8 ({exc.reason})"]
    value, parse_error = _parse_json_strict(text)
    if parse_error is not None:
        return None, [f"line {line_number}: invalid JSON ({parse_error})"]
    if not isinstance(value, dict):
        return None, [f"line {line_number}: expected a JSON object, got {_json_type(value)}"]
    return value, _validate_entry_shape(value, line_number)


def _validate_entry_shape(entry: dict[str, Any], line_number: int) -> list[str]:
    errors: list[str] = []
    prefix = f"line {line_number}: "
    missing = sorted(_ENTRY_FIELDS - entry.keys())
    if missing:
        errors.append(prefix + "missing field(s): " + ", ".join(missing))
    unexpected = sorted(entry.keys() - _ENTRY_FIELDS)
    if unexpected:
        errors.append(prefix + "unexpected field(s): " + ", ".join(unexpected))

    if "ledger_version" in entry and entry["ledger_version"] != LEDGER_VERSION:
        errors.append(
            prefix + f"ledger_version must be {LEDGER_VERSION!r}, found {entry['ledger_version']!r}"
        )
    if "sequence" in entry:
        sequence = entry["sequence"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            errors.append(prefix + f"sequence must be a positive integer, found {sequence!r}")
    if "timestamp" in entry:
        timestamp = entry["timestamp"]
        if not isinstance(timestamp, str) or not timestamp.strip():
            errors.append(prefix + "timestamp must be a non-empty string")
        elif not _timestamp_parseable(timestamp):
            errors.append(prefix + f"timestamp is not parseable: {timestamp!r}")
    for field in ("event_type", "actor"):
        if field in entry:
            value = entry[field]
            if not isinstance(value, str) or not value.strip():
                errors.append(prefix + f"{field} must be a non-empty string")
    for field in ("previous_hash", "entry_hash"):
        if field in entry:
            value = entry[field]
            if not isinstance(value, str) or not _HASH_RE.match(value):
                errors.append(prefix + f"{field} must be a 64-character hex SHA-256")
    if "payload" in entry and not isinstance(entry["payload"], dict):
        errors.append(prefix + f"payload must be a JSON object, got {_json_type(entry['payload'])}")
    nonfinite_path = _find_nonfinite(entry)
    if nonfinite_path is not None:
        errors.append(prefix + f"non-finite number at {nonfinite_path}")
    return errors


def _timestamp_parseable(value: str) -> bool:
    if "T" not in value and " " not in value:
        return False
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return True


def _validate_anchor_mapping(
    value: Any, ledger_name: str | None = None
) -> tuple[LedgerAnchor | None, list[str]]:
    if not isinstance(value, dict):
        return None, [f"expected a JSON object, got {_json_type(value)}"]
    errors: list[str] = []
    missing = sorted({"anchor_version", "entry_count", "tip_hash"} - value.keys())
    if missing:
        errors.append("missing field(s): " + ", ".join(missing))
    unexpected = sorted(value.keys() - _ANCHOR_FIELDS)
    if unexpected:
        errors.append("unexpected field(s): " + ", ".join(unexpected))
    if "anchor_version" in value and value["anchor_version"] != ANCHOR_VERSION:
        errors.append(
            f"anchor_version must be {ANCHOR_VERSION!r}, found {value['anchor_version']!r}"
        )
    entry_count = value.get("entry_count")
    if "entry_count" in value and (
        isinstance(entry_count, bool) or not isinstance(entry_count, int) or entry_count < 0
    ):
        errors.append(f"entry_count must be a non-negative integer, found {entry_count!r}")
    tip_hash = value.get("tip_hash")
    if "tip_hash" in value and (not isinstance(tip_hash, str) or not _HASH_RE.match(tip_hash)):
        errors.append("tip_hash must be a 64-character hex SHA-256")
    if (
        isinstance(entry_count, int)
        and entry_count == 0
        and isinstance(tip_hash, str)
        and tip_hash != GENESIS_HASH
    ):
        errors.append("an anchor for zero entries must commit the genesis tip hash")
    name = value.get("ledger_name")
    if "ledger_name" in value:
        if not isinstance(name, str) or not name:
            errors.append("ledger_name must be a non-empty string")
        elif ledger_name is not None and name != ledger_name:
            errors.append(f"ledger_name {name!r} does not match ledger file {ledger_name!r}")
    if errors:
        return None, errors
    return (
        LedgerAnchor(
            entry_count=int(value["entry_count"]),
            tip_hash=str(value["tip_hash"]),
            anchor_version=str(value["anchor_version"]),
            ledger_name=name if isinstance(name, str) else None,
        ),
        [],
    )


def _parse_json_strict(text: str) -> tuple[Any, str | None]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = item
        return result

    def reject_constant(name: str) -> Any:
        raise ValueError(f"non-finite number {name!r} is not allowed")

    try:
        return (
            json.loads(
                text,
                object_pairs_hook=object_pairs,
                parse_constant=reject_constant,
            ),
            None,
        )
    except json.JSONDecodeError as exc:
        return None, exc.msg
    except ValueError as exc:
        return None, str(exc)


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _find_nonfinite(value: Any, path: str = "$") -> str | None:
    if isinstance(value, float):
        return None if math.isfinite(value) else path
    if isinstance(value, dict):
        for key, item in value.items():
            found = _find_nonfinite(item, f"{path}.{key}")
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _find_nonfinite(item, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _contains_nonfinite(value: Any) -> bool:
    return _find_nonfinite(value) is not None


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _canonical(value: Any) -> str:
    # allow_nan=False (Spec 003 FR-5.5): a non-finite payload value
    # raises instead of writing a bare NaN/Infinity token strict
    # parsers reject. Finite values serialise byte-identically, so
    # existing entry hashes are unaffected.
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    # Escape exactly the characters Python's line splitting treats as
    # boundaries beyond LF. Other Unicode stays raw, preserving the
    # canonical bytes (and therefore entry hashes) of existing ledgers;
    # the escaped forms parse back to the same strings, so writer and
    # reader now agree on what one line is (Spec 003 FR-4.4).
    return (
        raw.replace("\u0085", "\\u0085").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    )


def _entry_hash(entry: dict[str, Any]) -> str:
    material = {key: value for key, value in entry.items() if key != "entry_hash"}
    return hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()


def assessment_content_digest(value: dict[str, Any]) -> str:
    """SHA-256 of an assessment's CONTENT (Spec 003 FR-5.8, RT2-M12).

    The digest is computed over the assessment dict with the
    wall-clock ``created_at`` stamp EXCLUDED: the stamp records when
    this particular run happened, not what was assessed, and while
    it was included, replaying identical input produced a different
    digest on every run — the hash was not a function of the input.
    ``created_at`` is not lost: ``append_assessment`` records it in
    the ledger payload as ``assessment_created_at``, separately from
    the digest. Identical input replayed (same bundle, same pinned
    scoring clock — see the CLI's ``--as-of``) now yields an
    identical digest, which is also what makes FR-4.6's duplicate
    refusal able to recognise a replay. The gate's ledger leg uses
    this same function, so writer and checker can never drift.
    """
    material = {key: item for key, item in value.items() if key != "created_at"}
    return hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()
