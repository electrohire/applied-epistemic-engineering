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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aee.model import BundleValidationError, Claim, Evidence, EvidenceDirection

if TYPE_CHECKING:
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

# Float-representation tolerance for the range checks in
# ``from_dict``: a legitimately computed Brier sum can sit a few
# ULPs from its mathematical bound. Anything beyond this is a
# poisoned or corrupt value, not rounding.
_TOL = 1e-9


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
    """

    observations: int = 0
    brier_sum: float = 0.0
    credit_weight: float | None = None
    provenance: str = ""

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
        brier = self.brier
        return None if brier is None else _clamp01(1.0 - brier)

    def to_dict(self) -> dict[str, object]:
        return {
            "observations": self.observations,
            "brier_sum": self.brier_sum,
            "credit_weight": self.effective_credit,
            "provenance": self.provenance or LEGACY_PROVENANCE,
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
        return cls(
            observations=observations,
            brier_sum=min(max(brier_sum, 0.0), float(observations)),
            credit_weight=credit_weight,
            provenance=raw_provenance,
        )


@dataclass(slots=True)
class ReliabilityTable:
    """Outcome history per source, with Brier-derived reliability.

    ``min_observations`` is the cold-start guard, measured against
    each source's effective (share-weighted) credit: below it a
    source has a record but no measured reliability, so scoring
    keeps the static prior — a source is neither canonized nor
    condemned on one outcome, or on a sliver of many outcomes.
    """

    min_observations: int = 3
    records: dict[str, SourceRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.min_observations < 1:
            raise ValueError("min_observations must be >= 1")

    def record(
        self,
        source_id: str,
        predicted: float,
        outcome: bool,
        *,
        provenance: str | None = None,
        allow_unattributed: bool = False,
    ) -> None:
        """Record one directly resolved (predicted, outcome) pair
        at full credit (share 1.0).

        Direct records must carry ``provenance`` — who/what
        resolved the claim (FR-3.5). Unattributed records are
        accepted only through the explicitly named
        ``allow_unattributed=True`` compatibility path and are
        marked as unattributed on the record.
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
        self._apply(source_id, predicted, outcome, share=1.0, provenance=provenance)

    def _apply(
        self,
        source_id: str,
        predicted: float,
        outcome: bool,
        *,
        share: float,
        provenance: str,
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
        rec.observations += 1
        rec.credit_weight = credit
        rec.brier_sum += share * (predicted - (1.0 if outcome else 0.0)) ** 2
        rec.provenance = provenance

    def observe_claim(
        self,
        claim: Claim,
        score: ClaimScore,
        outcome: bool,
        *,
        provenance: str | None = None,
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
        credited: list[str] = []
        for source_id, weight in per_source.items():
            self._apply(
                source_id,
                score.propagated_score,
                outcome,
                share=weight / total,
                provenance=prov,
            )
            credited.append(source_id)
        return credited

    def reliability(self, source_id: str) -> float | None:
        """Measured reliability, or None while the source is
        unmeasured (effective credit below the cold-start guard).
        Guaranteed in ``[0, 1]`` when not None (FR-3.2)."""
        rec = self.records.get(source_id)
        if rec is None or rec.effective_credit < self.min_observations:
            return None
        return rec.reliability

    def to_dict(self) -> dict[str, object]:
        return {
            "min_observations": self.min_observations,
            "records": {key: rec.to_dict() for key, rec in self.records.items()},
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ReliabilityTable:
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
        return cls(
            min_observations=int(min_f),
            records={
                key: SourceRecord.from_dict(rec, source_id=str(key))
                for key, rec in raw_records.items()
            },
        )


def blended_weight(
    item: Evidence,
    static_weight: float,
    table: ReliabilityTable | None,
    alpha: float,
) -> tuple[float, float | None]:
    """Blend a supporting item's static weight with measured reliability.

    Returns ``(weight, measured)`` where ``measured`` is the
    reliability used, or None when the static weight stands (no
    table, or the source has not reached ``min_observations``).
    The returned weight is guaranteed in ``[0, 1]`` (FR-3.2): the
    blend of two in-range values is clamped, and a non-finite
    measurement degrades to the static weight, never out of range.
    """
    if table is None:
        return static_weight, None
    measured = table.reliability(item.source_id or item.ref)
    if measured is None or not math.isfinite(measured):
        return static_weight, None
    measured = _clamp01(measured)
    return _clamp01((1.0 - alpha) * static_weight + alpha * measured), measured
