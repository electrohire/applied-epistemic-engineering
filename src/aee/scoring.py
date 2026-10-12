"""Transparent evidence-quality scoring and dependency propagation."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aee.graph import ClaimGraph
from aee.lexicons import (
    BOUNDARY_SCOPE_TERMS,
    COMPARATOR_PHRASES,
    FALSIFIABILITY_TERMS,
    PLACEHOLDER_TOKENS,
)
from aee.model import (
    Claim,
    ConfidenceBand,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    SourceQuality,
)
from aee.reliability import ReliabilityTable, blended_weight
from aee.sources import normalize_source_identity, source_identity

_SOURCE_WEIGHTS = {
    SourceQuality.TEST: 1.0,
    SourceQuality.PRIMARY: 0.95,
    SourceQuality.ARTIFACT: 0.90,
    SourceQuality.HUMAN: 0.70,
    SourceQuality.SECONDARY: 0.65,
    SourceQuality.TERTIARY: 0.40,
    SourceQuality.MODEL: 0.20,
    SourceQuality.UNKNOWN: 0.10,
}
_KIND_WEIGHTS = {
    EvidenceKind.OBSERVED: 1.0,
    EvidenceKind.INFERRED: 0.65,
    EvidenceKind.ASSERTED: 0.25,
    # Spec 004 R3.1: exposition (a named human's explanation) carries
    # asserted-level weight as evidence for the claim's truth - its
    # epistemic role is lane-2 (explanation), not verification.
    EvidenceKind.EXPOSITION: 0.25,
    EvidenceKind.CONTRADICTED: -0.75,
    EvidenceKind.UNSUPPORTED: 0.0,
}


@dataclass(slots=True)
class ClaimScore:
    claim_id: str
    direct_score: float
    propagated_score: float
    evidence_score: float
    independence_score: float
    falsifiability_score: float
    boundary_score: float
    contradiction_penalty: float
    notes: list[str] = field(default_factory=list)
    # Spec 003 FR-8.13(a): the author's declared state, surfaced
    # verbatim on every score record even where it does not move
    # the number - a score-only consumer must be able to tell a
    # claim its author marked `contradicted` from a settled one.
    declared_state: dict[str, object] = field(default_factory=dict)
    # Spec 003 FR-8.3: propagation state. "propagated" normally;
    # "suppressed_cycle" when the claim sits in a cyclic component
    # (its propagated score is then its direct score, and the
    # component is named). Scores are stored UNROUNDED (FR-8.13(b)):
    # threshold comparison happens on these values, and rounding is
    # a display concern only, applied by consumers that format.
    propagation_status: str = "propagated"
    cycle_component: list[str] = field(default_factory=list)

    @property
    def band(self) -> ConfidenceBand:
        return ConfidenceBand.from_score(self.propagated_score)

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "direct_score": self.direct_score,
            "propagated_score": self.propagated_score,
            "band": self.band.value,
            "components": {
                "evidence": self.evidence_score,
                "independence": self.independence_score,
                "falsifiability": self.falsifiability_score,
                "boundary": self.boundary_score,
                "contradiction_penalty": self.contradiction_penalty,
            },
            "declared_state": dict(self.declared_state),
            "propagation": {
                "status": self.propagation_status,
                "cycle_component": list(self.cycle_component),
            },
            "notes": list(self.notes),
        }


class ScoringEngine:
    """Score claims using published components, never hidden model confidence.

    With a ``reliability`` table attached, a supporting source's
    static quality weight blends toward its measured reliability
    (``1 - Brier`` over resolved claims it supported; see
    aee.reliability) by ``reliability_alpha``. Every substitution
    is recorded on the claim score's notes. Without a table the
    scoring is unchanged.
    """

    def __init__(
        self,
        reliability: ReliabilityTable | None = None,
        *,
        reliability_alpha: float = 0.5,
    ) -> None:
        if not 0.0 <= reliability_alpha <= 1.0:
            raise ValueError("reliability_alpha must be between 0 and 1")
        self.reliability = reliability
        self.reliability_alpha = reliability_alpha

    def score(
        self, claims: Iterable[Claim], *, as_of: datetime | None = None
    ) -> dict[str, ClaimScore]:
        """Score claims. ``as_of`` pins the instant freshness is judged
        against; the default is the current time. Pinning it makes an
        assessment replayable — previously the freshness penalty read
        the wall clock directly, so identical input scored differently
        on different days.

        Contract — mutation: each claim's ``confidence`` attribute is
        overwritten with its propagated score, so consumers reading
        the claim objects afterwards see the assessed values. The
        returned mapping is the authoritative per-claim record;
        re-scoring replaces the attribute again.
        """
        as_of = as_of or datetime.now(UTC)
        items = list(claims)
        scores = {claim.id: self._direct(claim, as_of) for claim in items}
        # Spec 003 FR-1.3 (RT1-12): duplicate claim ids must not crash
        # scoring. The stress tester has already minted the CRITICAL
        # duplicate-identity challenge that routes the assessment to
        # block; graph construction here therefore runs over the
        # first occurrence of each id (ClaimGraph.add refuses
        # duplicates by design, and that refusal stays for direct
        # graph consumers). Scores are keyed by id, so duplicates
        # share the one score record for their id.
        unique: dict[str, Claim] = {}
        for claim in items:
            unique.setdefault(claim.id, claim)
        graph = ClaimGraph(unique.values())
        # Spec 003 FR-8.3 (RT1-08): propagation is CYCLE-LOCAL. The
        # old rule skipped propagation for the whole graph when any
        # cycle existed anywhere, so one unrelated cycle silently
        # uncapped every claim. Now components are condensed and
        # processed dependency-first: a claim inside a cyclic
        # component keeps its direct score as its propagated score
        # and carries the suppression on its own score record; every
        # other claim propagates normally, including claims that
        # depend on a cyclic component (their cap uses the
        # component members' direct scores, which is the honest
        # weakest link available). The bundle-level cycle failure
        # still fires in the challenge pass.
        components = graph.strongly_connected_components()
        cyclic_components = graph.cyclic_components()
        cyclic_members = {member for comp in cyclic_components for member in comp}
        component_of: dict[str, list[str]] = {}
        for component in components:
            for member in component:
                component_of[member] = component
        for component in dependency_first_components(graph, components):
            for claim_id in component:
                claim_score = scores[claim_id]
                if claim_id in cyclic_members:
                    claim_score.propagation_status = "suppressed_cycle"
                    claim_score.cycle_component = list(component_of[claim_id])
                    claim_score.notes.append(
                        "Propagation suppressed (FR-8.3): claim is in "
                        f"dependency cycle component [{', '.join(component_of[claim_id])}]; "
                        "its propagated score is its direct score"
                    )
                    continue
                deps = graph.dependencies(claim_id)
                if deps:
                    weakest = min(scores[dep.id].propagated_score for dep in deps)
                    claim_score.propagated_score = min(claim_score.propagated_score, weakest)
                    if weakest < claim_score.direct_score:
                        claim_score.notes.append(f"Capped by weakest dependency at {weakest:.3f}")
        for claim in items:
            claim.confidence = scores[claim.id].propagated_score
        return scores

    def _direct(self, claim: Claim, as_of: datetime) -> ClaimScore:
        support = [item for item in claim.evidence if item.direction == EvidenceDirection.SUPPORTS]
        contradict = [
            item for item in claim.evidence if item.direction == EvidenceDirection.CONTRADICTS
        ]
        # FR-2.7 (RT1-23): an item with an empty ref is not inspectable
        # and earns no evidence weight. It is excluded here and noted
        # below; Spec 002 FR-3's verify-evidence is the full check.
        weighted_items = [item for item in support if item.ref.strip()]
        empty_ref_count = len(support) - len(weighted_items)
        # FR-2.1 (RT1-02): deduplicate by canonical identity before the
        # noisy-OR combination — repeating the identical item used to
        # add weight every time (20 copies of the weakest item crossed
        # the 0.70 threshold on zero new information). Duplicates still
        # count for freshness and the observed/support checks below:
        # repetition is not fabrication, it just adds no new support.
        unique_items, duplicate_count = _deduplicate(weighted_items)
        weighted = []
        reliability_notes: list[str] = []
        noted_sources: set[str] = set()
        for item in unique_items:
            static = _SOURCE_WEIGHTS[item.source_quality]
            weight, measured = blended_weight(
                item, static, self.reliability, self.reliability_alpha
            )
            if measured is not None:
                source_id = item.source_id or item.ref
                if source_id not in noted_sources:
                    noted_sources.add(source_id)
                    reliability_notes.append(
                        f"Source {source_id} weight {static:.2f} -> "
                        f"{weight:.2f} (measured reliability "
                        f"{measured:.3f})"
                    )
            weighted.append(max(0.0, _KIND_WEIGHTS[item.kind]) * weight)
        evidence_score = 1.0
        for value in weighted:
            evidence_score *= 1.0 - value
        evidence_score = 1.0 - evidence_score if weighted else 0.0

        independence_score, independence_basis, source_count = self._independence(support)
        # FR-8.7: substance over presence for falsifiability and
        # boundary - an entry earns full credit only against the
        # documented content criteria; present-but-below earns a
        # partial component and the failed criteria are named in the
        # notes below.
        falsifiability_score, falsifiability_notes = _substance_score(
            claim.falsification_tests, kind="falsification"
        )
        boundary_score, boundary_notes = _substance_score(claim.boundary, kind="boundary")
        contradiction_penalty = min(
            0.75,
            sum(
                abs(_KIND_WEIGHTS[item.kind]) * _SOURCE_WEIGHTS[item.source_quality]
                for item in contradict
            ),
        )
        freshness_penalty, freshness = self._freshness_penalty(support, as_of)
        unparseable_dates = freshness["unparseable"]

        direct = (
            0.55 * evidence_score
            + 0.20 * independence_score
            + 0.15 * falsifiability_score
            + 0.10 * boundary_score
            - contradiction_penalty
            - freshness_penalty
        )
        # FR-8.13(b): the stored score is the UNROUNDED value.
        # Rounding to 6 places used to happen here, which moved
        # 0.6999996 up to exactly 0.70 and across the threshold
        # (RT1-24). Rounding is a display concern only.
        direct = max(0.0, min(1.0, direct))
        notes: list[str] = []
        if duplicate_count:
            notes.append(
                f"Duplicate evidence: {duplicate_count} item(s) collapsed by "
                "canonical identity (FR-2.1); duplicates contribute once"
            )
        if empty_ref_count:
            notes.append(
                f"{empty_ref_count} supporting evidence item(s) had an empty "
                "ref and earned no evidence weight (FR-2.7)"
            )
        # FR-2.2 (RT1-03), scoring half: a contradicted-kind item routed
        # to context is visible here as well as in the challenge; the
        # item is never treated as support or contradiction by scoring
        # (its direction governs), but the mismatch is on the record.
        if any(
            item.kind == EvidenceKind.CONTRADICTED
            and item.direction != EvidenceDirection.CONTRADICTS
            for item in claim.evidence
        ):
            notes.append(
                "Polarity incoherence: contradicted-kind evidence is not routed "
                "as contradiction (FR-2.2); see the polarity challenge"
            )
        if not support:
            notes.append("No supporting evidence")
        if support and not any(item.kind == EvidenceKind.OBSERVED for item in support):
            notes.append("No observed supporting evidence")
        if source_count < 2:
            notes.append("Fewer than two independent supporting sources")
        # FR-6.4: the independence basis is always named — an assumption
        # surfaced, not buried. The inferred basis carries the caveat
        # that distinct references may share an origin (FR-6.1).
        if independence_basis == "declared":
            notes.append("Independence basis: declared (independent_of declarations honored)")
        elif independence_basis == "inferred-from-references":
            notes.append(
                "Independence basis: inferred-from-references (distinct references "
                "counted as independent; may overstate independence when "
                "references share an origin)"
            )
        else:
            notes.append("Independence basis: none (no identifiable supporting sources)")
        notes.extend(falsifiability_notes)
        notes.extend(boundary_notes)
        if freshness_penalty or freshness["unknown"]:
            # FR-8.6(e): the basis travels with the number - the set
            # composition that produced the penalty is on the record,
            # and unknown freshness is reported as unknown, never
            # silently treated as fresh.
            notes.append(
                f"Freshness penalty {freshness_penalty:.3f} on the supporting "
                f"set: {freshness['fresh']} fresh, {freshness['recent']} recent, "
                f"{freshness['stale']} stale, {freshness['unknown']} unknown "
                "of "
                f"{freshness['total']} item(s); unknown freshness counts as "
                "stale (FR-8.6)"
            )
        if unparseable_dates:
            notes.append(
                f"{unparseable_dates} supporting evidence item(s) had an "
                "unparseable observed_at: a freshness finding, counted as "
                "unknown/stale (FR-8.6)"
            )
        if freshness["future"]:
            notes.append(
                f"{freshness['future']} supporting evidence item(s) carry a "
                "future observed_at: invalid for freshness, counted as "
                "unknown - a future date can never make a claim fresher "
                "than present evidence (FR-8.6)"
            )
        if contradiction_penalty:
            notes.append(f"Contradiction penalty {contradiction_penalty:.3f}")
        notes.extend(reliability_notes)
        return ClaimScore(
            claim_id=claim.id,
            direct_score=direct,
            propagated_score=direct,
            evidence_score=evidence_score,
            independence_score=independence_score,
            falsifiability_score=falsifiability_score,
            boundary_score=boundary_score,
            contradiction_penalty=contradiction_penalty,
            notes=notes,
            declared_state={
                "status": claim.status.value,
                "uncertainty": claim.uncertainty.value,
                "severity": claim.severity.value,
                "conflicts_with": list(claim.conflicts_with),
            },
        )

    @staticmethod
    def _independence(support: Sequence[Evidence]) -> tuple[float, str, int]:
        """Independence component (Spec 002 FR-6.1/6.4; Spec 003 FR-2.4/2.5).

        Returns ``(score, basis, source_count)``. Only supporting items
        with positive evidence weight count (FR-2.4, RT1-06): a
        zero-weight item (``unsupported``/``contradicted`` kind) padded
        the source count for free before this phase, minting full
        independence from junk. Counted items are grouped by
        NORMALISED source identity (``aee.sources``, FR-2.5, RT1-14);
        items in one group count as ONE source. A declared
        ``independent_of`` entry naming another item (by ref or
        source_id, compared normalised) separates the two items even
        when they share an identity — declarations are honored, not
        ignored as they were when the field was write-only.

        Basis: ``declared`` when any independent_of declaration links
        two counted items, ``inferred-from-references`` when the count
        rests on distinct references alone, ``none`` when no counted
        item carries a source identity.
        """
        counted = [item for item in support if _KIND_WEIGHTS[item.kind] > 0]
        if not counted:
            return 0.0, "none", 0

        def identifiers(item: Evidence) -> set[str]:
            return {
                normalize_source_identity(value) for value in (item.source_id, item.ref) if value
            }

        def declared_pair(left: Evidence, right: Evidence) -> bool:
            left_declared = {normalize_source_identity(v) for v in left.independent_of}
            right_declared = {normalize_source_identity(v) for v in right.independent_of}
            return bool(left_declared & identifiers(right) or right_declared & identifiers(left))

        declared_any = any(
            declared_pair(left, right)
            for index, left in enumerate(counted)
            for right in counted[index + 1 :]
        )
        # Greedy grouping in evidence order: an item joins the first
        # same-identity group it is not declared independent of a
        # member of; otherwise it starts a new group (a new source).
        groups: list[tuple[str, list[Evidence]]] = []
        for item in counted:
            key = source_identity(item)
            if not key:
                continue
            for group_key, members in groups:
                if group_key == key and not any(declared_pair(item, member) for member in members):
                    members.append(item)
                    break
            else:
                groups.append((key, [item]))
        source_count = len(groups)
        if source_count == 0:
            return 0.0, "none", 0
        basis = "declared" if declared_any else "inferred-from-references"
        return min(1.0, source_count / 2.0), basis, source_count

    @staticmethod
    def _freshness_penalty(
        evidence: Sequence[Evidence], as_of: datetime
    ) -> tuple[float, dict[str, int]]:
        """Set-based freshness (Spec 003 FR-8.6, RT1-10).

        The basis is the whole SUPPORTING SET, never its newest
        member (the old rule read only the newest date, so one fresh
        or future-dated item erased the staleness of everything
        else, and undated evidence silently counted as fresh).
        Every supporting item is classified:

        - **fresh**: observed_at parses and is at most 90 days old;
        - **recent**: 91-365 days old;
        - **stale**: more than 365 days old;
        - **unknown**: no observed_at, an unparseable one (a finding,
          FR-8.6(b)), or a FUTURE one (invalid input, FR-8.6(c) -
          its age is never negative and it can never make a claim
          fresher than present evidence).

        The penalty is the mean of the per-item tier penalties
        (fresh 0, recent 0.05, stale 0.10) over the set, with
        UNKNOWN COUNTING AS STALE (FR-8.6(a): unknown freshness is
        reported as unknown in the notes and never treated as
        fresh). Tier magnitudes are unchanged from the pre-FR-8
        rule; what changed is the aggregation - that change is the
        methodology change FR-8.2 records. Returns (penalty,
        breakdown) where breakdown counts each class plus
        `unparseable` and `future` detail.
        """
        breakdown = {
            "fresh": 0,
            "recent": 0,
            "stale": 0,
            "unknown": 0,
            "unparseable": 0,
            "future": 0,
            "total": 0,
        }
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)
        tier_sum = 0.0
        for item in evidence:
            breakdown["total"] += 1
            observed_at = item.observed_at
            parsed: datetime | None = None
            if observed_at:
                try:
                    parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
                except ValueError:
                    breakdown["unparseable"] += 1
            if parsed is None:
                breakdown["unknown"] += 1
                tier_sum += 0.10
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            age_days = (as_of - parsed).days
            if age_days < 0:
                breakdown["future"] += 1
                breakdown["unknown"] += 1
                tier_sum += 0.10
            elif age_days <= 90:
                breakdown["fresh"] += 1
            elif age_days <= 365:
                breakdown["recent"] += 1
                tier_sum += 0.05
            else:
                breakdown["stale"] += 1
                tier_sum += 0.10
        if not breakdown["total"]:
            return 0.0, breakdown
        return tier_sum / breakdown["total"], breakdown


def dependency_first_components(graph: ClaimGraph, components: list[list[str]]) -> list[list[str]]:
    """Order strongly connected components so every component comes
    after the components it depends on (FR-8.3 propagation order)."""
    component_of: dict[str, int] = {}
    for index, component in enumerate(components):
        for member in component:
            component_of[member] = index
    prerequisites: list[set[int]] = [set() for _ in components]
    for index, component in enumerate(components):
        for member in component:
            for dep in graph.claims[member].depends_on:
                other = component_of.get(dep)
                if other is not None and other != index:
                    prerequisites[index].add(other)
    ordered: list[list[str]] = []
    done: set[int] = set()
    remaining = set(range(len(components)))
    while remaining:
        ready = sorted(i for i in remaining if prerequisites[i] <= done)
        if not ready:  # condensation is a DAG; unreachable defensively
            ready = [min(remaining)]
        for index in ready:
            ordered.append(components[index])
            done.add(index)
            remaining.discard(index)
    return ordered


# -- Spec 003 FR-8.7: substance over presence ------------------------------
#
# Before FR-8, falsifiability and boundary credit were presence
# booleans: `["x"]` and `["y"]` earned full components. An entry now
# earns FULL credit (1.0) only against the documented criteria for
# its kind, PARTIAL credit (0.5) when present but below them, and
# the score notes name the criteria each below-bar entry failed.
# The lexicons are versioned data (aee.lexicons, FR-8.8).

_PARTIAL_CREDIT = 0.5


def _is_placeholder(entry: str) -> bool:
    normalized = entry.strip().lower()
    if not normalized:
        return True
    if normalized in PLACEHOLDER_TOKENS:
        return True
    tokens = normalized.split()
    if len(tokens) == 1:
        return True  # a single token states no condition and no scope
    return len(set(normalized.replace(" ", ""))) == 1  # repeated character


def _falsification_credit(entry: str) -> tuple[float, list[str]]:
    """(credit, failed criteria) for one falsification-test entry."""
    failed: list[str] = []
    tokens = entry.split()
    if len(tokens) < 4:
        failed.append("fewer than four words")
    if _is_placeholder(entry):
        failed.append("placeholder content")
    lowered = f" {entry.lower()} "
    checkable = (
        any(char.isdigit() for char in entry)
        or any(symbol in entry for symbol in ("<", ">", "=", "≤", "≥"))
        or any(
            f" {phrase} " in lowered or lowered.strip().startswith(phrase)
            for phrase in COMPARATOR_PHRASES
        )
        or any(term in lowered for term in FALSIFIABILITY_TERMS)
    )
    if not checkable:
        failed.append(
            "no checkable condition (no numeric bound, comparator, or observation/action term)"
        )
    return (1.0 if not failed else _PARTIAL_CREDIT), failed


def _boundary_credit(entry: str) -> tuple[float, list[str]]:
    """(credit, failed criteria) for one boundary entry."""
    failed: list[str] = []
    if _is_placeholder(entry):
        failed.append("placeholder content")
    lowered = entry.lower()
    scoped = any(char.isdigit() for char in entry) or any(
        term in lowered for term in BOUNDARY_SCOPE_TERMS
    )
    if not scoped:
        failed.append("names no scope or limit (no scope term or numeric bound)")
    return (1.0 if not failed else _PARTIAL_CREDIT), failed


def _substance_score(entries: Sequence[str], *, kind: str) -> tuple[float, list[str]]:
    """Mean entry credit for a falsification/boundary list (FR-8.7).

    No entries still earns 0.0 (absence is not partial credit).
    Notes name the failed criteria for below-bar entries, capped at
    three named entries so a long list cannot flood the record.
    """
    if not entries:
        return 0.0, []
    credit_fn = _falsification_credit if kind == "falsification" else _boundary_credit
    credits: list[float] = []
    notes: list[str] = []
    for entry in entries:
        credit, failed = credit_fn(entry)
        credits.append(credit)
        if failed and len(notes) < 3:
            label = "Falsification test" if kind == "falsification" else "Boundary entry"
            notes.append(
                f"{label} {entry!r} earns partial credit (FR-8.7): "
                f"failed criteria: {'; '.join(failed)}"
            )
    return sum(credits) / len(credits), notes


def canonical_evidence_identity(item: Evidence) -> tuple[str, str, str, str, str]:
    """Canonical identity of an evidence item for deduplication (FR-2.1).

    Two items are the same evidence — repetition, not corroboration —
    when all five components match:

    - normalised ``ref`` (``aee.sources.normalize_source_identity``:
      whitespace/case/``./``/trailing-slash variants of one reference
      are one item);
    - normalised source identity (``source_id or ref``, normalised) —
      the same content arriving under a declared source identity is
      the same item even if the raw ref strings differ cosmetically;
    - ``kind`` — the same source asserting and observing are different
      epistemic acts;
    - ``source_quality`` — the same ref at a different declared
      quality is a different claim about the evidence;
    - ``direction`` — the same item cannot be both support and
      contradiction; direction keeps those apart (direction also
      partitions the scoring lists before dedup runs, so this is
      belt-and-braces).

    Deliberately NOT in the identity: ``description``, ``observed_at``,
    and ``content_hash`` — annotating or re-dating a copy does not
    make it new evidence. And deliberately strict: items differing in
    kind or quality are NOT merged, so dedup can never hide a genuine
    second measurement behind a cosmetic match.
    """
    return (
        normalize_source_identity(item.ref),
        source_identity(item),
        item.kind.value,
        item.source_quality.value,
        item.direction.value,
    )


def _deduplicate(items: Sequence[Evidence]) -> tuple[list[Evidence], int]:
    """First occurrence wins; returns (unique items, collapsed count)."""
    seen: set[tuple[str, str, str, str, str]] = set()
    unique: list[Evidence] = []
    for item in items:
        key = canonical_evidence_identity(item)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique, len(items) - len(unique)
