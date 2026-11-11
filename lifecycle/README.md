# Lifecycle records

This family records what one delivery cost over its life: inference,
human minutes, acceptance, verifier provenance and production cost,
censoring, rework, defect escapes, integration probes, and survival.

`schema.json` is the pinned schema. `intake.py` validates JSONL records
containing delivery, rework, and escape records. It follows the
program-ledger discipline: loud named refusals, no writes on refusal,
and append-only corrections represented by a new record carrying
`correction_of`.

`classifier.py` decides whether a path is hand-written source, using
the reviewed exclusions in `classifier_rules.json` and the hand-labeled
fixture set in `classifier_fixtures.jsonl`.

`survival.py` computes blame-based survival at a registered horizon on
hand-written files changed by a delivery commit.

Examples:

```bash
python3 lifecycle/intake.py lifecycle/fixtures.jsonl
python3 lifecycle/classifier.py src/aee/model.py program-ledger/matrix.json
python3 lifecycle/survival.py /path/to/repo DELIVERY_COMMIT \
  --snapshot-commit SNAPSHOT_COMMIT --horizon-days 30
```
