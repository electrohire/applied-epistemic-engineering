"""Decomposition and attribution structure (Spec 004 R2, R4).

A headline claim (``Claim.headline``) must decompose into five
sub-claims, one per role in ``DECOMPOSITION_ROLES``, each linked via
the parent's ``depends_on`` and independently scored and staged
(R2.1/R2.2). The check is structural, not semantic (R2.4): the
engine verifies the roles exist and are linked; whether a sub-claim
actually discharges its role is a human judgment recorded through
stage events.

Consequences, both inspectable in the assessment:

- A missing required role is a failure mode, category
  ``decomposition_incomplete``, severity HIGH, and the parent's
  effective stage is capped at ``created`` until all five roles
  exist (R2.3). The weakest-link propagation over ``depends_on``
  already caps the parent's score by its weakest linked sub-claim;
  that mechanism is unchanged.
- Attribution is the ``attribution`` role sub-claim (R4.1/R4.2).
  When it is in a contested state - author status ``contradicted``,
  or carrying an unresolved HIGH/CRITICAL failure in a contradiction
  category - the parent's effective stage is capped at ``checked``
  (R4.3), and the cap record names the attribution claim's id. The
  cap lifts only when the attribution claim leaves the contested
  state through new evidence or a recorded disposition.
"""

from __future__ import annotations

from aee.model import (
    DECOMPOSITION_ROLES,
    STAGE_ORDER,
    Claim,
    ClaimStage,
    ClaimStatus,
    FailureMode,
    Severity,
)

__all__ = [
    "attribution_contests",
    "decomposition_failures",
    "effective_stage_overrides",
    "linked_subclaims",
    "missing_roles",
    "override_reasons",
]


def linked_subclaims(claim: Claim, by_id: dict[str, Claim]) -> list[Claim]:
    """The bundle claims a headline claim links as sub-claims."""
    return [by_id[ref] for ref in claim.depends_on if ref in by_id]


def missing_roles(claim: Claim, by_id: dict[str, Claim]) -> list[str]:
    """Required roles with no linked sub-claim (empty for non-headlines)."""
    if not claim.headline:
        return []
    present = {
        sub.role for sub in linked_subclaims(claim, by_id) if sub.role is not None
    }
    return [role for role in DECOMPOSITION_ROLES if role not in present]


def decomposition_failures(claims: list[Claim]) -> list[FailureMode]:
    """One `decomposition_incomplete` failure per incomplete headline."""
    by_id = {claim.id: claim for claim in claims}
    failures: list[FailureMode] = []
    for claim in claims:
        missing = missing_roles(claim, by_id)
        if not missing:
            continue
        failures.append(
            FailureMode(
                id=f"decomposition-incomplete-{claim.id}",
                claim_id=claim.id,
                challenge=(
                    "Headline claim lacks required decomposition: missing "
                    f"role(s): {', '.join(missing)} (Spec 004 R2.1)"
                ),
                breakpoint=(
                    "A headline result asserted without one of its five "
                    "required sub-claims being independently scored"
                ),
                severity=Severity.HIGH,
                category="decomposition_incomplete",
                recovery_hint=(
                    "Add a linked sub-claim (depends_on) carrying each missing "
                    "role, with its own evidence and falsification test"
                ),
            )
        )
    return failures


def _is_contested(attribution: Claim) -> bool:
    if attribution.status == ClaimStatus.CONTRADICTED:
        return True
    return any(
        not failure.resolved
        and failure.severity in (Severity.HIGH, Severity.CRITICAL)
        and "contradiction" in failure.category
        for failure in attribution.failures
    )


def attribution_contests(claims: list[Claim]) -> dict[str, str]:
    """Parent claim id -> attribution claim id, where contested (R4.3)."""
    by_id = {claim.id: claim for claim in claims}
    contests: dict[str, str] = {}
    for claim in claims:
        for sub in linked_subclaims(claim, by_id):
            if sub.role == "attribution" and _is_contested(sub):
                contests[claim.id] = sub.id
                break
    return contests


def effective_stage_overrides(claims: list[Claim]) -> dict[str, ClaimStage]:
    """Stage caps imposed by decomposition/attribution rules (P1).

    The lowest applicable cap wins: an incomplete headline is capped
    at ``created`` (R2.3); a contested attribution caps at
    ``checked`` (R4.3). Only claims whose stored stage exceeds the
    cap appear here.
    """
    by_id = {claim.id: claim for claim in claims}
    contests = attribution_contests(claims)
    overrides: dict[str, ClaimStage] = {}
    for claim in claims:
        caps: list[ClaimStage] = []
        if missing_roles(claim, by_id):
            caps.append(ClaimStage.CREATED)
        if claim.id in contests:
            caps.append(ClaimStage.CHECKED)
        if caps:
            lowest = min(caps, key=lambda stage: STAGE_ORDER[stage])
            if STAGE_ORDER[lowest] < STAGE_ORDER[claim.stage]:
                overrides[claim.id] = lowest
    return overrides


def override_reasons(claims: list[Claim], overrides: dict[str, ClaimStage]) -> dict[str, str]:
    """Human-readable rule names for each override, for cap records."""
    by_id = {claim.id: claim for claim in claims}
    contests = attribution_contests(claims)
    reasons: dict[str, str] = {}
    for claim in claims:
        if claim.id not in overrides:
            continue
        parts: list[str] = []
        missing = missing_roles(claim, by_id)
        if missing and overrides[claim.id] == ClaimStage.CREATED:
            parts.append(
                f"decomposition incomplete (R2.3): missing role(s): {', '.join(missing)}"
            )
        if claim.id in contests:
            parts.append(
                f"attribution claim '{contests[claim.id]}' is contested (R4.3)"
            )
        reasons[claim.id] = "; ".join(parts)
    return reasons
