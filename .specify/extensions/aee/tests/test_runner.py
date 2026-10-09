from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).parents[1] / "scripts" / "python" / "run_aee.py"
SPEC = importlib.util.spec_from_file_location("run_aee", RUNNER)
assert SPEC and SPEC.loader
run_aee = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_aee)


def test_phase_is_normalized() -> None:
    assert run_aee._safe_segment("plan") == "after_plan"
    assert run_aee._safe_segment("after_tasks") == "after_tasks"


@pytest.mark.parametrize("value", ["../plan", "after-plan", "", "after plan"])
def test_invalid_phase_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        run_aee._safe_segment(value)


def test_existing_file_must_be_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes project root"):
        run_aee._safe_existing(root, outside)


def test_symlink_component_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    real = root / "real"
    root.mkdir()
    real.mkdir()
    (real / "spec.md").write_text("data", encoding="utf-8")
    link = root / "linked"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(ValueError):
        run_aee._safe_existing(root, link / "spec.md")


def test_output_parent_is_created(tmp_path: Path) -> None:
    target = run_aee._safe_output(tmp_path, Path(".specify/extensions/aee/result.json"))
    assert target.parent.is_dir()
    assert target.is_relative_to(tmp_path)


def test_challenge_subparser_is_registered() -> None:
    parser = run_aee.parser()
    args = parser.parse_args(
        ["challenge", "--input", "claims.json", "--phase", "after_plan"]
    )
    assert args.command == "challenge"
    assert args.input == Path("claims.json")
    assert args.phase == "after_plan"
    assert args.threshold == 0.70
    assert args.actor == "spec-kit-aee"


def test_challenge_end_to_end(tmp_path: Path) -> None:
    if shutil.which("aee") is None:
        pytest.fail("Install requirements/dev.txt and activate its environment: aee is required")
    root = tmp_path / "project"
    root.mkdir()
    claims = root / "claims.json"
    claims.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "claims": [
                    {
                        "id": "REQ-001",
                        "text": "The service responds quickly",
                        "kind": "requirement",
                        "status": "supported",
                        "boundary": [],
                        "falsification_tests": ["A load test observes slow responses"],
                        "source_ref": "spec.md#REQ-001",
                        "uncertainty": "low",
                        "evidence": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--project-root",
            str(root),
            "challenge",
            "--input",
            "claims.json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode in {0, 1, 2}, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["aee_exit_code"] == completed.returncode
    challenge_path = root / payload["challenge"]
    assert challenge_path.is_file()
    value = json.loads(challenge_path.read_text(encoding="utf-8"))
    assert value["mode"] == "challenge"
    assert "failures" in value
    assert "recoveries" in value
