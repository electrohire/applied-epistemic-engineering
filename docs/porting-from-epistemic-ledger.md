# Porting from the epistemic ledger

The living epistemic ledger (AXIOVEX/epistemic-ledger) is a sibling
program: an event-sourced store that tracks claims with fluid
credences and propagates re-evaluation through their dependents. It
ran a series of frozen, preregistered measurement studies
(REALWIRE-01, STANCE-01, STANCE-02, plus calibration batteries)
against authored corpora and verbatim published copy. This page
records which of its *measured* mechanisms transfer into this
library, which do not, and in what order they are being ported.
The ledger's discipline is the point of the transfer: nothing here
is ported on intuition — each item names the measurement behind it.

## Transferred

### Assessment policy gates — `aee.policy` (1.1.0)

Three rules from STANCE-02's production analysis, implemented as
opt-in gates that layer verdicts (ACCEPT / CHALLENGE / ABSTAIN)
above scores without mutating them:

- **Corroboration gate.** Fewer than two independent supporting
  sources → CHALLENGE. In the ledger's newsroom measurements,
  single-source claims were the dominant channel by which noisy
  extraction hardened into asserted knowledge.
- **Forced abstention.** No supporting evidence, or support made
  solely of model self-attestation → ABSTAIN ("unknown means
  ABSTAIN"). A near-zero score reads downstream as measured-and-
  weak; an abstention states the claim was never measured.
- **Contested gate.** Contradiction penalty at or above the policy
  threshold → CHALLENGE at best. STANCE-01/02 showed contradiction
  averaged into a score disappears; contradiction surfaced as a
  verdict does not.

With a policy attached, an assessment containing an ABSTAIN or
CHALLENGE verdict cannot report `pass`.

## Planned

### Per-source reliability (learned entrenchment)

The ledger learns each claim's entrenchment from outcomes
(1 − Brier of the score live at each outcome's timestamp) instead
of trusting static tiers — and its OVERRIDE-CAL-01 study showed the
loop absorbs even a reviewer who is wrong 20% of the time. The
analog here: per-`source_id` reliability estimated from resolved
claims, modulating the static `SourceQuality` prior in scoring.
Ported as an opt-in scoring input, with the static weights as the
prior for unmeasured sources.

### Materiality review queue

The ledger's revisit loop flags dependents for review only when
their score moves by at least a materiality threshold (default
0.05, validated by its TRIGGER-STRESS-01 epsilon sweep: recall
0.960 at epsilon 0.005, with flag volume — mean ≈ 17–37 per event —
the binding cost). The analog here: diffing two assessments of the
same claim set and emitting a bounded review list of claims whose
propagated score moved ≥ materiality, largest first, with an
optional top-k budget. In the Spec Kit flow this turns a
phase-to-phase re-read into a bounded review queue.

### Calibrated threshold provenance

The ledger's kill bars all carry the measurement that set them
(KILL-BARS-01: a bar breached by a healthy workload is reset to
observed max × 1.25, old value recorded; bars are never tightened
on a hunch). The policy thresholds in `aee.policy` follow the same
rule — each default states its provenance in the docstring — and
future threshold changes in this library should cite the workload
that moved them.

## Not transferred

- **LLM extraction and stance classification.** This library is
  deterministic by design. The ledger's stance findings enter only
  as policy defaults for model-sourced evidence (above), never as
  a neural code path.
- **Bitemporal event sourcing.** The ledger's store answers "what
  did we believe at T" from an append-only event log. This
  library's `HashChainLedger` serves a different purpose (tamper-
  evident assessment history) and is not converging with it.
- **The newsroom simulator and its corpora.** Measurement
  apparatus for the ledger's claims; the results transfer, the
  harness does not.
