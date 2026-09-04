"""Adapter for ElectroHire's Spec Kit Evaluator Contract v1.0."""

from __future__ import annotations

from typing import Any

from aee.engine import Assessment
from aee.model import Claim, Evidence, Severity

_ALLOWED_PHASES = {
    "after_specify",
    "after_plan",
    "after_tasks",
    "after_implement",
    "after_analyze",
    "after_checklist",
    "after_clarify",
    "after_constitution",
    "after_converge",
    "after_taskstoissues",
}
_ALLOWED_OUTCOMES = {"pass", "warn", "iterate", "clarify", "gather_evidence", "block"}
_FINDING_KINDS = {
    "unsupported_claim",
    "contradiction",
    "missing_evidence",
    "ambiguous_requirement",
    "unverified_assertion",
    "provenance_gap",
    "schema_violation",
    "policy_violation",
    "security_concern",
    "coverage_gap",
    "traceability_gap",
    "risk_unaddressed",
    "assumption_unvalidated",
    "other",
}


class EvaluatorAdapter:
    """Translate a rich AEE assessment into the shared evaluator envelope."""

    evaluator_version = "1.0.0"

    def to_evaluator_result(
        self,
        assessment: Assessment,
        *,
        artifacts: list[str] | None = None,
        model: str | None = None,
        deterministic: bool = False,
    ) -> dict[str, Any]:
        phase = _normalize_phase(assessment.phase)
        findings: list[dict[str, Any]] = []
        for claim in assessment.claims:
            findings.extend(self._findings_for_claim(claim))
        target_phase = _target_phase(assessment.outcome, phase)
        result = {
            "schema_version": "1.0",
            "evaluator": {
                "id": "aee",
                "version": self.evaluator_version,
                "name": "Applied Epistemic Engineering",
                "url": "https://github.com/electrohire/spec-kit-aee",
            },
            "phase": phase,
            "outcome": assessment.outcome,
            "summary": assessment.summary[:500],
            "findings": findings,
            "next_action": {
                "kind": assessment.outcome,
                "target_phase": target_phase,
                "message": _next_message(assessment.outcome, len(findings)),
            },
            "metadata": {
                "timestamp": assessment.created_at,
                "artifacts_evaluated": artifacts or [],
                "model": model,
                "deterministic": deterministic,
                "aee_methodology_version": assessment.methodology_version,
            },
            "state": {
                "aee": {
                    "project": assessment.project,
                    "claims": [claim.to_dict() for claim in assessment.claims],
                    "scores": {key: score.to_dict() for key, score in assessment.scores.items()},
                    "recoveries": [item.to_dict() for item in assessment.recoveries],
                }
            },
        }
        validate_evaluator_result(result)
        return result

    def _findings_for_claim(self, claim: Claim) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for failure in claim.unresolved_failures:
            kind = failure.category if failure.category in _FINDING_KINDS else "other"
            findings.append(
                {
                    "id": failure.id,
                    "severity": failure.severity.value,
                    "kind": kind,
                    "subject": claim.source_ref or claim.id,
                    "description": failure.breakpoint[:500],
                    "evidence_refs": [self._evidence_ref(item) for item in claim.evidence],
                    "provenance_refs": [
                        item for item in [claim.source_ref, *claim.depends_on] if item
                    ],
                    "uncertainty": claim.uncertainty.value,
                    "recommended_action": _action_for(failure.category, failure.severity),
                    "rationale": failure.challenge[:500],
                }
            )
        return findings

    @staticmethod
    def _evidence_ref(evidence: Evidence) -> dict[str, str]:
        item = {"ref": evidence.ref, "kind": evidence.kind.value}
        if evidence.description:
            item["description"] = evidence.description[:500]
        return item


def validate_evaluator_result(result: dict[str, Any]) -> None:
    """Dependency-free validation of the contract invariants AEE emits."""
    required = {"schema_version", "evaluator", "phase", "outcome", "findings"}
    missing = required - result.keys()
    if missing:
        raise ValueError(f"evaluator result missing fields: {sorted(missing)}")
    if result["schema_version"] != "1.0":
        raise ValueError("unsupported evaluator schema version")
    if result["phase"] not in _ALLOWED_PHASES:
        raise ValueError(f"unsupported evaluator phase: {result['phase']}")
    if result["outcome"] not in _ALLOWED_OUTCOMES:
        raise ValueError(f"unsupported evaluator outcome: {result['outcome']}")
    if not isinstance(result["findings"], list):
        raise ValueError("evaluator findings must be a list")
    for finding in result["findings"]:
        if finding.get("kind") not in _FINDING_KINDS:
            raise ValueError(f"unsupported finding kind: {finding.get('kind')}")


def _normalize_phase(phase: str) -> str:
    phase = phase if phase.startswith("after_") else f"after_{phase}"
    if phase not in _ALLOWED_PHASES:
        raise ValueError(f"unsupported evaluator phase: {phase}")
    return phase


def _target_phase(outcome: str, phase: str) -> str | None:
    if outcome != "iterate":
        return None
    return phase.removeprefix("after_")


def _next_message(outcome: str, finding_count: int) -> str:
    messages = {
        "pass": "No epistemic blockers found; continue to the next phase.",
        "warn": f"Continue with {finding_count} recorded warning(s).",
        "iterate": f"Revise the current phase to address {finding_count} finding(s).",
        "clarify": "Pause for human clarification; contradictory claims remain unresolved.",
        "gather_evidence": "Pause and collect independently inspectable evidence.",
        "block": "Stop; a critical epistemic failure must be resolved.",
    }
    return messages[outcome]


def _action_for(category: str, severity: Severity) -> str:
    if severity == Severity.CRITICAL:
        return "block"
    if category == "contradiction":
        return "clarify"
    if category in {"missing_evidence", "unsupported_claim", "unverified_assertion"}:
        return "gather_evidence"
    if category == "ambiguous_requirement":
        return "clarify"
    if category in {"coverage_gap", "assumption_unvalidated", "provenance_gap"}:
        return "revise"
    return "iterate"
