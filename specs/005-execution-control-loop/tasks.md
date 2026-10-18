# Tasks: Execution-evidence control loop

**Input**:spec.md, plan.md, research.md, data-model.md and contracts/. Tests explicitly requested.

## Foundation

- [x] T001 Refresh own Specify1.2.1 while preserving installed released AEE/evaluator pins in .specify/project-tooling.json.
- [x] T002 Fill design artifacts and run actual specification/planning AEE with composed results; draft/human acceptance stays unknown.
- [ ] T003 Measure maintained-code line/branch coverage including subprocesses; record cross-platform/shell gaps without exclusions.

- [x] T004 [US1] Test scoped freshness/error/forgery boundaries in tests/test_execution_scope.py then implement src/aee/execution_scope.py (45 local tests and100% module coverage recorded).
- [x] T005 [US1] Test explicit argv capture, exit/timeout/changed scope/log bounds/strict ingestion in tests/test_execution_evidence.py before implementing src/aee/execution_evidence.py.
- [ ] T006 [US1] Integrate versioned execution artifacts and anchored HashChainLedger; verify actual report/test inventory and producer policy without declared-CI trust. Core capture receipts, bounded JUnit, explicit digest policy and ledger are implemented/tested; CLI/agent/adapter provenance policy integration remains pending.
- [ ] T007 [US2] Test requirement/test discovery, shared links, broken IDs, orphan tests and scoped human-approved methods; implement src/aee/verification_links.py and reuse gap identities.
- [ ] T008 [US3] Test ambiguity, destructive authorization and missing/stale verification; implement src/aee/execution_preflight.py using links/evidence.
- [x] T009 [US4] Test bounded status/stage/contradiction preservation and ledger pointers; implement src/aee/context_handoff.py.
- [ ] T010 [US4] Expose all operations in src/aee/cli.py and packaged standalone SKILL.md; add real CLI/agent lifecycle and future extension integration tests.

## Cross-cutting verification

- [ ] T090 Update README/docs/skills/examples and CHANGELOG Unreleased with actual capabilities and assurance limits.
- [ ] T091 Complete actual after_tasks/after_implement AEE and deterministic Evaluator composition with inspectable command artifacts.
- [ ] T092 Pass lint/type/build/fuzz/security, meaningful100%line+branch coverage and all required cross-platform CI; disclose remaining gaps.
- [ ] T093 Open linked reviewable PR, merge only exact-green head with exact policy restoration; hold product releases during baseline.

## Dependencies and execution strategy

Foundation → scoped evidence → links → preflight → context → adapter integration. Evaluator schema fixtures can be prepared before final engine CLI, but cross-component acceptance blocks completion. Execute incrementally with one owner; no parallel agents authorized. Each story has targeted malformed/error tests and an independently runnable integration scenario. CLI, direct-agent and SpecKit routes share semantics.

## Benchmark gate

Valid baseline completion + all product validation → immutable versioned candidate/release under current rules → prospective matched after freeze. Never change baseline dependencies or tune features to hidden scored outcomes.
