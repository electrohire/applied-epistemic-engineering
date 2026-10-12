"""Spec 003 FR-5 remainder (T504/T505/T506/T508/T510, completing T511).

Inverts the RT2 probes the FR-5 main phase left to this branch:

- p04 (model coercion): strict loading rejects every coercion the
  probe exploited — a string is not a list, ``null`` is not "None",
  strings/bools are not numbers, ``observed_at``/``content_hash``
  are type-checked — with errors naming the row index and claim id;
- p05 §1 (duplicate JSON keys): refused, key named, at every load
  site (bundle, assessment/gate, reliability, session state,
  migrate input); §§4-5: case/Unicode claim-id variants are ONE
  identity (FR-5.7); §6: non-dict rows are named errors; §7: bare
  NaN refused at load;
- p06 (extraction): a BOM no longer deletes the first Markdown
  claim; a lowercase heading's source_ref carries the normalised
  id; injected bold fields cannot move status/confidence;
- p10 (determinism): ``--as-of`` pins the scoring clock and the
  ledgered digest is over assessment content (created_at excluded),
  so identical input replayed produces an identical digest;
- p04 §6 / RT2-L6 (content_hash): assessment output marks a
  declared hash declared_not_verified until a verification run in
  this process recomputes it (verified / mismatched), and a
  republished "verified" is never trusted on reload.
- p13 reorder pin: per-id scores and outcome are input-order
  invariant (p11/p13 schema aspects are pinned by
  tests/test_schema_parity.py).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aee.cli import main
from aee.engine import AEEEngine
from aee.evidence_check import check_evidence
from aee.extract import extract_markdown_claims, load_claims, validate_bundle_structure
from aee.ledger import HashChainLedger, assessment_content_digest
from aee.model import BundleValidationError, Claim, ClaimStatus, Evidence
from aee.session import AEESession


def _write(tmp_path: Path, text: str, name: str = "claims.json") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _bundle(tmp_path: Path, rows: list[dict], name: str = "claims.json") -> Path:
    return _write(tmp_path, json.dumps({"claims": rows}), name)


# ---------------------------------------------------------------------
# p04 — strict type coercion (T505 / FR-5.6)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "row",
    [
        # a string where a list belongs exploded into characters and
        # earned boundary/falsifiability credit (p04 §1)
        {"id": "CLM-1", "text": "x", "boundary": "production"},
        {"id": "CLM-1", "text": "x", "falsification_tests": "run it"},
        # explicit null became the literal string "None" (p04 §2)
        {"id": "CLM-2", "text": None},
        {"id": "CLM-2", "text": "t", "evidence": [{"ref": None}]},
        # strings/bools are not numbers (p04 §3)
        {"id": "C3", "text": "t", "confidence": "0.9"},
        {"id": "C4", "text": "t", "confidence": True},
        # typed fields stored verbatim crashed scoring later (p04 §4)
        {"id": "CLM-5", "text": "t", "evidence": [{"ref": "r", "observed_at": 20260101}]},
        {"id": "CLM-5", "text": "t", "evidence": [{"ref": "r", "content_hash": 123}]},
        # evidence as an object, boundary as an int (p04 §5)
        {"id": "C6", "text": "t", "evidence": {"ref": "r"}},
        {"id": "C7", "text": "t", "boundary": 42},
        # metadata: list-of-pairs silently became a dict; a plain
        # string crashed opaquely (p04 §8)
        {"id": "C9", "text": "t", "metadata": [["k", "v"]]},
        {"id": "C10", "text": "t", "metadata": "secret"},
    ],
)
def test_p04_coercions_rejected_by_strict_loading(row: dict) -> None:
    with pytest.raises(BundleValidationError):
        Claim.from_dict(row)


def test_p04_independent_of_string_rejected() -> None:
    with pytest.raises(BundleValidationError, match="independent_of"):
        Evidence.from_dict({"ref": "r", "independent_of": "src-A"})


def test_p04_no_character_explosion_credit() -> None:
    # The probe's scoring consequence: even the load path used by the
    # CLI refuses the char-exploding rows, so no boundary/falsifiability
    # credit can be minted from a bare string.
    with pytest.raises(BundleValidationError):
        Claim.from_dict({"id": "CLM-1", "text": "x", "boundary": "production"})


def test_load_errors_name_row_index_and_claim_id(tmp_path: Path) -> None:
    bundle = _bundle(
        tmp_path,
        [
            {"id": "CLM-OK", "text": "fine"},
            {"id": "CLM-BAD", "text": "t", "confidence": "0.9"},
        ],
    )
    with pytest.raises(BundleValidationError) as excinfo:
        load_claims(bundle)
    message = str(excinfo.value)
    assert "claims[1]" in message
    assert "CLM-BAD" in message
    assert "confidence" in message


def test_lenient_mode_remains_the_named_coercion_exception() -> None:
    # FR-5.6's strictness is the strict loader's; the explicitly
    # named lenient compatibility path (Spec 002 FR-1.3, echoed as
    # loading_mode wherever a command exposes it) still coerces.
    claim = Claim.from_dict({"id": "C3", "text": "t", "confidence": "0.9"}, strict=False)
    assert claim.confidence == 0.9


# ---------------------------------------------------------------------
# p05 §1 — duplicate JSON keys refused at every load site (T504 / FR-5.4)
# ---------------------------------------------------------------------


def test_p05_duplicate_top_level_key_refused(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '{"claims": [{"id": "CLM-1", "text": "benign"}], '
        '"claims": [{"id": "CLM-2", "text": "second bundle wins"}]}',
    )
    with pytest.raises(BundleValidationError, match="duplicate JSON key 'claims'"):
        load_claims(path)


def test_p05_duplicate_claim_field_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, '{"claims": [{"id": "CLM-1", "text": "first", "text": "overwritten"}]}')
    with pytest.raises(BundleValidationError, match="duplicate JSON key 'text'"):
        load_claims(path)


def test_p05_duplicate_nested_evidence_key_refused(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '{"claims": [{"id": "CLM-1", "text": "t", "evidence": [{"ref": "a", "ref": "b"}]}]}',
    )
    with pytest.raises(BundleValidationError, match="duplicate JSON key 'ref'"):
        load_claims(path)


def test_duplicate_keys_refused_in_assessment_for_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, '{"outcome": "pass", "outcome": "block"}', name="assessment.json")
    assert main(["gate", "--input", str(path)]) == 2
    assert "duplicate JSON key 'outcome'" in capsys.readouterr().err


def test_duplicate_keys_refused_in_reliability_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _bundle(tmp_path, [{"id": "CLM-1", "text": "t"}])
    reliability = _write(tmp_path, '{"sources": {}, "sources": {}}', name="reliability.json")
    assert (
        main(
            [
                "assess",
                "--input",
                str(bundle),
                "--no-ledger",
                "--reliability",
                str(reliability),
            ]
        )
        == 2
    )
    assert "duplicate JSON key 'sources'" in capsys.readouterr().err


def test_duplicate_keys_refused_in_migrate_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, '{"claims": [], "claims": []}', name="legacy.json")
    assert main(["migrate", str(path)]) == 2
    assert "duplicate JSON key 'claims'" in capsys.readouterr().err


def test_duplicate_keys_refused_in_session_state(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text('{"claims": [], "claims": []}', encoding="utf-8")
    session = AEESession("proj", state_file=state)
    with pytest.raises(ValueError, match="duplicate JSON key 'claims'"):
        session.load()


# ---------------------------------------------------------------------
# p05 §§4-6 — claim-id identity (T506 / FR-5.7) and malformed rows
# ---------------------------------------------------------------------


def test_p05_case_variant_ids_are_one_identity(tmp_path: Path) -> None:
    bundle = _bundle(
        tmp_path,
        [
            {"id": "clm-1", "text": "lower"},
            {"id": "CLM-1", "text": "upper", "depends_on": ["clm-1"]},
        ],
    )
    claims = load_claims(bundle)
    assert [claim.id for claim in claims] == ["CLM-1", "CLM-1"]
    # The lowercase reference resolves to the canonical id (here: a
    # self-reference, which structural validation names as an error
    # instead of the reference silently dangling).
    assert claims[1].depends_on == ["CLM-1"]
    errors, _warnings = validate_bundle_structure(claims)
    assert any("duplicate claim id" in error for error in errors)


def test_p05_unicode_nfc_nfd_ids_are_one_identity(tmp_path: Path) -> None:
    nfc = "CLM-\u00c4"  # precomposed U+00C4
    nfd = "CLM-A\u0308"  # A + combining diaeresis U+0308
    assert nfc != nfd
    bundle = _bundle(tmp_path, [{"id": nfc, "text": "a"}, {"id": nfd, "text": "b"}])
    claims = load_claims(bundle)
    assert [claim.id for claim in claims] == ["CLM-\u00c4", "CLM-\u00c4"]


def test_p05_whitespace_id_normalised() -> None:
    assert Claim.from_dict({"id": " CLM-9 ", "text": "t"}).id == "CLM-9"


def test_p05_session_add_claim_uses_the_same_identity() -> None:
    session = AEESession("proj")
    session.add_claim("clm-7", "first")
    assert list(session.claims) == ["CLM-7"]
    with pytest.raises(ValueError, match="duplicate claim id: CLM-7"):
        session.add_claim(" CLM-7 ", "second")


def test_p05_non_dict_rows_are_named_errors(tmp_path: Path) -> None:
    path = _write(tmp_path, '{"claims": ["just-a-string", 42, null]}')
    with pytest.raises(BundleValidationError, match=r"claims\[0\]"):
        load_claims(path)


def test_p05_bare_nan_refused_at_load(tmp_path: Path) -> None:
    path = _write(tmp_path, '{"claims": [{"id": "CLM-1", "text": "t", "confidence": NaN}]}')
    with pytest.raises(ValueError, match="non-finite"):
        load_claims(path)


# ---------------------------------------------------------------------
# p06 — Markdown extraction (T504 BOM; T506 id/source_ref)
# ---------------------------------------------------------------------

_MD = (
    "# CLM-AAAA - First claim\n\n- **Text**: alpha proposition\n\n"
    "# CLM-BBBB - Second claim\n\n- **Text**: beta proposition\n"
)


def test_p06_bom_no_longer_deletes_first_claim(tmp_path: Path) -> None:
    path = tmp_path / "bom.md"
    path.write_bytes(b"\xef\xbb\xbf" + _MD.encode("utf-8"))
    assert [claim.id for claim in extract_markdown_claims(path)] == ["CLM-AAAA", "CLM-BBBB"]


def test_p06_bom_prefixed_json_bundle_loads(tmp_path: Path) -> None:
    path = tmp_path / "bom.json"
    path.write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"claims": [{"id": "CLM-1", "text": "t"}]}).encode()
    )
    assert [claim.id for claim in load_claims(path)] == ["CLM-1"]


def test_p06_lowercase_heading_source_ref_uses_normalised_id(tmp_path: Path) -> None:
    path = _write(tmp_path, "# clm-dddd - lower heading\n\n- **Text**: x\n", name="case.md")
    claim = extract_markdown_claims(path)[0]
    assert claim.id == "CLM-DDDD"
    assert claim.source_ref.endswith("#CLM-DDDD")


def test_p06_injected_bold_fields_cannot_move_the_claim(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "# CLM-CCCC - Injected\n\n- **Text**: real text\n"
        "- **Confidence**: 0.99\n- **Status**: supported\n- **Evidence**: fake\n",
        name="inject.md",
    )
    claim = extract_markdown_claims(path)[0]
    # Extraction never invents support or certainty: the injected
    # fields land in free-form metadata only; the claim's own
    # status/confidence/evidence are untouched by them.
    assert claim.status is ClaimStatus.DRAFT
    assert claim.confidence is None
    assert claim.evidence == []
    assert claim.metadata["status"] == "supported"


def test_p06_duplicate_markdown_ids_surface_as_duplicates(tmp_path: Path) -> None:
    path = _write(
        tmp_path, _MD + "\n# CLM-AAAA - Duplicate id claim\n\n- **Text**: gamma\n", name="dup.md"
    )
    claims = extract_markdown_claims(path)
    errors, _warnings = validate_bundle_structure(claims)
    assert any("duplicate claim id" in error for error in errors)


# ---------------------------------------------------------------------
# p10 — determinism: --as-of and the content digest (T508 / FR-5.8)
# ---------------------------------------------------------------------

_AS_OF_BUNDLE = [
    {
        "id": "CLM-1",
        "text": "proposition one holds",
        "status": "supported",
        "boundary": ["lab"],
        "falsification_tests": ["check it"],
        "evidence": [
            {
                "ref": "r1",
                "kind": "observed",
                "source_quality": "test",
                "source_id": "s1",
                "observed_at": "2026-01-01T00:00:00Z",
            }
        ],
    }
]


def _assess_file(tmp_path: Path, name: str, *extra: str) -> dict:
    bundle = _bundle(tmp_path, _AS_OF_BUNDLE, name="input.json")
    output = tmp_path / name
    code = main(["assess", "--input", str(bundle), "--output", str(output), "--no-ledger", *extra])
    assert code in (0, 1)
    return json.loads(output.read_text(encoding="utf-8"))


def test_p10_as_of_replay_is_identical_apart_from_created_at(tmp_path: Path) -> None:
    first = _assess_file(tmp_path, "o1.json", "--as-of", "2026-06-01")
    second = _assess_file(tmp_path, "o2.json", "--as-of", "2026-06-01")
    first.pop("created_at")  # the run stamp is the one allowed difference
    second.pop("created_at")
    assert first == second
    assert first["metadata"]["as_of"] == "2026-06-01T00:00:00Z"


def test_p10_content_digest_ignores_created_at() -> None:
    one = {"outcome": "pass", "created_at": "2026-01-01T00:00:00Z", "claims": []}
    two = {"outcome": "pass", "created_at": "2030-12-31T23:59:59Z", "claims": []}
    assert assessment_content_digest(one) == assessment_content_digest(two)
    different = {"outcome": "block", "created_at": one["created_at"], "claims": []}
    assert assessment_content_digest(one) != assessment_content_digest(different)


def test_p10_ledgered_replay_has_identical_digest_and_is_refused_as_duplicate(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path, _AS_OF_BUNDLE, name="input.json")
    ledger_path = tmp_path / "ledger.jsonl"
    args = [
        "assess",
        "--input",
        str(bundle),
        "--ledger",
        str(ledger_path),
        "--as-of",
        "2026-06-01",
    ]
    assert main(args) in (0, 1)
    entries = HashChainLedger(ledger_path).entries()
    assert len(entries) == 1
    payload = entries[0]["payload"]
    assert payload["assessment_created_at"]  # the run stamp is kept, separately
    # Replay: same input, same pinned clock -> the append is the
    # FR-4.6 duplicate of the identical content digest.
    assert main(args) == 2
    assert len(HashChainLedger(ledger_path).entries()) == 1


def test_p10_as_of_actually_pins_the_scoring_clock(tmp_path: Path) -> None:
    fresh = _assess_file(tmp_path, "fresh.json", "--as-of", "2026-01-02")
    stale = _assess_file(tmp_path, "stale.json", "--as-of", "2028-01-01")
    assert (
        fresh["scores"]["CLM-1"]["propagated_score"] > stale["scores"]["CLM-1"]["propagated_score"]
    )


def test_p10_invalid_as_of_is_a_clean_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _bundle(tmp_path, _AS_OF_BUNDLE, name="input.json")
    with pytest.raises(SystemExit) as excinfo:
        main(["assess", "--input", str(bundle), "--no-ledger", "--as-of", "not a date"])
    assert excinfo.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


# ---------------------------------------------------------------------
# p04 §6 — content_hash verification states (T510 / FR-5.10)
# ---------------------------------------------------------------------


def _hash_claim(declared: str) -> Claim:
    return Claim(
        id="CLM-1",
        text="t",
        evidence=[Evidence(ref="data.bin", content_hash=declared)],
    )


def test_p10_plain_assessment_marks_declared_hash_not_verified(tmp_path: Path) -> None:
    (tmp_path / "data.bin").write_bytes(b"hello")
    digest = hashlib.sha256(b"hello").hexdigest()
    assessment = AEEEngine().assess([_hash_claim(digest)])
    item = assessment.to_dict()["claims"][0]["evidence"][0]
    assert item["content_hash_status"] == "declared_not_verified"


def test_content_hash_verified_and_mismatched_states(tmp_path: Path) -> None:
    (tmp_path / "data.bin").write_bytes(b"hello")
    digest = hashlib.sha256(b"hello").hexdigest()
    good = _hash_claim(digest)
    check_evidence([good], tmp_path)
    item = AEEEngine().assess([good]).to_dict()["claims"][0]["evidence"][0]
    assert item["content_hash_status"] == "verified"

    bad = _hash_claim("deadbeef")
    check_evidence([bad], tmp_path)
    item = AEEEngine().assess([bad]).to_dict()["claims"][0]["evidence"][0]
    assert item["content_hash_status"] == "mismatched"


def test_content_hash_unresolvable_ref_stays_declared(tmp_path: Path) -> None:
    claim = _hash_claim("deadbeef")  # no data.bin under tmp_path
    check_evidence([claim], tmp_path)
    item = AEEEngine().assess([claim]).to_dict()["claims"][0]["evidence"][0]
    assert item["content_hash_status"] == "declared_not_verified"


def test_republished_verified_status_is_never_trusted() -> None:
    forged = {
        "id": "CLM-1",
        "text": "t",
        "evidence": [
            {"ref": "data.bin", "content_hash": "deadbeef", "content_hash_status": "verified"}
        ],
    }
    reloaded = Claim.from_dict(forged)
    assert reloaded.evidence[0].content_hash_status is None
    assert reloaded.to_dict()["evidence"][0]["content_hash_status"] == "declared_not_verified"


def test_no_declared_hash_no_status_key() -> None:
    assessment = AEEEngine().assess([Claim(id="CLM-2", text="t", evidence=[Evidence(ref="x")])])
    assert "content_hash_status" not in assessment.to_dict()["claims"][0]["evidence"][0]


def test_assess_verify_evidence_cli_marks_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "data.bin").write_bytes(b"hello")
    digest = hashlib.sha256(b"hello").hexdigest()
    bundle = _bundle(
        tmp_path,
        [
            {
                "id": "CLM-1",
                "text": "t",
                "status": "supported",
                "evidence": [
                    {
                        "ref": "data.bin",
                        "kind": "observed",
                        "source_quality": "artifact",
                        "content_hash": digest,
                    }
                ],
            }
        ],
        name="input.json",
    )
    output = tmp_path / "out.json"
    code = main(
        [
            "assess",
            "--input",
            str(bundle),
            "--output",
            str(output),
            "--no-ledger",
            "--verify-evidence",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert code in (0, 1)
    item = json.loads(output.read_text(encoding="utf-8"))["claims"][0]["evidence"][0]
    assert item["content_hash_status"] == "verified"


# ---------------------------------------------------------------------
# p13 — reorder invariance pin (p11/p13 schema aspects live in
# tests/test_schema_parity.py)
# ---------------------------------------------------------------------


def test_p13_reorder_keeps_per_id_scores_and_outcome(tmp_path: Path) -> None:
    rows = [
        {
            "id": f"CLM-{i}",
            "text": f"proposition number {i} holds",
            "status": "draft",
            "boundary": ["lab"],
            "falsification_tests": ["check"],
            "evidence": [
                {"ref": f"r{i}", "kind": "observed", "source_quality": "test", "source_id": f"s{i}"}
            ],
        }
        for i in range(5)
    ]
    forward = AEEEngine().assess(load_claims(_bundle(tmp_path, rows, name="a.json")))
    reverse = AEEEngine().assess(
        load_claims(_bundle(tmp_path, list(reversed(rows)), name="b.json"))
    )
    assert forward.outcome == reverse.outcome
    for claim_id, score in forward.scores.items():
        assert score.propagated_score == reverse.scores[claim_id].propagated_score
