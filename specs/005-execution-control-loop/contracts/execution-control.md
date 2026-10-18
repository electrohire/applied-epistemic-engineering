# Contract invariants (design, implementation pending)

Inputs are untrusted bounded data. Reject unknown versions, fields where strict schema applies, duplicate identities/JSONkeys, malformed hashes/timestamps/statuses, path escapes and arbitrary command execution during ingest. Never equate absent evidence with successful verification.

Round trip must preserve explicit epistemic status, scoped applicability, record identity and provenance. In-memory calls receive the same validation as JSON calls. Every gate failure has a stable reason and evidence pointer. Any unsupported future engine/evaluator contract produces an actionable error.

Version negotiation must preserve1.0 callers and validate new preflight routing before use. Python/Bash/PowerShell must agree on schema errors, missing/stale evidence and strict/majority/optimistic compositions; hard malformed contract always blocks.

## Implemented engine records (development branch)

ExecutionRecord1.0 is immutable canonical JSON. It records explicit argv and
resolved executable, normalized requirement IDs, expected JUnit test IDs, actual
start/end/monotonic duration, exit/termination, before/after ScopeSnapshots,
bounded binary log hashes/prefixes/completeness, cleanup status and report receipts.
The canonical digest is SHA256 of sorted, compact, ASCII-escaped JSON without
NaN/Infinity. It is separate from arbitrary pretty-printed file bytes.

Capture refuses existing report outputs before execution and binds post-execution
report path/hash/byte count or an explicit error. Reports must be bounded regular
files inside the project root with no symlinked components. The process is an
explicit caller-authorized action with caller OS privileges, not a sandbox.
Ingest never executes recorded commands or interprets a CI label as authentication.

JUnit verification supports UTF-8 testsuite/testsuites with named, unique cases,
consistent declared counts and unstructured text output. DOCTYPE/entities,
malformed/nested results hidden in metadata, unsupported variants, missing expected
inventory, skips/errors, stale scope and changed/missing reports cannot pass.
Process failure remains distinct from incomplete verification. A pass is limited
to this scoped execution and declared inventory, not correctness or adequacy of
agent-authored tests. Actual requirement/test linking is the next integration step.

Imported records remain unverified by default. An explicit trusted digest policy
comes from the host's immediately observed capture transaction or independently
verified CI receipt, never from the imported record itself. A pin does not prove
CI identity by name. The existing anchored ledger records execution_observation
with its stable record digest and unverified producer label; actor names and
repeated receipts do not create identity proof or independent sources.

Scope freshness binds explicitly included code/test/config bytes; callers must
include relevant dependency/configuration inputs. It does not infer the complete
runtime environment, prove inputs never changed transiently, or supply trusted time.
