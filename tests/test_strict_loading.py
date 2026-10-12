"""Spec 002 FR-1 - strict, loud validation regression tests (T101-T106).

Fixtures under tests/fixtures/; golden files under tests/fixtures/golden/
record the OLD (pre-FR-1) behavior captured in Phase 0 (T002) — these
tests assert the new behavior inverts it.
"""

import json
from pathlib import Path

import pytest

from aee import BundleValidationError
from aee.cli import main
from aee.extract import load_claims, migrate_bundle
from aee.model import Claim, Evidence, FailureMode

FIXTURES = Path(__file__).parent / "fixtures"


def _golden(name: str) -> dict:
    return json.loads((FIXTURES / "golden" / f"{name}.old-behavior.json").read_text())


# --- T101/T102: strict from_dict ---------------------------------------------


def test_renamed_field_bundle_fails_strict_with_did_you_mean() -> None:
    golden = _golden("fr1-renamed-field")
    assert golden["behavior"] == "loaded"  # old: silently loaded
    assert golden["claims"][0]["text"] == ""  # old: text silently emptied
    with pytest.raises(BundleValidationError) as excinfo:
        load_claims(FIXTURES / "fr1-renamed-field.json")
    message = str(excinfo.value)
    assert "CLM-REN-01" in message  # names the claim
    assert "'statement'" in message  # names the field
    assert "did you mean 'text'" in message  # T102 suggestion


def test_unknown_field_near_miss_suggests_by_edit_distance() -> None:
    with pytest.raises(BundleValidationError, match=r"did you mean 'text'"):
        Claim.from_dict({"id": "X", "text": "t", "txet": "oops"})


def test_empty_or_missing_text_rejected() -> None:
    with pytest.raises(BundleValidationError, match="field 'text'"):
        Claim.from_dict({"id": "X", "text": "  "})
    with pytest.raises(BundleValidationError, match="field 'text'"):
        Claim.from_dict({"id": "X"})


def test_bad_enum_error_lists_valid_values() -> None:
    golden = _golden("fr1-bad-enum")
    assert golden["error"] == "'design' is not a valid ClaimKind"  # old: bare
    with pytest.raises(BundleValidationError) as excinfo:
        load_claims(FIXTURES / "fr1-bad-enum.json")
    message = str(excinfo.value)
    assert "CLM-ENUM-01" in message and "'kind'" in message
    assert "requirement" in message and "compliance" in message  # full set


def test_wrong_type_list_field_rejected_not_exploded() -> None:
    with pytest.raises(BundleValidationError, match="must be a list of strings"):
        Claim.from_dict({"id": "X", "text": "t", "boundary": "lab"})


def test_evidence_unknown_field_names_claim_and_field() -> None:
    with pytest.raises(BundleValidationError) as excinfo:
        Claim.from_dict({"id": "CLM-E", "text": "t", "evidence": [{"ref": "r", "reff": "x"}]})
    message = str(excinfo.value)
    assert "CLM-E" in message and "'reff'" in message and "did you mean 'ref'" in message


def test_evidence_missing_ref_rejected() -> None:
    with pytest.raises(BundleValidationError, match="field 'ref' is required"):
        Evidence.from_dict({"kind": "observed"})


def test_failure_mode_strict() -> None:
    with pytest.raises(BundleValidationError, match="valid values"):
        FailureMode.from_dict({"id": "F1", "claim_id": "C", "challenge": "c", "severity": "fatal"})
    ok = FailureMode.from_dict({"id": "F1", "claim_id": "C", "challenge": "c"})
    assert ok.severity.value == "medium"


def test_strict_is_default_and_round_trip_holds() -> None:
    claim = Claim.from_dict({"id": "X", "text": "t"})
    assert Claim.from_dict(claim.to_dict()).id == "X"


def test_lenient_mode_is_explicit_and_keeps_old_behavior() -> None:
    claim = Claim.from_dict({"id": "X", "statement": "ignored"}, strict=False)
    assert claim.text == ""  # historical silent default, only behind the flag
    loaded = load_claims(FIXTURES / "fr1-renamed-field.json", strict=False)
    assert loaded[0].text == ""


# --- T104: validate subcommand ------------------------------------------------


