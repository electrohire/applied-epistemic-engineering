"""Spec 006 — independent lane outcomes and stage recording (A1-A6).

The defect: lanes.lane_1.outcome was a copy of the headline outcome,
so a bundle with clean machine checking still showed iterate in both
lanes, and no shipped command could record the stage or status acts
that would let a draft bundle ever reach headline pass.

These tests pin, end to end:

- A1: lane 1 is computed from lane-1 facts only (draft cap and stage
  rule excluded), through the routing steps shared with the headline;
- A2: the lane pair is reported distinctly (assessment record,
  summary, evaluator adapter);
- A3: the gate recomputes lane 1 and refuses a forgery (exit 2), and
  --require-lane1-pass maps lane-1 pass / iterate-family / block to
  exit 0 / 1 / 2;
- A4: `aee stage` and `aee ratify` record the acts, enforce the
  explained / accepted rules, write atomically, and ledger;
- A6 controls: the positive control reaches headline pass through
  recorded acts only; the kill chain passes in neither lane; an
  empty bundle blocks in both lanes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aee import (
    AEEEngine,
    AssessmentPolicy,
    Claim,
    ClaimKind,
    ClaimStage,
    ClaimStatus,
    EvaluatorAdapter,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    SourceQuality,
)
from aee.cli import main
from aee.ledger import HashChainLedger

EXPLAINER = "jane-doe"
EXPLAINERS = {"PC-1": "jane-doe", "PC-2": "john-smith"}

IDENTITIES = {
    "identities": [
        {"id": "jane-doe", "name": "Jane Doe", "kind": "person"},
        {"id": "john-smith", "name": "John Smith", "kind": "person"},
        {"id": "helper-bot", "name": "Helper Bot", "kind": "tool"},
    ]
}


def _evidence(slug: str, explainer: str) -> list[dict]:
    # Source ids are unique to the claim: two claims measured by the
    # same two labs would (correctly) draw the shared-evidence
    # warning, which is a different behavior than the one under test.
    lab_a, lab_b = f"lab-a-{slug}", f"lab-b-{slug}"
    return [
        {
            "ref": f"reports/{slug}-a.json",
            "kind": "observed",
            "direction": "supports",
            "source_quality": "test",
            "source_id": lab_a,
            "independent_of": [lab_b],
            "description": "First independent measurement",
        },
        {
            "ref": f"reports/{slug}-b.json",
            "kind": "observed",
            "direction": "supports",
            "source_quality": "primary",
            "source_id": lab_b,
            "description": "Second independent measurement",
        },
        {
            "ref": f"notes/{slug}-walkthrough.md",
            "kind": "exposition",
            "direction": "supports",
            "source_quality": "human",
            "source_id": explainer,
            "description": (
                "The explainer's walkthrough: what the measurements do "
                "and do not establish, and where the boundary lies"
            ),
        },
    ]


def _claim_row(cid: str, slug: str, number: int) -> dict:
    return {
        "id": cid,
        "text": f"Widget latency is {number} ms at p95 under load profile L",
        "kind": "requirement",
        "status": "draft",
        "stage": "created",
        "boundary": ["load profile L"],
        "falsification_tests": [f"Measure p95 latency and observe a reading above {number} ms"],
        "evidence": _evidence(slug, EXPLAINERS.get(cid, EXPLAINER)),
    }


def _write_bundle(tmp_path: Path, rows: list[dict], *, identities: bool = True) -> Path:
    bundle = tmp_path / "claims.json"
    bundle.write_text(json.dumps({"claims": rows}), encoding="utf-8")
    if identities:
        (tmp_path / "identities.json").write_text(json.dumps(IDENTITIES), encoding="utf-8")
    return bundle


def _positive_bundle(tmp_path: Path) -> Path:
    return _write_bundle(tmp_path, [_claim_row("PC-1", "pc1", 42), _claim_row("PC-2", "pc2", 43)])


def _assess_cli(tmp_path: Path, bundle: Path, *, ledger: bool = False) -> tuple[int, Path]:
    output = tmp_path / "assessment.json"
    argv = [
        "assess",
        "--input",
        str(bundle),
        "--output",
        str(output),
        "--project-root",
        str(tmp_path),
    ]
    if not ledger:
        argv.append("--no-ledger")
    code = main(argv)
    return code, output


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# -- A1/A2: the positive control's first assessment -------------------------


def test_positive_control_lane1_passes_while_headline_iterates(tmp_path: Path) -> None:
    bundle = _positive_bundle(tmp_path)
    code, output = _assess_cli(tmp_path, bundle)
    assert code == 1  # headline iterate is a soft outcome
    value = _read(output)
    assert value["outcome"] == "iterate"
    assert value["lanes"]["lane_1"]["outcome"] == "pass"
    assert all(score["propagated_score"] >= 0.70 for score in value["scores"].values())
    # The summary states the pair next to the headline (A2).
    assert "Lane 1 (machine verification): outcome pass" in value["summary"]
    assert "Lane 2 (human acceptance):" in value["summary"]


def test_positive_control_gate_exit_codes(tmp_path: Path) -> None:
    bundle = _positive_bundle(tmp_path)
    _code, output = _assess_cli(tmp_path, bundle)
    # Default gate follows the headline: iterate -> 1.
    assert main(["gate", "--input", str(output)]) == 1
    # The lane-1 requirement is met: exit 0.
    assert main(["gate", "--input", str(output), "--require-lane1-pass"]) == 0


def test_evaluator_adapter_forwards_lane_1_outcome_distinctly(tmp_path: Path) -> None:
    # No exposition item here: the evaluator contract's evidence-ref
    # kinds predate the exposition kind, so a claim carrying both an
    # exposition item and an open failure cannot be expressed in a
    # finding — a pre-existing adapter limit on main, unchanged by
    # Spec 006 and outside its scope.
    assessment = AEEEngine().assess([_api_claim("EV-1")])
    result = EvaluatorAdapter().to_evaluator_result(assessment)
    assert result["outcome"] == "iterate"  # the blended headline
    assert result["metadata"]["lane_1_outcome"] == "pass"
    assert result["metadata"]["headline_outcome"] == "iterate"
    assert result["metadata"]["lanes"]["lane_1"]["outcome"] == "pass"
    assert assessment.lanes["lane_1"]["outcome"] == "pass"


# -- A1: policy demotion is lane-scoped --------------------------------------


def _api_claim(
    cid: str,
    *,
    status: ClaimStatus = ClaimStatus.DRAFT,
    stage: ClaimStage = ClaimStage.CREATED,
    sources: int = 2,
) -> Claim:
    evidence = [
        Evidence(
            ref="reports/a.json",
            kind=EvidenceKind.OBSERVED,
            direction=EvidenceDirection.SUPPORTS,
            source_quality=SourceQuality.TEST,
            source_id="lab-a",
            independent_of=["lab-b"],
        ),
    ]
    if sources >= 2:
        evidence.append(
            Evidence(
                ref="reports/b.json",
                kind=EvidenceKind.OBSERVED,
                direction=EvidenceDirection.SUPPORTS,
                source_quality=SourceQuality.PRIMARY,
                source_id="lab-b",
            )
        )
    return Claim(
        id=cid,
        text="Widget latency is 42 ms at p95 under load profile L",
        kind=ClaimKind.REQUIREMENT,
        status=status,
        stage=stage,
        boundary=["load profile L"],
        falsification_tests=["Measure p95 latency and observe a reading above 42 ms"],
        evidence=evidence,
    )


def test_unjudged_verdict_does_not_demote_lane_1() -> None:
    # Stage 'created' makes the policy verdict UNJUDGED — a lane-2
    # fact. Lane 1 stays pass; the headline stays iterate.
    assessment = AEEEngine(policy=AssessmentPolicy()).assess([_api_claim("U1")])
    assert assessment.verdicts["U1"].verdict.value == "unjudged"
    assert assessment.lanes["lane_1"]["outcome"] == "pass"
    assert assessment.outcome == "iterate"


def test_draft_only_challenge_does_not_demote_lane_1() -> None:
    # A ratified-stage claim whose only challenge reason is the
    # draft cap: the demotion is lane-2, so lane 1 stays pass.
    claim = _api_claim("D1", status=ClaimStatus.DRAFT, stage=ClaimStage.ACCEPTED)
    assessment = AEEEngine(policy=AssessmentPolicy()).assess([claim])
    verdict = assessment.verdicts["D1"]
    assert verdict.verdict.value == "challenge"
    assert all(reason.startswith(("draft claim:", "stage cap")) for reason in verdict.reasons)
    assert assessment.lanes["lane_1"]["outcome"] == "pass"
    assert assessment.outcome == "iterate"


def test_lane_1_challenge_reason_demotes_lane_1() -> None:
    # One source only: the corroboration challenge is a lane-1
    # reason, and lane 1 does not pass.
    claim = _api_claim("C1", status=ClaimStatus.SUPPORTED, stage=ClaimStage.ACCEPTED, sources=1)
    assessment = AEEEngine(policy=AssessmentPolicy()).assess([claim])
    assert assessment.verdicts["C1"].verdict.value == "challenge"
    assert assessment.lanes["lane_1"]["outcome"] != "pass"
    assert assessment.outcome != "pass"


# -- A6 negative controls -----------------------------------------------------


def test_kill_chain_passes_in_neither_lane() -> None:
    # RT1-04 kill chain: twenty copies of one model self-report plus
    # one human assertion, on a draft claim. Dedup collapses the
    # copies; the score falls short in both lanes.
    evidence = [
        Evidence(
            ref="self-report",
            kind=EvidenceKind.ASSERTED,
            direction=EvidenceDirection.SUPPORTS,
            source_quality=SourceQuality.HUMAN,
            source_id="human-1",
        )
    ]
    evidence += [
        Evidence(
            ref="model-out",
            kind=EvidenceKind.ASSERTED,
            direction=EvidenceDirection.SUPPORTS,
            source_quality=SourceQuality.MODEL,
            source_id="model-1",
        )
        for _ in range(20)
    ]
    claim = Claim(
        id="K1",
        text="Widget latency is 42 ms at p95 under load profile L",
        status=ClaimStatus.DRAFT,
        stage=ClaimStage.CREATED,
        boundary=["load profile L"],
        falsification_tests=["Measure p95 latency and observe a reading above 42 ms"],
        evidence=evidence,
    )
    assessment = AEEEngine(policy=AssessmentPolicy()).assess([claim])
    assert assessment.scores["K1"].propagated_score < 0.70
    assert assessment.outcome != "pass"
    assert assessment.lanes["lane_1"]["outcome"] != "pass"


def test_empty_bundle_blocks_in_both_lanes() -> None:
    assessment = AEEEngine().assess([])
    assert assessment.outcome == "block"
    assert assessment.lanes["lane_1"]["outcome"] == "block"


def test_gate_refuses_forged_lane_1_outcome(tmp_path: Path) -> None:
    bundle = _positive_bundle(tmp_path)
    _code, output = _assess_cli(tmp_path, bundle)
    value = _read(output)
    assert value["lanes"]["lane_1"]["outcome"] == "pass"
    value["lanes"]["lane_1"]["outcome"] = "block"
    output.write_text(json.dumps(value), encoding="utf-8")
    assert main(["gate", "--input", str(output)]) == 2
    assert main(["gate", "--input", str(output), "--require-lane1-pass"]) == 2


def test_gate_require_lane1_pass_maps_block_to_2_and_clarify_to_1(
    tmp_path: Path,
) -> None:
    # Block in both lanes (duplicate ids carry a CRITICAL failure).
    bundle = _positive_bundle(tmp_path)
    rows = _read(bundle)["claims"]
    rows.append(rows[0])
    bundle.write_text(json.dumps({"claims": rows}), encoding="utf-8")
    _code, output = _assess_cli(tmp_path, bundle)
    value = _read(output)
    assert value["outcome"] == "block"
    assert value["lanes"]["lane_1"]["outcome"] == "block"
    assert main(["gate", "--input", str(output), "--require-lane1-pass"]) == 2

    # Clarify in both lanes (a live contradiction).
    claim = _api_claim("X1", status=ClaimStatus.SUPPORTED, stage=ClaimStage.ACCEPTED)
    claim.evidence.append(
        Evidence(
            ref="reports/refutation.json",
            kind=EvidenceKind.OBSERVED,
            direction=EvidenceDirection.CONTRADICTS,
            source_quality=SourceQuality.TEST,
            source_id="lab-c",
        )
    )
    assessment = AEEEngine().assess([claim])
    assert assessment.outcome == "clarify"
    assert assessment.lanes["lane_1"]["outcome"] == "clarify"
    clarify_path = tmp_path / "clarify.json"
    clarify_path.write_text(json.dumps(assessment.to_dict()), encoding="utf-8")
    assert main(["gate", "--input", str(clarify_path), "--require-lane1-pass"]) == 1


# -- A4: stage and ratify refusals --------------------------------------------


def test_ratify_supported_at_created_is_refused_without_a_write(tmp_path: Path) -> None:
    bundle = _positive_bundle(tmp_path)
    before = bundle.read_bytes()
    code = main(
        [
            "ratify",
            str(bundle),
            "--claim",
            "PC-1",
            "--status",
            "supported",
            "--basis",
            "Trying to skip the checks",
            "--recorded-by",
            EXPLAINER,
        ]
    )
    assert code == 2
    assert bundle.read_bytes() == before


def test_stage_explained_requires_exposition(tmp_path: Path) -> None:
    rows = [_claim_row("NE-1", "ne1", 42)]
    rows[0]["evidence"] = rows[0]["evidence"][:2]  # no exposition item
    bundle = _write_bundle(tmp_path, rows)
    before = bundle.read_bytes()
    assert (
        main(["stage", str(bundle), "--claim", "NE-1", "--to", "checked", "--basis", "Assessed"])
        == 0
    )
    code = main(
        [
            "stage",
            str(bundle),
            "--claim",
            "NE-1",
            "--to",
            "explained",
            "--basis",
            "Claiming an explanation that is not on record",
        ]
    )
    assert code == 2
    after = _read(bundle)
    assert after["claims"][0]["stage"] == "checked"  # the refused act wrote nothing more
    assert len(after["claims"][0]["stage_events"]) == 1
    assert before != bundle.read_bytes()  # only the successful 'checked' act landed


def test_stage_accepted_requires_a_registered_person(tmp_path: Path) -> None:
    bundle = _positive_bundle(tmp_path)
    assert (
        main(["stage", str(bundle), "--claim", "PC-1", "--to", "checked", "--basis", "Assessed"])
        == 0
    )
    for bad_actor in (None, "unknown-person", "helper-bot"):
        argv = [
            "stage",
            str(bundle),
            "--claim",
            "PC-1",
            "--to",
            "accepted",
            "--basis",
            "Accepting",
        ]
        if bad_actor is not None:
            argv += ["--recorded-by", bad_actor]
        assert main(argv) == 2, bad_actor
    assert _read(bundle)["claims"][0]["stage"] == "checked"


def test_stage_and_ratify_refuse_bad_values_cleanly(tmp_path: Path) -> None:
    bundle = _positive_bundle(tmp_path)
    before = bundle.read_bytes()
    assert main(["stage", str(bundle), "--claim", "PC-1", "--to", "sideways", "--basis", "x"]) == 2
    assert main(["stage", str(bundle), "--claim", "NOPE", "--to", "checked", "--basis", "x"]) == 2
    assert (
        main(
            [
                "ratify",
                str(bundle),
                "--claim",
                "PC-1",
                "--status",
                "sideways",
                "--basis",
                "x",
                "--recorded-by",
                EXPLAINER,
            ]
        )
        == 2
    )
    # A backward stage move is refused by the recorded-event rule.
    assert (
        main(["stage", str(bundle), "--claim", "PC-1", "--to", "checked", "--basis", "Assessed"])
        == 0
    )
    assert (
        main(["stage", str(bundle), "--claim", "PC-1", "--to", "created", "--basis", "Rewind"]) == 2
    )
    assert bundle.read_bytes() != before


# -- A4/A6: the end-to-end path to headline pass -------------------------------


def test_recorded_acts_reach_headline_pass_and_ledger(tmp_path: Path) -> None:
    bundle = _positive_bundle(tmp_path)
    ledger_path = tmp_path / "ledger.jsonl"

    code, output = _assess_cli(tmp_path, bundle, ledger=True)
    assert code == 1
    default_ledger = tmp_path / ".specify/extensions/aee/ledger/epistemic-ledger.jsonl"
    assert default_ledger.is_file()
    ledger_path = default_ledger

    for cid, explainer in EXPLAINERS.items():
        assert (
            main(
                [
                    "stage",
                    str(bundle),
                    "--claim",
                    cid,
                    "--to",
                    "checked",
                    "--basis",
                    "Assessment run recorded as the checking event",
                ]
            )
            == 0
        )
        assert (
            main(
                [
                    "ratify",
                    str(bundle),
                    "--claim",
                    cid,
                    "--status",
                    "supported",
                    "--basis",
                    "Evidence reviewed; the claim is ratified",
                    "--recorded-by",
                    explainer,
                ]
            )
            == 0
        )
        assert (
            main(
                [
                    "stage",
                    str(bundle),
                    "--claim",
                    cid,
                    "--to",
                    "explained",
                    "--basis",
                    "The explainer's exposition is on the claim record",
                ]
            )
            == 0
        )
        assert (
            main(
                [
                    "stage",
                    str(bundle),
                    "--claim",
                    cid,
                    "--to",
                    "accepted",
                    "--basis",
                    "Recorded human acceptance after explanation",
                    "--recorded-by",
                    explainer,
                ]
            )
            == 0
        )

    recorded = _read(bundle)
    for row in recorded["claims"]:
        assert row["stage"] == "accepted"
        assert row["status"] == "supported"
        assert [event["kind"] for event in row["stage_events"]] == [
            "checked",
            "explained",
            "accepted",
        ]
        assert row["metadata"]["ratification_events"][0]["author"] == EXPLAINERS[row["id"]]

    # The acts joined the project's ledger, and the chain verifies.
    ledger = HashChainLedger(ledger_path)
    event_types = [entry["event_type"] for entry in ledger.entries()]
    assert event_types.count("stage_event") == 6
    assert event_types.count("ratification") == 2
    assert ledger.verify(require_anchor=True).valid
    assert main(["verify-ledger", "--ledger", str(ledger_path)]) == 0

    # A fresh assessment now reaches headline pass — and both gates agree.
    code, output = _assess_cli(tmp_path, bundle, ledger=True)
    assert code == 0
    value = _read(output)
    assert value["outcome"] == "pass"
    assert value["lanes"]["lane_1"]["outcome"] == "pass"
    assert main(["gate", "--input", str(output)]) == 0
    assert main(["gate", "--input", str(output), "--require-lane1-pass"]) == 0


# -- Headline regression: outcomes on representative bundles --------------------


def test_headline_outcomes_unchanged_on_representative_bundles() -> None:
    # Values the old engine (main at 8211643, methodology 2.0)
    # produced for these same bundles; Spec 006 must not move any
    # of them. Lane 1 is asserted alongside, differing only where
    # the draft/stage caps were the sole reason for iterate.
    strong = _api_claim("R-STRONG", status=ClaimStatus.SUPPORTED, stage=ClaimStage.ACCEPTED)
    draft = _api_claim("R-DRAFT", status=ClaimStatus.DRAFT, stage=ClaimStage.CREATED)
    weak = Claim(id="R-WEAK", text="The widget is fast", status=ClaimStatus.SUPPORTED)
    cases = [
        ([strong], "pass", "pass"),
        ([draft], "iterate", "pass"),
        ([weak], "gather_evidence", "gather_evidence"),
        ([], "block", "block"),
    ]
    for claims, headline, lane_1 in cases:
        assessment = AEEEngine().assess(claims)
        assert assessment.outcome == headline, [c.id for c in claims]
        assert assessment.lanes["lane_1"]["outcome"] == lane_1, [c.id for c in claims]
    # Scores are the old engine's scores for these fixtures.
    assessment = AEEEngine().assess([_api_claim("R-SCORE")])
    assert assessment.scores["R-SCORE"].propagated_score == pytest.approx(0.85)
