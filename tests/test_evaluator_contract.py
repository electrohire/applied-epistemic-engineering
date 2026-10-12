"""Spec 003 FR-6.7 / T609: the engine validates evaluator results
against the real Evaluator Contract schema.

Inverts RT4-M6: `validate_evaluator_result` used to check five
top-level keys, two enums, and the finding `kind` — and ACCEPTED
payloads the shipped schema rejects (no `evaluator.version`, a finding
carrying only `{"kind": "other"}`). The validator now delegates to the
schema the evaluator repo enforces (vendored in `aee.schemas`), with a
dependency-free structural mirror when `jsonschema` is unavailable.
Both paths must refuse every violation class by name, and both must
agree with the real schema on the evaluator repo's fixture corpus.
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from aee import AEEEngine, Claim, EvaluatorAdapter, __version__, validate_evaluator_result
from aee.adapters.evaluator import _validate_evaluator_result_structural
from aee.schemas import evaluator_result_schema_path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _evaluator_repo() -> Path | None:
    override = os.environ.get("AEE_EVALUATOR_REPO")
    candidates = [Path(override)] if override else []
    candidates.append(REPO_ROOT.parent / "spec-kit-evaluator")
    for candidate in candidates:
        if (candidate / "schemas" / "evaluator-result.schema.json").is_file():
            return candidate
    return None


def _valid_result() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "evaluator": {"id": "alpha", "version": "1.0.0", "name": "Alpha"},
        "phase": "after_specify",
        "outcome": "block",
        "summary": "One blocking finding.",
        "findings": [
            {
                "id": "ALPHA-001",
                "severity": "critical",
                "kind": "schema_violation",
                "subject": "spec.md",
                "description": "A blocking structural defect.",
                "evidence_refs": [{"ref": "spec.md", "kind": "observed"}],
                "provenance_refs": ["spec.md"],
                "uncertainty": "none",
                "recommended_action": "block",
                "rationale": "The spec cannot be implemented as written.",
            }
        ],
        "next_action": {"kind": "block", "target_phase": None, "message": "Stop."},
        "metadata": {"engine_version": "1.4.0", "deterministic": True},
    }


def _emitted_result() -> dict[str, Any]:
    claim = Claim(id="A", text="The service is fast")
    assessment = AEEEngine().assess([claim], phase="plan")
    result: dict[str, Any] = EvaluatorAdapter().to_evaluator_result(
        assessment, artifacts=["plan.md"]
    )
    return result


def test_emitted_result_validates() -> None:
    validate_evaluator_result(_emitted_result())
    _validate_evaluator_result_structural(_emitted_result())


def test_emitted_result_stamps_engine_version() -> None:
    """FR-6.7: the producing engine version rides alongside the
    contract version (schema_version) — RT4-M6 found no such trace."""
    result = _emitted_result()
    assert result["schema_version"] == "1.0"
    assert result["metadata"]["engine_version"] == __version__


def test_valid_handbuilt_result_validates() -> None:
    validate_evaluator_result(_valid_result())
    _validate_evaluator_result_structural(_valid_result())


def test_rt4_m6_poc_is_refused() -> None:
    """The red team's exact PoC: no evaluator.version, finding of only
    {"kind": "other"} — ACCEPTED by the old subset validator."""
    poc = {
        "schema_version": "1.0",
        "evaluator": {"id": "aee"},
        "phase": "after_specify",
        "outcome": "pass",
        "findings": [{"kind": "other"}],
    }
    with pytest.raises(ValueError, match="version"):
        validate_evaluator_result(poc)
    with pytest.raises(ValueError, match="version"):
        _validate_evaluator_result_structural(poc)


def _drop(key: str) -> Callable[[dict[str, Any]], None]:
    def mutate(result: dict[str, Any]) -> None:
        del result[key]

    return mutate


def _set(key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(result: dict[str, Any]) -> None:
        result[key] = value

    return mutate


def _finding_set(key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(result: dict[str, Any]) -> None:
        result["findings"][0][key] = value

    return mutate


def _finding_drop(key: str) -> Callable[[dict[str, Any]], None]:
    def mutate(result: dict[str, Any]) -> None:
        del result["findings"][0][key]

    return mutate


_VIOLATIONS: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
    ("missing_top_level_key", _drop("outcome"), "outcome"),
    ("missing_findings", _drop("findings"), "findings"),
    ("extra_top_level_property", _set("bogus_extra", True), "bogus_extra"),
    (
        "evaluator_missing_version",
        lambda r: r["evaluator"].pop("version"),
        "'version' is a required property",
    ),
    (
        "evaluator_missing_id",
        lambda r: r["evaluator"].pop("id"),
        "'id' is a required property",
    ),
    (
        "evaluator_extra_property",
        lambda r: r["evaluator"].update(bogus=1),
        "bogus",
    ),
    ("bad_phase", _set("phase", "during_lunch"), "during_lunch"),
    ("bad_outcome", _set("outcome", "explode"), "explode"),
    ("summary_too_long", _set("summary", "x" * 501), "too long"),
    ("findings_not_a_list", _set("findings", {}), "not of type 'array'"),
    ("finding_missing_id", _finding_drop("id"), "'id' is a required property"),
    (
        "finding_missing_severity",
        _finding_drop("severity"),
        "'severity' is a required property",
    ),
    (
        "finding_missing_subject",
        _finding_drop("subject"),
        "'subject' is a required property",
    ),
    ("bad_severity", _finding_set("severity", "catastrophic"), "catastrophic"),
    ("bad_kind", _finding_set("kind", "not_a_kind"), "not_a_kind"),
    ("finding_extra_property", _finding_set("extra", 1), "extra"),
    ("bad_uncertainty", _finding_set("uncertainty", "dunno"), "dunno"),
    ("bad_recommended_action", _finding_set("recommended_action", "nuke"), "nuke"),
    ("description_too_long", _finding_set("description", "x" * 501), "too long"),
    (
        "evidence_ref_missing_ref",
        lambda r: r["findings"][0]["evidence_refs"][0].pop("ref"),
        "'ref' is a required property",
    ),
    (
        "evidence_ref_bad_kind",
        lambda r: r["findings"][0]["evidence_refs"][0].update(kind="vibes"),
        "vibes",
    ),
    (
        "evidence_ref_extra_property",
        lambda r: r["findings"][0]["evidence_refs"][0].update(extra=1),
        "extra",
    ),
    (
        "provenance_ref_not_a_string",
        _finding_set("provenance_refs", [42]),
        "not of type 'string'",
    ),
    (
        "next_action_missing_kind",
        lambda r: r["next_action"].pop("kind"),
        "'kind' is a required property",
    ),
    (
        "next_action_bad_target_phase",
        lambda r: r["next_action"].update(target_phase="lunch"),
        "lunch",
    ),
    ("model_routing_null", _set("model_routing", None), "not of type 'object'"),
    (
        "model_routing_bad_tier",
        _set("model_routing", {"recommended_tier": "luxury"}),
        "luxury",
    ),
]


@pytest.mark.parametrize(
    "mutate,fragment",
    [pytest.param(mutate, fragment, id=name) for name, mutate, fragment in _VIOLATIONS],
)
def test_violation_classes_refused_by_name(
    mutate: Callable[[dict[str, Any]], None], fragment: str
) -> None:
    """Every contract violation class is refused, with the offending
    property/value named, on BOTH validation paths."""
    for validator in (validate_evaluator_result, _validate_evaluator_result_structural):
        result = _valid_result()
        mutate(result)
        with pytest.raises(ValueError) as excinfo:
            validator(result)
        assert fragment in str(excinfo.value), (validator.__name__, excinfo.value)


def test_vendored_schema_matches_specify_copy() -> None:
    """The package schema and the vendored extension copy in this repo
    are the same contract (guards against a stale package copy)."""
    vendored = json.loads(
        (
            REPO_ROOT
            / ".specify"
            / "extensions"
            / "evaluator"
            / "schemas"
            / "evaluator-result.schema.json"
        ).read_text("utf-8")
    )
    packaged = json.loads(evaluator_result_schema_path().read_text("utf-8"))
    assert packaged == vendored


def test_vendored_schema_matches_evaluator_repo() -> None:
    repo = _evaluator_repo()
    if repo is None:
        pytest.skip("sibling spec-kit-evaluator checkout not present")
    shipped = json.loads((repo / "schemas" / "evaluator-result.schema.json").read_text("utf-8"))
    packaged = json.loads(evaluator_result_schema_path().read_text("utf-8"))
    assert packaged == shipped


def test_fixture_corpus_agreement() -> None:
    """The evaluator repo's compose fixture corpus: the real schema,
    the public validator, and the structural mirror all return the
    same verdict for every parseable result file."""
    jsonschema = pytest.importorskip("jsonschema")
    repo = _evaluator_repo()
    if repo is None:
        pytest.skip("sibling spec-kit-evaluator checkout not present")
    schema = json.loads((repo / "schemas" / "evaluator-result.schema.json").read_text("utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    corpus = sorted((repo / "tests" / "fixtures" / "compose").glob("*/results/*.json"))
    assert len(corpus) >= 10, "fixture corpus unexpectedly small"
    verdicts: dict[str, bool] = {}
    for fixture in corpus:
        try:
            data = json.loads(fixture.read_text("utf-8"))
        except json.JSONDecodeError:
            # Refused at parse time, before any validator runs — the
            # malformed/ corpus case; not a validator verdict.
            continue
        schema_valid = validator.is_valid(data)
        for candidate in (validate_evaluator_result, _validate_evaluator_result_structural):
            try:
                candidate(copy.deepcopy(data))
                candidate_valid = True
            except ValueError:
                candidate_valid = False
            assert candidate_valid == schema_valid, (
                fixture.name,
                candidate.__name__,
                f"schema says {schema_valid}",
            )
        verdicts[fixture.parent.parent.name] = schema_valid
    # The corpus really does exercise both verdicts.
    assert verdicts["invalid-schema"] is False
    assert verdicts["valid-pass"] is True
    assert verdicts["engine-path"] is True
    # Phase-vs-filename mismatch is a composer rule (FR-6.5), not a
    # schema violation: the payload itself is contract-valid.
    assert verdicts["phase-mismatch"] is True
