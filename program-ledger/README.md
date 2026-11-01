# Program ledger — Spec-Kit AEE

The epistemic ledger for the Spec-Kit AEE program, kept under the
Winning Combination pattern (canonical note:
`projected-constraints-program/analyses/proposal-engine/winning-combination-pattern-2026-11-01.md`).

Rules:

- `claims.jsonl` is append-only and is the sole entry point: nothing
  enters the matrix or the map except through a claim here.
- Every claim is an engine claim (it must parse as `aee.model.Claim`)
  carrying the pattern's fields: statement (`text`), source
  (`source_ref` plus `evidence`), date (`metadata.date`), status,
  confidence, falsifier (`falsification_tests`), and a
  does-not-establish line (`boundary`).
- Nothing is appended without passing `intake.py` (see its docstring
  for rules R0–R9). Intake rejects; it never repairs silently.
- `schema.json` is the ledger's declared schema (Amendment 3):
  versioned, pinned beside the ledger, each field's provenance rule
  stated in it. Intake validates every entry against it, computes
  proposition fingerprints from the statement text (never stored,
  never trusted from the artifact) and refuses collisions, and
  prints INTAKE_COVERAGE counts on every run so a field gap is a
  standing number, never silence.
- Corrections are new claims that supersede (`status: superseded` on
  the old claim is itself recorded by appending the successor claim
  that names it in `depends_on` and states the correction). Frozen
  lines are never edited.
- `components.json` is data, not code: the suite's components, so the
  engine, the matrix generator, and the gate stay free of
  project-specific hardcoding.

Downstream layers (generated, never hand-edited): the matrix
(`tools/build_matrix.py`), the engine evaluation, the gate
(`tools/gate.py`), and the map (`map.html`). Truth flows one way:
ledger → matrix → map.
