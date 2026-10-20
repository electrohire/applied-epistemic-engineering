"""Adapter for the Spec Kit Evaluator Contract v1.0."""

from __future__ import annotations

import importlib
import json
from functools import lru_cache
from typing import Any, NoReturn

from aee._version import __version__
from aee.engine import Assessment
from aee.model import Claim, Evidence, Severity
from aee.schemas import evaluator_result_schema_path

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
                # Spec 003 FR-6.7: the producing engine's version rides
                # alongside the contract version (schema_version, above),
                # so a composed verdict can be traced to the engine that
                # produced it (RT4-M6 found no such trace).
                "engine_version": __version__,
                "aee_methodology_version": assessment.methodology_version,
                # Spec 004 P5 (R6/R8): the lane pair and the
                # residual-unknowns statement ride the contract, so
                # a composed result can present lane 1 and lane 2
                # side by side - and can never honestly present the
                # lane-1 outcome as the whole story. Lane 2 is state
                # (counts and stages), never a score, here as
                # everywhere.
                "lanes": {
                    "lane_1": assessment.lanes.get("lane_1", {}),
                    "lane_2": assessment.lanes.get("lane_2", {}),
                },
                # Spec 006 A2: the lane-1 outcome is forwarded as
                # its own field, distinct from the blended headline
                # outcome at the top of this result, so a consumer
                # can read machine verification's verdict without
                # unpacking the lane pair.
                "lane_1_outcome": assessment.lanes.get("lane_1", {}).get("outcome"),
                "headline_outcome": assessment.outcome,
                "not_understood": list(assessment.not_understood),
                "reported_statuses": dict(assessment.reported_statuses),
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


_SEVERITIES = {"critical", "high", "medium", "low", "info"}
_UNCERTAINTIES = {"none", "low", "medium", "high", "insufficient_evidence"}
_RECOMMENDED_ACTIONS = {
    "none",
    "gather_evidence",
    "clarify",
    "revise",
    "iterate",
    "escalate",
    "accept_risk",
    "block",
}
_EVIDENCE_REF_KINDS = {"observed", "inferred", "asserted", "contradicted", "unsupported"}
_TARGET_PHASES = {
    "specify",
    "plan",
    "tasks",
    "implement",
    "analyze",
    "checklist",
    "clarify",
    "constitution",
    "converge",
    None,
}
_ROUTING_TIERS = {"budget", "standard", "premium", "portfolio"}
_ESCALATE_TO = {"standard", "premium"}
_RESULT_KEYS = {
    "schema_version",
    "evaluator",
    "phase",
    "outcome",
    "summary",
    "findings",
    "next_action",
    "model_routing",
    "metadata",
    "state",
}
_EVALUATOR_KEYS = {"id", "version", "name", "url"}
_FINDING_KEYS = {
    "id",
    "severity",
    "kind",
    "subject",
    "description",
    "evidence_refs",
    "provenance_refs",
    "uncertainty",
    "recommended_action",
    "rationale",
}
_EVIDENCE_REF_KEYS = {"ref", "kind", "description"}
_NEXT_ACTION_KEYS = {"kind", "target_phase", "message"}
_MODEL_ROUTING_KEYS = {
    "recommended_tier",
    "reason",
    "escalation_triggers",
    "estimated_tokens",
    "estimated_cost_usd",
    "tier_breakdown",
}
_ESCALATION_TRIGGER_KEYS = {"condition", "escalate_to"}
_TIER_BREAKDOWN_KEYS = {"budget", "standard", "premium"}


@lru_cache(maxsize=1)
def _evaluator_result_schema() -> dict[str, Any]:
    """The vendored Evaluator Contract schema (see aee.schemas)."""
    loaded: dict[str, Any] = json.loads(evaluator_result_schema_path().read_text("utf-8"))
    return loaded


