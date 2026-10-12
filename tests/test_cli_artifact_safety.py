"""Spec 003 FR-5 (T501/T502/T503/T507): CLI artifact safety.

Inverts RT2 p09 sections 1-5 (path collisions, ledger-before-artifact
partial state, symlink truncation), p08/p13 (traceback exit codes),
and the RT2-M11 bare-NaN emission cases:

- no CLI output may resolve (symlink-aware) onto a path the run
  reads — input bundle, reliability file, ledger, anchor sidecar;
- artifacts are written atomically and BEFORE the ledger append, so
  a failed write leaves no ledger entry for a missing artifact;
- all CLI JSON emission is strict (allow_nan=False) and the
  gate/review/migrate/bundle loads refuse bare NaN/Infinity;
- malformed-but-readable inputs exit 2 with a named error — never a
  traceback, never exit 1 (the scored-soft-verdict code).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aee import cli
from aee.cli import main
from aee.ledger import DEFAULT_LEDGER_PATH, HashChainLedger

BUNDLE = {"claims": [{"id": "CLM-1", "text": "The widget works", "status": "draft"}]}

MATRIX_TEXT = (
    "| Test ID | Requirements | Layer | Gate |\n|---|---|---|---|\n| T-X-001 | R | unit | g |\n"
)


def _bundle(tmp_path: Path, name: str = "claims.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(BUNDLE), encoding="utf-8")
    return path


def _assess_args(bundle: Path, *extra: str) -> list[str]:
    return ["assess", "--input", str(bundle), "--no-ledger", *extra]


# ---------------------------------------------------------------------
# Path collisions (RT2 p09 §§1, 3; RT2-H4)
# ---------------------------------------------------------------------


def test_assess_output_equals_input_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    bundle = _bundle(tmp_path)
    before = bundle.read_bytes()
    assert main(_assess_args(bundle, "--output", str(bundle))) == 2
    assert bundle.read_bytes() == before
    assert "refusing to overwrite" in capsys.readouterr().err


def test_assess_output_equals_custom_ledger_refused(tmp_path: Path):
    bundle = _bundle(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    assert main(["assess", "--input", str(bundle), "--ledger", str(ledger)]) in (0, 1)
    before = ledger.read_bytes()
    code = main(
        ["assess", "--input", str(bundle), "--ledger", str(ledger), "--output", str(ledger)]
    )
    assert code == 2
    assert ledger.read_bytes() == before


def test_assess_output_equals_default_ledger_refused(tmp_path: Path):
    bundle = _bundle(tmp_path)
    default_ledger = tmp_path / DEFAULT_LEDGER_PATH
    code = main(
        [
            "assess",
            "--input",
            str(bundle),
            "--project-root",
            str(tmp_path),
            "--output",
            str(default_ledger),
        ]
    )
    assert code == 2
    assert not default_ledger.exists()


def test_assess_output_equals_ledger_anchor_refused(tmp_path: Path):
    bundle = _bundle(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    anchor = ledger.with_name(ledger.name + ".anchor.json")
    code = main(
        ["assess", "--input", str(bundle), "--ledger", str(ledger), "--output", str(anchor)]
    )
    assert code == 2
    assert not anchor.exists()
    assert not ledger.exists()


def test_assess_output_equals_evaluator_output_refused(tmp_path: Path):
    bundle = _bundle(tmp_path)
    out = tmp_path / "out.json"
    code = main(_assess_args(bundle, "--output", str(out), "--evaluator-output", str(out)))
    assert code == 2
    assert not out.exists()


def test_assess_evaluator_output_equals_input_refused(tmp_path: Path):
    bundle = _bundle(tmp_path)
    before = bundle.read_bytes()
    code = main(_assess_args(bundle, "--evaluator-output", str(bundle)))
    assert code == 2
    assert bundle.read_bytes() == before


def test_assess_output_equals_reliability_file_refused(tmp_path: Path):
    bundle = _bundle(tmp_path)
    reliability = tmp_path / "reliability.json"
    reliability.write_text(json.dumps({"sources": {}}), encoding="utf-8")
    before = reliability.read_bytes()
    code = main(
        _assess_args(bundle, "--reliability", str(reliability), "--output", str(reliability))
    )
    assert code == 2
    assert reliability.read_bytes() == before


def test_challenge_output_equals_input_refused(tmp_path: Path):
    bundle = _bundle(tmp_path)
    before = bundle.read_bytes()
    assert main(["challenge", "--input", str(bundle), "--output", str(bundle)]) == 2
    assert bundle.read_bytes() == before


def test_graph_output_equals_input_refused(tmp_path: Path):
    bundle = _bundle(tmp_path)
    before = bundle.read_bytes()
    assert main(["graph", "--input", str(bundle), "--output", str(bundle)]) == 2
    assert bundle.read_bytes() == before


def test_review_output_equals_inputs_refused(tmp_path: Path):
    previous = tmp_path / "prev.json"
    current = tmp_path / "cur.json"
    previous.write_text(json.dumps({"scores": {}, "verdicts": {}}), encoding="utf-8")
    current.write_text(json.dumps({"scores": {}, "verdicts": {}}), encoding="utf-8")
    for target in (previous, current):
        before = target.read_bytes()
        code = main(
            [
                "review",
                "--previous",
                str(previous),
                "--current",
                str(current),
                "--output",
                str(target),
            ]
        )
        assert code == 2
        assert target.read_bytes() == before


def test_migrate_output_equals_input_refused(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "fr1-legacy-tekmerion-001.json"
    bundle = tmp_path / "legacy.json"
    bundle.write_bytes(fixture.read_bytes())
    before = bundle.read_bytes()
    assert main(["migrate", str(bundle), "--output", str(bundle)]) == 2
    assert bundle.read_bytes() == before


def test_verify_evidence_output_equals_bundle_refused(tmp_path: Path):
    bundle = _bundle(tmp_path)
    before = bundle.read_bytes()
    assert main(["verify-evidence", str(bundle), "--output", str(bundle)]) == 2
    assert bundle.read_bytes() == before


def test_gaps_output_equals_matrix_refused(tmp_path: Path):
    matrix = tmp_path / "matrix.md"
    matrix.write_text(MATRIX_TEXT, encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    before = matrix.read_bytes()
    code = main(
        ["gaps", "--matrix", str(matrix), "--evidence", str(evidence), "--output", str(matrix)]
    )
    assert code == 2
    assert matrix.read_bytes() == before


def test_gaps_output_equals_existing_register_refused(tmp_path: Path):
    matrix = tmp_path / "matrix.md"
    matrix.write_text(MATRIX_TEXT, encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    existing = tmp_path / "GAPS.md"
    existing.write_text("# Gap Register\n", encoding="utf-8")
    before = existing.read_bytes()
    code = main(
        [
            "gaps",
            "--matrix",
            str(matrix),
            "--evidence",
            str(evidence),
            "--existing",
            str(existing),
            "--output",
            str(existing),
        ]
    )
    assert code == 2
    assert existing.read_bytes() == before


def test_verify_ledger_write_anchor_equals_ledger_refused(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    HashChainLedger(ledger_path).append("event", {"n": 1})
    before = ledger_path.read_bytes()
    code = main(
        [
            "verify-ledger",
            "--ledger",
            str(ledger_path),
            "--anchor",
            str(ledger_path),
            "--write-anchor",
        ]
    )
    assert code == 2
    assert ledger_path.read_bytes() == before
    assert HashChainLedger(ledger_path).verify().valid


# ---------------------------------------------------------------------
# Symlinks (RT2 p09 §4)
# ---------------------------------------------------------------------


def test_assess_output_symlink_to_input_refused(tmp_path: Path):
    bundle = _bundle(tmp_path)
    before = bundle.read_bytes()
    link = tmp_path / "link.json"
    link.symlink_to(bundle)
    assert main(_assess_args(bundle, "--output", str(link))) == 2
    assert bundle.read_bytes() == before


def test_assess_output_symlink_victim_survives(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    bundle = _bundle(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("IMPORTANT ORIGINAL CONTENT", encoding="utf-8")
    link = tmp_path / "out.json"
    link.symlink_to(victim)
    code = main(_assess_args(bundle, "--output", str(link)))
    assert code in (0, 1)
    # The victim was never truncated: the atomic rename replaced the
    # symlink itself, and the resolved target was reported first.
    assert victim.read_text(encoding="utf-8") == "IMPORTANT ORIGINAL CONTENT"
    assert not link.is_symlink()
    assert json.loads(link.read_text(encoding="utf-8"))["outcome"]
    assert "resolves through a symlink" in capsys.readouterr().err


def test_ledger_outside_project_root_warns_but_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    # RT2 p09 section 5 / RT2-L3: an out-of-root --ledger is created
    # (a local CLI has latitude) but never silently.
    bundle = _bundle(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "elsewhere" / "deep" / "ledger.jsonl"
    code = main(
        [
            "assess",
            "--input",
            str(bundle),
            "--project-root",
            str(project),
            "--ledger",
            str(outside),
        ]
    )
    assert code in (0, 1)
    assert outside.is_file()
    assert "outside the project root" in capsys.readouterr().err


# ---------------------------------------------------------------------
# Ordering + atomicity (RT2 p09 §2; RT2-M3)
# ---------------------------------------------------------------------


def test_failed_output_write_leaves_no_ledger_entry(tmp_path: Path):
    bundle = _bundle(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    outdir = tmp_path / "adir"
    outdir.mkdir()
    code = main(
        ["assess", "--input", str(bundle), "--ledger", str(ledger), "--output", str(outdir)]
    )
    assert code == 2
    assert not ledger.exists()


def test_successful_assess_writes_artifact_before_ledger(tmp_path: Path):
    bundle = _bundle(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    output = tmp_path / "assessment.json"
    code = main(
        ["assess", "--input", str(bundle), "--ledger", str(ledger), "--output", str(output)]
    )
    assert code in (0, 1)
    assert output.is_file()
    assert len(HashChainLedger(ledger).entries()) == 1
    # No temp-file litter from the atomic writes.
    assert not list(tmp_path.glob("*.tmp"))


# ---------------------------------------------------------------------
# Strict JSON (RT2-M11; FR-5.5)
# ---------------------------------------------------------------------


def test_gate_rejects_bare_nan(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    fake = tmp_path / "nan.json"
    fake.write_text(
        '{"outcome": "pass", "summary": "x", "claims": [], "scores": {}, '
        '"metadata": {"threshold": NaN}}',
        encoding="utf-8",
    )
    assert main(["gate", "--input", str(fake)]) == 2
    assert "non-finite number 'NaN'" in capsys.readouterr().err


def test_gate_rejects_bare_infinity(tmp_path: Path):
    fake = tmp_path / "inf.json"
    fake.write_text(
        '{"outcome": "pass", "summary": "x", "claims": [], "scores": {}, '
        '"metadata": {"threshold": 0.7, "x": Infinity}}',
        encoding="utf-8",
    )
    assert main(["gate", "--input", str(fake)]) == 2


def test_assess_bundle_with_nan_token_refused(tmp_path: Path):
    bundle = tmp_path / "claims.json"
    bundle.write_text(
        '{"claims": [{"id": "C-1", "text": "t", "metadata": {"x": NaN}}]}',
        encoding="utf-8",
    )
    assert main(_assess_args(bundle)) == 2


def test_assess_non_finite_metadata_value_fails_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    # 1e999 parses to inf without using a bare constant token; the
    # strict emitter must refuse it (exit 2) rather than print a bare
    # Infinity an external parser would reject.
    bundle = tmp_path / "claims.json"
    bundle.write_text(
        '{"claims": [{"id": "C-1", "text": "t", "metadata": {"x": 1e999}}]}',
        encoding="utf-8",
    )
    assert main(_assess_args(bundle)) == 2
    assert "Infinity" not in capsys.readouterr().out


def test_review_rejects_bare_nan(tmp_path: Path):
    previous = tmp_path / "prev.json"
    previous.write_text('{"scores": {"A": {"propagated_score": NaN}}}', encoding="utf-8")
    current = tmp_path / "cur.json"
    current.write_text('{"scores": {}}', encoding="utf-8")
    code = main(["review", "--previous", str(previous), "--current", str(current)])
    assert code == 2


def test_migrate_rejects_bare_nan(tmp_path: Path):
    bundle = tmp_path / "legacy.json"
    bundle.write_text('{"claims": [], "x": NaN}', encoding="utf-8")
    assert main(["migrate", str(bundle)]) == 2


# ---------------------------------------------------------------------
# Exit-code coherence on garbage review inputs (FR-5.3)
# ---------------------------------------------------------------------

_GARBAGE_REVIEW_INPUTS = [
    "[1, 2, 3]",
    '{"scores": [], "verdicts": {}}',
    '{"scores": {"A": 42}, "verdicts": {}}',
    '{"scores": {"A": {"propagated_score": "abc"}}, "verdicts": {}}',
    '{"scores": {"A": {"propagated_score": 1' + "0" * 400 + '}}, "verdicts": {}}',
    '{"scores": {"A": {"components": []}}, "verdicts": {}}',
    '{"scores": {"A": {"notes": {}}}, "verdicts": {}}',
    '{"scores": {}, "verdicts": []}',
    '{"scores": {}, "verdicts": {"A": {"verdict": "bogus"}}}',
    '{"scores": {}, "verdicts": {"A": {}}}',
    '{"scores": {}, "verdicts": {"A": {"verdict": "accept", "reasons": "why"}}}',
    "not json at all",
]


@pytest.mark.parametrize("content", _GARBAGE_REVIEW_INPUTS)
def test_review_garbage_inputs_exit_2(tmp_path: Path, content: str):
    previous = tmp_path / "prev.json"
    previous.write_text(content, encoding="utf-8")
    current = tmp_path / "cur.json"
    current.write_text('{"scores": {}, "verdicts": {}}', encoding="utf-8")
    assert main(["review", "--previous", str(previous), "--current", str(current)]) == 2


def test_review_valid_inputs_exit_0(tmp_path: Path):
    previous = tmp_path / "prev.json"
    current = tmp_path / "cur.json"
    body = json.dumps(
        {
            "scores": {
                "A": {
                    "claim_id": "A",
                    "direct_score": 0.9,
                    "propagated_score": 0.9,
                    "components": {"evidence": 0.9},
                    "notes": [],
                }
            },
            "verdicts": {"A": {"verdict": "accept", "reasons": ["ok"]}},
        }
    )
    previous.write_text(body, encoding="utf-8")
    current.write_text(body, encoding="utf-8")
    assert main(["review", "--previous", str(previous), "--current", str(current)]) == 0


def test_assess_huge_integer_confidence_exits_2(tmp_path: Path):
    bundle = tmp_path / "claims.json"
    bundle.write_text(
        '{"claims": [{"id": "C-1", "text": "t", "confidence": ' + "1" + "0" * 400 + "}]}",
        encoding="utf-8",
    )
    assert main(_assess_args(bundle)) == 2


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    src = Path(cli.__file__).parent.parent
    env = dict(os.environ, PYTHONPATH=str(src))
    return subprocess.run(
        [sys.executable, "-m", "aee", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_subprocess_bigint_has_no_traceback(tmp_path: Path):
    bundle = tmp_path / "claims.json"
    bundle.write_text(
        '{"claims": [{"id": "C-1", "text": "t", "confidence": ' + "1" + "0" * 400 + "}]}",
        encoding="utf-8",
    )
    result = _run_cli(["assess", "--input", str(bundle), "--no-ledger"])
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_subprocess_deep_nesting_has_no_traceback(tmp_path: Path):
    bundle = tmp_path / "deep.json"
    bundle.write_text(
        '{"claims": [{"id": "C-1", "text": "t", "metadata": '
        + '{"a":' * 2000
        + "1"
        + "}" * 2000
        + "}]}",
        encoding="utf-8",
    )
    result = _run_cli(["assess", "--input", str(bundle), "--no-ledger"])
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------
# Load independence (no shared mutable state between loads)
# ---------------------------------------------------------------------


def test_two_claim_loads_produce_independent_objects(tmp_path: Path):
    from aee.extract import load_claims

    bundle = tmp_path / "claims.json"
    bundle.write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "C-1",
                        "text": "t",
                        "evidence": [{"ref": "a.md"}],
                        "metadata": {"nested": {"x": 1}},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    first = load_claims(bundle)
    second = load_claims(bundle)
    first[0].evidence.clear()
    first[0].metadata["nested"]["x"] = 99
    first[0].boundary.append("mutated")
    assert len(second[0].evidence) == 1
    assert second[0].metadata["nested"]["x"] == 1
    assert second[0].boundary == []
