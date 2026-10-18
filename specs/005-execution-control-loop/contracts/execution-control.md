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

## Receipt-backed discovery (development branch)

TestDiscovery1.0 contains the actual collection ExecutionRecord, explicit managed
directories and literal suffix policy, before/after file membership snapshots,
and the path of its capture-bound JSON report. The report contains only
schema_version1.0 and tests[{id,path}]. Collection must discover real test items;
the API does not turn an agent-authored manifest into authoritative collection.
Test IDs are opaque unique strings bounded to8192characters, matching execution
record identities. Paths must be canonical and confined to managed source files.

Verification re-walks the bounded managed tree and checks membership, hashes,
captured input scope, actual process result and report receipt. New/orphan IDs and
changed/renamed/deleted files cannot remain implicitly fresh. Symlink/reparse
components, unreadable trees and unavailable post-collection membership cannot pass.
The suffix/directory policy is explicit: other files and the runtime environment
are not implicitly monitored. Concurrent/transient modifications still require
caller-managed isolation; hashes alone cannot prove historical immutability.

Trust pins authenticate the complete TestDiscovery digest via an independently
established host policy or immediately observed transaction. Pinning only the inner
command digest does not authenticate the declared directory policy. Ingestion
does not execute commands. A collector's name or collected=true flag is not proof.

check_verification_links accepts explicit accepted requirement IDs and many-to-many
test links, allows shared tests, and reports missing/unknown requirements,
broken IDs and orphan tests. Its pass means link integrity only; test execution,
verification adequacy and requirement acceptance remain separate. Human-approved
non-test methods need scoped authenticated approval, not a name/checkbox. The
permission record below supplies the API boundary; production host authority
and preflight/workflow integration remain pending.

## Scoped non-test permission (development branch)

VerificationMethodApproval1.0 is a bounded canonical JSON statement containing
decision=approve_method, canonical unique requirement IDs and method ID, method
description, approver label, timezone-bearing stated date, scoped receipt path
and ScopeSnapshot. The receipt itself must be among the hashed scoped files.
Neither the date nor the label proves identity, trusted time or actual approval.

check_method_approval defaults to unverified/gather_evidence. A dedicated
trusted_human_approval_digests policy must come from the embedding host after
authenticating the original human receipt through an independent channel. Keep
that policy outside the editable agent workspace. An agent-controlled CLI flag,
an imported approval boolean, a collection/command pin or an immediately observed
agent file write cannot establish that human policy. The core does not implement
an identity/signature/timestamp service. Policy removal revokes the receipt;
changed requirements, receipt bytes, repository identity or unreadable scope
cannot pass even with a pinned record. Ledger append preserves the statement
with approval_trust=unverified and does not authenticate the actor.

The link checker can use applicable approvals for individually named requirements
alongside real test links. Duplicate method IDs, unknown requirements, invalid
approvals and orphan/broken tests remain blockers. It still requires applicable
discovery; approval does not waive an empty/disappeared inventory. The result
only grants permission to use this scoped method. verification_status stays
unassessed; actual execution/result/freshness are separate requirements for the
final gate. Production host integration, preflight, gap mapping, CLI/skills and
cross-component routing remain pending. Tests use synthetic host policies and
receipts, never actual maintainer approval.
