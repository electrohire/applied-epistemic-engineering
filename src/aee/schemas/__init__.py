"""Bundled JSON schemas."""

from importlib.resources import files
from pathlib import Path


def assessment_schema_path() -> Path:
    return Path(str(files(__package__).joinpath("aee-assessment.schema.json")))


def evaluator_result_schema_path() -> Path:
    """The Spec Kit Evaluator Contract schema (Spec 003 FR-6.7 / T609).

    A vendored copy of the schema shipped by electrohire/spec-kit-evaluator
    (`schemas/evaluator-result.schema.json`); the engine validates emitted
    evaluator results against it so the adapter's contract check can never
    drift into a weaker subset (RT4-M6). Parity with the evaluator repo's
    shipped schema is pinned by tests/test_evaluator_contract.py.
    """
    return Path(str(files(__package__).joinpath("evaluator-result.schema.json")))


def claims_schema_path() -> Path:
    """The claims-bundle input schema (Spec 003 FR-5.9): the machine-
    checkable contract `aee validate` semantics rest on, kept in
    parity with the strict loader by tests/test_schema_parity.py."""
    return Path(str(files(__package__).joinpath("claim.schema.json")))


__all__ = [
    "assessment_schema_path",
    "claims_schema_path",
    "evaluator_result_schema_path",
]
