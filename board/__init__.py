"""Agent Board substrate and kernel (spec AB-001 as amended).

A board is an append-only, hash-chained event log plus a folded state
file, in one canonical directory. Events are the only way state changes;
the fold is a pure function of the log; completion is gated on external
verdict records (Phase 2). This family is dependency-free (stdlib only)
and follows the repo's record-family pattern (see lifecycle/ and
program-ledger/): a pinned schema beside the code, loud named refusals,
and verified writes.

Modules:
    canonical -- pinned canonical serialization and per-event hashing
    validate  -- the pinned schema's validator (schema.json)
    append    -- the append command: the log's one write path
    fold      -- fold and chain verification
    state     -- state snapshots and freshness labeling
    recover   -- torn-tail and fork recovery procedures
    view      -- the generated human tasks view
"""
