"""Regression tests for `aee demo` (the self-contained demonstration).

The demo is a CI smoke surface (the quality job runs
`python -m aee demo`), and it must pass HONESTLY under the Spec 004
model: lane 1 carries the observed load-test result, lane 2 carries
a named human's exposition and a recorded acceptance event. When
the demo's lane-2 support rotted (stage declared `accepted` on
machine-only evidence), R5.1 capped the claim at `checked`, R1.3
reported `supported` as `partially_supported`, and the demo exited
1 on `iterate` - while no test noticed. These tests pin the demo's
exit code and its printed lane-2 state so the surface cannot rot
silently again.
"""

import json

import pytest

from aee.cli import main


def test_demo_exits_zero_with_an_honest_pass(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["demo"])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert printed["outcome"] == "pass"
    assert printed["reported_statuses"] == {"REQ-DEMO-001": "supported"}
    assert printed["stage_caps"] == []


def test_demo_lane_2_shows_accepted_uncapped_with_exposition(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["demo"])
    printed = json.loads(capsys.readouterr().out)
    lane_2 = printed["lanes"]["per_claim"]["REQ-DEMO-001"]["lane_2"]
    assert lane_2["stage"] == "accepted"
    assert lane_2["stage_capped"] is False
    assert lane_2["exposition"] is True
    assert lane_2["explainers"] == ["jane-doe"]
    assert lane_2["verified_unexplained"] is False
