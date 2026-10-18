"""JUnit is bound to actual capture; no zero-exit or stale-report shortcut."""

from __future__ import annotations

import json
import sys

import pytest

from aee.execution_evidence import capture_execution
from aee.execution_reports import verify_test_report


def run(tmp_path, xml, *, tests=("tests::test_one",), exit_code=0):
    (tmp_path / "source.py").write_text("bounded\n")
    code = (
        "from pathlib import Path;Path('junit.xml').write_text("
        + repr(xml)
        + ");raise SystemExit("
        + str(exit_code)
        + ")"
    )
    record = capture_execution(
        [sys.executable, "-c", code],
        tmp_path,
        ["source.py"],
        repository_id="project",
        requirement_ids=["R01"],
        test_ids=tests,
        report_paths=["junit.xml"],
    )
    return record


def xml(case='<testcase classname="tests" name="test_one"/>', attrs='tests="1"'):
    return "<testsuites><testsuite " + attrs + ">" + case + "</testsuite></testsuites>"


def test_success_requires_explicit_provenance_pin_fresh_scope_and_complete_inventory(tmp_path):
    record = run(tmp_path, xml())
    unknown = verify_test_report(record, tmp_path, "junit.xml", repository_id="project")
    assert unknown["outcome"] == "gather_evidence" and unknown["producer_trust"] == "unverified"
    value = verify_test_report(
        record,
        tmp_path,
        "junit.xml",
        repository_id="project",
        trusted_record_digests={record.digest},
    )
    assert (
        value["outcome"] == "pass"
        and value["tests"] == 1
        and value["executed_test_ids"] == ["tests::test_one"]
    )
    assert (
        value["scope"]
        == "Only this explicitly scoped verification execution; not certification of correctness."
    )


@pytest.mark.parametrize(
    "content,tests,exit_code,status,outcome",
    [
        (
            xml('<testcase classname="tests" name="test_one"><failure>bug</failure></testcase>'),
            ("tests::test_one",),
            1,
            "failed",
            "iterate",
        ),
        (
            xml(
                '<testcase classname="tests" name="test_one">'
                "<error>collection error</error></testcase>"
            ),
            ("tests::test_one",),
            1,
            "error",
            "gather_evidence",
        ),
        (
            xml('<testcase classname="tests" name="test_one"><skipped/></testcase>'),
            ("tests::test_one",),
            0,
            "incomplete",
            "gather_evidence",
        ),
        (xml(), ("tests::test_missing",), 0, "incomplete", "gather_evidence"),
        (xml(), (), 0, "incomplete", "gather_evidence"),
        ('<testsuite tests="0"/>', ("tests::test_one",), 0, "incomplete", "gather_evidence"),
        (xml(), ("tests::test_one",), 2, "complete", "iterate"),
    ],
)
def test_failure_error_skip_empty_and_missing_inventory_never_pass(
    tmp_path, content, tests, exit_code, status, outcome
):
    record = run(tmp_path, content, tests=tests, exit_code=exit_code)
    value = verify_test_report(
        record,
        tmp_path,
        "junit.xml",
        repository_id="project",
        trusted_record_digests={record.digest},
    )
    assert value["report_status"] == status and value["outcome"] == outcome


@pytest.mark.parametrize(
    "content",
    [
        "not XML",
        "<wrong/>",
        '<!DOCTYPE testsuite [<!ENTITY x "fake">]><testsuite/>',
        xml(attrs='tests="2"'),
        xml(attrs='failures="1"'),
        xml(attrs='errors="bad"'),
        xml('<testcase name="no-class"/>'),
        xml('<testcase classname="tests"/>'),
        xml(
            '<testcase classname="tests" name="test_one"/>'
            '<testcase classname="tests" name="test_one"/>',
            attrs='tests="2"',
        ),
    ],
)
def test_invalid_ambiguous_or_entity_reports_cannot_pass(tmp_path, content):
    record = run(tmp_path, content)
    value = verify_test_report(
        record,
        tmp_path,
        "junit.xml",
        repository_id="project",
        trusted_record_digests={record.digest},
    )
    assert value["outcome"] == "gather_evidence" and value["report_status"] == "unknown"


def test_report_mutation_missing_receipt_and_scope_change(tmp_path):
    record = run(tmp_path, xml())
    pins = {record.digest}
    (tmp_path / "junit.xml").write_text(xml(attrs='tests="2"'))
    assert (
        verify_test_report(
            record, tmp_path, "junit.xml", repository_id="project", trusted_record_digests=pins
        )["outcome"]
        == "gather_evidence"
    )
    (tmp_path / "junit.xml").unlink()
    assert (
        verify_test_report(
            record, tmp_path, "junit.xml", repository_id="project", trusted_record_digests=pins
        )["outcome"]
        == "gather_evidence"
    )
    assert (
        verify_test_report(
            record, tmp_path, "absent.xml", repository_id="project", trusted_record_digests=pins
        )["outcome"]
        == "gather_evidence"
    )
    (tmp_path / "junit.xml").write_text(xml())
    (tmp_path / "source.py").write_text("changed")
    assert (
        verify_test_report(
            record, tmp_path, "junit.xml", repository_id="project", trusted_record_digests=pins
        )["outcome"]
        == "gather_evidence"
    )


