# Quickstart

## Install

```bash
python -m pip install applied-epistemic-engineering
```

Requires Python 3.11 or later; tested on Linux, macOS, and Windows with Python 3.11, 3.12,
and 3.13.

Using [Spec Kit](https://github.com/github/spec-kit)? You don't need to install this
package yourself. Install the Spec Kit extension, which installs a compatible engine
(`applied-epistemic-engineering>=1.5.0,<2`, the latest available) and its other
dependencies automatically on first use:

```bash
specify extension add aee --from https://github.com/electrohire/spec-kit-aee/archive/refs/tags/v1.5.1.zip
```

The example pins spec-kit-aee 1.5.1, the extension release tested with this engine; check
its [releases](https://github.com/electrohire/spec-kit-aee/releases) for newer versions.
`spec-kit-aee` is a Spec Kit extension distributed as a GitHub release archive, not a PyPI
package, and is versioned independently of this engine.

## Assess structured claims

Create `claims.json`:

```json
{
  "claims": [
    {
      "id": "REQ-API-001",
      "text": "The API returns within 100 ms",
      "kind": "requirement",
      "status": "supported",
      "boundary": ["p95", "nominal load", "production"],
      "falsification_tests": ["Observe p95 at or above 100 ms"],
      "uncertainty": "low",
      "evidence": [
        {
          "ref": "reports/load-test.json",
          "kind": "observed",
          "direction": "supports",
          "source_quality": "test",
          "source_id": "load-test-001"
        }
      ]
    }
  ]
}
```

Run the assessment:

```bash
aee assess \
  --input claims.json \
  --phase after_plan \
  --output assessment.json \
  --evaluator-output evaluator-result.json \
  --ledger .aee/epistemic-ledger.jsonl
```

The assessment retains the rich AEE model. `evaluator-result.json` conforms to the shared
Evaluator Contract used by Spec Kit.

## Extract identified claims from Markdown

The parser intentionally extracts only claims with stable identifiers:

```markdown
## REQ-API-001 — The API returns within 100 ms
- **Boundary:** p95 under nominal production load
- **Test:** Observe p95 at or above 100 ms
```

```bash
aee assess --input spec.md --phase after_specify
```

Unidentified prose is not silently promoted into claims.

## Challenge a claim set

`challenge` runs the same deterministic assessment and projects only the failure modes and
bounded recovery work (no scoring keys leak):

```bash
aee challenge --input claims.json --phase after_plan --output challenge.json
```

## Generate a gap register

`gaps` cross-references a verification matrix against test evidence and writes a `GAPS.md`
register. Use `--existing` to preserve previously closed gaps and `--close` to close one by ID:

```bash
aee gaps --matrix specs/verification-matrix.md --evidence evidence/ --output GAPS.md
aee gaps --matrix specs/verification-matrix.md --evidence evidence/ \
  --existing GAPS.md --close GAP-001 --output GAPS.md
```

