"""Verified writes for records that matter (fleet standard, 2026-10-28).

This VM intermittently refuses writes (EPERM waves) and sometimes
lands silent 0-byte or partial writes; a process that has spawned a
connector helper can lose write access for the rest of its life (see
~/workspace/system/safe-write/README.md and the VERIFIED WRITES entry
in ~/AGENTS.md). A bare ``write_text`` / ``open(..., "w")`` can
therefore "succeed" while the file on disk is empty or torn — for an
epistemic ledger, an assessment, or a session state file, that is an
integrity failure, not a nuisance.

This module vendors the shared utility's contract into the package so
the engine stays self-contained and portable (the canonical copy is
~/workspace/system/safe-write/safe_write.py):

* full-content writes go to a temp file in the same directory, are
  fsynced, atomically renamed over the target, and then READ BACK and
  compared byte-for-byte (length + SHA-256) before success is
  reported;
* appends (hash-chain ledger lines) are fsynced and then verified by
  reading back exactly the appended range; on any mismatch the file
  is rolled back to its pre-append size before the failure is raised,
  so an unverified line never stands as written;
* bounded retries alternate a fresh subprocess (a new interpreter
  running this module, which can land outside an EPERM wave or a
  write-tainted lineage) with local attempts;
* empty content is refused outright, and total failure raises
  :class:`SafeWriteError` — callers must fail closed, never fall back
  to an unverified write.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path


class SafeWriteError(RuntimeError):
    """A verified write failed on every path; the run must fail closed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def try_write_once(path: Path, data: bytes) -> bool:
    """One verified full-content write attempt in this process.

    Returns True only when the bytes read back from ``path`` after the
    atomic rename hash identically to ``data``.
    """
    if not data:
        return False
    directory = path.parent
    descriptor, temporary_name = tempfile.mkstemp(
        dir=directory, prefix=".aee-verified-", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(directory)
        return verify_bytes_on_disk(path, data)
    except OSError:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        return False


def verify_bytes_on_disk(path: Path, expected: bytes) -> bool:
    """True only when ``path`` currently holds exactly ``expected``."""
    try:
        back = path.read_bytes()
    except OSError:
        return False
    return len(back) == len(expected) and _sha256(back) == _sha256(expected)


def _try_child(path: Path, data: bytes) -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "aee.verified_write", "--child-write", str(path)],
            input=data,
            timeout=30,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def write_bytes_verified(path: str | Path, data: bytes, *, retries: int = 3) -> dict[str, object]:
    """Write ``data`` to ``path`` with read-back verification.

    Raises :class:`SafeWriteError` on empty content or when every
    attempt fails verification. Returns a small report dict on
    success (``via`` names the attempt that landed).
    """
    target = Path(path)
    if not data:
        raise SafeWriteError(f"refusing to write empty content to {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if try_write_once(target, data):
        return {"ok": True, "via": "local", "attempts": 1, "sha256": _sha256(data)}
    attempts = 1
    for round_ in range(1, retries + 1):
        time.sleep(min(0.5 * round_, 2.0))
        attempts += 1
        if _try_child(target, data):
            return {
                "ok": True,
                "via": f"child-{round_}",
                "attempts": attempts,
                "sha256": _sha256(data),
            }
        attempts += 1
        if try_write_once(target, data):
            return {
                "ok": True,
                "via": f"local-retry-{round_}",
                "attempts": attempts,
                "sha256": _sha256(data),
            }
    raise SafeWriteError(
        f"verified write to {target} failed on every path ({attempts} attempts): "
        "EPERM wave or write-tainted process suspected"
    )


def write_text_verified(
    path: str | Path, text: str, *, encoding: str = "utf-8", retries: int = 3
) -> dict[str, object]:
    """Verified write of ``text`` encoded once, written as bytes.

    Encoding here (instead of a text-mode file) keeps the bytes on
    disk independent of platform newline translation: the string's
    ``\\n`` characters land as-is, byte-identical to the previous
    text-mode writes on POSIX.
    """
    return write_bytes_verified(path, text.encode(encoding), retries=retries)


def _append_once(path: Path, data: bytes) -> None:
    with path.open("ab") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _tail_matches(path: Path, offset: int, data: bytes) -> bool:
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            return handle.read(len(data)) == data
    except OSError:
        return False


def _rollback_append(path: Path, size_before: int, existed: bool) -> None:
    """Best-effort restore of the pre-append state after a bad append."""
    try:
        if existed:
            with path.open("r+b") as handle:
                handle.truncate(size_before)
                handle.flush()
                os.fsync(handle.fileno())
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def append_bytes_verified(path: str | Path, data: bytes) -> dict[str, object]:
    """Append ``data`` and verify the appended range by read-back.

    Appends are deliberately NOT retried blindly: an ambiguous append
    failure retried as-is could double-append. Instead the append is
    verified against the exact byte range it should occupy, and any
    failure rolls the file back to its pre-append size before
    :class:`SafeWriteError` is raised — the append either lands whole
    and verified, or does not land at all.
    """
    target = Path(path)
    if not data:
        raise SafeWriteError(f"refusing to append empty content to {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    size_before = target.stat().st_size if existed else 0
    try:
        _append_once(target, data)
    except OSError as exc:
        _rollback_append(target, size_before, existed)
        raise SafeWriteError(
            f"append to {target} failed ({exc}); rolled back to {size_before} bytes"
        ) from exc
    if not _tail_matches(target, size_before, data):
        _rollback_append(target, size_before, existed)
        raise SafeWriteError(
            f"append to {target} could not be verified by read-back; "
            f"rolled back to {size_before} bytes"
        )
    if not existed:
        _fsync_directory(target.parent)
    return {"ok": True, "via": "append", "attempts": 1, "sha256": _sha256(data)}


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


def _main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("--write", "--child-write"):
        print(
            "usage: python -m aee.verified_write --write|--child-write <path>  (content on stdin)",
            file=sys.stderr,
        )
        return 2
    mode, target = argv[0], Path(argv[1])
    payload = sys.stdin.buffer.read()
    if mode == "--child-write":
        target.parent.mkdir(parents=True, exist_ok=True)
        return 0 if try_write_once(target, payload) else 1
    try:
        result = write_bytes_verified(target, payload)
    except SafeWriteError as exc:
        print(f"SAFE-WRITE FAILED: {exc}", file=sys.stderr)
        return 3
    print(
        f"verified write ok via {result['via']} "
        f"({len(payload)} bytes, sha256 {str(result['sha256'])[:16]}...)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
