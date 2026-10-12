"""Per-source reliability learned from resolved claims.

Ported from the epistemic ledger's learned entrenchment
(AXIOVEX/epistemic-ledger): there, a claim's entrenchment stops
being a hand-assigned tier once outcomes exist and becomes
``1 - Brier`` over the scores that were live when each outcome
landed. Its OVERRIDE-CAL-01 study showed the loop absorbs even a
reviewer who is wrong 20% of the time — bad input degrades the
source's measured reliability instead of poisoning the store. That
promise only holds with the credit rule below, which is the rule
this module now implements (Spec 003 FR-3, closing RT1-05/RT1-07
and RT2-C1):

* **Contribution-weighted credit.** ``observe_claim`` credits a
  source in proportion to its share of the claim's positive
  supporting evidence weight (the same static kind x quality
  weights scoring uses, duplicates collapsed, empty-ref items
  weightless). A zero-weight source earns no record at all, so a
  junk source riding claims carried by someone else's evidence is
  never canonised; symmetrically, a source attached to a failing
  claim takes only its share of the loss, not full blame for a
  claim it barely touched. Each record tracks both the integer
  claim count (``observations``) and the share-weighted effective
  count (``credit_weight``); the cold-start guard and the Brier
  mean both run on ``credit_weight``, so three claims at a 2%
  share are 0.06 effective observations, not three.
* **Validated loading.** ``from_dict`` rejects non-finite,
  negative, or out-of-range values with an error naming the
  source: ``observations`` must be a non-negative integer,
  ``brier_sum`` must lie in ``[0, observations]`` (the Brier
  bound), and ``credit_weight`` in ``[0, observations]`` with
  ``brier_sum <= credit_weight``. A poisoned table fails load; it
  is never silently clamped into validity.
* **Range guarantee.** ``reliability()`` and ``blended_weight``
  return values in ``[0, 1]`` by construction (asserted in
  tests); non-finite internal state degrades to "unmeasured"
  (the static prior stands), never to a number outside the range
  and never to a bare ``NaN`` in emitted output.
* **Provenance.** Every record carries who/what resolved the
  claims behind it. The direct ``record()`` path requires a
  provenance argument; unattributed records are accepted only via
  the explicitly named ``allow_unattributed=True`` compatibility
  path and are marked as such. Tables written before provenance
  existed load with the ``legacy`` provenance marker.
* **Provenance authority (Spec 003 FR-3.6 to FR-3.8, closing the
  RT1-07 residual).** A provenance string is a label, not an
  authority check: the Phase 9 probe re-run showed three direct
  ``record()`` calls with any self-asserted string still canonised
  a junk source at the original numbers. Canonisation — measured
  reliability from ``reliability()``, and therefore any
  ``blended_weight`` lift or drag — now runs on **anchored credit
  only**. An observation earns anchored credit when it is recorded
  against a :class:`ProvenanceAnchor` the engine verifies at
  record time against the table's bound hash-chained ledger: the
  cited entry must resolve, the chain must verify, and the entry
  payload must match the observation (source / predicted /
  outcome for ``record()``; claim id / outcome for
  ``observe_claim()``). A bogus, mismatched, or already-consumed
  anchor is refused loudly. Unanchored observations still
  accumulate, as a **provisional** measurement: gated by the same
  cold-start guard, capped at ``PROVISIONAL_RELIABILITY_CAP``,
  labelled in serialised output, and never consumed by
  ``blended_weight``. A table loaded from disk carries its anchor
  digests as claims, not as trust: canonisation activates only
  after the digests resolve against a ledger the consumer binds
  (``from_dict(..., ledger=...)`` or ``verify_anchors()``), and
  legacy records — which carry no anchors — gain no canonisation
  from legacy history alone. The resolver-side helpers
  ``record_resolution()`` / ``observe_claim_resolution()`` append
  the resolution entry to the bound ledger and record against
  its anchor in one call, so the honest path is the short path.

The analog here is per-source. A :class:`ReliabilityTable`
records, for each source, the assessments in which that source
supported a claim: the claim's propagated score at assessment
time (the system's credence, which the source's evidence fed) and
the claim's eventual outcome, once known. A source's measured
reliability is ``1 - Brier`` over those observations. In scoring,
a measured reliability blends with the static
:class:`SourceQuality` prior:

    weight = (1 - alpha) * static + alpha * measured

so an unmeasured source keeps its prior exactly, a source with a
perfect record can lift even MODEL evidence above its 0.20 prior,
and a source with a poor record drags even TEST evidence down.
Contradicting evidence keeps its static weight in this version:
reliability at asserting a claim and reliability at refuting one
are different tracks, and only the support track is measured here.

Everything is opt-in: ``ScoringEngine()`` without a table scores
bit-identically to previous releases. Whenever a measured weight
replaces a static one, the claim score's notes say so — measured
weights are inspectable, never silent.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aee.model import BundleValidationError, Claim, Evidence, EvidenceDirection

if TYPE_CHECKING:
    from aee.ledger import HashChainLedger
    from aee.scoring import ClaimScore

#: Provenance marker for records loaded from tables written before
#: provenance existed (Spec 003 FR-3.5 compatibility default).
LEGACY_PROVENANCE = "legacy (no provenance recorded)"

#: Provenance marker for records accepted through the explicitly
#: named unattributed compatibility path in ``record()``.
UNATTRIBUTED_PROVENANCE = "unattributed (compatibility path)"

#: Provenance default for claims resolved through ``observe_claim``
#: when the caller does not name the resolving authority.
OBSERVE_CLAIM_PROVENANCE = "observe_claim"

#: Ceiling on provisional (self-asserted, unanchored) reliability.
#: A history nobody can check may be reported, but it may never
#: claim more than this as even a provisional measurement — and it
#: never feeds scoring at any value (Spec 003 FR-3.7).
PROVISIONAL_RELIABILITY_CAP = 0.5

#: Ledger event type recording one direct (source, predicted,
#: outcome) resolution; the payload an anchored ``record()`` must
#: match (Spec 003 FR-3.6).
RESOLUTION_EVENT_TYPE = "reliability.resolution"

#: Ledger event type recording one claim resolution; the payload
#: an anchored ``observe_claim()`` must match (Spec 003 FR-3.6).
CLAIM_RESOLUTION_EVENT_TYPE = "claim.resolution"

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ProvenanceAnchor:
    """A verifiable reference backing one recorded observation.

    ``kind`` names the artifact class; the only kind the engine
    resolves today is ``"ledger-entry"``, whose ``digest`` is the
    ``entry_hash`` of an entry in the table's bound hash-chained
    ledger recording the resolution. The anchor is a reference,
    not a proof by itself: trust comes from the engine resolving
    it against the ledger at record (or load) time — the digest
    must exist on a chain that verifies, with a payload matching
    the observation it backs.
    """

    digest: str
    kind: str = "ledger-entry"

    def __post_init__(self) -> None:
        if self.kind != "ledger-entry":
            raise ValueError(
                f"unsupported provenance anchor kind {self.kind!r}; "
                "only 'ledger-entry' anchors resolve in this engine"
            )
        if not _DIGEST_RE.match(self.digest):
            raise ValueError(
                "provenance anchor digest must be a 64-character hex "
                f"SHA-256 (a ledger entry hash), got {self.digest!r}"
            )


# Float-representation tolerance for the range checks in
# ``from_dict``: a legitimately computed Brier sum can sit a few
# ULPs from its mathematical bound. Anything beyond this is a
# poisoned or corrupt value, not rounding.
_TOL = 1e-9


def _verified_entry_map(ledger: HashChainLedger) -> dict[str, dict[str, Any]]:
    """Index a ledger's entries by hash, requiring the chain to
    verify. Anchor resolution never runs against an unverified
    chain: a tampered or truncated ledger canonises nothing."""
    verification = ledger.verify()
    if not verification.valid:
        raise BundleValidationError(
            "reliability anchor verification refused: the bound "
            "ledger does not verify (" + "; ".join(verification.errors) + ")"
        )
    return {str(entry["entry_hash"]): entry for entry in ledger.entries()}


def _require_anchor_payload(
    entry: dict[str, Any],
    *,
    event_type: str,
    expected: dict[str, Any],
    anchor: ProvenanceAnchor,
) -> None:
    """Require a resolved ledger entry to record exactly the
    observation the anchor is asked to back (FR-3.6)."""
    if entry.get("event_type") != event_type:
        raise ValueError(
            f"provenance anchor {anchor.digest} resolves to a "
            f"{entry.get('event_type')!r} entry, not a {event_type!r} "
            "resolution record; refusing to credit it as anchored"
        )
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        raise ValueError(
            f"provenance anchor {anchor.digest}: resolution entry "
            "payload is not an object; refusing to credit it as anchored"
        )
    for key, want in expected.items():
        got = payload.get(key)
        if isinstance(want, float):
            matches = (
                isinstance(got, (int, float))
                and not isinstance(got, bool)
                and abs(float(got) - want) <= _TOL
            )
        else:
            matches = got == want
        if not matches:
            raise ValueError(
                f"provenance anchor {anchor.digest}: resolution entry "
                f"records {key}={got!r}, not the {want!r} being "
                "recorded; refusing to credit it as anchored"
            )


def _resolve_anchor(
    entries: dict[str, dict[str, Any]],
    anchor: ProvenanceAnchor,
    *,
    event_type: str,
    expected: dict[str, Any],
) -> dict[str, Any]:
    entry = entries.get(anchor.digest)
    if entry is None:
        raise ValueError(
            f"provenance anchor {anchor.digest} does not resolve to "
            "any entry in the bound ledger; refusing to credit the "
            "observation as anchored (record it without an anchor "
            "for provisional credit instead)"
        )
    _require_anchor_payload(entry, event_type=event_type, expected=expected, anchor=anchor)
    return entry


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def _finite_number(source_id: str, field_name: str, raw: Any) -> float:
    """Coerce a loaded reliability field to a finite float or raise
    a loud, source-naming error (Spec 003 FR-3.1/FR-3.3)."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise BundleValidationError(
            f"reliability record '{source_id}': field '{field_name}' "
            f"must be a number, got {type(raw).__name__}"
        )
    try:
        value = float(raw)
    except OverflowError:
        raise BundleValidationError(
            f"reliability record '{source_id}': field '{field_name}' "
            "is too large to represent as a float"
        ) from None
    if not math.isfinite(value):
        raise BundleValidationError(
            f"reliability record '{source_id}': field '{field_name}' "
            f"must be finite, got {raw!r} (non-finite numbers are "
            "rejected at load, Spec 003 FR-3.3)"
        )
    return value


