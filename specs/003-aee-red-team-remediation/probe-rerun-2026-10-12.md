# Spec 003 Phase 9 — Red-Team Probe Re-Run, 2026-10-12

**Targets (current mains, verified by commit):** engine `electrohire/applied-epistemic-engineering` @ `6449975` · extension `electrohire/spec-kit-aee` @ `527feae` · evaluator `electrohire/spec-kit-evaluator` @ `eee9fef` · benchmark `electrohire/spec-kit-aee-benchmark` @ `e248d49`.

**Method:** every probe in `~/workspace/aee-redteam/rt1..rt4/probes/` was re-run against fresh worktrees of the current mains (one worktree set per suite, never the shared checkouts). Verdicts: **INVERTED** = the attack no longer works / behavior is now correct, on observed output; **REMAINDER** = still possible, but a recorded and accepted limitation, with the reason; **STILL-LIVE** = the probe still exploits on current main. Still-live findings are reported here, loudly, and are **not** fixed in this pass.

**Full per-finding records** (decisive observed output quoted per finding, probe adaptations, run ledgers): `~/workspace/aee-closeout/results/rt1-verdicts.md`, `rt2-verdicts.md`, `rt3-verdicts.md`, `rt4-verdicts.md`; raw re-run outputs under `~/workspace/aee-closeout/w-rt1/my-outputs/` and the sibling `w-rt2`/`w-rt3`/`w-rt4` worktrees.

**Counting note:** the four FINDINGS.md files are counted as 90 findings by the program (26 + 24 + 20 + 20). RT3's FINDINGS.md header says 20 but enumerates 21 IDs (RT3-01…RT3-21); all 21 were verdicted. Totals below are over the 91 enumerated IDs.

## Verdict totals

| Suite | Findings | INVERTED | REMAINDER | STILL-LIVE |
|---|---|---|---|---|
| RT1 (engine core) | 26 | 10 | 2 | 14 |
| RT2 (trust surfaces) | 24 | 21 | 3 | 0 |
| RT3 (extension) | 21 | 9 | 0 | 12 |
| RT4 (evaluator/benchmark) | 20 | 17 | 3 | 0 |
| **Total** | **91** | **57** | **8** | **26** |

---

## STILL-LIVE findings (named first, per close-out discipline)

### A. The FR-8 package — still live because FR-8 is HELD, not because landed work failed

Thirteen RT1 findings are the Spec 003 FR-8 work package (tasks T802–T815, all still unchecked on this main). Under owner decision **OD-T1** (2026-10-12), FR-8 is held for joint implementation with Spec 004's model work as one methodology-version bump. These probes still exploit, at outputs substantively identical to the original red-team run — that is the expected state of deliberately unimplemented scope, recorded here so the hold is a visible fact, not an invisible one:

| ID | Finding | Observed on current main |
|---|---|---|
| RT1-08 | Unrelated cycle disables propagation graph-wide | STRONG propagates 1.0 past an unrelated X↔Y cycle; policy ACCEPTs it alone (FR-8.3/T802 not implemented) |
| RT1-09 | Policy verdicts blind to failure modes | ACCEPT issued alongside HIGH boundary failure and a `clarify` outcome (FR-8.4/T803) |
| RT1-10 | Freshness gameable four ways | Undated/future-dated evidence scores 1.0 vs honest-old 0.9; one fresh junk item erases the staleness penalty (FR-8.6/T805) |
| RT1-11 | Falsifiability/boundary scores are presence booleans | `boundary=['x']`, `falsifier=['y']` earn full credit (FR-8.7/T806) |
| RT1-15 | Challenge recall holes (compound/vague evasion) | All named evasion sentences still produce zero challenges (FR-8.8/T807) |
| RT1-16 | Negation-conflict detector: paraphrase evades, different subjects false-fire | Both directions reproduce verbatim (FR-8.9/T808) |
| RT1-17 | Absolute-language gate suppressed by any boundary string | `["unrelated note"]` suppresses the gate completely (FR-8.10/T809) |
| RT1-18 | Review queue blind to salami slicing, band crossings, failure-only changes | 0.90→0.5 slide in 0.04 steps flags 0 items; a gained CRITICAL failure at unchanged score is invisible (FR-8.11/T810) |
| RT1-19 | Review-queue top-k flooding | 20 decoys at +0.99 push a −0.80 collapse past `limit=5` (FR-8.12/T811) |
| RT1-20 | Scoring ignores author-declared uncertainty/severity/status/conflicts | Twin claims' full score *records* are indistinguishable (FR-8.13a/T812) |
| RT1-24 | Threshold boundary widened by 6-decimal rounding | **Proven end-to-end:** constructed exact score 0.6999995 is stored as 0.7 and `_outcome` returns `pass` (FR-8.13b/T813) |
| RT1-25 | Contested-gate asymmetry for weak-kind contradictions | Standalone policy ACCEPTs with recorded contradicting evidence at penalty 0.05 (FR-8.5/T804) |
| RT1-26 | Atomic-claims false-fires (partial: 1 of 4 fixed) | Version-list comma case fixed; Celsius/Fahrenheit, demographic, and proper-noun (Secure Boot) false-fires all still reproduce (FR-8.15/T815) |

