"""Spec 002 FR-4 — version coherence tests (T401, T402).

FR-4.4: ``aee --version`` and the ``metadata.engine_version`` stamp on
every assessment are the same string from the same source
(``aee.__version__``, defined once in ``aee._version``); these tests
fail if they ever diverge. FR-4.1: ``methodology_version`` stays a
distinct, separately-versioned field.
"""

import json
from pathlib import Path

import pytest

import aee
from aee.cli import main
from aee.engine import AEEEngine
from aee.model import Claim


def test_version_flag_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"aee {aee.__version__}"


def test_engine_stamps_engine_version_from_the_same_source() -> None:
    assessment = AEEEngine().assess([Claim(id="CLM-V", text="A claim")])
    assert assessment.metadata["engine_version"] == aee.__version__
    assert assessment.to_dict()["metadata"]["engine_version"] == aee.__version__


def test_caller_metadata_cannot_override_the_stamp() -> None:
    assessment = AEEEngine().assess(
        [Claim(id="CLM-V", text="A claim")],
        metadata={"engine_version": "0.0.0-forged"},
    )
    assert assessment.metadata["engine_version"] == aee.__version__


def test_cli_assessment_carries_the_stamp(tmp_path: Path) -> None:
    bundle = tmp_path / "claims.json"
    bundle.write_text(
        json.dumps({"claims": [{"id": "CLM-V", "text": "A claim"}]}),
        encoding="utf-8",
    )
    out = tmp_path / "assessment.json"
    main(["assess", "--input", bundle.as_posix(), "--output", out.as_posix()])
    value = json.loads(out.read_text(encoding="utf-8"))
    assert value["metadata"]["engine_version"] == aee.__version__


def test_methodology_version_is_a_distinct_field() -> None:
    assessment = AEEEngine().assess([Claim(id="CLM-V", text="A claim")])
    value = assessment.to_dict()
    # Separately versioned: methodology changes bump this constant on
    # their own schedule; it is not the engine version in disguise.
    assert value["methodology_version"] == "1.0"
    assert assessment.methodology_version != value["metadata"]["engine_version"]
