# Feature Specification: Agent Board — Execution Substrate with the Spec-Kit Kernel (AB-001)

**Feature Branch**: `agent-board-plan-2026-11-19`

**Created**: 2026-11-19

**Status**: Ratified spec, held externally. This file is the in-repo pointer
to the canonical specification; it does not restate or replace it.

**Canonical source**: Spec AB-001, "Agent Board — execution substrate with
the spec-kit kernel," ratified by Tristen Pierson on 2026-11-19 as amended
by Amendment 1 (2026-11-19). The canonical documents live in the owning
program's workspace, not in this repo:

| Document | SHA-256 (verified 2026-11-19) |
|---|---|
| Spec AB-001 as amended (`2026-11-12-agent-board-spec-DRAFT.md`) | `213cf42fff149f0a3e6f4472efb2dbb26d22b84ce007393233f271d3a195c473` |
| Design note as amended (`2026-11-12-agent-board-kernel-design-note.md`) | `8b471ff895fc53887c3f4723f65c8b051b30f064005c96175706b5ac691570ff` |
| Amendment 1 (`2026-11-19-agent-board-spec-amendment-1-DRAFT.md`, status APPLIED) | `cc1af619b6f232ff0032d794a071f6c8e97aabe1186e82956a09b0a695528cd8` |

## What the spec requires, in one paragraph

One shared, append-only table of work rows per program: an event log with a
per-event hash chain and a folded state file, written only through a single
append command (OS advisory lock, idempotent event IDs, verified append).
The spec-kit kernel defines the legal status transitions; a row may reach
`done` only when it cites a verdict record outside the board whose own
outcome is favorable, bound by a content hash captured at citation time. A
keeper role carries external events onto the board, matches waits, and
sweeps for missed wakes; a dead-keeper detector owned by a different chat
watches the keeper's heartbeat. Weekly audits check that done rows cite
favorable records, that the generated tasks view agrees with the log, and
that served state reproduces from the log. The pilot runs two boards: the
ninety-day program's governance board and one ordinary suite campaign
board. The board never enters the ninety-day program's study arms.

## Where the work lands

- **This repo**: the substrate and kernel as a new top-level module family,
  `board/`, beside `lifecycle/` and `program-ledger/` (ratified hosting
  decision, spec Section 11). The fold implementation here is the canonical
  machine form of the kernel's transition table (spec Section 4.7).
- **electrohire/spec-kit-aee**: the kernel definitions shipped by the
  extension, generated from the canonical form or hash-pinned to it with a
  freshness test (spec Section 4.7). Those tasks are listed in
  [tasks.md](tasks.md) Phase 5 and land as separate PRs in that repo.

## Explicitly not in this spec's plan

- Registration of claims KB-1 through KB-6 in the program ledger is a
  separate governed motion through the program-ledger intake (spec
  Section 8). It is named in [plan.md](plan.md) as a later motion and is
  **not** a task in [tasks.md](tasks.md).
- Caller authentication for board actors is out of scope for the pilot:
  actor-based guards are accountability controls, recorded but not
  structurally enforced (spec Section 4.2 honesty note). No plan surface
  may describe them as enforcement while that note stands.
- No change to any running system is authorized by the ratification; this
  plan's pilot phase stands the boards up as new artifacts.
