"""CLI wiring for the ported mechanisms: assess --policy /
--reliability, the review subcommand, and the abstain exit code.

The Spec Kit extension drives this engine through the CLI, so the
policy gates, reliability blending, and review queue are only
real features once they are reachable here.
"""

import json

from aee.cli import main
from aee.reliability import ReliabilityTable


def write_claims(tmp_path, claims) -> str:
    path = tmp_path / "claims.json"
    path.write_text(json.dumps({"claims": claims}), encoding="utf-8")
    return str(path)


def strong_claim(claim_id="A", sources=("S1", "S2")):
    return {
        "id": claim_id,
        "text": "Latency is below 100 ms",
        "status": "supported",
        "boundary": ["p95 in production"],
        "falsification_tests": ["Observe p95 at or above 100 ms"],
        "evidence": [
            {
                "ref": f"run-{source}",
                "source_id": source,
                "kind": "observed",
                "source_quality": "test",
                "direction": "supports",
            }
            for source in sources
        ],
    }


def run_assess(tmp_path, claims, *extra):
    output = tmp_path / "assessment.json"
    code = main(
        [
            "assess",
            "--input",
            write_claims(tmp_path, claims),
            "--output",
            str(output),
            *extra,
        ]
    )
    return code, json.loads(output.read_text(encoding="utf-8"))


def test_assess_without_policy_has_empty_verdicts(tmp_path) -> None:
    code, value = run_assess(tmp_path, [strong_claim()])
    assert code == 0
    assert value["verdicts"] == {}


def test_assess_policy_accepts_corroborated_claim(tmp_path) -> None:
    code, value = run_assess(tmp_path, [strong_claim()], "--policy")
    assert code == 0
    assert value["verdicts"]["A"]["verdict"] == "accept"
    assert value["outcome"] == "pass"


def test_assess_policy_single_source_challenges(tmp_path) -> None:
    code, value = run_assess(tmp_path, [strong_claim(sources=("S1",))], "--policy")
    assert value["verdicts"]["A"]["verdict"] == "challenge"
    assert code == 1  # outcome demoted to iterate: soft exit


def test_assess_policy_abstain_exit_code_is_soft(tmp_path) -> None:
    bare = strong_claim()
    bare["evidence"] = []
    code, value = run_assess(tmp_path, [bare], "--policy")
    assert value["verdicts"]["A"]["verdict"] == "abstain"
    assert value["outcome"] != "pass"
    assert code == 1  # NOT 2: abstention is a verdict, not an error


def test_assess_policy_threshold_overrides(tmp_path) -> None:
    _code, value = run_assess(
        tmp_path, [strong_claim(sources=("S1",))], "--policy", "--min-independent-sources", "1"
    )
    assert value["verdicts"]["A"]["verdict"] == "accept"


def test_assess_reliability_blends_scores(tmp_path) -> None:
    table = ReliabilityTable()
    for _ in range(5):
        table.record("M", 1.0, True)
    table_path = tmp_path / "reliability.json"
    table_path.write_text(json.dumps(table.to_dict()), encoding="utf-8")
    model_claim = {
        "id": "A",
        "text": "The model says latency is fine",
        "status": "supported",
        "boundary": ["p95 in production"],
        "falsification_tests": ["Observe p95 at or above 100 ms"],
        "evidence": [
            {
                "ref": "model-note",
                "source_id": "M",
                "kind": "asserted",
                "source_quality": "model",
                "direction": "supports",
            }
        ],
    }
    _, plain = run_assess(tmp_path, [model_claim])
    _, blended = run_assess(tmp_path, [model_claim], "--reliability", str(table_path))
    assert blended["scores"]["A"]["direct_score"] > plain["scores"]["A"]["direct_score"]
    notes = blended["scores"]["A"]["notes"]
    assert any("measured reliability" in note for note in notes)


def test_review_subcommand_diffs_assessments(tmp_path) -> None:
    _, first = run_assess(tmp_path, [strong_claim(sources=())])
    first_path = tmp_path / "first.json"
    first_path.write_text(json.dumps(first), encoding="utf-8")
    _, second = run_assess(tmp_path, [strong_claim()])
    second_path = tmp_path / "second.json"
    second_path.write_text(json.dumps(second), encoding="utf-8")
    out = tmp_path / "queue.json"
    code = main(
        [
            "review",
            "--previous",
            str(first_path),
            "--current",
            str(second_path),
            "--output",
            str(out),
        ]
    )
    assert code == 0
    queue = json.loads(out.read_text(encoding="utf-8"))
    assert [item["claim_id"] for item in queue["items"]] == ["A"]
    assert queue["items"][0]["delta"] > 0.05


def test_review_rejects_bad_materiality(tmp_path) -> None:
    _, value = run_assess(tmp_path, [strong_claim()])
    path = tmp_path / "a.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    code = main(
        [
            "review",
            "--previous",
            str(path),
            "--current",
            str(path),
            "--materiality",
            "1.5",
        ]
    )
    assert code == 2
