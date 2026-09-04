# Quickstart

## Install

```bash
python -m pip install applied-epistemic-engineering
```

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

