"""Bundled JSON schemas."""

from importlib.resources import files
from pathlib import Path


def assessment_schema_path() -> Path:
    return Path(str(files(__package__).joinpath("aee-assessment.schema.json")))


__all__ = ["assessment_schema_path"]
