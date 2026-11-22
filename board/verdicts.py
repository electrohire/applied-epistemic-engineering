"""Verdict reference resolution for the Agent Board (spec AB-001 FR-K1).

A ``done`` transition is gated on a verdict reference that *resolves*
to a record carrying a *favorable* verdict for the row's claims and
work products (FR-K1, as corrected by Amendment 1 finding C-1). This
module is the resolver: it parses the pinned reference format, reads
the cited record in the shape its class really produces, and returns
one of three outcomes:

- ``favorable`` — the record resolves and its verdict is favorable
  under the per-class rule;
- ``unfavorable`` — the record resolves and its verdict is not
  favorable (a violated claim, a payload exit other than 0, a failed
  CI conclusion, a CI run at a different commit than the work
  product);
- ``unresolvable`` — the reference cannot be resolved to the record
  it cites (missing file, content hash mismatch, malformed record,
  a gate record kept inside the board it gates, FR-K1b).

Per-class favorable rules (FR-K1's table):

- ``engine`` — the cited evaluation record (the program ledger's
  evaluation JSON) carries a favorable verdict for every claim the
  row names: ``verified`` or ``consistent`` in the engine's verdict
  vocabulary (``supported`` / ``pass`` / ``passed`` are accepted for
  records in those vocabularies). A claim absent from the evaluation
  has no favorable verdict.
- ``gatekeeper`` — the cited queue record's *payload* exit code is
  0. The payload verdict convention in gatekeeper records is the
  job's own ``*_PAYLOAD_EXIT=<n>`` token, carried in the record's
  ``markers`` or ``log_tail`` (a top-level integer
  ``payload_exit_code`` field, when a record carries one, wins). The
  wrapper's own completion fields (``state``, ``run_conclusion``)
  are never read for favorability: wrapper success is not payload
  success. A record with no payload exit record is not favorable.
- ``ci`` — the cited run record's conclusion is ``success`` and its
  head SHA equals both the reference's digest and a commit recorded
  in the row's work products.
- ``gate`` — the cited record lives *outside* the board it gates
  (FR-K1b), states an approval (``approve`` / ``approved``), and
  names the decider.

The citation hash is the SHA-256 of the *extracted verdict record*
(the per-class facts the decision rests on), in board canonical
form — not of the whole source file, so a queue record that later
gains unrelated fields still verifies against its citation.

This module is the one canonical parser of the reference format;
``board.kernel`` imports ``parse_verdict_ref`` from here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import canonical

VERDICT_CLASSES = ("engine", "gatekeeper", "ci", "gate")

# The pinned format (spec 4.3): class:identifier#digest, where
# engine/gatekeeper/gate references cite a 64-hex content digest of
# the record and ci references cite the run's 40-hex head SHA.
_REF_RE = re.compile(r"^(?P<cls>engine|gatekeeper|ci|gate):(?P<locator>.+)#(?P<digest>[0-9a-f]+)$")
_DIGEST_LENGTHS = {"engine": 64, "gatekeeper": 64, "ci": 40, "gate": 64}

ENGINE_FAVORABLE_VERDICTS = frozenset({"verified", "consistent", "supported", "pass", "passed"})

# The gatekeeper payload verdict convention: a job-specific token
# ending in PAYLOAD_EXIT=<n> in the record's markers or log tail
# (e.g. RESTORE_PAYLOAD_EXIT=0). The last token wins: it is the
# payload's own final word.
_PAYLOAD_EXIT_RE = re.compile(r"(?:^|[^A-Za-z0-9])PAYLOAD_EXIT=(-?\d+)")

OUTCOMES = ("favorable", "unfavorable", "unresolvable")


@dataclass(frozen=True)
class VerdictRef:
    """A parsed verdict reference (FR-K1's pinned format)."""

    cls: str
    locator: str
    digest: str


@dataclass(frozen=True)
class VerdictCheck:
    """The outcome of resolving one verdict reference."""

    outcome: str  # one of OUTCOMES
    detail: str
    record_hash: str | None  # citation hash of the extracted record


def parse_verdict_ref(ref: object) -> VerdictRef | None:
    """Parse a verdict reference, or return None when malformed."""
    if not isinstance(ref, str):
        return None
    match = _REF_RE.match(ref)
    if match is None:
        return None
    cls = match.group("cls")
    digest = match.group("digest")
    if len(digest) != _DIGEST_LENGTHS[cls]:
        return None
    return VerdictRef(cls=cls, locator=match.group("locator"), digest=digest)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _citation_hash(extracted: dict[str, Any]) -> str:
    return _sha256_bytes(canonical.canonical_bytes(extracted))


def _unresolvable(detail: str) -> VerdictCheck:
    return VerdictCheck(outcome="unresolvable", detail=detail, record_hash=None)


def _read_json_record(path: Path) -> tuple[dict[str, Any] | None, bytes, str | None]:
    """Read a JSON record file: (record, raw bytes, error detail)."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, b"", f"the cited record cannot be read: {exc}"
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, raw, f"the cited record is not valid JSON: {exc}"
    if not isinstance(record, dict):
        return None, raw, "the cited record is not a JSON object"
    return record, raw, None


def _check_engine(
    ref: VerdictRef, claim_ids: tuple[str, ...], board_dir: Path | None
) -> VerdictCheck:
    path = Path(ref.locator)
    record, raw, error = _read_json_record(path)
    if error is not None or record is None:
        return _unresolvable(error or "the cited record cannot be read")
    if _sha256_bytes(raw) != ref.digest:
        return _unresolvable("the evaluation record's content hash does not match the citation")
    verdicts = {
        entry.get("id"): entry.get("verdict")
        for entry in record.get("verdicts") or []
        if isinstance(entry, dict)
    }
    extracted = {
        "class": "engine",
        "locator": ref.locator,
        "claim_verdicts": {claim: verdicts.get(claim) for claim in claim_ids},
    }
    record_hash = _citation_hash(extracted)
    if not claim_ids:
        return VerdictCheck(
            "unfavorable",
            "the row names no claims for the evaluation to carry a verdict on",
            record_hash,
        )
    for claim in claim_ids:
        verdict = verdicts.get(claim)
        if verdict not in ENGINE_FAVORABLE_VERDICTS:
            return VerdictCheck(
                "unfavorable",
                f"claim {claim} carries verdict {verdict!r}, not a favorable verdict",
                record_hash,
            )
    return VerdictCheck(
        "favorable",
        f"the evaluation record carries a favorable verdict for {list(claim_ids)}",
        record_hash,
    )


def _gatekeeper_payload_exit(record: dict[str, Any]) -> int | None:
    """The payload's own exit code from a gatekeeper queue record.

    A top-level integer ``payload_exit_code`` wins when present;
    otherwise the last ``*_PAYLOAD_EXIT=<n>`` token across the
    record's markers, then its log tail. Wrapper completion fields
    are never consulted.
    """
    direct = record.get("payload_exit_code")
    if isinstance(direct, int) and not isinstance(direct, bool):
        return direct
    found: int | None = None
    for lines in (record.get("markers"), record.get("log_tail")):
        if not isinstance(lines, list):
            continue
        for line in lines:
            if isinstance(line, str):
                for match in _PAYLOAD_EXIT_RE.finditer(line):
                    found = int(match.group(1))
    return found


def _check_gatekeeper(
    ref: VerdictRef, gatekeeper_queue_dir: Path | None, board_dir: Path | None
) -> VerdictCheck:
    if gatekeeper_queue_dir is None:
        return _unresolvable("no gatekeeper queue directory was supplied for the resolution")
    path = Path(gatekeeper_queue_dir) / f"{ref.locator}.json"
    record, _raw, error = _read_json_record(path)
    if error is not None or record is None:
        return _unresolvable(error or "the cited record cannot be read")
    if record.get("id") != ref.locator:
        return _unresolvable("the queue record's id does not match the citation's job id")
    payload_exit = _gatekeeper_payload_exit(record)
    extracted = {"job_id": ref.locator, "payload_exit_code": payload_exit}
    record_hash = _citation_hash(extracted)
    if record_hash != ref.digest:
        return _unresolvable("the payload exit record's hash does not match the citation")
    if payload_exit == 0:
        return VerdictCheck("favorable", "the job's payload exit code is 0", record_hash)
    if payload_exit is None:
        return VerdictCheck(
            "unfavorable",
            "the queue record carries no payload exit record; wrapper completion "
            "is not a payload verdict",
            record_hash,
        )
    return VerdictCheck(
        "unfavorable", f"the job's payload exit code is {payload_exit}, not 0", record_hash
    )


def _check_ci(
    ref: VerdictRef, work_product: tuple[str, ...], ci_records_dir: Path | None
) -> VerdictCheck:
    if ci_records_dir is None:
        return _unresolvable("no CI records directory was supplied for the resolution")
    path = Path(ci_records_dir) / f"{ref.locator}.json"
    record, _raw, error = _read_json_record(path)
    if error is not None or record is None:
        return _unresolvable(error or "the cited record cannot be read")
    if str(record.get("databaseId")) != ref.locator:
        return _unresolvable("the run record's id does not match the citation's run id")
    head_sha = record.get("headSha")
    extracted = {
        "class": "ci",
        "run_id": ref.locator,
        "conclusion": record.get("conclusion"),
        "head_sha": head_sha,
    }
    record_hash = _citation_hash(extracted)
    if head_sha != ref.digest:
        return _unresolvable("the run's head SHA does not match the citation's digest")
    if record.get("conclusion") != "success":
        return VerdictCheck(
            "unfavorable",
            f"the run's conclusion is {record.get('conclusion')!r}, not 'success'",
            record_hash,
        )
    commits = {entry.split(":", 1)[1] for entry in work_product if entry.startswith("commit:")}
    if not work_product:
        return VerdictCheck(
            "unfavorable",
            "the row records no work products for the run to cover",
            record_hash,
        )
    if head_sha not in commits:
        return VerdictCheck(
            "unfavorable",
            "the run's head SHA is not among the commits recorded in the row's work products",
            record_hash,
        )
    return VerdictCheck(
        "favorable",
        "the run concluded success at the commit recorded in the work products",
        record_hash,
    )


def _gate_decision(
    record_text: str, record: dict[str, Any] | None
) -> tuple[str | None, str | None]:
    """(decision, decider) from a gate record, JSON or line form."""
    if record is not None:
        decision = record.get("decision")
        decider = record.get("decider") or record.get("decided_by")
        return (
            decision if isinstance(decision, str) else None,
            decider if isinstance(decider, str) else None,
        )
    decision = decider = None
    for line in record_text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        if key.strip().lower() == "decision":
            decision = value.strip()
        elif key.strip().lower() in ("decider", "decided_by"):
            decider = value.strip()
    return decision, decider


def _check_gate(
    ref: VerdictRef, work_product: tuple[str, ...], board_dir: Path | None
) -> VerdictCheck:
    path = Path(ref.locator)
    if board_dir is not None:
        try:
            inside = path.resolve().is_relative_to(Path(board_dir).resolve())
        except OSError:
            inside = False
        if inside:
            return _unresolvable(
                "FR-K1b: the gate record lives inside the board it gates; "
                "a gate record must be kept outside the board"
            )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return _unresolvable(f"the cited gate record cannot be read: {exc}")
    if _sha256_bytes(raw) != ref.digest:
        return _unresolvable("the gate record's content hash does not match the citation")
    record: dict[str, Any] | None = None
    try:
        parsed = json.loads(raw.decode("utf-8"))
        if isinstance(parsed, dict):
            record = parsed
    except (UnicodeDecodeError, json.JSONDecodeError):
        record = None
    decision, decider = _gate_decision(raw.decode("utf-8", errors="replace"), record)
    extracted = {
        "class": "gate",
        "locator": ref.locator,
        "decision": decision,
        "decider": decider,
        "covers": sorted(work_product),
    }
    record_hash = _citation_hash(extracted)
    if decision is None or decision.strip().lower() not in ("approve", "approved"):
        return VerdictCheck(
            "unfavorable",
            f"the gate record states decision {decision!r}, not an approval",
            record_hash,
        )
    if not (decider and decider.strip()):
        return VerdictCheck("unfavorable", "the gate record names no decider", record_hash)
    return VerdictCheck(
        "favorable",
        f"the gate record approves, decided by {decider}",
        record_hash,
    )


def evaluate_verdict(
    ref_text: str,
    *,
    claim_ids: tuple[str, ...] = (),
    work_product: tuple[str, ...] = (),
    board_dir: Path | None = None,
    gatekeeper_queue_dir: Path | None = None,
    ci_records_dir: Path | None = None,
) -> VerdictCheck:
    """Resolve one verdict reference to its favorable/unfavorable/
    unresolvable outcome under FR-K1's per-class rules."""
    ref = parse_verdict_ref(ref_text)
    if ref is None:
        return _unresolvable(f"malformed verdict reference: {ref_text!r}")
    if ref.cls == "engine":
        return _check_engine(ref, tuple(claim_ids), board_dir)
    if ref.cls == "gatekeeper":
        return _check_gatekeeper(ref, gatekeeper_queue_dir, board_dir)
    if ref.cls == "ci":
        return _check_ci(ref, tuple(work_product), ci_records_dir)
    return _check_gate(ref, tuple(work_product), board_dir)