def test_actual_pytest_report_capture_and_verification(tmp_path):
    (tmp_path / "test_example.py").write_text("def test_value():\n    assert 2+2==4\n")
    record = capture_execution(
        [sys.executable, "-m", "pytest", "-q", "test_example.py", "--junitxml=junit.xml"],
        tmp_path,
        ["test_example.py"],
        repository_id="example",
        requirement_ids=["R01"],
        test_ids=["test_example::test_value"],
        report_paths=["junit.xml"],
    )
    value = verify_test_report(
        record,
        tmp_path,
        "junit.xml",
        repository_id="example",
        trusted_record_digests={record.digest},
    )
    assert value["outcome"] == "pass", json.dumps(value)


@pytest.mark.parametrize(
    "content",
    [
        xml('<testcase classname="tests" name="test_one"><script/></testcase>'),
        xml('<testcase classname="tests" name="test_one" status="unknown"/>'),
        xml("<script/>", attrs='tests="0"'),
        xml(attrs='tests="1" disabled="1"'),
    ],
)
def test_unsupported_report_variants_fail_closed(tmp_path, content):
    record = run(tmp_path, content)
    assert (
        verify_test_report(
            record,
            tmp_path,
            "junit.xml",
            repository_id="project",
            trusted_record_digests={record.digest},
        )["outcome"]
        == "gather_evidence"
    )


def test_case_count_bound_and_nonexecuted_status(tmp_path, monkeypatch):
    import aee.execution_reports as reports

    record = run(tmp_path, xml('<testcase classname="tests" name="test_one" status="notrun"/>'))
    assert (
        verify_test_report(
            record,
            tmp_path,
            "junit.xml",
            repository_id="project",
            trusted_record_digests={record.digest},
        )["report_status"]
        == "incomplete"
    )
    monkeypatch.setattr(reports, "MAX_TEST_CASES", 0)
    assert (
        verify_test_report(
            record,
            tmp_path,
            "junit.xml",
            repository_id="project",
            trusted_record_digests={record.digest},
        )["report_status"]
        == "unknown"
    )


def test_metadata_and_nested_suite_counts(tmp_path):
    content = (
        '<testsuites tests="1"><properties><property name="x" value="data"/></properties>'
        '<testsuite tests="1"><system-out>data</system-out>'
    )
    content += (
        '<testcase classname="tests" name="test_one"><properties/>'
        "<system-err>data</system-err></testcase>"
    )
    content += "</testsuite></testsuites>"
    record = run(tmp_path, content)
    assert (
        verify_test_report(
            record,
            tmp_path,
            "junit.xml",
            repository_id="project",
            trusted_record_digests={record.digest},
        )["outcome"]
        == "pass"
    )


def test_valid_report_before_timeout_still_cannot_pass(tmp_path):
    (tmp_path / "source.py").write_text("bounded")
    code = (
        "from pathlib import Path;import time;Path('junit.xml').write_text("
        + repr(xml())
        + ");time.sleep(10)"
    )
    record = capture_execution(
        [sys.executable, "-c", code],
        tmp_path,
        ["source.py"],
        repository_id="project",
        requirement_ids=["R01"],
        test_ids=["tests::test_one"],
        report_paths=["junit.xml"],
        timeout=2,
    )
    value = verify_test_report(
        record,
        tmp_path,
        "junit.xml",
        repository_id="project",
        trusted_record_digests={record.digest},
    )
    assert value["outcome"] == "gather_evidence" and "execution_incomplete" in value["findings"]


@pytest.mark.parametrize(
    "metadata",
    [
        '<properties><testcase classname="hidden" name="failure">'
        "<failure/></testcase></properties>",
        '<properties><property name="x"><error/></property></properties>',
        "<system-out><error>hidden result</error></system-out>",
    ],
)
def test_structured_results_cannot_hide_inside_metadata(tmp_path, metadata):
    content = xml(metadata + '<testcase classname="tests" name="test_one"/>')
    record = run(tmp_path, content)
    value = verify_test_report(
        record,
        tmp_path,
        "junit.xml",
        repository_id="project",
        trusted_record_digests={record.digest},
    )
    assert value["outcome"] == "gather_evidence" and value["report_status"] == "unknown"
