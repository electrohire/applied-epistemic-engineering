"""Axiomere anchoring of assessments (Spec 002 FR-8b, T804-T806).

WP-8b is an OPTIONAL dependency by design (FR-8.6): the `axiomere`
package (AXIOVEX/axiomere-python) is never imported at module
import time, and its absence degrades to a clear "anchor
unavailable" outcome - never to an assess failure. Anchoring is a
separate, explicit act (`aee anchor`), performed on an assessment
that already exists.

What anchoring deposits: the assessment's content SHA-256 (the
same canonical digest the hash-chain ledger records,
`assessment_content_digest`) as an event in an Axiomere `.axmr`
ledger, together with the assessment's project / phase / outcome
context, followed by a checkpoint so the receipt can name the
ledger's checkpoint (Merkle) root at the moment of anchoring. The
receipt is written back into the assessment as `metadata.anchor`
(FR-8.5), so the working copy carries the coordinates of its own
external commitment: ledger path, event sequence + hash,
checkpoint sequence + root, and the digest that was deposited.
Anyone with the `.axmr` file can verify the whole chain with the
axiomere package's own `verify_file` (T806).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from aee.ledger import assessment_content_digest

ANCHOR_EVENT_TYPE = "aee.assessment.anchored"


class AnchorUnavailable(RuntimeError):
    """The optional axiomere package is not available."""


def anchor_available() -> bool:
    """Whether the optional `axiomere` package can be imported."""
    return importlib.util.find_spec("axiomere") is not None


def anchor_assessment(
    assessment: dict[str, Any],
    *,
    ledger_path: str | Path,
    actor: str = "aee-anchor",
    project: str | None = None,
    phase: str | None = None,
) -> dict[str, Any]:
    """Deposit the assessment's SHA-256 in an Axiomere ledger.

    Returns the anchor receipt (also suitable for
    ``metadata.anchor``). Raises :class:`AnchorUnavailable` when
    the optional package is absent - callers surface that as the
    FR-8.6 "anchor unavailable" degradation, not as a failure of
    the assessment itself.
    """
    if not anchor_available():
        raise AnchorUnavailable(
            "anchor unavailable: the optional 'axiomere' package is not "
            "installed (Spec 002 FR-8.6); the assessment itself is "
            "unaffected - install axiomere to enable Axiomere anchoring"
        )
    # The optional package has no stubs on this path; availability
    # was verified by anchor_available() above (FR-8.6).
    import axiomere  # type: ignore[import-not-found]

    digest = assessment_content_digest(assessment)
    metadata = assessment.get("metadata", {})
    payload = {
        "assessment_sha256": digest,
        "project": project or metadata.get("project"),
        "phase": phase or metadata.get("phase"),
        "outcome": assessment.get("outcome"),
        "methodology_version": assessment.get("methodology_version"),
    }
    path = Path(ledger_path)
    database = (
        axiomere.Database.open(str(path)) if path.exists() else axiomere.Database.create(str(path))
    )
    event = database.append(ANCHOR_EVENT_TYPE, payload, actor=actor)
    checkpoint = database.checkpoint(actor=actor)
    checkpoint_payload = checkpoint.get("payload", {})
    return {
        "ledger": str(path),
        "assessment_sha256": digest,
        "event_seq": event.get("seq"),
        "event_hash": event.get("hash"),
        "checkpoint_seq": checkpoint.get("seq"),
        "checkpoint_root": checkpoint_payload.get("merkle_root"),
        "checkpoint_hash": checkpoint.get("hash"),
        "anchored_at": event.get("ts"),
        "actor": actor,
    }
