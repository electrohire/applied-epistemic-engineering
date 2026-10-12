---
name: speckit-aee-route-evidence
description: Route oversized logs and sources into raw evidence slices for AEE gates
compatibility: Requires spec-kit project structure with .specify/ directory
metadata:
  author: ElectroHire
  source: extension:aee
---

# Aee Route Evidence Skill

# AEE Route Evidence

Route a file that is too large to load directly into verbatim raw slices, so
`speckit.aee.assess` and `speckit.aee.challenge` gates reason over evidence
instead of whole files.

## User input

```text
$ARGUMENTS
```

Accept `file=<path>`, `mode=<error_log|heavy_code|agent_context>`, and
`query="<text>"`. Infer the mode from the file kind when omitted: logs, stack
traces, and CI output are `error_log`; source files are `heavy_code`; long
instruction references such as `AGENTS.md` or `agent-context/*.md` are
`agent_context`.

## Prerequisites

1. The target file must be inside the project root. Never follow symlinks or
   read outside the project root.
2. Never route secrets: files whose names suggest credentials, private keys,
   service accounts, or `.env` content are refused fail-closed.

## Execution

Run the policy helper, which selects the backend and enforces the evidence
rule:

```bash
python .specify/extensions/aee/scripts/python/aee_token_economy.py route \
  --file <path> --mode <mode> --query "<query>"
```

Backend selection, in order:

1. The upstream `token-router` script plus Ollama, when both are available.
   The local model is a line router, never a summarizer: it returns line
   ranges, and the helper extracts the exact raw slices.
2. Deterministic fallback (`rg`/`grep` literal match windows) when
   token-router or Ollama is absent. State the backend in the notes.

When the helper answers `read_directly`, read the file directly; routing a
small file wastes more than it saves. When it answers `no_matches`, sharpen
the query or widen the window instead of inventing ranges.

## AEE evidence rule

- The router selects lines; it never analyzes. Its prose is `unsupported`
  unless grounded in a verbatim slice.
- Evidence citations are `path:start-end` ranges over the original file.
- Raw slices keep their AEE evidence `kind` (`observed` for tool output and
  logs, `artifact` source quality where the vocabulary applies).
- Never assume omitted lines are irrelevant. If a slice looks too narrow,
  expand the range and re-read before making claims.
- Save evidence notes under `.specify/extensions/aee/evidence/` with file
  paths, line ranges, the backend used, and timestamps.

## Guardrails

- Assess and challenge gates must see the raw slices, never a compressed or
  summarized substitute. Compression is for transport, not for evidence.
- Keep mandatory always-on root instructions short; routing cannot save
  tokens after a long root instruction file has already been injected.
- Do not describe routed evidence as proof, certification, or truth.
