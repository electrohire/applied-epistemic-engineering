"""Spec 002 FR-3 - verifiable evidence tests (T301-T305).

Fixture project under tests/fixtures/fr3-project/ is a self-contained
project root: the mismatch bundle carries the three acceptance cases
(a) dangling ref, (b) corrupted content_hash, (c) a tests/ ref declared
tertiary; the clean bundle must verify with no findings.
"""

import hashlib
import json
from pathlib import Path

from aee import check_evidence
from aee.cli import main
from aee.evidence_check import derive_source_quality
from aee.extract import load_claims
from aee.model import Claim, Evidence, SourceQuality

PROJECT = Path(__file__).parent / "fixtures" / "fr3-project"


def _categories(bundle: str) -> list[str]:
    claims = load_claims(PROJECT / bundle)
    report = check_evidence(claims, PROJECT)
    return [finding.category for finding in report.findings]


def _claim(*evidence: Evidence) -> Claim:
    return Claim(id="CLM-T", text="The widget holds", evidence=list(evidence))


# --- T305: acceptance fixtures ----------------------------------------------


def test_mismatch_fixture_reports_all_three_acceptance_cases() -> None:
    assert _categories("fr3-mismatch.json") == [
        "missing_ref",
        "content_hash_mismatch",
        "quality_mismatch",
    ]


def test_clean_fixture_passes_with_no_findings() -> None:
    claims = load_claims(PROJECT / "fr3-clean.json")
    report = check_evidence(claims, PROJECT)
    assert report.ok
    assert report.checked == 4
    assert report.unresolvable_offline == 1


def test_undeclared_quality_stays_unknown_in_all_outputs() -> None:
    claims = load_claims(PROJECT / "fr3-clean.json")
    report = check_evidence(claims, PROJECT)
    item = report.items[2]
    assert item.declared_quality == "unknown"
    # The ref type derives 'artifact' — reported, never upgraded into
    # the declaration (FR-3.4), in the item and in the claim itself.
    assert item.derived_quality == "artifact"
    assert claims[0].evidence[2].source_quality is SourceQuality.UNKNOWN
    assert report.to_dict()["items"][2]["declared_quality"] == "unknown"


# --- T301: ref resolution + path safety --------------------------------------


def test_url_ref_is_unresolvable_offline_never_fetched(tmp_path: Path) -> None:
    claim = _claim(
        Evidence(ref="https://example.org/study", source_quality=SourceQuality.SECONDARY)
    )
    report = check_evidence([claim], tmp_path)
    assert report.items[0].status == "unresolvable_offline"
    assert report.ok  # reported, not a finding


def test_traversal_ref_is_a_path_safety_finding(tmp_path: Path) -> None:
    (tmp_path / "inner").mkdir()
    claim = _claim(Evidence(ref="../outside.txt"))
    report = check_evidence([claim], tmp_path / "inner")
    assert [finding.category for finding in report.findings] == ["path_safety"]


def test_absolute_ref_outside_root_is_a_path_safety_finding(tmp_path: Path) -> None:
    claim = _claim(Evidence(ref="/etc/hostname"))
    report = check_evidence([claim], tmp_path)
    assert [finding.category for finding in report.findings] == ["path_safety"]


