"""File-boundary fuzz target shared by Atheris and portable regression tests."""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from aee.engine import AEEEngine
from aee.execution_evidence import MAX_RECORD_BYTES, ExecutionRecord
from aee.execution_reports import _junit
from aee.extract import load_claims, validate_bundle_structure
from aee.graph import ClaimGraph


def fuzz_one(data: bytes) -> None:
    """Malformed inputs may be rejected; accepted inputs must remain processable."""
    # New boundaries are ingestion only: never execute a fuzzed record's argv.
    if data[:1] == b"\x02":
        try:
            record = ExecutionRecord.from_bytes(data[1:])
        except ValueError:
            return
        if ExecutionRecord.from_dict(record.to_dict()).digest != record.digest:
            raise AssertionError("execution record roundtrip changed its identity")
        return
    if data[:1] == b"\x03":
        if len(data) > MAX_RECORD_BYTES:
            return
        try:
            report = _junit(data[1:])
        except (ValueError, ET.ParseError, RecursionError):
            return
        if report["tests"] < 0:
            raise AssertionError("negative report inventory")
        return
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