def validate_evaluator_result(result: dict[str, Any]) -> None:
    """Validate an evaluator result against the real contract schema.

    Spec 003 FR-6.7 / T609 (inverting RT4-M6): the previous hand-rolled
    check verified only five top-level keys and the finding ``kind``
    enum, so schema-invalid results — no ``evaluator.version``, a
    finding carrying nothing but ``kind`` — were ACCEPTED while the
    evaluator repo's shipped schema rejected them. This validator now
    delegates to that schema: a vendored copy ships in ``aee.schemas``
    and parity with spec-kit-evaluator's shipped schema is
    pinned by tests.

    When the ``jsonschema`` package is importable the vendored schema
    is applied with a Draft 2020-12 validator, exactly as the
    evaluator repo's composer applies it. The engine keeps
    ``jsonschema`` optional, so without it a dependency-free structural
    check enforces the same contract (required keys, enums, finding and
    evidence-ref shapes, no undeclared properties). Either way an
    invalid result is REFUSED with a ``ValueError`` naming the failing
    path — never silently trusted.

    The engine currently only *emits* evaluator results (``aee assess
    --evaluator-output``); every emitted result passes through here.
    There is no ingestion consumer yet — this public validator is the
    gate the first one must call.
    """
    try:
        # Dynamic import: jsonschema is an optional dependency of the
        # engine (absent from the pinned requirements), so it is not
        # imported statically.
        jsonschema: Any = importlib.import_module("jsonschema")
    except ImportError:
        _validate_evaluator_result_structural(result)
        return
    validator = jsonschema.Draft202012Validator(_evaluator_result_schema())
    errors = sorted(
        validator.iter_errors(result),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise ValueError(f"schema validation failed at {path}: {error.message}")


def _fail(path: str, detail: str) -> NoReturn:
    raise ValueError(f"schema validation failed at {path}: {detail}")


def _check_object(
    value: Any,
    path: str,
    *,
    required: set[str],
    allowed: set[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, f"{value!r} is not of type 'object'")
    missing = sorted(required - value.keys())
    if missing:
        _fail(path, f"{missing[0]!r} is a required property")
    extra = sorted(set(value) - allowed)
    if extra:
        _fail(path, f"additional property {extra[0]!r} is not allowed")
    return value


def _check_string(value: Any, path: str, *, max_length: int | None = None) -> str:
    if not isinstance(value, str):
        _fail(path, f"{value!r} is not of type 'string'")
    if max_length is not None and len(value) > max_length:
        _fail(path, f"{value!r} is too long ({len(value)} > {max_length})")
    return value


def _check_enum(value: Any, path: str, allowed: set[Any]) -> Any:
    if value not in allowed:
        _fail(path, f"{value!r} is not one of {sorted(allowed, key=repr)}")
    return value


def _check_array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(path, f"{value!r} is not of type 'array'")
    return value


def _check_integer(value: Any, path: str, *, minimum: int | None = None) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(path, f"{value!r} is not of type 'integer'")
    if minimum is not None and value < minimum:
        _fail(path, f"{value!r} is less than the minimum of {minimum}")


def _check_number(value: Any, path: str, *, minimum: int | None = None) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _fail(path, f"{value!r} is not of type 'number'")
    if minimum is not None and value < minimum:
        _fail(path, f"{value!r} is less than the minimum of {minimum}")


def _validate_evaluator_result_structural(result: dict[str, Any]) -> None:
    """Dependency-free mirror of the shipped schema (see above)."""
    root = _check_object(
        result,
        "<root>",
        required={"schema_version", "evaluator", "phase", "outcome", "findings"},
        allowed=_RESULT_KEYS,
    )
    _check_string(root["schema_version"], "schema_version")
    evaluator = _check_object(
        root["evaluator"], "evaluator", required={"id", "version"}, allowed=_EVALUATOR_KEYS
    )
    for key in ("id", "version", "name", "url"):
        if key in evaluator:
            _check_string(evaluator[key], f"evaluator.{key}")
    _check_enum(root["phase"], "phase", _ALLOWED_PHASES)
    _check_enum(root["outcome"], "outcome", _ALLOWED_OUTCOMES)
    if "summary" in root:
        _check_string(root["summary"], "summary", max_length=500)
    for index, finding in enumerate(_check_array(root["findings"], "findings")):
        _validate_finding(finding, f"findings[{index}]")
    if "next_action" in root:
        _validate_next_action(root["next_action"])
    if "model_routing" in root:
        _validate_model_routing(root["model_routing"])
    if "metadata" in root:
        _validate_metadata(root["metadata"])
    if "state" in root and not isinstance(root["state"], dict):
        _fail("state", f"{root['state']!r} is not of type 'object'")


def _validate_finding(finding: Any, path: str) -> None:
    item = _check_object(
        finding,
        path,
        required={"id", "severity", "kind", "subject"},
        allowed=_FINDING_KEYS,
    )
    _check_string(item["id"], f"{path}.id")
    _check_enum(item["severity"], f"{path}.severity", _SEVERITIES)
    _check_enum(item["kind"], f"{path}.kind", _FINDING_KINDS)
    _check_string(item["subject"], f"{path}.subject")
    if "description" in item:
        _check_string(item["description"], f"{path}.description", max_length=500)
    if "rationale" in item:
        _check_string(item["rationale"], f"{path}.rationale", max_length=500)
    if "uncertainty" in item:
        _check_enum(item["uncertainty"], f"{path}.uncertainty", _UNCERTAINTIES)
    if "recommended_action" in item:
        _check_enum(item["recommended_action"], f"{path}.recommended_action", _RECOMMENDED_ACTIONS)
    if "provenance_refs" in item:
        for ref_index, ref in enumerate(
            _check_array(item["provenance_refs"], f"{path}.provenance_refs")
        ):
            _check_string(ref, f"{path}.provenance_refs[{ref_index}]")
    if "evidence_refs" in item:
        for ref_index, ref in enumerate(
            _check_array(item["evidence_refs"], f"{path}.evidence_refs")
        ):
            ref_path = f"{path}.evidence_refs[{ref_index}]"
            evidence_ref = _check_object(
                ref, ref_path, required={"ref", "kind"}, allowed=_EVIDENCE_REF_KEYS
            )
            _check_string(evidence_ref["ref"], f"{ref_path}.ref")
            _check_enum(evidence_ref["kind"], f"{ref_path}.kind", _EVIDENCE_REF_KINDS)
            if "description" in evidence_ref:
                _check_string(evidence_ref["description"], f"{ref_path}.description")


def _validate_next_action(next_action: Any) -> None:
    item = _check_object(next_action, "next_action", required={"kind"}, allowed=_NEXT_ACTION_KEYS)
    _check_enum(item["kind"], "next_action.kind", _ALLOWED_OUTCOMES)
    if "target_phase" in item:
        _check_enum(item["target_phase"], "next_action.target_phase", _TARGET_PHASES)
    if "message" in item:
        _check_string(item["message"], "next_action.message", max_length=500)


def _validate_model_routing(model_routing: Any) -> None:
    item = _check_object(
        model_routing, "model_routing", required=set(), allowed=_MODEL_ROUTING_KEYS
    )
    if "recommended_tier" in item:
        _check_enum(item["recommended_tier"], "model_routing.recommended_tier", _ROUTING_TIERS)
    if "reason" in item:
        _check_string(item["reason"], "model_routing.reason", max_length=300)
    if "estimated_tokens" in item:
        _check_integer(item["estimated_tokens"], "model_routing.estimated_tokens", minimum=0)
    if "estimated_cost_usd" in item:
        _check_number(item["estimated_cost_usd"], "model_routing.estimated_cost_usd", minimum=0)
    if "escalation_triggers" in item:
        triggers = _check_array(item["escalation_triggers"], "model_routing.escalation_triggers")
        for index, trigger in enumerate(triggers):
            path = f"model_routing.escalation_triggers[{index}]"
            entry = _check_object(
                trigger,
                path,
                required={"condition", "escalate_to"},
                allowed=_ESCALATION_TRIGGER_KEYS,
            )
            _check_string(entry["condition"], f"{path}.condition")
            _check_enum(entry["escalate_to"], f"{path}.escalate_to", _ESCALATE_TO)
    if "tier_breakdown" in item:
        breakdown = _check_object(
            item["tier_breakdown"],
            "model_routing.tier_breakdown",
            required=set(),
            allowed=_TIER_BREAKDOWN_KEYS,
        )
        for tier, entry in breakdown.items():
            path = f"model_routing.tier_breakdown.{tier}"
            if not isinstance(entry, dict):
                _fail(path, f"{entry!r} is not of type 'object'")
            if "estimated_tokens" in entry:
                _check_integer(entry["estimated_tokens"], f"{path}.estimated_tokens")
            if "estimated_cost_usd" in entry:
                _check_number(entry["estimated_cost_usd"], f"{path}.estimated_cost_usd")


def _validate_metadata(metadata: Any) -> None:
    if not isinstance(metadata, dict):
        _fail("metadata", f"{metadata!r} is not of type 'object'")
    if "timestamp" in metadata:
        _check_string(metadata["timestamp"], "metadata.timestamp")
    if "duration_ms" in metadata:
        _check_integer(metadata["duration_ms"], "metadata.duration_ms")
    if "artifacts_evaluated" in metadata:
        for index, artifact in enumerate(
            _check_array(metadata["artifacts_evaluated"], "metadata.artifacts_evaluated")
        ):
            _check_string(artifact, f"metadata.artifacts_evaluated[{index}]")
    if "model" in metadata and metadata["model"] is not None:
        _check_string(metadata["model"], "metadata.model")
    if "deterministic" in metadata and not isinstance(metadata["deterministic"], bool):
        _fail("metadata.deterministic", f"{metadata['deterministic']!r} is not of type 'boolean'")


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