### B. RT1-07 (composite) — a residual inside landed FR-3 territory

Coattail farming and framing are INVERTED (`observe_claim` credits only positive-contribution sources, share-weighted; the junk source's reliability stays `None` and the framed victim is unburned). **But direct `record()` minting still reproduces at the original numbers:** the verbatim unattributed call is refused (FR-3.5 provenance is required), yet supplying *any* self-asserted provenance string (or `allow_unattributed=True`) canonises a junk source in 3 calls — reliability 1.0, MODEL weight blending 0.20 → 0.60. Provenance is a caller-asserted label, not an authority check. If `record()` is adjudicated a trusted-resolver-only API, the bundle-author-reachable half of this finding is closed; as a probe verdict on the code as shipped, the finding remains live and is recorded as a context item on claim RT-003-23.

### C. RT3 — extension findings still live (12)

RT3 was cross-referenced only in Spec 003 (§10); its remediation is extension-side work, separately owned. The runner's core contract did invert (see below), but twelve findings still reproduce on extension main @ `527feae`:

| ID | Finding | Observed |
|---|---|---|
| RT3-05 | `gaps` symlinked evidence escapes project root | Symlinked evidence file outside the root still closes a gap (`Open: 0 / Closed: 1`, exit 0) |
| RT3-08 | Second-resolution filename collisions | Identical repeats now fail cleanly on the ledger duplicate check, but two *distinct* assessments in one second shared one filename with 2 ledger entries |
| RT3-09 | Token-economy `shell`: unconfined exec, caller cwd, no timeout, full-argv telemetry | Reproduced live, including verbatim secret argv in telemetry |
| RT3-10 | `TOKEN_ROUTER_HOME` out-of-root code execution; bool ranges accepted | Fake router executed; `[true, 3]` accepted as `[1, 3]` |
| RT3-11 | No subprocess timeout in `run_aee.py` | Hung engine never returns; probe's external timeout had to kill it |
| RT3-12 | Unquoted placeholders in command `.md` templates | Confirmed by inspection of the current tree |
| RT3-13 | Hooks unbound; no `gate --latest` | Confirmed by inspection |
| RT3-14 | Docs/install drift | README still installs v1.0.1 and calls the branch "1.1.0 (unreleased)"; confirmed by inspection |
| RT3-16 | `check_install.py` local-path only, bare `assert`s | Confirmed by inspection |
| RT3-17 | `_safe_output` returns unresolved path (check-then-use window) | Still unresolved in both scripts |
| RT3-18 | `route` whole-file read; fallback/savings doc misdescriptions | Confirmed, including the `rg`/`grep` misdescription |
| RT3-19 | Config template decorative for both scripts; disclaimer names only `run_aee.py` | Confirmed by inspection |

---

## REMAINDERS (8) — recorded limitations, verified not assumed

| ID | Residual | Recorded basis |
|---|---|---|
| RT1-03 | Ref-string-only contradiction laundering: an `observed`-kind item whose ref string alone marks it as a refutation, relabelled `direction: "context"`, still passes clean (score 1.0, no failures). The kind-carrying variant is INVERTED (HIGH polarity-coherence failure → `clarify`). | Spec 003 FR-2 recorded limit: with no kind signal, the item is indistinguishable from legitimate context evidence (T209 task note) |
| RT1-22 | Dependency laundering by omission: an omitted `depends_on` link is undetectable in-engine (omitted-link claim propagates 1.0) | Spec 003 FR-8.14: admitted documentation-only. **Caveat:** the docs-side mitigation (T814) is still unchecked — `docs/scoring.md` does not yet state the author-declared conditionality in plain terms |
| RT2-H2 | Ledger tail truncation | Ledger-alone truncation now FAILS on the anchor leg (`aee gate`: `anchor_status=mismatch`); legacy anchor-less ledgers honestly report `unverifiable-anchor` and `--require-anchor` exits 2. Residual = both-files case (below) |
| RT2-M1 | Whole-chain rehash forgery | Rehash against an intact anchor fails; rewriting BOTH the ledger (rehashed) and the anchor sidecar verifies fully (`valid=True, anchor_status='verified'`) | 
…[truncated 7895 chars]