@dataclass(slots=True)
class SourceRecord:
    """Resolved observations for one source.

    ``observations`` is the integer count of resolved claims the
    source was credited on; ``credit_weight`` is the sum of its
    contribution shares over those claims (the effective sample
    size). For records built by the direct ``record()`` path every
    share is 1.0 and the two agree; for pre-FR-3 tables loaded
    without a ``credit_weight`` field, the effective credit
    defaults to ``observations`` (legacy records were full-credit
    by construction). ``provenance`` names who/what resolved the
    claims behind the most recent record.

    The anchored tallies (FR-3.6) track the subset of observations
    backed by verified provenance anchors: ``anchored_credit_weight``
    and ``anchored_brier_sum`` mirror the totals over that subset,
    ``anchors`` holds the consumed anchor digests (one per anchored
    observation for this source — an anchor backs exactly one
    observation), and ``anchors_verified`` records whether those
    digests have been resolved against a bound ledger in this
    process (at record time, or at load time via
    ``ReliabilityTable.verify_anchors``). It is process state, not
    file data: a serialised table's digests are claims a consumer
    re-verifies, so ``from_dict`` never restores the flag from the
    file itself.
    """

    observations: int = 0
    brier_sum: float = 0.0
    credit_weight: float | None = None
    provenance: str = ""
    anchored_credit_weight: float = 0.0
    anchored_brier_sum: float = 0.0
    anchors: tuple[str, ...] = ()
    anchors_verified: bool = False

    @property
    def effective_credit(self) -> float:
        """Share-weighted observation count (cold-start basis)."""
        if self.credit_weight is not None:
            return self.credit_weight
        return float(self.observations)

    @property
    def brier(self) -> float | None:
        credit = self.effective_credit
        if not credit:
            return None
        value = self.brier_sum / credit
        if not math.isfinite(value):
            # Defense in depth (FR-3.2): state that bypassed the
            # validated loaders degrades to "unmeasured", never to
            # a non-finite number downstream.
            return None
        return value

    @property
    def reliability(self) -> float | None:
        """Measured reliability over ALL observations, anchored or
        not. This is the provisional track's raw value; the
        canonisation-grade figure is ``canonised_reliability``."""
        brier = self.brier
        return None if brier is None else _clamp01(1.0 - brier)

    @property
    def anchored_credit(self) -> float:
        """Effective credit backed by provenance anchors."""
        return self.anchored_credit_weight

    @property
    def canonised_reliability(self) -> float | None:
        """Reliability over anchored observations only (FR-3.6).

        None when the source has no anchored credit or the anchored
        state is non-finite. Whether this value is *used* is the
        table's decision (verified anchors + cold-start guard)."""
        credit = self.anchored_credit_weight
        if not credit:
            return None
        value = self.anchored_brier_sum / credit
        if not math.isfinite(value):
            return None
        return _clamp01(1.0 - value)

    @property
    def provisional_reliability(self) -> float | None:
        """The self-asserted track, capped (FR-3.7): the all-history
        measurement, never above ``PROVISIONAL_RELIABILITY_CAP``."""
        value = self.reliability
        if value is None:
            return None
        return min(value, PROVISIONAL_RELIABILITY_CAP)

    def to_dict(self) -> dict[str, object]:
        return {
            "observations": self.observations,
            "brier_sum": self.brier_sum,
            "credit_weight": self.effective_credit,
            "provenance": self.provenance or LEGACY_PROVENANCE,
            "anchored_credit_weight": self.anchored_credit_weight,
            "anchored_brier_sum": self.anchored_brier_sum,
            "anchors": list(self.anchors),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, source_id: str = "") -> SourceRecord:
        name = source_id or "<unknown>"
        if not isinstance(value, dict):
            raise BundleValidationError(
                f"reliability record '{name}': record must be an object, got {type(value).__name__}"
            )
        raw_obs = value.get("observations", 0)
        observations_f = _finite_number(name, "observations", raw_obs)
        if observations_f < 0 or observations_f != int(observations_f):
            raise BundleValidationError(
                f"reliability record '{name}': field 'observations' "
                f"must be a non-negative integer, got {raw_obs!r}"
            )
        observations = int(observations_f)
        brier_sum = _finite_number(name, "brier_sum", value.get("brier_sum", 0.0))
        if brier_sum < -_TOL or brier_sum > observations + _TOL:
            raise BundleValidationError(
                f"reliability record '{name}': field 'brier_sum' "
                f"must lie in [0, observations={observations}] (the "
                f"Brier bound), got {brier_sum!r}"
            )
        credit_weight: float | None = None
        if "credit_weight" in value:
            credit_weight = _finite_number(name, "credit_weight", value["credit_weight"])
            if credit_weight < -_TOL or credit_weight > observations + _TOL:
                raise BundleValidationError(
                    f"reliability record '{name}': field 'credit_weight' "
                    f"must lie in [0, observations={observations}], "
                    f"got {credit_weight!r}"
                )
            if brier_sum > credit_weight + _TOL:
                raise BundleValidationError(
                    f"reliability record '{name}': field 'brier_sum' "
                    f"({brier_sum!r}) exceeds 'credit_weight' "
                    f"({credit_weight!r}); a share-weighted Brier sum "
                    "cannot exceed the total credited share"
                )
            credit_weight = min(max(credit_weight, 0.0), float(observations))
        raw_provenance = value.get("provenance", LEGACY_PROVENANCE)
        if not isinstance(raw_provenance, str) or not raw_provenance.strip():
            raise BundleValidationError(
                f"reliability record '{name}': field 'provenance' "
                "must be a non-empty string naming who/what resolved "
                "the claims behind this record"
            )
        # Anchored tallies (FR-3.6/FR-3.7): absent on pre-addendum
        # files, where they default to zero — a legacy record
        # carries no anchored credit and canonises nothing. When
        # present they must be internally consistent: the anchored
        # subset can hold neither more credit than the record's
        # whole history nor a Brier sum beyond its own credit (or
        # beyond the record's total Brier sum), and anchored credit
        # claimed without anchor digests is not a claim at all.
        anchored_credit = _finite_number(
            name, "anchored_credit_weight", value.get("anchored_credit_weight", 0.0)
        )
        credit_bound = credit_weight if credit_weight is not None else float(observations)
        if anchored_credit < -_TOL or anchored_credit > credit_bound + _TOL:
            raise BundleValidationError(
                f"reliability record '{name}': field "
                f"'anchored_credit_weight' must lie in [0, "
                f"credit_weight={credit_bound}], got {anchored_credit!r}"
            )
        anchored_brier = _finite_number(
            name, "anchored_brier_sum", value.get("anchored_brier_sum", 0.0)
        )
        if (
            anchored_brier < -_TOL
            or anchored_brier > anchored_credit + _TOL
            or anchored_brier > brier_sum + _TOL
        ):
            raise BundleValidationError(
                f"reliability record '{name}': field "
                f"'anchored_brier_sum' ({anchored_brier!r}) must lie "
                f"in [0, anchored_credit_weight={anchored_credit!r}] "
                f"and within 'brier_sum' ({brier_sum!r})"
            )
        raw_anchors = value.get("anchors", [])
        if not isinstance(raw_anchors, list) or any(
            not isinstance(item, str) or not _DIGEST_RE.match(item) for item in raw_anchors
        ):
            raise BundleValidationError(
                f"reliability record '{name}': field 'anchors' must "
                "be a list of 64-character hex SHA-256 digests "
                "(ledger entry hashes)"
            )
        anchors = tuple(dict.fromkeys(raw_anchors))
        if anchored_credit > _TOL and not anchors:
            raise BundleValidationError(
                f"reliability record '{name}': anchored credit "
                f"({anchored_credit!r}) is claimed without any anchor "
                "digests; anchored credit must name the ledger "
                "entries backing it (Spec 003 FR-3.7)"
            )
        return cls(
            observations=observations,
            brier_sum=min(max(brier_sum, 0.0), float(observations)),
            credit_weight=credit_weight,
            provenance=raw_provenance,
            anchored_credit_weight=min(max(anchored_credit, 0.0), credit_bound),
            anchored_brier_sum=min(max(anchored_brier, 0.0), max(anchored_credit, 0.0)),
            anchors=anchors,
        )


