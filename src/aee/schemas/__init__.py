"""Bundled JSON schemas."""

from importlib.resources import files
from pathlib import Path


def assessment_schema_path() -> Path:
    return Path(str(files(__package__).joinpath("aee-assessment.schema.json")))


def claims_schema_path() -> Path:
    """The claims-bundle input schema (Spec 003 FR-5.9): the machine-
    checkable contract `aee validate` semantics rest on, kept in
    parity with the strict loader by tests/test_schema_parity.py."""
    return Path(str(files(__package__).joinpath("claim.schema.json")))


__all__ = ["assessment_schema_path", "claims_schema_path"]
