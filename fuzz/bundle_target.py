"""File-boundary fuzz target shared by Atheris and portable regression tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

from aee.engine import AEEEngine
from aee.extract import load_claims, validate_bundle_structure
from aee.graph import ClaimGraph


def fuzz_one(data: bytes) -> None:
    """Malformed inputs may be rejected; accepted inputs must remain processable."""
    suffix = ".json" if not data or data[0] % 2 == 0 else ".md"
    with tempfile.TemporaryDirectory(prefix="aee-fuzz-") as directory:
        path = Path(directory) / f"claims{suffix}"
        path.write_bytes(data[1:] if data else data)
        original = path.read_bytes()
        try:
            claims = load_claims(path)
        except (ValueError, UnicodeError):
            # Invalid JSON, encoding, or claim fields are expected input errors.
            return
        errors, _warnings = validate_bundle_structure(claims)
        if not errors:
            assessment = AEEEngine().assess(claims)
            assessment.to_dict()
            ClaimGraph(claims).to_mermaid()
        if path.read_bytes() != original:
            raise AssertionError("assessment mutated its input")