def test_validate_valid_bundle_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / "ok.json"
    path.write_text(json.dumps({"claims": [{"id": "A", "text": "A claim"}]}))
    assert main(["validate", str(path)]) == 0
    assert "valid: 1 claim(s)" in capsys.readouterr().out


def test_validate_invalid_bundle_exits_2_without_traceback(
    capsys: pytest.CaptureFixture,
) -> None:
    assert main(["validate", str(FIXTURES / "fr1-renamed-field.json")]) == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "did you mean 'text'" in captured.err


def test_validate_duplicate_ids_are_structural_errors(tmp_path: Path) -> None:
    path = tmp_path / "dup.json"
    row = {"id": "A", "text": "A claim"}
    path.write_text(json.dumps({"claims": [row, row]}))
    assert main(["validate", str(path)]) == 2


def test_validate_repo_spec_bundles_pass() -> None:
    specs = Path(__file__).parent.parent / "specs"
    for bundle in sorted(specs.glob("*/claims.json")):
        assert main(["validate", str(bundle)]) == 0, bundle


# --- T105/T106: migrate --------------------------------------------------------


def test_migrate_legacy_fixture_round_trip_to_assessment(tmp_path: Path) -> None:
    golden = _golden("fr1-legacy-tekmerion-001")
    assert golden["behavior"] == "raised"  # old engine could not load it at all
    raw = json.loads((FIXTURES / "fr1-legacy-tekmerion-001.json").read_text())
    migrated, report = migrate_bundle(raw)
    assert len(migrated["claims"]) == 7
    joined = "\n".join(report)
    assert "'statement' -> 'text'" in joined
    assert "'falsifier' -> 'falsification_tests'" in joined
    assert "kind 'design' -> 'requirement'" in joined
    assert "kind 'scope' -> 'decision'" in joined
    assert "status 'asserted-design' -> 'draft'" in joined
    assert "status 'proposed-pending-owner' -> 'draft'" in joined
    first = migrated["claims"][0]
    assert first["text"].startswith("Freezing the research design")
    assert first["evidence"][0] == {"ref": "docs/design-notes/DN-001-founding-decisions.md §6"}
    assert isinstance(first["falsification_tests"], list)
    out = tmp_path / "migrated.json"
    assert (
        main(["migrate", str(FIXTURES / "fr1-legacy-tekmerion-001.json"), "--output", str(out)])
        == 0
    )
    claims = load_claims(out)  # strict load of the migrated bundle
    assert len(claims) == 7
    assessment = tmp_path / "assessment.json"
    # A soft verdict (1) or pass (0) both prove assessability; 2 would be error.
    assert main(["assess", "--input", str(out), "--output", str(assessment)]) in (0, 1)


def test_migrate_refuses_unmappable_values_loudly() -> None:
    raw = {"claims": [{"id": "X", "statement": "t", "kind": "banana", "status": "draft"}]}
    with pytest.raises(BundleValidationError, match="no known mapping"):
        migrate_bundle(raw)
    raw2 = {"claims": [{"id": "X", "statement": "t", "kind": "design", "mystery": 1}]}
    with pytest.raises(BundleValidationError, match="no known mapping"):
        migrate_bundle(raw2)


def test_migrate_cli_unmappable_exits_2(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"claims": [{"id": "X", "statement": "t", "kind": "zzz"}]}))
    assert main(["migrate", str(path)]) == 2


def test_assess_renamed_field_exits_2_clean(capsys: pytest.CaptureFixture) -> None:
    code = main(["assess", "--input", str(FIXTURES / "fr1-renamed-field.json")])
    assert code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_assess_lenient_echoes_metadata(tmp_path: Path) -> None:
    out = tmp_path / "assessment.json"
    code = main(
        [
            "assess",
            "--input",
            str(FIXTURES / "fr1-renamed-field.json"),
            "--lenient",
            "--output",
            str(out),
        ]
    )
    assert code in (0, 1, 2)  # it loads; the verdict is the engine's business
    value = json.loads(out.read_text())
    assert value["metadata"]["loading_mode"] == "lenient"
    strict_out = tmp_path / "strict.json"
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"claims": [{"id": "A", "text": "A claim"}]}))
    assert main(["assess", "--input", str(ok), "--output", str(strict_out)]) in (0, 1)
    assert "loading_mode" not in json.loads(strict_out.read_text())["metadata"]
