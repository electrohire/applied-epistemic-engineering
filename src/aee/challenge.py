"""Deterministic adversarial checks for claim systems."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from aee.graph import ClaimGraph
from aee.model import (
    Claim,
    ClaimKind,
    ClaimStatus,
    EvidenceDirection,
    EvidenceKind,
    FailureMode,
    Severity,
    SourceQuality,
)

_VAGUE = re.compile(
    r"\b(appropriate|best|easy|efficient|fast|good|high[- ]quality|normal|"
    r"reasonable|robust|scalable|secure|significant|simple|soon|user[- ]friendly)\b",
    re.IGNORECASE,
)
_COMPOUND = re.compile(r"[,;]|\b(and|or|while|unless|except)\b", re.IGNORECASE)
_ABSOLUTE = re.compile(r"\b(always|never|all|none|guarantee[sd]?|impossible)\b", re.IGNORECASE)


class StressTester:
    """Apply transparent checks; it does not pretend to establish truth."""

    def run(self, claims: Iterable[Claim]) -> list[FailureMode]:
        items = list(claims)
        graph = ClaimGraph()
        failures: list[FailureMode] = []
        seen: Counter[str] = Counter(claim.id for claim in items)

        for claim_id, count in sorted(seen.items()):
            if count > 1:
                failures.append(
                    self._failure(
                        claim_id,
                        "Duplicate identity challenge",
                        f"{count} claims share the same identifier",
                        Severity.CRITICAL,
                        "contradiction",
                        "Assign stable, unique claim identifiers.",
                    )
                )
        for claim in items:
            if claim.id not in graph.claims:
                graph.add(claim)
            failures.extend(self._test_claim(claim))

        report = graph.report()
        for claim_id, missing in sorted(report.missing_dependencies.items()):
            failures.append(
                self._failure(
                    claim_id,
                    "Dependency existence challenge",
                    f"Referenced dependencies do not exist: {', '.join(missing)}",
                    Severity.HIGH,
                    "provenance_gap",
                    "Add the missing claims or remove the invalid dependency links.",
                )
            )
        for cycle in report.cycles:
            failures.append(
                self._failure(
                    cycle[0],
                    "Circular inference challenge",
                    "Dependency cycle: " + " -> ".join(cycle),
                    Severity.HIGH,
                    "contradiction",
                    "Break the cycle with independently observed evidence.",
                )
            )
        for left, right in report.conflicts:
            failures.append(
                self._failure(
                    left,
                    "Declared contradiction challenge",
                    f"{left} conflicts with {right}",
                    Severity.HIGH,
                    "contradiction",
                    "Preserve both claims and obtain discriminating evidence.",
                )
            )
        failures.extend(self._implicit_negation_conflicts(items))

        by_claim: dict[str, list[FailureMode]] = {}
        for failure in failures:
            by_claim.setdefault(failure.claim_id, []).append(failure)
        for claim in items:
            claim.failures = by_claim.get(claim.id, [])
        return failures

    def _test_claim(self, claim: Claim) -> list[FailureMode]:
        failures: list[FailureMode] = []
        if not claim.text.strip():
            failures.append(
                self._failure(
                    claim.id,
                    "Observability challenge",
                    "Claim has no inspectable proposition",
                    Severity.CRITICAL,
                    "missing_claim",
                    "Write one atomic proposition.",
                )
            )
            return failures
        if not claim.boundary:
            failures.append(
                self._failure(
                    claim.id,
                    "Boundary challenge",
                    "Scope and operating assumptions are not explicit",
                    Severity.HIGH,
                    "assumption_unvalidated",
                    "Declare where, when, and under which assumptions the claim holds.",
                )
            )
        if _VAGUE.search(claim.text):
            failures.append(
                self._failure(
                    claim.id,
                    "Precision challenge",
                    "Claim contains an undefined or non-measurable term",
                    Severity.MEDIUM,
                    "ambiguous_requirement",
                    "Replace vague language with a threshold, observable, or decision rule.",
                )
            )
        if _COMPOUND.search(claim.text):
            failures.append(
                self._failure(
                    claim.id,
                    "Irreducibility challenge",
                    "Claim may contain multiple independently falsifiable propositions",
                    Severity.MEDIUM,
                    "coverage_gap",
                    "Split the claim into atomic propositions and link them explicitly.",
                )
            )
        if _ABSOLUTE.search(claim.text) and not claim.boundary:
            failures.append(
                self._failure(
                    claim.id,
                    "Counterexample challenge",
                    "Absolute language is used without a bounded domain",
                    Severity.HIGH,
                    "assumption_unvalidated",
                    "Narrow the claim or document evidence covering the entire domain.",
                )
            )
        if not claim.falsification_tests and claim.status != ClaimStatus.DRAFT:
            failures.append(
                self._failure(
                    claim.id,
                    "Falsifiability challenge",
                    "Non-draft claim has no stated falsification test",
                    Severity.HIGH,
                    "missing_evidence",
                    "Define an observation that would show the claim is wrong.",
                )
            )
        supporting = [
            item for item in claim.evidence if item.direction == EvidenceDirection.SUPPORTS
        ]
        observed_support = [item for item in supporting if item.kind == EvidenceKind.OBSERVED]
        if (
            claim.status in {ClaimStatus.SUPPORTED, ClaimStatus.PARTIALLY_SUPPORTED}
            and not observed_support
        ):
            failures.append(
                self._failure(
                    claim.id,
                    "Evidence-grounding challenge",
                    "Claim is labeled supported without observed supporting evidence",
                    Severity.HIGH,
                    "unsupported_claim",
                    "Attach independently inspectable evidence or downgrade the status.",
                )
            )
        if supporting and all(item.is_model_self_attestation for item in supporting):
            failures.append(
                self._failure(
                    claim.id,
                    "Independent-evidence challenge",
                    "Only model self-attestation supports the claim",
                    Severity.HIGH,
                    "unverified_assertion",
                    "Obtain evidence from a test, artifact, primary source, or human observation.",
                )
            )
        if claim.kind == ClaimKind.COMPLIANCE and not any(
            item.source_quality in {SourceQuality.PRIMARY, SourceQuality.TEST}
            and item.kind == EvidenceKind.OBSERVED
            for item in supporting
        ):
            failures.append(
                self._failure(
                    claim.id,
                    "Authority challenge",
                    "Compliance claim lacks observed primary-authority or test evidence",
                    Severity.HIGH,
                    "missing_evidence",
                    "Cite the controlling text and attach assessment evidence.",
                )
            )
        if any(item.direction == EvidenceDirection.CONTRADICTS for item in claim.evidence):
            failures.append(
                self._failure(
                    claim.id,
                    "Counterevidence challenge",
                    "Recorded evidence contradicts the claim",
                    Severity.HIGH,
                    "contradiction",
                    "Resolve, narrow, or supersede the claim without deleting counterevidence.",
                )
            )
        return failures

    def _implicit_negation_conflicts(self, claims: list[Claim]) -> list[FailureMode]:
        failures: list[FailureMode] = []
        for index, left in enumerate(claims):
            left_tokens = self._tokens(left.text)
            for right in claims[index + 1 :]:
                right_tokens = self._tokens(right.text)
                if len(left_tokens & right_tokens) < 3:
                    continue
                left_neg = bool(re.search(r"\b(not|never|no|must not|cannot)\b", left.text, re.I))
                right_neg = bool(re.search(r"\b(not|never|no|must not|cannot)\b", right.text, re.I))
                if left_neg != right_neg:
                    failures.append(
                        self._failure(
                            left.id,
                            "Negation conflict challenge",
                            f"{left.id} may contradict {right.id}",
                            Severity.MEDIUM,
                            "contradiction",
                            (
                                "Confirm whether the claims share a boundary and preserve both "
                                "pending review."
                            ),
                        )
                    )
        return failures

    @staticmethod
    def _tokens(text: str) -> set[str]:
        stop = {"a", "an", "and", "be", "is", "must", "not", "of", "or", "the", "to"}
        return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in stop}

    @staticmethod
    def _failure(
        claim_id: str,
        challenge: str,
        breakpoint: str,
        severity: Severity,
        category: str,
        recovery_hint: str,
    ) -> FailureMode:
        slug = re.sub(r"[^A-Z0-9]+", "-", challenge.upper()).strip("-")[:24]
        return FailureMode(
            id=f"AEE-{claim_id}-{slug}",
            claim_id=claim_id,
            challenge=challenge,
            breakpoint=breakpoint,
            severity=severity,
            category=category,
            recovery_hint=recovery_hint,
        )
