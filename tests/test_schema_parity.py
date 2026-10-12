"""Spec 003 FR-5.9 (T509): schema authority and loader parity.

Inverts RT2-M9 (the engine emitted assessments its own shipped
schema rejected — `abstain`, `ref: ""`, unspecified `verdicts`) and
RT2-L4 (no input-bundle schema existed at all):

- `claim.schema.json` is the bundle contract: its enums ARE the
  model's enums, its required fields and additionalProperties match
  the strict loader's field sets, and a generated corpus of valid
  and invalid bundles is accepted/rejected IDENTICALLY by the
  schema and by `load_claims` (strict).
- `aee-assessment.schema.json` validates real engine output,
  including policy verdicts, an abstain outcome, and empty-ref
  evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

jsonschema = pytest.importorskip("jsonschema")

from aee import AEEEngine  # noqa: E402
from aee.extract import load_claims  # noqa: E402
from aee.model import (  # noqa: E402
    Claim,
    ClaimKind,
    ClaimStage,
    ClaimStatus,
    DispositionKind,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    Severity,
    SourceQuality,
    Uncertainty,
)
from aee.policy import AssessmentPolicy  # noqa: E402
from aee.schemas import assessment_schema_path, claims_schema_path  # noqa: E402


def _schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


CLAIM_SCHEMA = _schema(claims_schema_path())
ASSESSMENT_SCHEMA = _schema(assessment_schema_path())
REPO_ROOT = Path(__file__).parent.parent


def _enum_values(schema: dict[str, Any], *keys: str) -> set[str]:
    node: Any = schema
    for key in keys:
        node = node[key]
    return set(node)


def test_both_schemas_are_valid_json_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(CLAIM_SCHEMA)
    jsonschema.Draft202012Validator.check_schema(ASSESSMENT_SCHEMA)


def test_claim_schema_enums_are_the_model_enums() -> None:
    defs = ("$defs", "claim", "properties")
    assert _enum_values(CLAIM_SCHEMA, *defs, "kind", "enum") == {m.value for m in ClaimKind}
    assert _enum_values(CLAIM_SCHEMA, *defs, "status", "enum") == {m.value for m in ClaimStatus}
    assert _enum_values(CLAIM_SCHEMA, *defs, "stage", "enum") == {m.value for m in ClaimStage}
    assert _enum_values(CLAIM_SCHEMA, "$defs", "stage_event", "properties", "kind", "enum") == {
        m.value for m in ClaimStage
    }
    assert _enum_values(CLAIM_SCHEMA, *defs, "uncertainty", "enum") == {
        m.value for m in Uncertainty
    }
    assert _enum_values(CLAIM_SCHEMA, *defs, "severity", "enum") == {m.value for m in Severity}
    ev = ("$defs", "evidence", "properties")
    assert _enum_values(CLAIM_SCHEMA, *ev, "kind", "enum") == {m.value for m in EvidenceKind}
    assert _enum_values(CLAIM_SCHEMA, *ev, "direction", "enum") == {
        m.value for m in EvidenceDirection
    }
    assert _enum_values(CLAIM_SCHEMA, *ev, "source_quality", "enum") == {
        m.value for m in SourceQuality
    }
    assert _enum_values(CLAIM_SCHEMA, "$defs", "disposition", "properties", "kind", "enum") == {
        m.value for m in DispositionKind
    }
    assert _enum_values(CLAIM_SCHEMA, "$defs", "failure", "properties", "severity", "enum") == {
        m.value for m in Severity
    }


def test_claim_schema_fields_match_model_field_sets() -> None:
    from aee.model import Disposition as DispositionModel
    from aee.model import Evidence as EvidenceModel
    from aee.model import FailureMode

    assert set(CLAIM_SCHEMA["$defs"]["claim"]["properties"]) == set(Claim._FIELDS)
    assert set(CLAIM_SCHEMA["$defs"]["evidence"]["properties"]) == set(EvidenceModel._FIELDS)
    assert set(CLAIM_SCHEMA["$defs"]["failure"]["properties"]) == set(FailureMode._FIELDS)
    assert set(CLAIM_SCHEMA["$defs"]["disposition"]["properties"]) == set(DispositionModel._FIELDS)
    for name in ("claim", "evidence", "failure", "disposition"):
        assert CLAIM_SCHEMA["$defs"][name]["additionalProperties"] is False
    # Spec 004 R1.1: stage joins the required set - the schema and
    # the strict loader name the same missing field on old bundles.
    assert CLAIM_SCHEMA["$defs"]["claim"]["required"] == ["id", "text", "stage"]
    assert CLAIM_SCHEMA["$defs"]["evidence"]["required"] == ["ref"]
    assert CLAIM_SCHEMA["$defs"]["failure"]["required"] == ["id", "claim_id", "challenge"]
    assert CLAIM_SCHEMA["$defs"]["disposition"]["required"] == ["challenge_category", "reason"]


# ---------------------------------------------------------------------
# Generated corpus: schema and strict loader must agree on every case
# ---------------------------------------------------------------------

_FULL_CLAIM: dict[str, Any] = {
    "id": "C-1",
    "text": "The widget returns within 100 ms under load profile L",
    "kind": "requirement",
    "status": "supported",
    "boundary": ["load profile L"],
    "depends_on": ["C-0"],
    "conflicts_with": [],
    "assumptions": ["load profile L is representative"],
    "alternatives": ["raise the budget"],
    "falsification_tests": ["Run load profile L and observe p95 above 100 ms"],
    "uncertainty": "low",
    "severity": "high",
    "source_ref": "spec.md#C-1",
    "domain": "performance",
    "confidence": 0.5,
    "evidence": [
        {
            "ref": "reports/load.json",
            "kind": "observed",
            "direction": "supports",
            "source_quality": "test",
            "description": "p95 was 83 ms",
            "source_id": "load-test-1",
            "independent_of": [],
            "observed_at": "2026-09-04T00:00:00Z",
            "content_hash": None,
        },
        # An empty ref loads (it earns no weight, FR-2.7).
        {"ref": "", "kind": "asserted", "direction": "context"},
    ],
    "failures": [
        {
            "id": "F-1",
            "claim_id": "C-1",
            "challenge": "no_counterexample_search",
            "breakpoint": "falsifiability",
            "severity": "low",
            "category": "falsifiability",
            "recovery_hint": "search harder",
            "resolved": True,
            "disposition": None,
        }
    ],
    "stage": "accepted",
    "stage_events": [
        {"kind": "accepted", "author": "reviewer", "date": "2026-10-12", "basis": "reviewed"}
    ],
    "metadata": {"origin": "corpus"},
    "dispositions": [
        {
            "challenge_category": "irreducibility",
            "kind": "accepted-atomic",
            "reason": "reviewed by a human",
            "author": "reviewer",
            "date": "2026-10-12",
            "successors": [],
        }
    ],
}


def _bundle(claim: Any) -> dict[str, Any]:
    return {"schema_version": "1.0", "claims": [claim]}


def _variant(**changes: Any) -> dict[str, Any]:
    claim = json.loads(json.dumps(_FULL_CLAIM))
    claim.update(changes)
    return _bundle(claim)


CORPUS: list[tuple[str, Any, bool]] = [
    # --- valid under both ---
    ("minimal claim with stage", _bundle({"id": "C-1", "text": "t", "stage": "created"}), True),
    # Spec 004 R1.1: a claim without a stage is invalid under both.
    ("claim without stage", _bundle({"id": "C-1", "text": "t"}), False),
    ("bad stage enum", _variant(stage="settled"), False),
    ("stage event without basis", _variant(stage_events=[{"kind": "checked"}]), False),
    ("full claim", _bundle(_FULL_CLAIM), True),
    ("empty claims list", {"claims": []}, True),
    ("bare list bundle", [_FULL_CLAIM], True),
    ("extra top-level keys", {"claims": [], "spec": "003", "date": "2026-10-12"}, True),
    ("confidence null", _variant(confidence=None), True),
    ("confidence zero", _variant(confidence=0), True),
    ("confidence one", _variant(confidence=1), True),
    # confidence_band is a known field the loader accepts and ignores.
    ("confidence_band arbitrary", _variant(confidence_band="banana"), True),
    ("confidence_band non-string", _variant(confidence_band=42), True),
    ("TODOIST is not a TODO placeholder", _variant(falsification_tests=["TODOIST parsing"]), True),
    (
        "disposition without kind (defaulted)",
        _variant(dispositions=[{"challenge_category": "x", "reason": "y"}]),
        True,
    ),
    # --- invalid under both ---
    ("missing text", _bundle({"id": "C-1"}), False),
    ("blank id", _variant(id="   "), False),
    ("blank text", _variant(text=" "), False),
    ("unknown claim field", _variant(bogus_field=1), False),
    ("bad kind enum", _variant(kind="design"), False),
    ("bad status enum", _variant(status="done"), False),
    ("boundary as bare string", _variant(boundary="production"), False),
    (
        "falsification test TODO placeholder",
        _variant(falsification_tests=["TODO: write it"]),
        False,
    ),
    ("falsification test non-string", _variant(falsification_tests=[42]), False),
    ("confidence bool", _variant(confidence=True), False),
    ("confidence string", _variant(confidence="0.9"), False),
    ("confidence above range", _variant(confidence=1.5), False),
    ("confidence huge int", _variant(confidence=10**30), False),
    ("metadata as list", _variant(metadata=[["k", "v"]]), False),
    ("evidence missing ref", _variant(evidence=[{"kind": "observed"}]), False),
    ("evidence unknown field", _variant(evidence=[{"ref": "a", "bogus": 1}]), False),
    ("evidence bad direction", _variant(evidence=[{"ref": "a", "direction": "sideways"}]), False),
    ("evidence not a list", _variant(evidence={"ref": "a"}), False),
    ("failure missing challenge", _variant(failures=[{"id": "F", "claim_id": "C-1"}]), False),
    (
        "failure resolved not bool",
        _variant(failures=[{"id": "F", "claim_id": "C-1", "challenge": "c", "resolved": "yes"}]),
        False,
    ),
    ("disposition missing reason", _variant(dispositions=[{"challenge_category": "x"}]), False),
    (
        "disposition blank reason",
        _variant(dispositions=[{"challenge_category": "x", "reason": " "}]),
        False,
    ),
    ("claim row not an object", {"claims": ["just-a-string"]}, False),
    ("bundle object without claims", {"schema_version": "1.0"}, False),
    ("claims not a list", {"claims": {"id": "C-1"}}, False),
    ("scalar bundle", 42, False),
]


@pytest.mark.parametrize("name,value,expected", CORPUS, ids=[name for name, _, _ in CORPUS])
def test_schema_and_strict_loader_agree(tmp_path: Path, name: str, value: Any, expected: bool):
    validator = jsonschema.Draft202012Validator(CLAIM_SCHEMA)
    schema_ok = validator.is_valid(value)
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    try:
        load_claims(path)
        loader_ok = True
    except Exception:
        loader_ok = False
    assert schema_ok == expected, f"{name}: schema disagrees with expectation"
    assert loader_ok == expected, f"{name}: strict loader disagrees with expectation"
    assert schema_ok == loader_ok, f"{name}: schema and loader disagree"


def test_real_spec_bundles_validate_and_load() -> None:
    # Spec 004 R1.1: the repo's historical spec bundles predate the
    # stage field. The schema and the strict loader agree on them
    # too - both reject them for the missing stage; the lenient path
    # loads them with the default recorded, and after `aee migrate`
    # backfills the stage they validate and load strictly.
    from aee.extract import migrate_bundle

    validator = jsonschema.Draft202012Validator(CLAIM_SCHEMA)
    bundles = sorted((REPO_ROOT / "specs").glob("*/claims.json"))
    assert bundles, "expected the repo's own spec bundles to be present"
    for bundle in bundles:
        value = json.loads(bundle.read_text(encoding="utf-8"))
        assert not validator.is_valid(value), f"{bundle}: schema accepted a stageless bundle"
        with pytest.raises(Exception, match="field 'stage'"):
            load_claims(bundle)
        assert load_claims(bundle, strict=False), f"{bundle}: lenient loader returned no claims"
        migrated, _report = migrate_bundle(value)
        errors = list(validator.iter_errors(migrated))
        assert errors == [], f"{bundle} migrated: {[e.message for e in errors]}"


# ---------------------------------------------------------------------
# Real engine output against the reconciled assessment schema (RT2-M9)
# ---------------------------------------------------------------------


def _validate_assessment(value: dict[str, Any]) -> list[str]:
    validator = jsonschema.Draft202012Validator(ASSESSMENT_SCHEMA)
    return [error.message for error in validator.iter_errors(value)]


def test_assessment_outcome_enum_includes_abstain() -> None:
    outcomes = set(ASSESSMENT_SCHEMA["properties"]["outcome"]["enum"])
    assert outcomes == {
        "pass",
        "warn",
        "iterate",
        "clarify",
        "gather_evidence",
        "abstain",
        "block",
    }


def test_real_engine_output_validates() -> None:
    claim = Claim(
        id="C-1",
        text="The widget returns within 100 ms under load profile L",
        status=ClaimStatus.SUPPORTED,
        boundary=["load profile L"],
        falsification_tests=["Run load profile L and observe p95 above 100 ms"],
        evidence=[
            Evidence(
                ref="",
                kind=EvidenceKind.ASSERTED,
                source_quality=SourceQuality.MODEL,
            )
        ],
    )
    assessment = AEEEngine().assess([claim], project="p", phase="after_specify")
    assert _validate_assessment(assessment.to_dict()) == []


def test_policy_output_with_verdicts_and_abstain_validates() -> None:
    evidence = [
        Evidence(
            ref=f"model-report-{i}.md",
            kind=EvidenceKind.ASSERTED,
            source_quality=SourceQuality.MODEL,
            source_id=f"model-{i}",
        )
        for i in range(3)
    ]
    claim = Claim(
        id="C-1",
        text="The model reports the widget works under load profile L",
        status=ClaimStatus.SUPPORTED,
        boundary=["load profile L"],
        falsification_tests=["Run load profile L and observe a failure"],
        evidence=evidence,
    )
    assessment = AEEEngine(policy=AssessmentPolicy()).assess(
        [claim], project="p", phase="after_specify"
    )
    value = assessment.to_dict()
    assert value["verdicts"], "expected policy verdicts in the output"
    assert _validate_assessment(value) == []
    # RT2-M9's exact case: a policy-demoted abstain outcome was
    # rejected by the shipped schema's outcome enum.
    value["outcome"] = "abstain"
    assert _validate_assessment(value) == []


def test_assessment_schema_rejects_junk() -> None:
    claim = Claim(id="C-1", text="t")
    value = AEEEngine().assess([claim], project="p", phase="after_specify").to_dict()
    value["scores"]["C-1"]["components"]["surprise"] = 0.5
    assert _validate_assessment(value) != []
    value = AEEEngine().assess([claim], project="p", phase="after_specify").to_dict()
    value["claims"][0]["bogus"] = True
    assert _validate_assessment(value) != []
