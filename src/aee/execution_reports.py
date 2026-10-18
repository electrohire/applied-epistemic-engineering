"""Capture-bound JUnit verification, independent of claim confidence scores.

Supported input is UTF-8 JUnit testsuite/testsuites with named cases. Parsing
cannot execute a command, resolve entities or certify a producer. The receipt
binds bytes observed after capture; caller-managed isolation/provenance is still
required. A successful gate is limited to the declared test inventory and scope.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from collections.abc import Collection
from pathlib import Path
from typing import Any

from aee.execution_evidence import (
    ExecutionRecord,
    check_execution_applicability,
    report_bytes,
)
from aee.execution_scope import scope_path

MAX_TEST_CASES = 10_000


def _junit(data: bytes) -> dict[str, Any]:
    text = data.decode("utf-8")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("JUnit entities/DOCTYPE are unsupported")
    root = ET.fromstring(text)
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("unsupported JUnit root")
    for node in root.iter():
        if node.tag == "properties":
            if any(child.tag != "property" or len(child) for child in node):
                raise ValueError("unsupported structured JUnit properties")
        elif node.tag in {"system-out", "system-err"} and len(node):
            raise ValueError("JUnit output must be text, not nested result elements")
    seen: set[str] = set()

    def suite(node: ET.Element) -> list[dict[str, Any]]:
        cases = []
        for child in node:
            if child.tag == "testsuite":
                cases.extend(suite(child))
            elif child.tag == "testcase" and node.tag == "testsuite":
                classname = child.get("classname", "")
                name = child.get("name", "")
                if not classname.strip() or not name.strip() or len(classname) + len(name) > 8190:
                    raise ValueError("JUnit cases need bounded class/name identities")
                identity = classname + "::" + name
                if identity in seen:
                    raise ValueError("duplicate JUnit test identity")
                seen.add(identity)
                if len(seen) > MAX_TEST_CASES:
                    raise ValueError("too many JUnit cases")
                if any(
                    item.tag
                    not in {"failure", "error", "skipped", "system-out", "system-err", "properties"}
                    for item in child
                ):
                    raise ValueError("unsupported JUnit case content")
                status = child.get("status", "run")
                if status not in {"run", "passed", "notrun", "disabled"}:
                    raise ValueError("unsupported JUnit case status")
                cases.append(
                    dict(
                        id=identity,
                        failure=child.find("failure") is not None,
                        error=child.find("error") is not None,
                        skipped=child.find("skipped") is not None
                        or status in {"notrun", "disabled"},
                    )
                )
            elif child.tag not in {"properties", "system-out", "system-err"}:
                raise ValueError("unsupported JUnit suite content")
        counts = dict(
            tests=len(cases),
            failures=sum(c["failure"] for c in cases),
            errors=sum(c["error"] for c in cases),
            skipped=sum(c["skipped"] for c in cases),
        )
        for name, count in counts.items():
            if name in node.attrib and int(node.attrib[name]) != count:
                raise ValueError("JUnit declared counts disagree with cases")
        if int(node.get("disabled", "0")) != 0:
            raise ValueError("disabled JUnit suite inventory is incomplete")
        return cases

    cases = suite(root)
    failures = sum(c["failure"] for c in cases)
    errors = sum(c["error"] for c in cases)
    skipped = sum(c["skipped"] for c in cases)
    status = (
        "error"
        if errors
        else "incomplete"
        if skipped or not cases
        else "failed"
        if failures
        else "complete"
    )
    return dict(
        tests=len(cases),
        failures=failures,
        errors=errors,
        skipped=skipped,
        executed_test_ids=sorted(c["id"] for c in cases),
        report_status=status,
    )


def verify_test_report(
    record: ExecutionRecord,
    root: str | Path,
    report_path: str,
    *,
    repository_id: str,
    trusted_record_digests: Collection[str] = (),
) -> dict[str, Any]:
    """Verify retained bytes, scope, actual process result and declared inventory.

    Trust pins must come from the host's independently verified receipt policy or
    the immediately observed capture transaction. Never infer CI authenticity
    from a name/URL or accept pins carried inside an imported record.
    """
    record = ExecutionRecord(record.payload)
    name = scope_path(report_path)
    applicability = check_execution_applicability(
        record, root, repository_id=repository_id, trusted_record_digests=trusted_record_digests
    )
    result = dict(
        **applicability,
        outcome="gather_evidence",
        report_status="unknown",
        tests=None,
        failures=None,
        errors=None,
        skipped=None,
        executed_test_ids=[],
        missing_test_ids=[],
        findings=[],
        scope=(
            "Only this explicitly scoped verification execution; not certification of correctness."
        ),
    )
    value = record.to_dict()
    receipt = next((item for item in value["reports"] if item["path"] == name), None)
    if receipt is None or receipt["error"]:
        result["findings"].append("missing_or_unavailable_report_receipt")
        return result
    try:
        data = report_bytes(root, name)
        if (
            len(data) != receipt["byte_count"]
            or hashlib.sha256(data).hexdigest() != receipt["sha256"]
        ):
            raise ValueError("report bytes differ from capture receipt")
        parsed = _junit(data)
    except (OSError, ValueError, ET.ParseError, RecursionError) as exc:
        result["findings"].append("unverifiable_report:" + type(exc).__name__)
        return result
    result.update(parsed)
    expected = set(value["test_ids"])
    missing = sorted(expected - set(parsed["executed_test_ids"]))
    result["missing_test_ids"] = missing
    if missing or not expected:
        result["report_status"] = "incomplete"
        result["findings"].append("expected_test_inventory_incomplete")
    result["test_verification"] = result["report_status"]
    if applicability["producer_trust"] == "unverified":
        result["findings"].append("producer_unverified")
    if applicability["freshness"] != "fresh":
        result["findings"].append("scope_not_fresh")
    if result["report_status"] in {"unknown", "error", "incomplete"}:
        result["findings"].append("verification_incomplete")
    if applicability["execution_status"] == "unknown":
        result["findings"].append("execution_incomplete")
    if not result["findings"]:
        result["outcome"] = (
            "iterate"
            if applicability["execution_status"] == "failed" or result["report_status"] == "failed"
            else "pass"
        )
    return result