@dataclass(slots=True)
class ReliabilityTable:
    """Outcome history per source, with Brier-derived reliability.

    ``min_observations`` is the cold-start guard: for canonisation
    it is measured against each source's **anchored** effective
    credit, and for the provisional track against its total
    effective credit. Below the guard a source has a record but no
    measurement on that track, so scoring keeps the static prior —
    a source is neither canonized nor condemned on one outcome, or
    on a sliver of many outcomes, or (since FR-3.6) on any number
    of purely self-asserted outcomes.

    ``ledger`` binds the hash-chained ledger anchors resolve
    against. Anchored recording (``record(..., anchor=...)``,
    ``record_resolution()``, ``observe_claim_resolution()``)
    requires it; plain recording does not.
    """

    min_observations: int = 3
    records: dict[str, SourceRecord] = field(default_factory=dict)
    ledger: HashChainLedger | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.min_observations < 1:
            raise ValueError("min_observations must be >= 1")

    def _bound_entry_map(self) -> dict[str, dict[str, Any]]:
        if self.ledger is None:
            raise ValueError(
                "anchored recording requires a bound ledger: pass "
                "ledger=HashChainLedger(...) to ReliabilityTable so "
                "the anchor can be resolved and verified (Spec 003 "
                "FR-3.6)"
            )
        return _verified_entry_map(self.ledger)

    def record(
        self,
        source_id: str,
        predicted: float,
        outcome: bool,
        *,
        provenance: str | None = None,
        allow_unattributed: bool = False,
        anchor: ProvenanceAnchor | None = None,
    ) -> None:
        """Record one directly resolved (predicted, outcome) pair
        at full credit (share 1.0).

        Direct records must carry ``provenance`` — who/what
        resolved the claim (FR-3.5). Unattributed records are
        accepted only through the explicitly named
        ``allow_unattributed=True`` compatibility path and are
        marked as unattributed on the record.

        With ``anchor`` the observation also earns canonisation-
        grade credit (FR-3.6): the anchor is verified against the
        bound ledger before anything is recorded — its entry must
        record this exact resolution — and each anchor backs
        exactly one observation for a source. Without an anchor
        the observation is provisional credit only, however
        plausible the provenance string reads.
        """
        if provenance is None:
            if not allow_unattributed:
                raise ValueError(
                    "record() requires a provenance naming who/what "
                    "resolved the claim (Spec 003 FR-3.5); pass "
                    "allow_unattributed=True to use the explicitly "
                    "named compatibility path instead"
                )
            provenance = UNATTRIBUTED_PROVENANCE
        elif not provenance.strip():
            raise ValueError("record() provenance must be a non-empty string")
        if anchor is not None:
            entries = self._bound_entry_map()
            _resolve_anchor(
                entries,
                anchor,
                event_type=RESOLUTION_EVENT_TYPE,
                expected={
                    "source_id": source_id,
                    "predicted": float(predicted),
                    "outcome": bool(outcome),
                },
            )
            existing = self.records.get(source_id)
            if existing is not None and anchor.digest in existing.anchors:
                raise ValueError(
                    f"provenance anchor {anchor.digest} already backs "
                    f"an observation for source {source_id!r}; one "
                    "ledger entry canonises one observation (FR-3.6)"
                )
        self._apply(
            source_id,
            predicted,
            outcome,
            share=1.0,
            provenance=provenance,
            anchored=anchor is not None,
            anchor_digest=anchor.digest if anchor is not None else None,
        )

    def record_resolution(
        self,
        source_id: str,
        predicted: float,
        outcome: bool,
        *,
        provenance: str,
        actor: str = "aee",
    ) -> ProvenanceAnchor:
        """Append this resolution to the bound ledger and record
        it as anchored credit in one call — the honest resolver
        path (FR-3.6). Returns the minted anchor."""
        if self.ledger is None:
            raise ValueError(
                "record_resolution() requires a bound ledger: pass "
                "ledger=HashChainLedger(...) to ReliabilityTable"
            )
        if not provenance or not provenance.strip():
            raise ValueError("record_resolution() provenance must be a non-empty string")
        entry = self.ledger.append(
            RESOLUTION_EVENT_TYPE,
            {
                "source_id": source_id,
                "predicted": float(predicted),
                "outcome": bool(outcome),
                "provenance": provenance,
            },
            actor=actor,
        )
        anchor = ProvenanceAnchor(digest=str(entry["entry_hash"]))
        self.record(source_id, predicted, outcome, provenance=provenance, anchor=anchor)
        return anchor

    def _apply(
        self,
        source_id: str,
        predicted: float,
        outcome: bool,
        *,
        share: float,
        provenance: str,
        anchored: bool = False,
        anchor_digest: str | None = None,
    ) -> None:
        if not source_id:
            return
        if not math.isfinite(predicted) or not 0.0 <= predicted <= 1.0:
            raise ValueError("predicted must be between 0 and 1")
        if not 0.0 < share <= 1.0:
            raise ValueError("contribution share must lie in (0, 1]")
        rec = self.records.setdefault(source_id, SourceRecord())
        # Read effective credit BEFORE incrementing observations:
        # for a record whose credit_weight is still None (legacy /
        # hand-built), effective credit is derived from observations.
        credit = rec.effective_credit + share
        error = (predicted - (1.0 if outcome else 0.0)) ** 2
        rec.observations += 1
        rec.credit_weight = credit
        rec.brier_sum += share * error
        rec.provenance = provenance
        if anchored:
            rec.anchored_credit_weight += share
            rec.anchored_brier_sum += share * error
            if anchor_digest is not None and anchor_digest not in rec.anchors:
                rec.anchors = (*rec.anchors, anchor_digest)
            # The anchor was verified against the bound ledger by
            # the caller before this observation was applied.
            rec.anchors_verified = True

    def observe_claim(
        self,
        claim: Claim,
        score: ClaimScore,
        outcome: bool,
        *,
        provenance: str | None = None,
        anchor: ProvenanceAnchor | None = None,
    ) -> list[str]:
        """Credit a resolved claim to its supporting sources,
        weighted by contribution (FR-3.4).

        A source's share is its portion of the claim's total
        positive supporting evidence weight — the static kind x
        quality weights scoring uses, with duplicate items
        collapsed (FR-2.1) and empty-ref items weightless
        (FR-2.7). Zero-weight sources earn no record at all, so
        coattail sources are never canonised; a source's recorded
        Brier error and its effective credit both scale by its
        share, so a minor contributor to a failed claim takes a
        minor loss, not full blame. Returns the source ids
        credited. The prediction recorded is the claim's
        propagated score from the assessment being resolved — the
        credence the system actually held.

        With ``anchor`` every credited share also earns
        canonisation-grade credit (FR-3.6): the anchor must
        resolve, on the bound ledger's verified chain, to the
        ``claim.resolution`` entry recording this claim's outcome,
        and it backs one observation per credited source.
        """
        # Local import: scoring imports this module at module
        # level, so the weight tables are read lazily here to use
        # exactly the weights scoring used — never a second copy.
        from aee.scoring import _KIND_WEIGHTS, _SOURCE_WEIGHTS, _deduplicate

        prov = provenance if provenance is not None else OBSERVE_CLAIM_PROVENANCE
        if not prov.strip():
            raise ValueError("observe_claim() provenance must be a non-empty string")
        support = [
            item
            for item in claim.evidence
            if item.direction == EvidenceDirection.SUPPORTS and item.ref.strip()
        ]
        unique, _ = _deduplicate(support)
        per_source: dict[str, float] = {}
        for item in unique:
            weight = max(0.0, _KIND_WEIGHTS[item.kind]) * _SOURCE_WEIGHTS[item.source_quality]
            if weight <= 0.0:
                continue
            source_id = item.source_id or item.ref
            if not source_id:
                continue
            per_source[source_id] = per_source.get(source_id, 0.0) + weight
        total = sum(per_source.values())
        if total <= 0.0:
            return []
        if anchor is not None:
            entries = self._bound_entry_map()
            _resolve_anchor(
                entries,
                anchor,
                event_type=CLAIM_RESOLUTION_EVENT_TYPE,
                expected={"claim_id": claim.id, "outcome": bool(outcome)},
            )
            for source_id in per_source:
                existing = self.records.get(source_id)
                if existing is not None and anchor.digest in existing.anchors:
                    raise ValueError(
                        f"provenance anchor {anchor.digest} already "
                        f"backs an observation for source {source_id!r}; "
                        "one ledger entry canonises one observation "
                        "per source (FR-3.6)"
                    )
        credited: list[str] = []
        for source_id, weight in per_source.items():
            self._apply(
                source_id,
                score.propagated_score,
                outcome,
                share=weight / total,
                provenance=prov,
                anchored=anchor is not None,
                anchor_digest=anchor.digest if anchor is not None else None,
            )
            credited.append(source_id)
        return credited

    def observe_claim_resolution(
        self,
        claim: Claim,
        score: ClaimScore,
        outcome: bool,
        *,
        provenance: str | None = None,
        actor: str = "aee",
    ) -> list[str]:
        """Append this claim's resolution to the bound ledger and
        credit its sources as anchored in one call — the honest
        adjudication path (FR-3.6). Returns the credited source
        ids, exactly as ``observe_claim`` does."""
        if self.ledger is None:
            raise ValueError(
                "observe_claim_resolution() requires a bound ledger: "
                "pass ledger=HashChainLedger(...) to ReliabilityTable"
            )
        prov = provenance if provenance is not None else OBSERVE_CLAIM_PROVENANCE
        if not prov.strip():
            raise ValueError("observe_claim() provenance must be a non-empty string")
        entry = self.ledger.append(
            CLAIM_RESOLUTION_EVENT_TYPE,
            {"claim_id": claim.id, "outcome": bool(outcome), "provenance": prov},
            actor=actor,
        )
        anchor = ProvenanceAnchor(digest=str(entry["entry_hash"]))
        return self.observe_claim(claim, score, outcome, provenance=prov, anchor=anchor)

    def reliability(self, source_id: str) -> float | None:
        """Canonised (measured) reliability, or None.

        Canonisation is earned on the anchored track only
        (FR-3.6): the source's anchor digests must have been
        verified against a bound ledger and its anchored
        effective credit must reach the cold-start guard. A
        source with any amount of purely self-asserted history —
        and no verified anchored credit at the guard — returns
        None here, so scoring keeps its static prior. Guaranteed
        in ``[0, 1]`` when not None (FR-3.2)."""
        rec = self.records.get(source_id)
        if rec is None or not rec.anchors_verified:
            return None
        if rec.anchored_credit < self.min_observations:
            return None
        return rec.canonised_reliability

    def provisional_reliability(self, source_id: str) -> float | None:
        """Provisional reliability over the source's whole
        history, or None below the cold-start guard (FR-3.7).

        This is the self-asserted track's report: capped at
        ``PROVISIONAL_RELIABILITY_CAP`` and never consumed by
        scoring. It exists so an unanchored history is visible
        and labelled, not silently trusted and not silently
        erased."""
        rec = self.records.get(source_id)
        if rec is None or rec.effective_credit < self.min_observations:
            return None
        return rec.provisional_reliability

    def credit_status(self, source_id: str) -> str:
        """``"canonised"`` when ``reliability()`` measures the
        source, ``"provisional"`` when only its self-asserted
        history measures, else ``"unmeasured"`` (FR-3.7 labels)."""
        if self.reliability(source_id) is not None:
            return "canonised"
        if self.provisional_reliability(source_id) is not None:
            return "provisional"
        return "unmeasured"

    def verify_anchors(self, ledger: HashChainLedger) -> int:
        """Bind ``ledger`` and verify every record's claimed
        anchor digests against it (FR-3.7).

        The chain must verify and every digest must resolve to a
        real entry; an unresolvable digest is a loud error naming
        the source, not a quiet downgrade — a table that claims
        anchored credit it cannot show is corrupt data, in the
        same family as the poisoned tables FR-3.1 refuses. On
        success the records' anchors count as verified in this
        process and canonisation can activate. Returns the number
        of digests verified."""
        entries = _verified_entry_map(ledger)
        verified = 0
        for source_id, rec in self.records.items():
            for digest in rec.anchors:
                if digest not in entries:
                    raise BundleValidationError(
                        f"reliability record '{source_id}': anchor "
                        f"{digest} does not resolve to any entry in "
                        "the bound ledger; claimed anchored credit "
                        "cannot be verified (Spec 003 FR-3.7)"
                    )
                verified += 1
            if rec.anchors:
                rec.anchors_verified = True
        self.ledger = ledger
        return verified

    def to_dict(self) -> dict[str, object]:
        records: dict[str, object] = {}
        for key, rec in self.records.items():
            value = rec.to_dict()
            # FR-3.7: the credit state is part of the record's
            # public shape — a consumer can see whether a source
            # is canonised, merely provisional (with its capped
            # value), or unmeasured, without re-deriving it.
            value["credit_status"] = self.credit_status(key)
            value["canonised"] = self.reliability(key) is not None
            value["provisional_reliability"] = self.provisional_reliability(key)
            records[key] = value
        return {
            "min_observations": self.min_observations,
            "records": records,
        }

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], *, ledger: HashChainLedger | None = None
    ) -> ReliabilityTable:
        if not isinstance(value, dict):
            raise BundleValidationError(
                f"reliability table must be an object, got {type(value).__name__}"
            )
        raw_min = value.get("min_observations", 3)
        min_f = _finite_number("<table>", "min_observations", raw_min)
        if min_f < 1 or min_f != int(min_f):
            raise BundleValidationError(
                "reliability table: field 'min_observations' must be "
                f"a positive integer, got {raw_min!r}"
            )
        raw_records = value.get("records", {})
        if not isinstance(raw_records, dict):
            raise BundleValidationError(
                "reliability table: field 'records' must be an object "
                f"mapping source id to record, got {type(raw_records).__name__}"
            )
        table = cls(
            min_observations=int(min_f),
            records={
                key: SourceRecord.from_dict(rec, source_id=str(key))
                for key, rec in raw_records.items()
            },
        )
        if ledger is not None:
            # FR-3.7: claimed anchors are verified at load when
            # the consumer binds the ledger they should resolve
            # against. Without a ledger the tallies load as
            # unverified claims and canonise nothing.
            table.verify_anchors(ledger)
        return table


def blended_weight(
    item: Evidence,
    static_weight: float,
    table: ReliabilityTable | None,
    alpha: float,
) -> tuple[float, float | None]:
    """Blend a supporting item's static weight with measured reliability.

    Returns ``(weight, measured)`` where ``measured`` is the
    reliability used, or None when the static weight stands (no
    table, or the source is not canonised). Only canonised
    reliability blends (FR-3.6): a provisional, self-asserted
    measurement never moves a weight at any value. The returned
    weight is guaranteed in ``[0, 1]`` (FR-3.2): the blend of two
    in-range values is clamped, and a non-finite measurement
    degrades to the static weight, never out of range.
    """
    if table is None:
        return static_weight, None
    measured = table.reliability(item.source_id or item.ref)
    if measured is None or not math.isfinite(measured):
        return static_weight, None
    measured = _clamp01(measured)
    return _clamp01((1.0 - alpha) * static_weight + alpha * measured), measured
