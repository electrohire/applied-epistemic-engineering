"""Spec 002 FR-2 (T201/T205) + FR-8a ledger parity (T801/T803).

Drafting: one draft per requirement in the fixture spec, every draft
born ``status: draft`` with evidence quality capped at model/asserted,
source_ref set, a proposed falsifier where the requirement text can
anchor one, and the TODO marker — which strict loading must reject —
where it cannot.

Ledger parity: ``assess`` ledgers by default to the documented
default path under the project root, ``--no-ledger`` leaves none,
``--ledger`` still selects a custom path, and the choice is echoed
into assessment metadata.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from aee import AEEEngine
from aee.cli import main
from aee.extract import TODO_FALSIFIER, draft_claims, draft_claims_from_spec
from aee.ledger import DEFAULT_LEDGER_PATH, HashChainLedger
from aee.model import BundleValidationError, ClaimStatus, SourceQuality

FIXTURES = Path(__file__).parent / "fixtures"
SPEC = FIXTURES / "fr2-draft-spec.md"

# Quality values at or below the FR-2.2 cap for drafted evidence.
_CAPPED = {SourceQuality.MODEL, SourceQuality.UNKNOWN}
# The helper happens to emit MODEL; ASSERTED is the EvidenceKind, and a
# source_quality of 'asserted' does not exist — the cap in quality
# terms is: nothing at or above human/test/primary/artifact/secondary/
# tertiary may ever appear on a draft.
_FORBIDDEN_QUALITY = {
    SourceQuality.PRIMARY,
    SourceQuality.SECONDARY,
    SourceQuality.TERTIARY,
    SourceQuality.ARTIFACT,
    SourceQuality.TEST,
    SourceQuality.HUMAN,
}


def _drafts():
    return draft_claims(SPEC)


def test_one_draft_per_requirement_all_draft_source_ref_set() -> None:
    drafts = _drafts()
    refs = [d.metadata["requirement_ref"] for d in drafts]
    assert refs == ["FR-1", "FR-2", "FR-3", "US-1", "AC-1", "AC-2"]
    for draft in drafts:
        assert draft.status is ClaimStatus.DRAFT
        assert draft.source_ref == f"{SPEC.as_posix()}#{draft.metadata['requirement_ref']}"
        assert len(draft.evidence) == 1
        quality = draft.evidence[0].source_quality
        assert quality not in _FORBIDDEN_QUALITY
        assert quality in _CAPPED or quality is SourceQuality.MODEL
        assert draft.id  # derived_claim_id-based, non-empty
    # ids are derived (stable + unique per requirement)
    assert len({d.id for d in drafts}) == len(drafts)
    again = _drafts()
    assert [d.id for d in again] == [d.id for d in drafts]


def test_no_code_path_ratifies() -> None:
    """FR-2.2: the helper contains no path that sets a claim above
    draft. Behavioural check above (all outputs are draft) plus a
    source guard so a future edit cannot quietly add one."""
    source = inspect.getsource(draft_claims_from_spec)
    assert "SUPPORTED" not in source
    assert "ClaimStatus.DRAFT" in source


def test_completed_drafts_pass_strict_validation(tmp_path: Path) -> None:
    drafts = [d for d in _drafts() if d.falsification_tests != [TODO_FALSIFIER]]
    assert len(drafts) == 5  # the AC-2 aspiration is the only TODO draft
    bundle = tmp_path / "drafts.json"
    from aee.extract import dump_claims

    bundle.write_text(dump_claims(drafts), encoding="utf-8")
    assert main(["validate", str(bundle)]) == 0


def test_todo_falsifier_draft_is_rejected_by_strict_loading(tmp_path: Path) -> None:
    drafts = _drafts()
    todo = [d for d in drafts if d.falsification_tests == [TODO_FALSIFIER]]
    assert [d.metadata["requirement_ref"] for d in todo] == ["AC-2"]
    assert todo[0].metadata["falsifier_proposed"] is False
    from aee.extract import dump_claims, load_claims

    bundle = tmp_path / "todo-drafts.json"
    bundle.write_text(dump_claims(drafts), encoding="utf-8")
    # Direct strict load and the CI validate path both refuse it.
    with pytest.raises(BundleValidationError, match="TODO"):
        load_claims(bundle)
    assert main(["validate", str(bundle)]) == 2
    # The same rejection protects assess: drafts cannot sneak past FR-1.
    assert main(["assess", "--input", str(bundle), "--no-ledger"]) == 2


def test_proposed_falsifiers_are_marked_proposed() -> None:
    for draft in _drafts():
        if draft.falsification_tests == [TODO_FALSIFIER]:
            continue
        assert draft.metadata["falsifier_proposed"] is True
        assert draft.falsification_tests[0].startswith("Proposed falsification test:")


def test_depends_on_proposals_from_explicit_cross_references() -> None:
    """FR-6.3 engine capability: FR-2's text references FR-1, so its
    draft scaffolds a depends_on proposal pointing at FR-1's draft;
    the proposal is a proposal by virtue of draft status, and its
    source ref is recorded in metadata."""
    drafts = {d.metadata["requirement_ref"]: d for d in _drafts()}
    fr2 = drafts["FR-2"]
    assert fr2.depends_on == [drafts["FR-1"].id]
    assert fr2.metadata["depends_on_proposed_from"] == ["FR-1"]
    assert drafts["FR-1"].depends_on == []
    # All other drafts carry no invented dependencies.
    for ref, draft in drafts.items():
        if ref != "FR-2":
            assert draft.depends_on == []


def test_unedited_drafts_assess_as_drafts_on_their_authored_evidence() -> None:
    """T205 acceptance: an assessment of the completed (non-TODO)
    drafts — whose only evidence is the helper's own model-quality
    attestation of the requirement text — must not produce an outcome
    above gather_evidence/iterate attributable to the tool."""
    drafts = [d for d in _drafts() if d.falsification_tests != [TODO_FALSIFIER]]
    assessment = AEEEngine().assess(drafts, project="fr2-fixture", phase="after_specify")
    assert assessment.outcome in {"gather_evidence", "iterate", "clarify", "abstain", "block"}
    assert assessment.outcome not in {"pass", "warn"}


def test_draft_claims_from_spec_text_api() -> None:
    drafts = draft_claims_from_spec("- **FR-9**: The system must store each record.\n")
    assert len(drafts) == 1
    assert drafts[0].source_ref == "spec.md#FR-9"
    assert drafts[0].status is ClaimStatus.DRAFT
    # Heading-style requirements with em/en dash separators parse to
    # the heading title, not a title still carrying the separator.
    headed = draft_claims_from_spec(
        "## FR-3 — Export\n\nThe widget must export data.\n\n"
        "## FR-5 \u2013 Archive\n\nThe widget must archive data.\n"
    )
    assert [(d.metadata["requirement_ref"], d.text) for d in headed] == [
        ("FR-3", "Export"),
        ("FR-5", "Archive"),
    ]


# --- FR-8a ledger parity (T801) -------------------------------------------------


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "claims.json"
    bundle.write_text(
        json.dumps({"claims": [{"id": "A", "text": "A measurable result", "stage": "created"}]}),
        encoding="utf-8",
    )
    return bundle


def test_assess_ledgers_by_default_under_project_root(tmp_path: Path) -> None:
    out = tmp_path / "assessment.json"
    code = main(
        [
            "assess",
            "--input",
            str(_bundle(tmp_path)),
            "--output",
            str(out),
            "--project-root",
            str(tmp_path),
        ]
    )
    assert code in (0, 1)
    ledger = tmp_path / DEFAULT_LEDGER_PATH
    assert ledger.is_file()
    assert HashChainLedger(ledger).verify().valid
    assert main(["verify-ledger", "--ledger", str(ledger)]) == 0
    value = json.loads(out.read_text(encoding="utf-8"))
    assert value["metadata"]["ledger"] == {"mode": "default", "path": ledger.as_posix()}
    entry = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert entry["payload"]["assessment_sha256"]  # FR-8.3: the entry is the record


def test_assess_no_ledger_leaves_none_and_echoes_opt_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "assessment.json"
    code = main(
        [
            "assess",
            "--input",
            str(_bundle(tmp_path)),
            "--output",
            str(out),
            "--no-ledger",
        ]
    )
    assert code in (0, 1)
    assert not (tmp_path / DEFAULT_LEDGER_PATH).exists()
    value = json.loads(out.read_text(encoding="utf-8"))
    assert value["metadata"]["ledger"] == {"mode": "disabled", "path": None}


def test_assess_custom_ledger_path_still_wins(tmp_path: Path) -> None:
    custom = tmp_path / "custom.jsonl"
    out = tmp_path / "assessment.json"
    code = main(
        [
            "assess",
            "--input",
            str(_bundle(tmp_path)),
            "--output",
            str(out),
            "--ledger",
            str(custom),
        ]
    )
    assert code in (0, 1)
    assert custom.is_file()
    assert HashChainLedger(custom).verify().valid
    value = json.loads(out.read_text(encoding="utf-8"))
    assert value["metadata"]["ledger"] == {"mode": "custom", "path": custom.as_posix()}


def test_assess_ledger_and_no_ledger_conflict_is_a_clean_error(tmp_path: Path) -> None:
    code = main(
        [
            "assess",
            "--input",
            str(_bundle(tmp_path)),
            "--ledger",
            str(tmp_path / "x.jsonl"),
            "--no-ledger",
        ]
    )
    assert code == 2
    assert not (tmp_path / "x.jsonl").exists()