def test_symlinked_ref_is_refused_not_followed(tmp_path: Path) -> None:
    secret = tmp_path.parent / "secret-target.txt"
    secret.write_text("outside the root", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(secret)
    claim = _claim(Evidence(ref="link.txt"))
    report = check_evidence([claim], tmp_path)
    assert [finding.category for finding in report.findings] == ["path_safety"]
    assert report.items[0].resolved_path is None


def test_empty_ref_is_a_finding(tmp_path: Path) -> None:
    report = check_evidence([_claim(Evidence(ref=""))], tmp_path)
    assert [finding.category for finding in report.findings] == ["empty_ref"]


# --- T302: content_hash + observed_at ----------------------------------------


def test_content_hash_bare_hex_and_prefixed_both_verify(tmp_path: Path) -> None:
    target = tmp_path / "data.bin"
    target.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    for declared in (digest, f"sha256:{digest}", f"SHA256:{digest.upper()}"):
        claim = _claim(Evidence(ref="data.bin", content_hash=declared))
        report = check_evidence([claim], tmp_path)
        assert report.ok, declared


def test_content_hash_unsupported_algorithm_is_a_finding(tmp_path: Path) -> None:
    (tmp_path / "data.bin").write_bytes(b"payload")
    claim = _claim(Evidence(ref="data.bin", content_hash="md5:abc123"))
    report = check_evidence([claim], tmp_path)
    assert [finding.category for finding in report.findings] == ["content_hash_unsupported"]


def test_unparseable_observed_at_is_a_finding_not_a_note(tmp_path: Path) -> None:
    (tmp_path / "data.bin").write_bytes(b"payload")
    claim = _claim(Evidence(ref="data.bin", observed_at="last Tuesday-ish"))
    report = check_evidence([claim], tmp_path)
    assert [finding.category for finding in report.findings] == ["unparseable_observed_at"]


# --- T303: derived quality rules ----------------------------------------------


def test_derived_quality_rule_table() -> None:
    assert derive_source_quality("tests/test_widget.py") is SourceQuality.TEST
    assert derive_source_quality("src/widget_test.py") is SourceQuality.TEST
    assert derive_source_quality("docs/design-record.md") is SourceQuality.PRIMARY
    assert derive_source_quality("decisions/adr-0042-widget.md") is SourceQuality.PRIMARY
    assert derive_source_quality("reports/run.log") is SourceQuality.ARTIFACT
    assert derive_source_quality("artifacts/screenshot.png") is SourceQuality.ARTIFACT
    assert derive_source_quality("src/widget.py") is None
    assert derive_source_quality("README.md") is None


def test_declared_matching_derived_is_corroborated_not_challenged(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "check.py").write_text("x = 1\n", encoding="utf-8")
    claim = _claim(Evidence(ref="tests/check.py", source_quality=SourceQuality.TEST))
    assert check_evidence([claim], tmp_path).ok


# --- T304: CLI -----------------------------------------------------------------


def test_cli_verify_evidence_exit_codes(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    rc = main(
        [
            "verify-evidence",
            (PROJECT / "fr3-mismatch.json").as_posix(),
            "--project-root",
            PROJECT.as_posix(),
            "--output",
            out.as_posix(),
        ]
    )
    assert rc == 2
    report = json.loads(out.read_text(encoding="utf-8"))
    assert [finding["category"] for finding in report["findings"]] == [
        "missing_ref",
        "content_hash_mismatch",
        "quality_mismatch",
    ]
    rc = main(
        [
            "verify-evidence",
            (PROJECT / "fr3-clean.json").as_posix(),
            "--project-root",
            PROJECT.as_posix(),
        ]
    )
    assert rc == 0


def test_cli_assess_verify_evidence_folds_failure_modes(tmp_path: Path) -> None:
    out = tmp_path / "assessment.json"
    rc = main(
        [
            "assess",
            "--input",
            (PROJECT / "fr3-mismatch.json").as_posix(),
            "--project-root",
            PROJECT.as_posix(),
            "--verify-evidence",
            "--output",
            out.as_posix(),
        ]
    )
    value = json.loads(out.read_text(encoding="utf-8"))
    folded = [
        failure
        for claim in value["claims"]
        for failure in claim["failures"]
        if failure["category"] == "provenance_gap"
    ]
    assert len(folded) == 3
    assert {failure["challenge"] for failure in folded} == {
        "Evidence verification (missing_ref)",
        "Evidence verification (content_hash_mismatch)",
        "Evidence verification (quality_mismatch)",
    }
    assert value["metadata"]["evidence_verification"] == {
        "checked": 3,
        "findings": 3,
        "unresolvable_offline": 0,
    }
    assert value["outcome"] != "pass"
    assert rc == 1  # soft outcome (iterate), not an input error


def test_cli_assess_without_verify_evidence_has_no_folded_modes(tmp_path: Path) -> None:
    out = tmp_path / "assessment.json"
    main(
        [
            "assess",
            "--input",
            (PROJECT / "fr3-mismatch.json").as_posix(),
            "--output",
            out.as_posix(),
        ]
    )
    value = json.loads(out.read_text(encoding="utf-8"))
    assert "evidence_verification" not in value["metadata"]
    assert not [
        failure
        for claim in value["claims"]
        for failure in claim["failures"]
        if failure["category"] == "provenance_gap"
    ]
